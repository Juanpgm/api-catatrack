"""
Rutas para gestiÃ³n de Artefacto de Captura DAGMA
"""
from fastapi import APIRouter, HTTPException, Form, UploadFile, File, Query, Body
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import json
import re
import unicodedata
import uuid
import math
import os
import io
import gzip
from pydantic import BaseModel, Field
import httpx
from shapely.geometry import shape, Point
from shapely.ops import nearest_points

# Importar configuraciÃ³n de Firebase y S3/Storage
from app.firebase_config import db
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config as BotoConfig

router = APIRouter(tags=["Artefacto de Captura"])

# Zona horaria Colombia (UTC-5)
_COL_TZ = timezone(timedelta(hours=-5))

def now_colombia() -> datetime:
    """Retorna la hora actual en zona horaria de Colombia (America/Bogota, UTC-5)."""
    return datetime.now(_COL_TZ)


# ==================== FUNCIONES AUXILIARES ====================#
def clean_nan_values(obj):
    """
    Limpia valores NaN, infinitos y otros valores no compatibles con JSON
    """
    if isinstance(obj, dict):
        return {key: clean_nan_values(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [clean_nan_values(item) for item in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    else:
        return obj


def validate_coordinates(coordinates: list, geometry_type: str) -> bool:
    """
    Valida coordenadas segÃºn el tipo de geometrÃ­a
    """
    if not isinstance(coordinates, list):
        raise ValueError("Las coordenadas deben ser un array")
    
    if geometry_type == "Point":
        if len(coordinates) != 2:
            raise ValueError("Point debe tener exactamente 2 coordenadas [lon, lat]")
        lon, lat = coordinates
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
            raise ValueError("Las coordenadas deben ser nÃºmeros")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Longitud invÃ¡lida: {lon}. Debe estar entre -180 y 180")
        if not (-90 <= lat <= 90):
            raise ValueError(f"Latitud invÃ¡lida: {lat}. Debe estar entre -90 y 90")
    
    elif geometry_type in ["LineString", "MultiPoint"]:
        if len(coordinates) < 2:
            raise ValueError(f"{geometry_type} debe tener al menos 2 puntos")
        for point in coordinates:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("Cada punto debe ser [lon, lat]")
            lon, lat = point
            if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
                raise ValueError(f"Coordenadas fuera de rango: [{lon}, {lat}]")
    
    elif geometry_type == "Polygon":
        if len(coordinates) < 1:
            raise ValueError("Polygon debe tener al menos un anillo")
        for ring in coordinates:
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError("Cada anillo del polÃ­gono debe tener al menos 4 puntos")
    
    return True


def validate_photo_file(file: UploadFile) -> bool:
    """
    Valida que el archivo sea una imagen vÃ¡lida
    """
    # Validar tipo MIME
    allowed_types = ["image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic"]
    if file.content_type not in allowed_types:
        raise ValueError(f"Tipo de archivo no permitido: {file.content_type}. Permitidos: {', '.join(allowed_types)}")
    
    # Validar extensiÃ³n
    allowed_extensions = [".jpg", ".jpeg", ".png", ".webp", ".heic"]
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        raise ValueError(f"ExtensiÃ³n no permitida: {file_ext}")
    
    return True


def get_s3_client():
    """
    Crear cliente de S3 con las credenciales del entorno
    """
    from dotenv import load_dotenv
    load_dotenv(override=True)

    aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
    aws_region = os.getenv('AWS_REGION', 'us-east-2')
    
    if not aws_access_key or not aws_secret_key:
        raise ValueError("Credenciales de AWS no configuradas. Verifica AWS_ACCESS_KEY_ID y AWS_SECRET_ACCESS_KEY")
    
    return boto3.client(
        's3',
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        region_name=aws_region,
        config=BotoConfig(signature_version='s3v4')
    )


def _listar_documentos_s3(vid: str, rid: str, s3_client=None, expiration: int = 3600) -> list:
    """
    Lista todos los objetos en S3 bajo requerimientos/{vid}/{rid}/ y genera
    URLs presignadas (descarga y visualizaciÃ³n) para cada uno.
    """
    bucket_name = os.getenv('S3_BUCKET_NAME', 'catatrack-photos')
    prefix = f"requerimientos/{vid}/{rid}/"

    if s3_client is None:
        try:
            s3_client = get_s3_client()
        except Exception:
            return []

    try:
        response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
    except Exception:
        return []

    documentos = []
    for obj in response.get('Contents', []):
        key = obj['Key']
        filename = key.rsplit('/', 1)[-1] if '/' in key else key
        ext = os.path.splitext(filename)[1].lower()
        ct_map = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
            '.webp': 'image/webp', '.heic': 'image/heic',
            '.pdf': 'application/pdf', '.mp3': 'audio/mpeg', '.wav': 'audio/wav',
            '.ogg': 'audio/ogg', '.webm': 'audio/webm', '.m4a': 'audio/mp4',
            '.gz': 'application/gzip',
        }
        content_type = ct_map.get(ext, 'application/octet-stream')
        s3_url = f"https://{bucket_name}.s3.amazonaws.com/{key}"

        try:
            url_descarga = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket_name, 'Key': key,
                        'ResponseContentDisposition': f'attachment; filename="{filename}"'},
                ExpiresIn=expiration)
        except Exception:
            url_descarga = s3_url

        try:
            url_visualizar = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket_name, 'Key': key,
                        'ResponseContentDisposition': 'inline'},
                ExpiresIn=expiration)
        except Exception:
            url_visualizar = s3_url

        documentos.append({
            "filename": filename,
            "s3_key": key,
            "s3_url": s3_url,
            "content_type": content_type,
            "size": obj.get('Size', 0),
            "upload_date": obj['LastModified'].isoformat() if obj.get('LastModified') else None,
            "url_descarga": url_descarga,
            "url_visualizar": url_visualizar,
            "url_presigned": url_visualizar,
            "url_expiration_seconds": expiration,
        })
    return documentos


# ==================== GEOLOCALIZACIÃ“N ====================
# Cargar basemaps en memoria al iniciar el mÃ³dulo
def _load_basemap(filepath: str, property_name: str) -> list:
    """Carga un GeoJSON y retorna lista de tuplas (polygon_shape, property_value)"""
    basemap_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), filepath)
    try:
        with open(basemap_path, 'r', encoding='utf-8') as f:
            geojson_data = json.load(f)
        polygons = []
        for feature in geojson_data.get('features', []):
            try:
                geom = shape(feature['geometry'])
                value = feature['properties'].get(property_name)
                polygons.append((geom, value))
            except Exception:
                continue
        print(f"âœ… Basemap '{filepath}' cargado: {len(polygons)} polÃ­gonos")
        return polygons
    except Exception as e:
        print(f"âš ï¸ Error cargando basemap '{filepath}': {str(e)}")
        return []

_BARRIOS_POLYGONS = _load_basemap('basemaps/barrios_veredas.geojson', 'barrio_vereda')
_COMUNAS_POLYGONS = _load_basemap('basemaps/comunas_corregimientos.geojson', 'comuna_corregimiento')

# Ãndice nombre (mayÃºsculas) â†’ (polÃ­gono, nombre_canÃ³nico) para bÃºsqueda rÃ¡pida
_BARRIOS_INDEX: dict = {}
_COMUNAS_INDEX: dict = {}


def geolocate_point(lon: float, lat: float) -> dict:
    """
    Realiza intersecciÃ³n geogrÃ¡fica de un punto con los polÃ­gonos de barrios/veredas
    y comunas/corregimientos.
    Retorna dict con 'barrio_vereda' y 'comuna_corregimiento' (None si no intersecta).
    """
    point = Point(lon, lat)
    result = {"barrio_vereda": None, "comuna_corregimiento": None}
    
    for polygon, name in _BARRIOS_POLYGONS:
        if polygon.contains(point):
            result["barrio_vereda"] = name
            break
    
    for polygon, name in _COMUNAS_POLYGONS:
        if polygon.contains(point):
            result["comuna_corregimiento"] = name
            break
    
    return result


# Cache en memoria para evitar geocodificar la misma direcciÃ³n mÃºltiples veces
_GEOCODE_CACHE: dict = {}

# Bounding box del municipio de Cali (incluye corregimientos rurales)
_CALI_BBOX = {"lon_min": -76.75, "lon_max": -76.20, "lat_min": 3.10, "lat_max": 3.80}
# Viewbox en formato Nominatim: left,top,right,bottom
_CALI_VIEWBOX = f"{_CALI_BBOX['lon_min']},{_CALI_BBOX['lat_max']},{_CALI_BBOX['lon_max']},{_CALI_BBOX['lat_min']}"


def _dentro_de_cali(lon: float, lat: float) -> bool:
    """Verifica que las coordenadas estÃ©n dentro del Ã¡rea de Cali"""
    b = _CALI_BBOX
    return b["lon_min"] <= lon <= b["lon_max"] and b["lat_min"] <= lat <= b["lat_max"]


def _strip_acentos(s: str) -> str:
    """Elimina diacrÃ­ticos para comparaciÃ³n insensible a tildes/acentos (SiloÃ© â†” SILOE)."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    ).upper()


def _limpiar_complementos(texto: str) -> str:
    """
    Elimina de una direcciÃ³n los complementos que confunden a los geocodificadores:
    - Indicaciones relativas: 'junto a', 'frente a', 'contiguo a', 'cerca de', etc.
    - Datos de unidad: apto, piso, torre, casa, local, oficina, int.
    - Descriptores vacÃ­os: 'conjunto', 'urb.', 'manzana X'.
    Conserva el nombre del barrio/sector para que Nominatim lo use como contexto.
    """
    # Indicaciones de referencia (hasta la siguiente coma o fin de texto)
    texto = re.sub(
        r'\b(junto\s+a|frente\s+al?|contiguo\s+a|al\s+lado\s+de'
        r'|cerca\s+de|detr[aÃ¡]s\s+de|al\s+frente\s+de|esquina\s+con)[^,;]*',
        '', texto, flags=re.IGNORECASE
    )
    # Datos de unidad: eliminar token + valor
    texto = re.sub(
        r'\b(apto\.?|apartamento|piso|torre|casa|local|of\.?|oficina|int\.?)\s*[\w\-]+',
        '', texto, flags=re.IGNORECASE
    )
    # Normalizar comas y espacios residuales
    texto = re.sub(r',\s*,+', ',', texto)
    texto = re.sub(r'\s{2,}', ' ', texto).strip(' ,')
    return texto


def _normalizar_direccion_colombiana(direccion: str) -> list:
    """
    Genera variantes normalizadas de una direcciÃ³n colombiana para maximizar
    las posibilidades de geocodificaciÃ³n exitosa.

    Mejoras respecto a la versiÃ³n anterior:
    - Elimina complementos ruidosos (apto, junto a, frente a) antes de geocodificar.
    - Maneja abreviaciones (Cl, Cra, Av, Dg, Tv), notaciÃ³n # vs No. y cuadrantes.
    - Genera variante para intersecciones "con" â†’ "&" (mejor soporte OSM/Nominatim).
    - Genera variante con solo la vÃ­a principal como fallback genÃ©rico.
    """
    sufijo = ", Cali, Valle del Cauca, Colombia"
    clean_orig = direccion.strip()
    # VersiÃ³n limpia: sin complementos ruidosos (prioridad para Nominatim)
    clean = _limpiar_complementos(clean_orig)

    abreviaciones = [
        (r'\bCl\.?\b', 'Calle'), (r'\bCll\.?\b', 'Calle'),
        (r'\bCr\.?\b', 'Carrera'), (r'\bCra\.?\b', 'Carrera'), (r'\bKr\.?\b', 'Carrera'),
        (r'\bAv\.?\b', 'Avenida'), (r'\bAvd\.?\b', 'Avenida'),
        (r'\bDg\.?\b', 'Diagonal'), (r'\bDiag\.?\b', 'Diagonal'),
        (r'\bTv\.?\b', 'Transversal'), (r'\bTvs\.?\b', 'Transversal'),
        (r'\bCq\.?\b', 'Circular'),
    ]
    cuadrantes = {
        'N': 'Norte', 'S': 'Sur', 'E': 'Este', 'O': 'Oeste',
        'NE': 'Noreste', 'NO': 'Noroeste', 'SE': 'Sureste', 'SO': 'Suroeste',
    }

    def _expandir(texto: str) -> str:
        for pattern, repl in abreviaciones:
            texto = re.sub(pattern, repl, texto, flags=re.IGNORECASE)
        texto = re.sub(
            r'(\d)([NnSsEeOo]{1,2})\b',
            lambda m: m.group(1) + ' ' + cuadrantes.get(m.group(2).upper(), m.group(2)),
            texto
        )
        return texto

    expanded = _expandir(clean)
    expanded_orig = _expandir(clean_orig)

    variantes = []

    # v1: versiÃ³n limpia con abreviaciones expandidas (Ã³ptima para Nominatim)
    variantes.append(f"{expanded}{sufijo}")

    # v2: # â†’ No. en versiÃ³n limpia
    no_fmt = re.sub(r'\s*#\s*', ' No. ', expanded)
    if no_fmt != expanded:
        variantes.append(f"{no_fmt}{sufijo}")

    # v3: intersecciÃ³n "con" â†’ "&" (mejor soporte OSM para cruces de calles)
    if re.search(r'\bcon\b', expanded, re.IGNORECASE):
        con_fmt = re.sub(r'\s+con\s+', ' & ', expanded, flags=re.IGNORECASE)
        variantes.append(f"{con_fmt}{sufijo}")

    # v4: versiÃ³n original expandida (con complementos; por si el nombre de referencia ayuda)
    if expanded_orig.lower() != expanded.lower():
        variantes.append(f"{expanded_orig}{sufijo}")

    # v5: original sin expandir como Ãºltimo recurso
    if clean_orig.lower() not in {expanded.lower(), expanded_orig.lower()}:
        variantes.append(f"{clean_orig}{sufijo}")

    # v6: solo la vÃ­a principal antes del # o primera coma (fallback muy genÃ©rico)
    main = re.split(r'\s*[#,]\s*', expanded)[0].strip()
    if len(main) > 5 and main.lower() != expanded.lower():
        variantes.append(f"{main}{sufijo}")

    seen, unique = set(), []
    for v in variantes:
        v = v.strip()
        if v not in seen:
            seen.add(v)
            unique.append(v)
    return unique


def _extraer_barrios_mencionados(direccion: str) -> list:
    """
    Detecta barrios/veredas mencionados en la direcciÃ³n usando cuatro estrategias:

    1. Coincidencia directa insensible a acentos: 'Centenario', 'La Flora'.
    2. Prefijo de 2 palabras del basemap: 'San Fernando' â†’ 'San Fernando Viejo'.
    3. ExtracciÃ³n por palabra clave ('barrio X', 'sector X', 'vereda X'):
       el texto extraÃ­do se empareja exactamente, por prefijo y por palabras clave.
    4. Palabras significativas (â‰¥5 chars, no artÃ­culos): 'El Obrero' â†’ 'Barrio Obrero'.

    Retorna lista de (nombre_canÃ³nico, polÃ­gono) ordenada por longitud descendente.
    """
    global _BARRIOS_INDEX
    if not _BARRIOS_INDEX:
        # NÃºmeros escritos como palabra â†’ dÃ­gito, para que "7 de Agosto" encuentre "Siete de Agosto"
        _NUM_TO_DIGIT = {
            'PRIMERO': '1', 'UNO': '1', 'DOS': '2', 'TRES': '3', 'CUATRO': '4',
            'CINCO': '5', 'SEIS': '6', 'SIETE': '7', 'OCHO': '8', 'NUEVE': '9',
            'DIEZ': '10', 'ONCE': '11', 'DOCE': '12', 'VEINTE': '20',
        }
        for poly, name in _BARRIOS_POLYGONS:
            if not name or len(name) < 5:
                continue
            key = _strip_acentos(name)
            _BARRIOS_INDEX[key] = (poly, name)
            # Variante dÃ­gito para nombres que comienzan con nÃºmero escrito
            # ("SIETE DE AGOSTO" â†’ "7 DE AGOSTO")
            first = key.split()[0]
            if first in _NUM_TO_DIGIT:
                alt = _NUM_TO_DIGIT[first] + key[len(first):]
                _BARRIOS_INDEX.setdefault(alt, (poly, name))

    texto_norm = _strip_acentos(direccion)
    encontrados: dict = {}  # canonical_name â†’ polygon (deduplicado)

    # â”€â”€ Estrategia 1: coincidencia directa insensible a acentos â”€â”€
    for nombre_norm, (polygon, nombre_canonical) in _BARRIOS_INDEX.items():
        if nombre_norm in texto_norm:
            encontrados[nombre_canonical] = polygon

    # â”€â”€ Estrategia 1b: prefijo de 2 palabras del nombre del basemap â”€â”€
    # Captura "San Fernando" â†’ "San Fernando Viejo" / "San Fernando Nuevo"
    for nombre_norm, (polygon, nombre_canonical) in _BARRIOS_INDEX.items():
        if nombre_canonical in encontrados:
            continue
        palabras = nombre_norm.split()
        if len(palabras) >= 2:
            prefijo = ' '.join(palabras[:2])
            if len(prefijo) >= 10 and prefijo in texto_norm:
                encontrados[nombre_canonical] = polygon

    # â”€â”€ Estrategia 2: extracciÃ³n por palabra clave "barrio X", "sector X", "urb X", etc. â”€â”€
    _STOP_WORDS_GEO = {
        'EL', 'LA', 'LOS', 'LAS', 'SAN', 'SANTA', 'DE', 'DEL', 'UN', 'UNA',
        'BARRIO', 'SECTOR', 'VEREDA', 'CON', 'CALLE', 'CARRERA', 'AVENIDA',
        'CIUDAD', 'PARQUE', 'VILLA', 'NUEVO', 'NUEVA', 'VIEJO', 'VIEJA',
        'URBANIZACION', 'CIUDADELA', 'CONJUNTO', 'RESIDENCIAL', 'UNIDAD',
    }
    kw_pattern = re.compile(
        r'\b(?:barrio|bario|sector|vereda|b[oOÂºÂ°]'
        r'|urb\.?|urbanizaci[oÃ³]n|ciudadela'
        r'|conj\.?|cjto\.?|conjunto|res\.?|residencial)\s+'
        r'([A-Za-z\u00c0-\u024f][A-Za-z\u00c0-\u024f0-9\s]{2,30}?)'
        r'(?=\s*[,;#\n]|\s*$)',
        re.IGNORECASE
    )
    for m in kw_pattern.finditer(direccion):
        candidato_norm = _strip_acentos(m.group(1).strip())
        if not candidato_norm:
            continue

        # 2a. Exacto
        if candidato_norm in _BARRIOS_INDEX:
            poly, canonical = _BARRIOS_INDEX[candidato_norm]
            encontrados[canonical] = poly
            continue

        # 2b. Prefijo: basemap_key comienza con el candidato o viceversa
        matched = False
        for idx_key, (poly, canonical) in _BARRIOS_INDEX.items():
            if (idx_key.startswith(candidato_norm) or candidato_norm.startswith(idx_key)) \
                    and len(idx_key) >= 5:
                encontrados[canonical] = poly
                matched = True
                break

        # 2c. Palabras significativas en comÃºn (fallback para "El Obrero" â†’ "Barrio Obrero")
        if not matched:
            palabras_cand = {
                w for w in candidato_norm.split()
                if len(w) >= 6 and w not in _STOP_WORDS_GEO
            }
            if palabras_cand:
                for idx_key, (poly, canonical) in _BARRIOS_INDEX.items():
                    palabras_idx = {
                        w for w in idx_key.split()
                        if len(w) >= 6 and w not in _STOP_WORDS_GEO
                    }
                    if palabras_cand & palabras_idx:
                        encontrados[canonical] = poly
                        break

    result = [(name, poly) for name, poly in encontrados.items()]
    result.sort(key=lambda x: len(x[0]), reverse=True)
    return result


def _extraer_comunas_mencionadas(direccion: str) -> list:
    """
    Detecta comunas o corregimientos mencionados en la direcciÃ³n usando tres estrategias:

    A. NÃºmero de comuna: 'comuna 10', 'c. 10', 'com 10', 'c.10', 'COMUNA 01'â€¦
    B. Nombre de corregimiento directo insensible a acentos: 'Pance', 'Felidia', 'La Buitrera'.
    C. Keyword 'corregimiento X' / 'cgto X' con bÃºsqueda exacta y por prefijo.

    Retorna lista de (nombre_canÃ³nico, polÃ­gono).
    """
    global _COMUNAS_INDEX
    if not _COMUNAS_INDEX:
        _COMUNAS_INDEX = {
            _strip_acentos(name): (poly, name)
            for poly, name in _COMUNAS_POLYGONS
            if name
        }

    texto_norm = _strip_acentos(direccion)
    encontrados: dict = {}

    # A: nÃºmero de comuna â€” soporta "comuna 10", "c.10", "com 10", "c. 10"
    num_pattern = re.compile(
        r'\b(?:comunas?|com\.?|c\.)\s*0?(\d{1,2})\b',
        re.IGNORECASE
    )
    for m in num_pattern.finditer(direccion):
        num = int(m.group(1))
        clave = f'COMUNA {num:02d}'
        if clave in _COMUNAS_INDEX:
            poly, canonical = _COMUNAS_INDEX[clave]
            encontrados[canonical] = poly

    # B: nombre de corregimiento directo (solo entradas nombradas, no "COMUNA NN")
    for nombre_norm, (polygon, nombre_canonical) in _COMUNAS_INDEX.items():
        if not nombre_norm.startswith('COMUNA') and len(nombre_norm) >= 5:
            if nombre_norm in texto_norm:
                encontrados[nombre_canonical] = polygon

    # C: keyword "corregimiento X" / "cgto X" / "correg X"
    kw_corr = re.compile(
        r'\b(?:corregimiento|correg\.?|cgto\.?)\s+'
        r'([A-Za-z\u00c0-\u024f][A-Za-z\u00c0-\u024f0-9\s]{2,25}?)'
        r'(?=\s*[,;#\n]|\s*$)',
        re.IGNORECASE
    )
    for m in kw_corr.finditer(direccion):
        candidato_norm = _strip_acentos(m.group(1).strip())
        if candidato_norm in _COMUNAS_INDEX:
            poly, canonical = _COMUNAS_INDEX[candidato_norm]
            encontrados[canonical] = poly
        else:
            for idx_key, (poly, canonical) in _COMUNAS_INDEX.items():
                if not idx_key.startswith('COMUNA') and (
                    idx_key.startswith(candidato_norm) or candidato_norm.startswith(idx_key)
                ) and len(idx_key) >= 5:
                    encontrados[canonical] = poly
                    break

    return [(name, poly) for name, poly in encontrados.items()]


def _snap_al_interior(lon: float, lat: float, polygon) -> tuple:
    """
    Si el punto estÃ¡ fuera del polÃ­gono, devuelve el representative_point()
    de shapely, que estÃ¡ garantizado estrictamente dentro del polÃ­gono
    (funciona correctamente incluso con polÃ­gonos no convexos).
    Retorna (lon, lat, fue_corregido).
    """
    point = Point(lon, lat)
    if polygon.contains(point):
        return lon, lat, False
    # representative_point() siempre estÃ¡ dentro, a diferencia de nearest_points
    # que proyecta al borde y puede generar ambigÃ¼edad con polÃ­gonos vecinos.
    rep = polygon.representative_point()
    return rep.x, rep.y, True


def _seleccionar_candidato(candidatos: list, barrio_polygon, barrio_name: str) -> Optional[dict]:
    """
    De una lista de candidatos geocodificados, elige el que mejor corresponde
    al barrio indicado:
      1. Si alguno cae dentro del polÃ­gono del barrio â†’ devuelve ese directamente.
      2. Si ninguno â†’ toma el mÃ¡s cercano al centroide y lo proyecta dentro del polÃ­gono.
    """
    if not candidatos:
        return None

    # Paso 1: candidatos que ya caen dentro del barrio
    dentro = [
        c for c in candidatos
        if barrio_polygon.contains(Point(c["lon"], c["lat"]))
    ]
    if dentro:
        return {**dentro[0], "barrio_snap": False}

    # Paso 2: ninguno cae dentro â†’ el mÃ¡s cercano al centroide
    centroide = barrio_polygon.centroid

    def dist_sq(c):
        return (c["lon"] - centroide.x) ** 2 + (c["lat"] - centroide.y) ** 2

    mejor = min(candidatos, key=dist_sq)
    lon_orig, lat_orig = mejor["lon"], mejor["lat"]
    lon_snap, lat_snap, fue_corregido = _snap_al_interior(lon_orig, lat_orig, barrio_polygon)

    return {
        "lat": lat_snap,
        "lon": lon_snap,
        "proveedor": mejor["proveedor"],
        "barrio_snap": fue_corregido,
        "barrio_snap_desde": f"[{lon_orig:.6f}, {lat_orig:.6f}]",
    }


async def _geocode_nominatim_multi(
    query: str, client: httpx.AsyncClient, limit: int = 5
) -> list:
    """Nominatim con mÃºltiples candidatos acotados al bbox de Cali."""
    try:
        r = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": query,
                "format": "json",
                "limit": limit,
                "countrycodes": "co",
                "viewbox": _CALI_VIEWBOX,
                "bounded": 1,
            },
            headers={"User-Agent": "catatrack-api/1.0"},
        )
        r.raise_for_status()
        return [
            {"lat": float(item["lat"]), "lon": float(item["lon"]), "proveedor": "nominatim"}
            for item in r.json()
            if _dentro_de_cali(float(item["lon"]), float(item["lat"]))
        ]
    except Exception:
        return []


async def _geocode_nominatim(query: str, client: httpx.AsyncClient) -> Optional[dict]:
    """Nominatim (OpenStreetMap) â€” gratuito, sin API key, 1 req/s"""
    results = await _geocode_nominatim_multi(query, client, limit=1)
    return results[0] if results else None


async def _geocode_photon(query: str, client: httpx.AsyncClient) -> Optional[dict]:
    """Photon (Komoot) â€” gratuito, basado en OSM, sin API key, mejor cobertura LATAM"""
    try:
        r = await client.get(
            "https://photon.komoot.io/api/",
            params={"q": query, "limit": 1, "lang": "es", "lat": "3.45", "lon": "-76.53"},
        )
        r.raise_for_status()
        features = r.json().get("features", [])
        if features:
            lon, lat = features[0]["geometry"]["coordinates"][:2]
            if _dentro_de_cali(lon, lat):
                return {"lat": lat, "lon": lon, "proveedor": "photon"}
    except Exception:
        pass
    return None


async def _geocode_arcgis(query: str, client: httpx.AsyncClient) -> Optional[dict]:
    """ArcGIS World Geocoding Service â€” acceso anÃ³nimo gratuito (1M req/mes)"""
    try:
        r = await client.get(
            "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates",
            params={
                "SingleLine": query,
                "f": "json",
                "maxLocations": 1,
                "countryCode": "COL",
                "outFields": "Match_addr",
            },
        )
        r.raise_for_status()
        candidates = r.json().get("candidates", [])
        if candidates and candidates[0].get("score", 0) >= 70:
            loc = candidates[0]["location"]
            lon, lat = loc["x"], loc["y"]
            if _dentro_de_cali(lon, lat):
                return {"lat": lat, "lon": lon, "proveedor": "arcgis"}
    except Exception:
        pass
    return None


async def geocodificar_direccion_cali(direccion: str) -> Optional[dict]:
    """
    Geocodifica una direcciÃ³n en Cali con cadena de proveedores, barrio/comuna-hint y fallback.

    Estrategia:
      1. CachÃ© en memoria: evita llamadas redundantes.
      2a. Extrae barrios/veredas mencionados (insensible a acentos, 4 estrategias).
      2b. Extrae comunas/corregimientos mencionados (nÃºmero o nombre).
      3. Nominatim multi-candidato acotado al bbox de Cali:
         - Si hay barrio_hint â†’ elige/proyecta el candidato dentro del polÃ­gono del barrio.
         - Si solo hay comuna_hint â†’ elige/proyecta dentro del polÃ­gono de la comuna.
      4. Nominatim simple (sin hint o sin resultados con hint).
      5. Photon (Komoot) como fallback OSM alternativo.
      6. ArcGIS World Geocoding.
      7. Fallback al centroide del barrio mencionado.
      8. Fallback al centroide de la comuna mencionada.

    Retorna dict con 'lat', 'lon', 'proveedor' y opcionalmente 'barrio_snap' (bool),
    'barrio_snap_desde' (str). Retorna None si todos los pasos fallan.
    """
    clave = direccion.strip().lower()
    if clave in _GEOCODE_CACHE:
        cached = _GEOCODE_CACHE[clave]
        print(f"ðŸ’¾ GeocodificaciÃ³n (cachÃ©): '{direccion}' â†’ [{cached['lon']}, {cached['lat']}]")
        return cached

    variantes = _normalizar_direccion_colombiana(direccion)
    barrios_hint = _extraer_barrios_mencionados(direccion)
    comunas_hint = _extraer_comunas_mencionadas(direccion)

    hint_b = barrios_hint[0][0] if barrios_hint else "â€”"
    hint_c = comunas_hint[0][0] if comunas_hint else "â€”"
    print(
        f"ðŸ” Geocodificando '{direccion}' | variantes={len(variantes)}"
        f" | barrio='{hint_b}' | comuna='{hint_c}'"
    )

    async with httpx.AsyncClient(timeout=12.0) as client:

        # â”€â”€ Paso 1: Nominatim multi-candidato restringido al polÃ­gono del barrio â”€â”€
        if barrios_hint:
            barrio_name_hint, barrio_polygon_hint = barrios_hint[0]
            variantes_hint = variantes + [f"{barrio_name_hint}, Cali, Valle del Cauca, Colombia"]
            for query in variantes_hint:
                candidatos = await _geocode_nominatim_multi(query, client, limit=5)
                if candidatos:
                    mejor = _seleccionar_candidato(candidatos, barrio_polygon_hint, barrio_name_hint)
                    if mejor:
                        snap_msg = (
                            f" (proyectado desde {mejor['barrio_snap_desde']})"
                            if mejor.get("barrio_snap") else ""
                        )
                        print(
                            f"âœ… [{mejor['proveedor']}+barrio:'{barrio_name_hint}'] â†’"
                            f" [{mejor['lon']:.6f}, {mejor['lat']:.6f}]{snap_msg}"
                        )
                        _GEOCODE_CACHE[clave] = mejor
                        return mejor

        # â”€â”€ Paso 2: Nominatim multi-candidato restringido al polÃ­gono de la comuna â”€â”€
        if comunas_hint and not barrios_hint:
            comuna_name_hint, comuna_polygon_hint = comunas_hint[0]
            variantes_hint = variantes + [f"{comuna_name_hint}, Cali, Valle del Cauca, Colombia"]
            for query in variantes_hint:
                candidatos = await _geocode_nominatim_multi(query, client, limit=5)
                if candidatos:
                    mejor = _seleccionar_candidato(candidatos, comuna_polygon_hint, comuna_name_hint)
                    if mejor:
                        snap_msg = (
                            f" (proyectado desde {mejor['barrio_snap_desde']})"
                            if mejor.get("barrio_snap") else ""
                        )
                        print(
                            f"âœ… [{mejor['proveedor']}+comuna:'{comuna_name_hint}'] â†’"
                            f" [{mejor['lon']:.6f}, {mejor['lat']:.6f}]{snap_msg}"
                        )
                        _GEOCODE_CACHE[clave] = mejor
                        return mejor

        # â”€â”€ Paso 3: Nominatim simple (sin hint o sin resultados con hint) â”€â”€
        for query in variantes:
            result = await _geocode_nominatim(query, client)
            if result:
                print(f"âœ… [nominatim] '{query}' â†’ [{result['lon']}, {result['lat']}]")
                _GEOCODE_CACHE[clave] = result
                return result

        # â”€â”€ Paso 4: Photon â”€â”€
        for query in variantes[:2]:
            result = await _geocode_photon(query, client)
            if result:
                print(f"âœ… [photon] '{query}' â†’ [{result['lon']}, {result['lat']}]")
                _GEOCODE_CACHE[clave] = result
                return result

        # â”€â”€ Paso 5: ArcGIS â”€â”€
        for query in variantes[:2]:
            result = await _geocode_arcgis(query, client)
            if result:
                print(f"âœ… [arcgis] '{query}' â†’ [{result['lon']}, {result['lat']}]")
                _GEOCODE_CACHE[clave] = result
                return result

        # â”€â”€ Paso 6: Fallback al centroide del barrio mencionado â”€â”€
        if barrios_hint:
            barrio_name_hint, barrio_polygon_hint = barrios_hint[0]
            centroide = barrio_polygon_hint.centroid
            result = {
                "lat": centroide.y, "lon": centroide.x,
                "proveedor": "barrio_centroide",
                "barrio_snap": True, "barrio_snap_desde": "centroide_fallback",
            }
            print(f"ðŸ“ Fallback centroide barrio '{barrio_name_hint}': [{centroide.x:.6f}, {centroide.y:.6f}]")
            _GEOCODE_CACHE[clave] = result
            return result

        # â”€â”€ Paso 7: Fallback al centroide de la comuna mencionada â”€â”€
        if comunas_hint:
            comuna_name_hint, comuna_polygon_hint = comunas_hint[0]
            centroide = comuna_polygon_hint.centroid
            result = {
                "lat": centroide.y, "lon": centroide.x,
                "proveedor": "comuna_centroide",
                "barrio_snap": True, "barrio_snap_desde": "centroide_fallback",
            }
            print(f"ðŸ“ Fallback centroide comuna '{comuna_name_hint}': [{centroide.x:.6f}, {centroide.y:.6f}]")
            _GEOCODE_CACHE[clave] = result
            return result

    print(f"âš ï¸ Sin resultados en ningÃºn proveedor para: '{direccion}'")
    return None


# ==================== MODELOS ====================#
class AcompananteModel(BaseModel):
    """Modelo para datos de acompaÃ±ante"""
    nombre_completo: str
    telefono: str
    email: str
    centro_gestor: str


class RegistroVisitaRequest(BaseModel):
    """Modelo de solicitud para registro de visitas"""
    direccion_visita: str = Field(..., min_length=1, description="DirecciÃ³n de la visita en Cali, Valle del Cauca")
    descripcion_visita: str = Field(..., min_length=1, description="DescripciÃ³n de la visita")
    observaciones_visita: str = Field(..., min_length=1, description="Observaciones de la visita")
    acompanantes: Optional[List[AcompananteModel]] = Field(None, description="Lista de acompaÃ±antes (opcional)")
    fecha_visita: str = Field(..., description="Fecha de la visita en formato dd/mm/aaaa")
    hora_visita: str = Field(..., description="Hora de la visita en formato HH:mm (hora BogotÃ¡)")


class RegistroVisitaResponse(BaseModel):
    """Modelo de respuesta para registro de visitas"""
    success: bool
    vid: str
    message: str
    direccion_visita: str
    coords: Optional[dict]
    geocodificacion_fuente: Optional[str]
    barrio_vereda: Optional[str]
    comuna_corregimiento: Optional[str]
    descripcion_visita: str
    observaciones_visita: str
    acompanantes: Optional[List[dict]]
    fecha_visita: str
    hora_visita: str
    timestamp: str


class RegistroDelegadoResponse(BaseModel):
    """Modelo de respuesta para registro de asistencia de delegado"""
    success: bool
    vid: str
    id_acompanante: str
    message: str
    nombre_completo: str
    rol: str
    nombre_centro_gestor: str
    telefono: str
    email: str
    latitud: str
    longitud: str
    fecha_registro: str
    timestamp: str


class RegistroComunidadResponse(BaseModel):
    """Modelo de respuesta para registro de asistencia de comunidad"""
    success: bool
    vid: str
    id_asistente_comunidad: str
    message: str
    nombre_completo: str
    rol_comunidad: str
    direccion: str
    barrio_vereda: str
    comuna_corregimiento: str
    telefono: str
    email: str
    latitud: str
    longitud: str
    fecha_registro: str
    timestamp: str


class RegistroRequerimientoResponse(BaseModel):
    """Modelo de respuesta para registro de requerimiento"""
    success: bool
    vid: str
    rid: str
    message: str
    datos_solicitante: dict
    tipo_requerimiento: str
    requerimiento: str
    observaciones: str
    direccion: Optional[str] = None
    barrio_vereda: Optional[str] = None
    comuna_corregimiento: Optional[str] = None
    coords: dict
    estado: str
    nota_voz_url: Optional[str] = None
    documentos_urls: Optional[List[dict]] = None
    fecha_registro: str
    organismos_encargados: List[str]
    timestamp: str


# ==================== ENDPOINT 1: InicializaciÃ³n de Unidades de Proyecto ====================#
GESTORPROYECTO_API_BASE = "https://gestorproyectoapi-production.up.railway.app"


@router.get(
    "/init/unidades-proyecto",
    summary="ðŸ”µ GET | InicializaciÃ³n de Unidades de Proyecto",
    description="""
## ðŸ”µ GET | InicializaciÃ³n de Unidades de Proyecto

**PropÃ³sito**: Obtener datos iniciales de unidades de proyecto para el artefacto de captura.

### âœ… Respuesta
Retorna la respuesta original de la API de GestorProyecto.

### ðŸ“ Ejemplo de uso:
```javascript
const response = await fetch('/init/unidades-proyecto');
const data = await response.json();
```
    """,
)
async def get_init_unidades_proyecto():
    """
    Obtener datos iniciales de unidades de proyecto
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{GESTORPROYECTO_API_BASE}/unidades-proyecto/geometry"
            )
            response.raise_for_status()

        return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Error consultando unidades de proyecto: {str(e)}"
        )


# ==================== ENDPOINT 2: Registro de Visita ====================
@router.post(
    "/registrar-visita/",
    summary="ðŸŸ¢ POST | Registro de Visita",
    description="""
## ðŸŸ¢ POST | Registro de Visita

**PropÃ³sito**: Registrar una visita realizada con informaciÃ³n de ubicaciÃ³n,
descripciÃ³n, observaciones, acompaÃ±antes y fecha/hora.

### âœ… Campos requeridos:
- **barrio_vereda**: Nombre del barrio o vereda (texto)
- **comuna_corregimiento**: Comuna o corregimiento (texto)
- **descripcion_visita**: DescripciÃ³n de la visita (texto)
- **observaciones_visita**: Observaciones de la visita (texto)
- **acompanantes**: (Opcional) Array JSON con datos de acompaÃ±antes: [{"nombre_completo", "telefono", "email", "centro_gestor"}, ...]
- **fecha_visita**: Fecha de la visita en formato dd/mm/aaaa
- **hora_visita**: Hora de la visita en formato HH:mm (hora de BogotÃ¡, Colombia)

### ðŸ”¢ VID (ID de Visita):
El sistema genera automÃ¡ticamente un ID Ãºnico con formato **VID-#** donde # es un 
consecutivo incremental. Ejemplo: VID-1, VID-2, VID-3...

### ðŸ“ Ejemplo de uso con JSON:
```javascript
const response = await fetch('/registrar-visita/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        barrio_vereda: 'San Fernando',
        comuna_corregimiento: 'Comuna 3',
        descripcion_visita: 'Visita de inspecciÃ³n ambiental',
        observaciones_visita: 'Se encontraron residuos sÃ³lidos en la zona',
        acompanantes: [
            {
                nombre_completo: 'Juan PÃ©rez',
                telefono: '3001234567',
                email: 'juan@example.com',
                centro_gestor: 'Centro Gestor Norte'
            },
            {
                nombre_completo: 'MarÃ­a LÃ³pez',
                telefono: '3009876543',
                email: 'maria@example.com',
                centro_gestor: 'Centro Gestor Sur'
            }
        ],
        fecha_visita: '13/04/2026',
        hora_visita: '14:30'
    })
});
```

### âœ… Respuesta exitosa:
```json
{
    "success": true,
    "vid": "VID-1",
    "message": "Visita registrada exitosamente",
    "barrio_vereda": "San Fernando",
    "comuna_corregimiento": "Comuna 3",
    "descripcion_visita": "Visita de inspecciÃ³n ambiental",
    "observaciones_visita": "Se encontraron residuos sÃ³lidos en la zona",
    "acompanantes": [
        {
            "nombre_completo": "Juan PÃ©rez",
            "telefono": "3001234567",
            "email": "juan@example.com",
            "centro_gestor": "Centro Gestor Norte"
        },
        {
            "nombre_completo": "MarÃ­a LÃ³pez",
            "telefono": "3009876543",
            "email": "maria@example.com",
            "centro_gestor": "Centro Gestor Sur"
        }
    ],
    "fecha_visita": "13/04/2026",
    "hora_visita": "14:30",
    "timestamp": "2026-04-13T19:30:00Z"
}
```
    """,
    response_model=RegistroVisitaResponse
)
async def post_registro_visita(payload: RegistroVisitaRequest):
    """
    Registrar una visita. Geocodifica la direcciÃ³n para obtener coordenadas WGS84
    y determina barrio/vereda y comuna/corregimiento por intersecciÃ³n geogrÃ¡fica.
    """
    import re

    try:
        direccion_visita = payload.direccion_visita
        descripcion_visita = payload.descripcion_visita
        observaciones_visita = payload.observaciones_visita
        acompanantes = payload.acompanantes
        fecha_visita = payload.fecha_visita
        hora_visita = payload.hora_visita

        # Validar formato fecha_visita dd/mm/aaaa
        if not re.match(r'^\d{2}/\d{2}/\d{4}$', fecha_visita):
            raise HTTPException(
                status_code=400,
                detail="Formato de fecha_visita invÃ¡lido. Debe ser dd/mm/aaaa (ejemplo: 18/04/2026)"
            )
        try:
            datetime.strptime(fecha_visita, "%d/%m/%Y")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Fecha invÃ¡lida: {fecha_visita}. Verifique que sea una fecha real en formato dd/mm/aaaa"
            )

        # Validar formato hora_visita HH:mm
        if not re.match(r'^\d{2}:\d{2}$', hora_visita):
            raise HTTPException(
                status_code=400,
                detail="Formato de hora_visita invÃ¡lido. Debe ser HH:mm (ejemplo: 14:30)"
            )
        try:
            datetime.strptime(hora_visita, "%H:%M")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Hora invÃ¡lida: {hora_visita}. Verifique que sea una hora real en formato HH:mm"
            )

        # Geocodificar direcciÃ³n â†’ coordenadas WGS84
        geo = await geocodificar_direccion_cali(direccion_visita)
        coords_dict = None
        geocodificacion_fuente = None
        barrio_vereda = None
        comuna_corregimiento = None

        if geo:
            lat = geo["lat"]
            lon = geo["lon"]
            geocodificacion_fuente = geo.get("proveedor")
            coords_dict = {"type": "Point", "coordinates": [lon, lat]}
            # IntersecciÃ³n geogrÃ¡fica con basemaps
            geo_result = geolocate_point(lon, lat)
            barrio_vereda = geo_result["barrio_vereda"]
            comuna_corregimiento = geo_result["comuna_corregimiento"]
            print(f"ðŸ“ Barrio: {barrio_vereda} | Comuna: {comuna_corregimiento}")
        else:
            print(f"âš ï¸ No se pudo geocodificar '{direccion_visita}', se registra sin coordenadas")

        # Generar VID con consecutivo incremental
        try:
            visitas_ref = db.collection('visitas')
            last_visita = visitas_ref.order_by('vid_number', direction='DESCENDING').limit(1).get()

            if len(last_visita) > 0:
                last_vid_number = last_visita[0].to_dict().get('vid_number', 0)
                new_vid_number = last_vid_number + 1
            else:
                new_vid_number = 1

            vid = f"VID-{new_vid_number}"

        except Exception as e:
            print(f"âŒ Error generando VID: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error generando VID: {str(e)}"
            )

        # Preparar datos para guardar en Firebase
        visita_data = {
            "vid": vid,
            "vid_number": new_vid_number,
            "direccion_visita": direccion_visita,
            "coords": coords_dict,
            "geocodificacion_fuente": geocodificacion_fuente,
            "barrio_vereda": barrio_vereda,
            "comuna_corregimiento": comuna_corregimiento,
            "descripcion_visita": descripcion_visita,
            "observaciones_visita": observaciones_visita,
            "acompanantes": [a.model_dump() for a in acompanantes] if acompanantes else None,
            "fecha_visita": fecha_visita,
            "hora_visita": hora_visita,
            "created_at": now_colombia().isoformat(),
            "timestamp": now_colombia().isoformat()
        }

        # Guardar en Firebase
        try:
            db.collection('visitas').document(vid).set(visita_data)
            print(f"âœ… Visita {vid} guardada en Firebase")
        except Exception as e:
            print(f"âŒ Error guardando en Firebase: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error guardando en Firebase: {str(e)}"
            )

        return RegistroVisitaResponse(
            success=True,
            vid=vid,
            message="Visita registrada exitosamente",
            direccion_visita=direccion_visita,
            coords=coords_dict,
            geocodificacion_fuente=geocodificacion_fuente,
            barrio_vereda=barrio_vereda,
            comuna_corregimiento=comuna_corregimiento,
            descripcion_visita=descripcion_visita,
            observaciones_visita=observaciones_visita,
            acompanantes=[a.model_dump() for a in acompanantes] if acompanantes else None,
            fecha_visita=fecha_visita,
            hora_visita=hora_visita,
            timestamp=now_colombia().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error registrando visita: {str(e)}"
        )


# ==================== ENDPOINT: Obtener Visitas Programadas ====================
@router.get(
    "/obtener-visitas-programadas/",
    summary="ðŸ”µ GET | Obtener Visitas Programadas",
    description="""
## ðŸ”µ GET | Obtener Visitas Programadas

**PropÃ³sito**: Obtener todos los registros de la colecciÃ³n "visitas" almacenados en Firebase.

### ðŸ“ Ejemplo de uso:
```javascript
const response = await fetch('/obtener-visitas-programadas/');
const data = await response.json();
```

### âœ… Respuesta exitosa:
```json
{
    "success": true,
    "total": 2,
    "visitas": [
        {
            "vid": "VID-1",
            "barrio_vereda": "San Fernando",
            "comuna_corregimiento": "Comuna 3",
            "descripcion_visita": "Visita de inspecciÃ³n ambiental",
            "observaciones_visita": "Se encontraron residuos sÃ³lidos",
            "acompanantes": [...],
            "fecha_visita": "13/04/2026",
            "hora_visita": "14:30",
            "timestamp": "2026-04-13T19:30:00Z"
        }
    ]
}
```
    """,
)
async def obtener_visitas_programadas():
    """
    Obtener todos los registros de la colecciÃ³n visitas
    """
    try:
        visitas_ref = db.collection('visitas')
        docs = visitas_ref.stream()

        visitas = []
        for doc in docs:
            visitas.append(doc.to_dict())

        return {
            "success": True,
            "total": len(visitas),
            "visitas": visitas
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error obteniendo visitas: {str(e)}"
        )


# ==================== ENDPOINT 3: Obtener Reportes ====================#
@router.get(
    "/grupo-operativo/reportes",
    summary="ðŸ”µ GET | Obtener Reportes",
    description="""
## ðŸ”µ GET | Obtener Reportes del Grupo Operativo

**PropÃ³sito**: Consultar todos los reportes registrados por el grupo operativo.

### âœ… Respuesta
Retorna lista de reportes con sus detalles.

### ðŸ“ Ejemplo de uso:
```javascript
const response = await fetch('/grupo-operativo/reportes');
const reportes = await response.json();
```
    """
)
async def get_reportes():
    """
    Obtener todos los reportes del grupo operativo desde Firebase
    """
    try:
        reportes = []
        docs = db.collection('requerimientos_dagma').order_by('created_at', direction='DESCENDING').stream()
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            reportes.append(clean_nan_values(data))

        return {
            "success": True,
            "data": reportes,
            "count": len(reportes),
            "timestamp": now_colombia().isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error obteniendo reportes: {str(e)}"
        )


# ==================== ENDPOINT 4: Eliminar Reporte ====================#
@router.delete(
    "/grupo-operativo/eliminar-reporte",
    summary="ðŸ”´ DELETE | Eliminar Reporte",
    description="""
## ðŸ”´ DELETE | Eliminar Reporte del Grupo Operativo

**PropÃ³sito**: Eliminar un reporte especÃ­fico del sistema, incluyendo las fotos en S3.

### ðŸ“¥ ParÃ¡metros
- **reporte_id**: ID Ãºnico del reporte a eliminar

### ðŸ—‘ï¸ Acciones realizadas:
1. Eliminar imÃ¡genes del bucket S3 (360-dagma-photos)
2. Eliminar documento de Firebase (reconocimientos_dagma)

### ðŸ“ Ejemplo de uso:
```javascript
const response = await fetch('/grupo-operativo/eliminar-reporte?reporte_id=abc-123', {
    method: 'DELETE'
});
```

### âœ… Respuesta exitosa:
```json
{
    "success": true,
    "id": "abc-123",
    "message": "Reporte y fotos eliminados exitosamente",
    "photos_deleted": 3,
    "timestamp": "2026-01-24T..."
}
```
    """
)
async def delete_reporte(
    reporte_id: str = Query(..., description="ID del reporte a eliminar")
):
    """
    Eliminar un reporte del grupo operativo
    """
    try:
        doc_ref = db.collection('requerimientos_dagma').document(reporte_id)
        doc = doc_ref.get()
        if not doc.exists:
            raise HTTPException(
                status_code=404,
                detail=f"Reporte {reporte_id} no encontrado"
            )

        # Intentar eliminar nota de voz de S3 si existe
        photos_deleted = 0
        try:
            data = doc.to_dict() or {}
            nota_voz_url = data.get('nota_voz_url')
            if nota_voz_url:
                s3_client = get_s3_client()
                bucket_name = os.getenv('S3_BUCKET_NAME', 'catatrack-photos')
                vid = data.get('vid', '')
                rid = data.get('rid', '')
                prefix = f"requerimientos/{vid}/{rid}/"
                response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
                if 'Contents' in response:
                    for obj in response['Contents']:
                        s3_client.delete_object(Bucket=bucket_name, Key=obj['Key'])
                        photos_deleted += 1
        except Exception:
            pass

        doc_ref.delete()

        return {
            "success": True,
            "id": reporte_id,
            "message": "Reporte eliminado exitosamente",
            "photos_deleted": photos_deleted,
            "timestamp": now_colombia().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error eliminando reporte: {str(e)}"
        )


# ==================== ENDPOINT: Registrar Asistencia de Delegado ====================#
@router.post(
    "/registrar-asistencia-delegado",
    summary="ðŸŸ¢ POST | Registrar Asistencia de Delegado",
    description="""
## ðŸŸ¢ POST | Registrar Asistencia de Delegado

**PropÃ³sito**: Registrar la asistencia de un delegado o acompaÃ±ante a una visita,
incluyendo informaciÃ³n personal, ubicaciÃ³n GPS y timestamp del registro.

### âœ… Campos requeridos:
- **vid**: ID de la visita (texto)
- **id_acompanante**: ID Ãºnico del acompaÃ±ante (texto)
- **nombre_completo**: Nombre completo del delegado (texto)
- **rol**: Rol o cargo del delegado (texto)
- **nombre_centro_gestor**: Nombre del centro gestor (texto)
- **telefono**: NÃºmero de telÃ©fono de contacto (texto)
- **email**: Correo electrÃ³nico (texto)
- **latitud**: Latitud GPS (nÃºmero como texto)
- **longitud**: Longitud GPS (nÃºmero como texto)

### ðŸ“ Ejemplo de uso con form-urlencoded:
```javascript
const data = new URLSearchParams();
data.append('vid', 'VID-1');
data.append('id_acompanante', 'ACMP-001');
data.append('nombre_completo', 'Juan PÃ©rez GarcÃ­a');
data.append('rol', 'Supervisor');
data.append('nombre_centro_gestor', 'Centro Administrativo');
data.append('telefono', '+57 300 1234567');
data.append('email', 'juan.perez@example.com');
data.append('latitud', '3.4516');
data.append('longitud', '-76.5320');

const response = await fetch('/registrar-asistencia-delegado', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: data
});
```

### âœ… Respuesta exitosa:
```json
{
    "success": true,
    "vid": "VID-1",
    "id_acompanante": "ACMP-001",
    "message": "Asistencia de delegado registrada exitosamente",
    "nombre_completo": "Juan PÃ©rez GarcÃ­a",
    "rol": "Supervisor",
    "nombre_centro_gestor": "Centro Administrativo",
    "telefono": "+57 300 1234567",
    "email": "juan.perez@example.com",
    "latitud": "3.4516",
    "longitud": "-76.5320",
    "fecha_registro": "2026-02-06T15:30:45.123456",
    "timestamp": "2026-02-06T15:30:45.123456"
}
```
    """,
    response_model=RegistroDelegadoResponse
)
async def post_registrar_asistencia_delegado(
    vid: str = Form(..., min_length=1, description="ID de la visita"),
    id_acompanante: str = Form(..., min_length=1, description="ID del acompaÃ±ante"),
    nombre_completo: str = Form(..., min_length=1, description="Nombre completo del delegado"),
    rol: str = Form(..., min_length=1, description="Rol o cargo del delegado"),
    nombre_centro_gestor: str = Form(..., min_length=1, description="Nombre del centro gestor"),
    telefono: str = Form(..., min_length=1, description="NÃºmero de telÃ©fono de contacto"),
    email: str = Form(..., min_length=1, description="Correo electrÃ³nico"),
    latitud: str = Form(..., description="Latitud GPS"),
    longitud: str = Form(..., description="Longitud GPS")
):
    """
    Registrar la asistencia de un delegado o acompaÃ±ante a una visita
    """
    try:
        # Validar y parsear coordenadas
        try:
            lat = float(latitud)
            lng = float(longitud)

            # Validar rango de coordenadas
            if not (-90 <= lat <= 90):
                raise ValueError(f"Latitud invÃ¡lida: {lat}. Debe estar entre -90 y 90")
            if not (-180 <= lng <= 180):
                raise ValueError(f"Longitud invÃ¡lida: {lng}. Debe estar entre -180 y 180")

        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error en coordenadas: {str(e)}"
            )

        # Validar formato de email bÃ¡sico
        if "@" not in email or "." not in email:
            raise HTTPException(
                status_code=400,
                detail="Formato de email invÃ¡lido"
            )

        # Generar timestamp del momento del registro
        fecha_registro = now_colombia()

        # Crear ID Ãºnico para el documento (combinaciÃ³n de VID e ID_acompanante)
        doc_id = f"{vid}_{id_acompanante}"

        # Preparar datos para guardar en Firebase
        delegado_data = {
            "vid": vid,
            "id_acompanante": id_acompanante,
            "nombre_completo": nombre_completo,
            "rol": rol,
            "nombre_centro_gestor": nombre_centro_gestor,
            "telefono": telefono,
            "email": email,
            "latitud": latitud,
            "longitud": longitud,
            "fecha_registro": fecha_registro.isoformat(),
            "created_at": fecha_registro.isoformat(),
            "timestamp": fecha_registro.isoformat()
        }

        # Guardar en Firebase
        try:
            db.collection('delegados_asistencia').document(doc_id).set(delegado_data)
            print(f"âœ… Asistencia de delegado {id_acompanante} para visita {vid} guardada en Firebase")
        except Exception as e:
            print(f"âŒ Error guardando en Firebase: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error guardando en Firebase: {str(e)}"
            )

        return RegistroDelegadoResponse(
            success=True,
            vid=vid,
            id_acompanante=id_acompanante,
            message="Asistencia de delegado registrada exitosamente",
            nombre_completo=nombre_completo,
            rol=rol,
            nombre_centro_gestor=nombre_centro_gestor,
            telefono=telefono,
            email=email,
            latitud=latitud,
            longitud=longitud,
            fecha_registro=fecha_registro.isoformat(),
            timestamp=now_colombia().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error registrando asistencia de delegado: {str(e)}"
        )


# ==================== ENDPOINT: Registrar Asistencia de Comunidad ====================#
@router.post(
    "/registrar-asistencia-comunidad",
    summary="ðŸŸ¢ POST | Registrar Asistencia de Comunidad",
    description="""
## ðŸŸ¢ POST | Registrar Asistencia de Comunidad

**PropÃ³sito**: Registrar la asistencia de un miembro de la comunidad a una visita,
incluyendo informaciÃ³n personal, direcciÃ³n, ubicaciÃ³n GPS y timestamp del registro.

### âœ… Campos requeridos:
- **vid**: ID de la visita (texto)
- **id_asistente_comunidad**: ID Ãºnico del asistente de la comunidad (texto)
- **nombre_completo**: Nombre completo del asistente (texto)
- **rol_comunidad**: Rol en la comunidad (texto)
- **direccion**: DirecciÃ³n de residencia (texto)
- **barrio_vereda**: Nombre del barrio o vereda (texto)
- **comuna_corregimiento**: Comuna o corregimiento (texto)
- **telefono**: NÃºmero de telÃ©fono de contacto (texto)
- **email**: Correo electrÃ³nico (texto)
- **latitud**: Latitud GPS (nÃºmero como texto)
- **longitud**: Longitud GPS (nÃºmero como texto)

### âœ… Respuesta exitosa:
```json
{
    "success": true,
    "vid": "VID-1",
    "id_asistente_comunidad": "COM-001",
    "message": "Asistencia de comunidad registrada exitosamente",
    "latitud": "3.4516",
    "longitud": "-76.5320",
    "fecha_registro": "2026-02-06T15:30:45.123456",
    "timestamp": "2026-02-06T15:30:45.123456"
}
```
    """,
    response_model=RegistroComunidadResponse
)
async def post_registrar_asistencia_comunidad(
    vid: str = Form(..., min_length=1, description="ID de la visita"),
    id_asistente_comunidad: str = Form(..., min_length=1, description="ID del asistente de la comunidad"),
    nombre_completo: str = Form(..., min_length=1, description="Nombre completo del asistente"),
    rol_comunidad: str = Form(..., min_length=1, description="Rol en la comunidad"),
    direccion: str = Form(..., min_length=1, description="DirecciÃ³n de residencia"),
    barrio_vereda: str = Form(..., min_length=1, description="Nombre del barrio o vereda"),
    comuna_corregimiento: str = Form(..., min_length=1, description="Comuna o corregimiento"),
    telefono: str = Form(..., min_length=1, description="NÃºmero de telÃ©fono de contacto"),
    email: str = Form(..., min_length=1, description="Correo electrÃ³nico"),
    latitud: str = Form(..., description="Latitud GPS"),
    longitud: str = Form(..., description="Longitud GPS")
):
    """
    Registrar la asistencia de un miembro de la comunidad a una visita
    """
    try:
        # Validar y parsear coordenadas
        try:
            lat = float(latitud)
            lng = float(longitud)

            # Validar rango de coordenadas
            if not (-90 <= lat <= 90):
                raise ValueError(f"Latitud invÃ¡lida: {lat}. Debe estar entre -90 y 90")
            if not (-180 <= lng <= 180):
                raise ValueError(f"Longitud invÃ¡lida: {lng}. Debe estar entre -180 y 180")

        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error en coordenadas: {str(e)}"
            )

        # Validar formato de email bÃ¡sico
        if "@" not in email or "." not in email:
            raise HTTPException(
                status_code=400,
                detail="Formato de email invÃ¡lido"
            )

        # Generar timestamp del momento del registro
        fecha_registro = now_colombia()

        # Crear ID Ãºnico para el documento (combinaciÃ³n de VID e ID_asistente_comunidad)
        doc_id = f"{vid}_{id_asistente_comunidad}"

        # Preparar datos para guardar en Firebase
        comunidad_data = {
            "vid": vid,
            "id_asistente_comunidad": id_asistente_comunidad,
            "nombre_completo": nombre_completo,
            "rol_comunidad": rol_comunidad,
            "direccion": direccion,
            "barrio_vereda": barrio_vereda,
            "comuna_corregimiento": comuna_corregimiento,
            "telefono": telefono,
            "email": email,
            "latitud": latitud,
            "longitud": longitud,
            "fecha_registro": fecha_registro.isoformat(),
            "created_at": fecha_registro.isoformat(),
            "timestamp": fecha_registro.isoformat()
        }

        # Guardar en Firebase
        try:
            db.collection('comunidad_asistencia').document(doc_id).set(comunidad_data)
            print(f"âœ… Asistencia de comunidad {id_asistente_comunidad} para visita {vid} guardada en Firebase")
        except Exception as e:
            print(f"âŒ Error guardando en Firebase: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error guardando en Firebase: {str(e)}"
            )

        return RegistroComunidadResponse(
            success=True,
            vid=vid,
            id_asistente_comunidad=id_asistente_comunidad,
            message="Asistencia de comunidad registrada exitosamente",
            nombre_completo=nombre_completo,
            rol_comunidad=rol_comunidad,
            direccion=direccion,
            barrio_vereda=barrio_vereda,
            comuna_corregimiento=comuna_corregimiento,
            telefono=telefono,
            email=email,
            latitud=latitud,
            longitud=longitud,
            fecha_registro=fecha_registro.isoformat(),
            timestamp=now_colombia().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error registrando asistencia de comunidad: {str(e)}"
        )


# ==================== ENDPOINT: Crear Delegado ====================#
@router.post(
    "/crear-delegado/",
    summary="ðŸŸ¢ POST | Crear Delegado",
    description="""
## ðŸŸ¢ POST | Crear Delegado

**PropÃ³sito**: Crear un nuevo registro de delegado en la colecciÃ³n "directorio_contactos".

### âœ… Campos requeridos:
- **nombre_completo**: Nombre completo del delegado (texto)
- **telefono**: TelÃ©fono de contacto (texto)
- **email**: Correo electrÃ³nico (texto)
- **centro_gestor**: Centro gestor al que pertenece (texto)

### âœ… Campos opcionales:
- **cedula**: CÃ©dula del delegado (texto)
- **rol**: Rol o cargo (texto)
- **organismo**: Organismo al que pertenece (texto)

### ðŸ“ Ejemplo de uso:
```javascript
const response = await fetch('/crear-delegado/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        nombre_completo: 'Juan PÃ©rez',
        telefono: '3001234567',
        email: 'juan@example.com',
        centro_gestor: 'Centro Gestor Norte',
        cedula: '1234567890',
        rol: 'LÃ­der ambiental',
        organismo: 'DAGMA'
    })
});
```
    """,
)
async def crear_delegado(payload: dict = Body(...)):
    """
    Crear un nuevo delegado en la colecciÃ³n directorio_contactos
    """
    try:
        # Validar campos requeridos
        campos_requeridos = ["nombre_completo", "telefono", "email", "centro_gestor"]
        faltantes = [c for c in campos_requeridos if not payload.get(c)]
        if faltantes:
            raise HTTPException(
                status_code=400,
                detail=f"Campos requeridos faltantes: {', '.join(faltantes)}"
            )

        delegado_data = {
            "nombre_completo": payload["nombre_completo"],
            "telefono": str(payload["telefono"]),
            "email": payload["email"],
            "centro_gestor": payload["centro_gestor"],
            "cedula": str(payload.get("cedula", "")),
            "rol": payload.get("rol", ""),
            "organismo": payload.get("organismo", ""),
            "created_at": now_colombia().isoformat(),
            "updated_at": now_colombia().isoformat()
        }

        doc_ref = db.collection("directorio_contactos").document()
        doc_ref.set(delegado_data)

        return {
            "success": True,
            "id": doc_ref.id,
            "message": "Delegado creado exitosamente",
            "delegado": delegado_data,
            "timestamp": now_colombia().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error creando delegado: {str(e)}"
        )


# ==================== ENDPOINT: Actualizar Delegado ====================#
@router.patch(
    "/actualizar-delegado/{delegado_id}",
    summary="ðŸŸ¡ PATCH | Actualizar Delegado",
    description="""
## ðŸŸ¡ PATCH | Actualizar Delegado

**PropÃ³sito**: Actualizar parcialmente los datos de un delegado existente en la colecciÃ³n "directorio_contactos".
Solo se actualizan los campos enviados en el body.

### âœ… ParÃ¡metro de ruta:
- **delegado_id**: ID del documento del delegado en Firestore

### âœ… Campos actualizables (todos opcionales):
- **nombre_completo**: Nombre completo del delegado
- **telefono**: TelÃ©fono de contacto
- **email**: Correo electrÃ³nico
- **centro_gestor**: Centro gestor
- **cedula**: CÃ©dula del delegado
- **rol**: Rol o cargo
- **organismo**: Organismo al que pertenece

### ðŸ“ Ejemplo de uso:
```javascript
const response = await fetch('/actualizar-delegado/ABC123docId', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        telefono: '3009999999',
        rol: 'Coordinador ambiental'
    })
});
```
    """,
)
async def actualizar_delegado(delegado_id: str, payload: dict = Body(...)):
    """
    Actualizar parcialmente los datos de un delegado en directorio_contactos
    """
    try:
        doc_ref = db.collection("directorio_contactos").document(delegado_id)
        doc = doc_ref.get()

        if not doc.exists:
            raise HTTPException(
                status_code=404,
                detail=f"Delegado con ID '{delegado_id}' no encontrado"
            )

        campos_permitidos = [
            "nombre_completo", "telefono", "email", "centro_gestor",
            "cedula", "rol", "organismo"
        ]
        update_data = {k: v for k, v in payload.items() if k in campos_permitidos}

        if not update_data:
            raise HTTPException(
                status_code=400,
                detail=f"No se enviaron campos vÃ¡lidos para actualizar. Campos permitidos: {', '.join(campos_permitidos)}"
            )

        # Convertir telefono y cedula a string si vienen como nÃºmero
        if "telefono" in update_data:
            update_data["telefono"] = str(update_data["telefono"])
        if "cedula" in update_data:
            update_data["cedula"] = str(update_data["cedula"])

        update_data["updated_at"] = now_colombia().isoformat()

        doc_ref.update(update_data)

        # Obtener el documento actualizado
        updated_doc = doc_ref.get().to_dict()
        updated_doc["id"] = delegado_id

        return {
            "success": True,
            "id": delegado_id,
            "message": "Delegado actualizado exitosamente",
            "campos_actualizados": list(update_data.keys()),
            "delegado": updated_doc,
            "timestamp": now_colombia().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error actualizando delegado: {str(e)}"
        )


# ==================== ENDPOINT: Registrar Requerimiento ====================#
@router.post(
    "/registrar-requerimiento",
    summary="ðŸŸ¢ POST | Registrar Requerimiento",
    description="""
## ðŸŸ¢ POST | Registrar Requerimiento

**PropÃ³sito**: Registrar un nuevo requerimiento con datos del solicitante,
coordenadas GPS del dispositivo, nota de voz opcional y organismos encargados.
El sistema determina automÃ¡ticamente el barrio/vereda y comuna/corregimiento
mediante intersecciÃ³n geogrÃ¡fica con los basemaps.

### âœ… Campos requeridos:
- **vid**: ID de la visita (texto)
- **datos_solicitante**: Datos del solicitante en formato JSON string (diccionario con datos de una o mÃ¡s personas)
- **requerimiento**: DescripciÃ³n del requerimiento (texto)
- **observaciones**: Observaciones adicionales (texto)
- **coords**: Coordenadas GPS en formato GeoJSON Point string `{"type": "Point", "coordinates": [lng, lat]}`
- **organismos_encargados**: Lista de nombres de centros gestores en formato JSON array `["nombre1", "nombre2"]`

### ðŸ“¥ Campos opcionales:
- **nota_voz**: Archivo de audio (opcional)

### ðŸ”¢ RID (ID de Requerimiento):
El sistema genera automÃ¡ticamente un ID Ãºnico con formato **REQ-#** donde # es un 
consecutivo incremental dentro de cada visita. Ejemplo: REQ-1, REQ-2, REQ-3...

### ðŸ“ Estado:
Por defecto, el registro se crea con estado "Pendiente".

### ðŸ“ Coordenadas GPS:
Debes enviar las coordenadas como un string JSON en formato GeoJSON Point:
```json
{"type": "Point", "coordinates": [-76.5320, 3.4516]}
```
El sistema automÃ¡ticamente determinarÃ¡ el barrio/vereda y la comuna/corregimiento
correspondientes usando intersecciÃ³n geogrÃ¡fica.

### ðŸ‘¤ Datos del Solicitante:
Se envÃ­a como un diccionario JSON que puede contener datos de una o mÃ¡s personas:
```json
{
    "personas": [
        {"nombre": "MarÃ­a LÃ³pez", "email": "maria@example.com", "telefono": "+57 300 1234567", "centro_gestor": "DAGMA"},
        {"nombre": "Juan PÃ©rez", "email": "juan@example.com", "telefono": "+57 310 9876543"}
    ]
}
```

### ðŸŽ¤ Nota de Voz:
Si se incluye un archivo de audio, este se sube a S3 y se retorna la URL.

### ðŸ“ Ejemplo de uso con FormData:
```javascript
const coords = JSON.stringify({type: "Point", coordinates: [-76.5320, 3.4516]});
const organismos = JSON.stringify(["DAGMA", "SecretarÃ­a de Obras"]);
const datosSolicitante = JSON.stringify({
    personas: [
        {nombre: "MarÃ­a LÃ³pez", email: "maria@example.com", telefono: "+57 300 1234567", centro_gestor: "DAGMA"}
    ]
});

const formData = new FormData();
formData.append('vid', 'VID-1');
formData.append('datos_solicitante', datosSolicitante);
formData.append('requerimiento', 'Solicitud de mejoramiento vial');
formData.append('observaciones', 'Urgente, vÃ­a en mal estado');
formData.append('coords', coords);
formData.append('organismos_encargados', organismos);

// Archivo de audio opcional
if (audioFile) {
    formData.append('nota_voz', audioFile);
}

const response = await fetch('/registrar-requerimiento', {
    method: 'POST',
    body: formData
});
```

### âœ… Respuesta exitosa:
```json
{
    "success": true,
    "vid": "VID-1",
    "rid": "REQ-1",
    "message": "Requerimiento registrado exitosamente",
    "datos_solicitante": {"personas": [{"nombre": "MarÃ­a LÃ³pez", "email": "maria@example.com"}]},
    "requerimiento": "Solicitud de mejoramiento vial",
    "observaciones": "Urgente, vÃ­a en mal estado",
    "barrio_vereda": "San Fernando",
    "comuna_corregimiento": "COMUNA 03",
    "coords": {"type": "Point", "coordinates": [-76.5320, 3.4516]},
    "estado": "Pendiente",
    "nota_voz_url": "https://s3.amazonaws.com/bucket/audio.mp3",
    "fecha_registro": "2026-02-06T15:30:45.123456",
    "organismos_encargados": ["DAGMA", "SecretarÃ­a de Obras"],
    "timestamp": "2026-02-06T15:30:45.123456"
}
```
    """,
    response_model=RegistroRequerimientoResponse
)
async def post_registrar_requerimiento(
    vid: str = Form(..., min_length=1, description="ID de la visita"),
    datos_solicitante: str = Form(..., min_length=1, description="Datos del solicitante en formato JSON (diccionario con datos de una o mÃ¡s personas)"),
    tipo_requerimiento: str = Form(..., min_length=1, description="Tipo de requerimiento"),
    requerimiento: str = Form(..., min_length=1, description="DescripciÃ³n del requerimiento"),
    observaciones: str = Form(..., min_length=1, description="Observaciones adicionales"),
    coords: str = Form(..., description='Coordenadas GPS en formato GeoJSON Point: {"type": "Point", "coordinates": [lng, lat]}'),
    organismos_encargados: str = Form(..., description="Lista de nombres de centros gestores en formato JSON array"),
    direccion: Optional[str] = Form(None, description="DirecciÃ³n del requerimiento (texto)"),
    nota_voz: Optional[UploadFile] = File(None, description="Archivo de audio opcional"),
    fotos: List[UploadFile] = File(default=[], description="Fotos/documentos adjuntos (mÃºltiples archivos)")
):
    """
    Registrar un nuevo requerimiento con datos del solicitante y coordenadas GPS.
    El barrio/vereda y comuna/corregimiento se determinan automÃ¡ticamente por intersecciÃ³n geogrÃ¡fica.
    """
    try:
        # Parsear datos del solicitante
        try:
            datos_solicitante_dict = json.loads(datos_solicitante)
            if not isinstance(datos_solicitante_dict, dict):
                raise ValueError("datos_solicitante debe ser un diccionario JSON")
            if len(datos_solicitante_dict) == 0:
                raise ValueError("datos_solicitante no puede estar vacÃ­o")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"Formato de datos_solicitante invÃ¡lido. Debe ser un diccionario JSON no vacÃ­o: {str(e)}"
            )
        
        # Parsear coordenadas GPS en formato GeoJSON Point
        try:
            coords_dict = json.loads(coords)
            if not isinstance(coords_dict, dict):
                raise ValueError("coords debe ser un objeto JSON")
            if coords_dict.get('type') != 'Point':
                raise ValueError("coords debe ser de tipo GeoJSON Point (type: 'Point')")
            coordinates = coords_dict.get('coordinates')
            if not isinstance(coordinates, list) or len(coordinates) != 2:
                raise ValueError("coordinates debe ser un array de 2 elementos [lng, lat]")
            
            lng = float(coordinates[0])
            lat = float(coordinates[1])
            
            if not (-90 <= lat <= 90):
                raise ValueError(f"Latitud invÃ¡lida: {lat}. Debe estar entre -90 y 90")
            if not (-180 <= lng <= 180):
                raise ValueError(f"Longitud invÃ¡lida: {lng}. Debe estar entre -180 y 180")
            
            # Normalizar coords con valores validados
            coords_dict = {"type": "Point", "coordinates": [lng, lat]}
            
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
            raise HTTPException(
                status_code=400,
                detail=f'Formato de coords invÃ¡lido. Debe ser GeoJSON Point: {{"type": "Point", "coordinates": [lng, lat]}}. Error: {str(e)}'
            )
        
        # GeolocalizaciÃ³n automÃ¡tica: intersecciÃ³n con basemaps
        geo_result = geolocate_point(lng, lat)
        barrio_vereda = geo_result["barrio_vereda"]
        comuna_corregimiento = geo_result["comuna_corregimiento"]
        
        # Parsear organismos encargados
        try:
            organismos_list = json.loads(organismos_encargados)
            if not isinstance(organismos_list, list):
                raise ValueError("organismos_encargados debe ser un array")
            organismos_list = [str(org) for org in organismos_list]
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"Formato de organismos_encargados invÃ¡lido. Debe ser un JSON array: {str(e)}"
            )
        
        # Generar RID con consecutivo incremental dentro de cada visita
        try:
            requerimientos_ref = db.collection('requerimientos')
            requerimientos_visita = requerimientos_ref.where('vid', '==', vid).get()
            
            if len(requerimientos_visita) > 0:
                max_rid = max(doc.to_dict().get('rid_number', 0) for doc in requerimientos_visita)
                new_rid_number = max_rid + 1
            else:
                new_rid_number = 1
            
            rid = f"REQ-{new_rid_number}"
            
        except Exception as e:
            print(f"âŒ Error generando RID: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error generando RID: {str(e)}"
            )
        
        # Procesar archivo de audio si se proporciona
        nota_voz_url = None
        if nota_voz and nota_voz.filename:
            try:
                allowed_audio_types = [
                    "audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg",
                    "audio/webm", "audio/m4a", "audio/x-m4a", "audio/mp4",
                    "video/mp4",  # iOS Safari graba nota de voz como video/mp4
                ]
                if nota_voz.content_type not in allowed_audio_types:
                    raise ValueError(f"Tipo de archivo no permitido: {nota_voz.content_type}. Permitidos: {', '.join(allowed_audio_types)}")

                audio_content = await nota_voz.read()
                audio_extension = os.path.splitext(nota_voz.filename)[1] or '.mp3'
                audio_filename = f"requerimientos/{vid}/{rid}/nota_voz_{uuid.uuid4().hex}{audio_extension}.gz"
                
                # Comprimir con gzip para ahorrar espacio en S3
                compressed_content = gzip.compress(audio_content)
                print(f"ðŸ“¦ CompresiÃ³n: {len(audio_content)} bytes â†’ {len(compressed_content)} bytes ({100 - len(compressed_content)*100//len(audio_content)}% ahorro)")
                
                s3_client = get_s3_client()
                bucket_name = os.getenv('S3_BUCKET_NAME', 'catatrack-photos')
                
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=audio_filename,
                    Body=compressed_content,
                    ContentType=nota_voz.content_type,
                    ContentEncoding='gzip'
                )
                
                nota_voz_url = f"https://{bucket_name}.s3.amazonaws.com/{audio_filename}"
                print(f"âœ… Nota de voz subida a S3: {nota_voz_url}")
                
            except Exception as e:
                print(f"âš ï¸ Advertencia: Error subiendo nota de voz: {str(e)}")

        # Procesar fotos/documentos adjuntos
        documentos_urls = []
        if fotos:
            try:
                import mimetypes
                s3_client_fotos = get_s3_client()
                bucket_name_fotos = os.getenv('S3_BUCKET_NAME', 'catatrack-photos')
                allowed_extensions = {
                    ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif",
                    ".pdf", ".gif", ".bmp", ".tiff", ".tif",
                }
                print(f"ðŸ“Ž Recibidas {len(fotos)} fotos/documentos para {vid}/{rid}")
                for i, foto in enumerate(fotos):
                    if not foto or not foto.filename:
                        print(f"  â­ï¸ foto[{i}]: sin archivo o nombre vacÃ­o, omitido")
                        continue
                    # Determinar content_type real: preferir extensiÃ³n del archivo
                    ext = os.path.splitext(foto.filename)[1].lower()
                    guessed_type, _ = mimetypes.guess_type(foto.filename)
                    content_type = foto.content_type
                    if content_type in (None, "", "application/octet-stream") and guessed_type:
                        content_type = guessed_type
                    print(f"  ðŸ“„ foto[{i}]: {foto.filename} | ext={ext} | content_type_original={foto.content_type} | content_type_final={content_type}")
                    # Validar por extensiÃ³n (mÃ¡s confiable que content_type del cliente)
                    if ext not in allowed_extensions:
                        print(f"  âš ï¸ ExtensiÃ³n no permitida, omitido: {foto.filename} (ext={ext})")
                        continue
                    file_content = await foto.read()
                    if len(file_content) == 0:
                        print(f"  â­ï¸ foto[{i}]: archivo vacÃ­o (0 bytes), omitido")
                        continue
                    safe_name = re.sub(r'[^\w.\-]', '_', foto.filename)
                    s3_key = f"requerimientos/{vid}/{rid}/{uuid.uuid4().hex}_{safe_name}"
                    s3_client_fotos.put_object(
                        Bucket=bucket_name_fotos, Key=s3_key,
                        Body=file_content, ContentType=content_type or "application/octet-stream",
                    )
                    documentos_urls.append({
                        "filename": foto.filename, "s3_key": s3_key,
                        "s3_url": f"https://{bucket_name_fotos}.s3.amazonaws.com/{s3_key}",
                        "content_type": content_type or "application/octet-stream", "size": len(file_content),
                    })
                    print(f"  âœ… Documento subido a S3: {s3_key} ({len(file_content)} bytes)")
            except Exception as e:
                import traceback
                print(f"âš ï¸ Error subiendo fotos/documentos: {str(e)}")
                traceback.print_exc()

        # Capturar fecha y hora de registro
        fecha_registro = now_colombia()
        
        # Crear ID Ãºnico para el documento
        doc_id = f"{vid}_{rid}"
        
        # Preparar datos para guardar en Firebase
        requerimiento_data = {
            "vid": vid,
            "rid": rid,
            "rid_number": new_rid_number,
            "datos_solicitante": datos_solicitante_dict,
            "tipo_requerimiento": tipo_requerimiento,
            "requerimiento": requerimiento,
            "observaciones": observaciones,
            "direccion": direccion,
            "barrio_vereda": barrio_vereda,
            "comuna_corregimiento": comuna_corregimiento,
            "coords": coords_dict,
            "estado": "Pendiente",
            "nota_voz_url": nota_voz_url,
            "documentos_s3": [{"filename": d["filename"], "s3_key": d["s3_key"],
                               "content_type": d["content_type"], "size": d["size"]}
                              for d in documentos_urls],
            "fecha_registro": fecha_registro.isoformat(),
            "organismos_encargados": organismos_list,
            "created_at": now_colombia().isoformat(),
            "timestamp": now_colombia().isoformat()
        }
        
        # Guardar en Firebase
        try:
            db.collection('requerimientos').document(doc_id).set(requerimiento_data)
            print(f"âœ… Requerimiento {rid} para visita {vid} guardado en Firebase")
        except Exception as e:
            print(f"âŒ Error guardando en Firebase: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error guardando en Firebase: {str(e)}"
            )
        
        return RegistroRequerimientoResponse(
            success=True,
            vid=vid,
            rid=rid,
            message="Requerimiento registrado exitosamente",
            datos_solicitante=datos_solicitante_dict,
            tipo_requerimiento=tipo_requerimiento,
            requerimiento=requerimiento,
            observaciones=observaciones,
            direccion=direccion,
            barrio_vereda=barrio_vereda,
            comuna_corregimiento=comuna_corregimiento,
            coords=coords_dict,
            estado="Pendiente",
            nota_voz_url=nota_voz_url,
            documentos_urls=documentos_urls if documentos_urls else None,
            fecha_registro=fecha_registro.isoformat(),
            organismos_encargados=organismos_list,
            timestamp=now_colombia().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error registrando requerimiento: {str(e)}"
        )


# ==================== ENDPOINT: Obtener Requerimientos ====================#
@router.get(
    "/obtener-requerimientos",
    summary="ðŸ”µ GET | Obtener Requerimientos",
    description="""
## ðŸ”µ GET | Obtener Requerimientos

**PropÃ³sito**: Obtener todos los requerimientos registrados en la colecciÃ³n "requerimientos".
Se puede filtrar opcionalmente por VID (visita).

### ðŸ“¥ ParÃ¡metros opcionales:
- **vid**: Filtrar requerimientos por ID de visita (ej: VID-1)

### ðŸ“ Ejemplo de uso:
```javascript
// Todos los requerimientos
const response = await fetch('/obtener-requerimientos');

// Filtrar por visita
const response = await fetch('/obtener-requerimientos?vid=VID-1');
```

### âœ… Respuesta exitosa:
```json
{
    "success": true,
    "total": 15,
    "requerimientos": [
        {
            "id": "VID-1_REQ-1",
            "vid": "VID-1",
            "rid": "REQ-1",
            "datos_solicitante": {...},
            "requerimiento": "Solicitud de mejoramiento vial",
            "observaciones": "VÃ­a en mal estado",
            "barrio_vereda": "San Pedro",
            "comuna_corregimiento": "COMUNA 03",
            "coords": {"type": "Point", "coordinates": [-76.532, 3.4516]},
            "estado": "Pendiente",
            "organismos_encargados": ["DAGMA"],
            "fecha_registro": "2026-04-14T05:09:34.325667",
            "timestamp": "2026-04-14T05:09:34.325667"
        }
    ]
}
```
    """,
)
async def obtener_requerimientos(
    vid: Optional[str] = Query(None, description="Filtrar por ID de visita (ej: VID-1)")
):
    """
    Obtener todos los requerimientos de la colecciÃ³n 'requerimientos'.
    Incluye documentos_con_enlaces con URLs presignadas de S3 para cada requerimiento.
    """
    try:
        requerimientos_ref = db.collection('requerimientos')

        if vid:
            docs = requerimientos_ref.where('vid', '==', vid).stream()
        else:
            docs = requerimientos_ref.stream()

        # Crear cliente S3 una sola vez para generar presigned URLs
        s3_client = None
        try:
            s3_client = get_s3_client()
        except Exception as e:
            print(f"âš ï¸ No se pudo crear cliente S3 para URLs presignadas: {e}")

        requerimientos = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id

            # Listar documentos de S3 con URLs presignadas
            req_vid = data.get('vid', '')
            req_rid = data.get('rid', '')
            if req_vid and req_rid and s3_client:
                documentos = _listar_documentos_s3(req_vid, req_rid, s3_client=s3_client)
                data['documentos_con_enlaces'] = documentos
                data['total_documentos'] = len(documentos)
            else:
                data['documentos_con_enlaces'] = []
                data['total_documentos'] = 0

            requerimientos.append(clean_nan_values(data))

        return {
            "success": True,
            "total": len(requerimientos),
            "requerimientos": requerimientos
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error obteniendo requerimientos: {str(e)}"
        )
