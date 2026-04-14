"""
Rutas para gestión de Artefacto de Captura DAGMA
"""
from fastapi import APIRouter, HTTPException, Form, UploadFile, File, Query, Body
from typing import List, Optional
from datetime import datetime
import json
import uuid
import math
import os
import io
from pydantic import BaseModel, Field
import httpx
from shapely.geometry import shape, Point

# Importar configuración de Firebase y S3/Storage
from app.firebase_config import db
import boto3
from botocore.exceptions import ClientError

router = APIRouter(tags=["Artefacto de Captura"])


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
    Valida coordenadas según el tipo de geometría
    """
    if not isinstance(coordinates, list):
        raise ValueError("Las coordenadas deben ser un array")
    
    if geometry_type == "Point":
        if len(coordinates) != 2:
            raise ValueError("Point debe tener exactamente 2 coordenadas [lon, lat]")
        lon, lat = coordinates
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
            raise ValueError("Las coordenadas deben ser números")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Longitud inválida: {lon}. Debe estar entre -180 y 180")
        if not (-90 <= lat <= 90):
            raise ValueError(f"Latitud inválida: {lat}. Debe estar entre -90 y 90")
    
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
                raise ValueError("Cada anillo del polígono debe tener al menos 4 puntos")
    
    return True


def validate_photo_file(file: UploadFile) -> bool:
    """
    Valida que el archivo sea una imagen válida
    """
    # Validar tipo MIME
    allowed_types = ["image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic"]
    if file.content_type not in allowed_types:
        raise ValueError(f"Tipo de archivo no permitido: {file.content_type}. Permitidos: {', '.join(allowed_types)}")
    
    # Validar extensión
    allowed_extensions = [".jpg", ".jpeg", ".png", ".webp", ".heic"]
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        raise ValueError(f"Extensión no permitida: {file_ext}")
    
    return True


def get_s3_client():
    """
    Crear cliente de S3 con las credenciales del entorno
    """
    aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
    aws_region = os.getenv('AWS_REGION', 'us-east-1')
    
    if not aws_access_key or not aws_secret_key:
        raise ValueError("Credenciales de AWS no configuradas. Verifica AWS_ACCESS_KEY_ID y AWS_SECRET_ACCESS_KEY")
    
    return boto3.client(
        's3',
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        region_name=aws_region
    )


# ==================== GEOLOCALIZACIÓN ====================#
# Cargar basemaps en memoria al iniciar el módulo
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
        print(f"✅ Basemap '{filepath}' cargado: {len(polygons)} polígonos")
        return polygons
    except Exception as e:
        print(f"⚠️ Error cargando basemap '{filepath}': {str(e)}")
        return []

_BARRIOS_POLYGONS = _load_basemap('basemaps/barrios_veredas.geojson', 'barrio_vereda')
_COMUNAS_POLYGONS = _load_basemap('basemaps/comunas_corregimientos.geojson', 'comuna_corregimiento')


def geolocate_point(lon: float, lat: float) -> dict:
    """
    Realiza intersección geográfica de un punto con los polígonos de barrios/veredas
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


# ==================== MODELOS ====================#
class AcompananteModel(BaseModel):
    """Modelo para datos de acompañante"""
    nombre_completo: str
    telefono: str
    email: str
    centro_gestor: str


class RegistroVisitaRequest(BaseModel):
    """Modelo de solicitud para registro de visitas"""
    barrio_vereda: str = Field(..., min_length=1, description="Nombre del barrio o vereda")
    comuna_corregimiento: str = Field(..., min_length=1, description="Comuna o corregimiento")
    descripcion_visita: str = Field(..., min_length=1, description="Descripción de la visita")
    observaciones_visita: str = Field(..., min_length=1, description="Observaciones de la visita")
    acompanantes: Optional[List[AcompananteModel]] = Field(None, description="Lista de acompañantes (opcional)")
    fecha_visita: str = Field(..., description="Fecha de la visita en formato dd/mm/aaaa")
    hora_visita: str = Field(..., description="Hora de la visita en formato HH:mm (hora Bogotá)")


class RegistroVisitaResponse(BaseModel):
    """Modelo de respuesta para registro de visitas"""
    success: bool
    vid: str
    message: str
    barrio_vereda: str
    comuna_corregimiento: str
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
    barrio_vereda: Optional[str]
    comuna_corregimiento: Optional[str]
    coords: dict
    estado: str
    nota_voz_url: Optional[str]
    fecha_registro: str
    organismos_encargados: List[str]
    timestamp: str


# ==================== ENDPOINT 1: Inicialización de Unidades de Proyecto ====================#
GESTORPROYECTO_API_BASE = "https://gestorproyectoapi-production.up.railway.app"


@router.get(
    "/init/unidades-proyecto",
    summary="🔵 GET | Inicialización de Unidades de Proyecto",
    description="""
## 🔵 GET | Inicialización de Unidades de Proyecto

**Propósito**: Obtener datos iniciales de unidades de proyecto para el artefacto de captura.

### ✅ Respuesta
Retorna la respuesta original de la API de GestorProyecto.

### 📝 Ejemplo de uso:
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
    summary="🟢 POST | Registro de Visita",
    description="""
## 🟢 POST | Registro de Visita

**Propósito**: Registrar una visita realizada con información de ubicación,
descripción, observaciones, acompañantes y fecha/hora.

### ✅ Campos requeridos:
- **barrio_vereda**: Nombre del barrio o vereda (texto)
- **comuna_corregimiento**: Comuna o corregimiento (texto)
- **descripcion_visita**: Descripción de la visita (texto)
- **observaciones_visita**: Observaciones de la visita (texto)
- **acompanantes**: (Opcional) Array JSON con datos de acompañantes: [{"nombre_completo", "telefono", "email", "centro_gestor"}, ...]
- **fecha_visita**: Fecha de la visita en formato dd/mm/aaaa
- **hora_visita**: Hora de la visita en formato HH:mm (hora de Bogotá, Colombia)

### 🔢 VID (ID de Visita):
El sistema genera automáticamente un ID único con formato **VID-#** donde # es un 
consecutivo incremental. Ejemplo: VID-1, VID-2, VID-3...

### 📝 Ejemplo de uso con JSON:
```javascript
const response = await fetch('/registrar-visita/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        barrio_vereda: 'San Fernando',
        comuna_corregimiento: 'Comuna 3',
        descripcion_visita: 'Visita de inspección ambiental',
        observaciones_visita: 'Se encontraron residuos sólidos en la zona',
        acompanantes: [
            {
                nombre_completo: 'Juan Pérez',
                telefono: '3001234567',
                email: 'juan@example.com',
                centro_gestor: 'Centro Gestor Norte'
            },
            {
                nombre_completo: 'María López',
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

### ✅ Respuesta exitosa:
```json
{
    "success": true,
    "vid": "VID-1",
    "message": "Visita registrada exitosamente",
    "barrio_vereda": "San Fernando",
    "comuna_corregimiento": "Comuna 3",
    "descripcion_visita": "Visita de inspección ambiental",
    "observaciones_visita": "Se encontraron residuos sólidos en la zona",
    "acompanantes": [
        {
            "nombre_completo": "Juan Pérez",
            "telefono": "3001234567",
            "email": "juan@example.com",
            "centro_gestor": "Centro Gestor Norte"
        },
        {
            "nombre_completo": "María López",
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
    Registrar una visita con información de ubicación, descripción, acompañantes y fecha/hora
    """
    import re

    try:
        barrio_vereda = payload.barrio_vereda
        comuna_corregimiento = payload.comuna_corregimiento
        descripcion_visita = payload.descripcion_visita
        observaciones_visita = payload.observaciones_visita
        acompanantes = payload.acompanantes
        fecha_visita = payload.fecha_visita
        hora_visita = payload.hora_visita

        # Validar formato fecha_visita dd/mm/aaaa
        if not re.match(r'^\d{2}/\d{2}/\d{4}$', fecha_visita):
            raise HTTPException(
                status_code=400,
                detail="Formato de fecha_visita inválido. Debe ser dd/mm/aaaa (ejemplo: 13/04/2026)"
            )
        try:
            datetime.strptime(fecha_visita, "%d/%m/%Y")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Fecha inválida: {fecha_visita}. Verifique que sea una fecha real en formato dd/mm/aaaa"
            )

        # Validar formato hora_visita HH:mm
        if not re.match(r'^\d{2}:\d{2}$', hora_visita):
            raise HTTPException(
                status_code=400,
                detail="Formato de hora_visita inválido. Debe ser HH:mm (ejemplo: 14:30)"
            )
        try:
            datetime.strptime(hora_visita, "%H:%M")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Hora inválida: {hora_visita}. Verifique que sea una hora real en formato HH:mm"
            )

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
            print(f"❌ Error generando VID: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error generando VID: {str(e)}"
            )

        # Preparar datos para guardar en Firebase
        visita_data = {
            "vid": vid,
            "vid_number": new_vid_number,
            "barrio_vereda": barrio_vereda,
            "comuna_corregimiento": comuna_corregimiento,
            "descripcion_visita": descripcion_visita,
            "observaciones_visita": observaciones_visita,
            "acompanantes": [a.model_dump() for a in acompanantes] if acompanantes else None,
            "fecha_visita": fecha_visita,
            "hora_visita": hora_visita,
            "created_at": datetime.utcnow().isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        }

        # Guardar en Firebase
        try:
            db.collection('visitas').document(vid).set(visita_data)
            print(f"✅ Visita {vid} guardada en Firebase")
        except Exception as e:
            print(f"❌ Error guardando en Firebase: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error guardando en Firebase: {str(e)}"
            )

        return RegistroVisitaResponse(
            success=True,
            vid=vid,
            message="Visita registrada exitosamente",
            barrio_vereda=barrio_vereda,
            comuna_corregimiento=comuna_corregimiento,
            descripcion_visita=descripcion_visita,
            observaciones_visita=observaciones_visita,
            acompanantes=[a.model_dump() for a in acompanantes] if acompanantes else None,
            fecha_visita=fecha_visita,
            hora_visita=hora_visita,
            timestamp=datetime.utcnow().isoformat()
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
    summary="🔵 GET | Obtener Visitas Programadas",
    description="""
## 🔵 GET | Obtener Visitas Programadas

**Propósito**: Obtener todos los registros de la colección "visitas" almacenados en Firebase.

### 📝 Ejemplo de uso:
```javascript
const response = await fetch('/obtener-visitas-programadas/');
const data = await response.json();
```

### ✅ Respuesta exitosa:
```json
{
    "success": true,
    "total": 2,
    "visitas": [
        {
            "vid": "VID-1",
            "barrio_vereda": "San Fernando",
            "comuna_corregimiento": "Comuna 3",
            "descripcion_visita": "Visita de inspección ambiental",
            "observaciones_visita": "Se encontraron residuos sólidos",
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
    Obtener todos los registros de la colección visitas
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
    summary="🔵 GET | Obtener Reportes",
    description="""
## 🔵 GET | Obtener Reportes del Grupo Operativo

**Propósito**: Consultar todos los reportes registrados por el grupo operativo.

### ✅ Respuesta
Retorna lista de reportes con sus detalles.

### 📝 Ejemplo de uso:
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
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error obteniendo reportes: {str(e)}"
        )


# ==================== ENDPOINT 4: Eliminar Reporte ====================#
@router.delete(
    "/grupo-operativo/eliminar-reporte",
    summary="🔴 DELETE | Eliminar Reporte",
    description="""
## 🔴 DELETE | Eliminar Reporte del Grupo Operativo

**Propósito**: Eliminar un reporte específico del sistema, incluyendo las fotos en S3.

### 📥 Parámetros
- **reporte_id**: ID único del reporte a eliminar

### 🗑️ Acciones realizadas:
1. Eliminar imágenes del bucket S3 (360-dagma-photos)
2. Eliminar documento de Firebase (reconocimientos_dagma)

### 📝 Ejemplo de uso:
```javascript
const response = await fetch('/grupo-operativo/eliminar-reporte?reporte_id=abc-123', {
    method: 'DELETE'
});
```

### ✅ Respuesta exitosa:
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
                bucket_name = os.getenv('AWS_S3_BUCKET_NAME', '360-dagma-photos')
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
            "timestamp": datetime.utcnow().isoformat()
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
    summary="🟢 POST | Registrar Asistencia de Delegado",
    description="""
## 🟢 POST | Registrar Asistencia de Delegado

**Propósito**: Registrar la asistencia de un delegado o acompañante a una visita,
incluyendo información personal, ubicación GPS y timestamp del registro.

### ✅ Campos requeridos:
- **vid**: ID de la visita (texto)
- **id_acompanante**: ID único del acompañante (texto)
- **nombre_completo**: Nombre completo del delegado (texto)
- **rol**: Rol o cargo del delegado (texto)
- **nombre_centro_gestor**: Nombre del centro gestor (texto)
- **telefono**: Número de teléfono de contacto (texto)
- **email**: Correo electrónico (texto)
- **latitud**: Latitud GPS (número como texto)
- **longitud**: Longitud GPS (número como texto)

### 📝 Ejemplo de uso con form-urlencoded:
```javascript
const data = new URLSearchParams();
data.append('vid', 'VID-1');
data.append('id_acompanante', 'ACMP-001');
data.append('nombre_completo', 'Juan Pérez García');
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

### ✅ Respuesta exitosa:
```json
{
    "success": true,
    "vid": "VID-1",
    "id_acompanante": "ACMP-001",
    "message": "Asistencia de delegado registrada exitosamente",
    "nombre_completo": "Juan Pérez García",
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
    id_acompanante: str = Form(..., min_length=1, description="ID del acompañante"),
    nombre_completo: str = Form(..., min_length=1, description="Nombre completo del delegado"),
    rol: str = Form(..., min_length=1, description="Rol o cargo del delegado"),
    nombre_centro_gestor: str = Form(..., min_length=1, description="Nombre del centro gestor"),
    telefono: str = Form(..., min_length=1, description="Número de teléfono de contacto"),
    email: str = Form(..., min_length=1, description="Correo electrónico"),
    latitud: str = Form(..., description="Latitud GPS"),
    longitud: str = Form(..., description="Longitud GPS")
):
    """
    Registrar la asistencia de un delegado o acompañante a una visita
    """
    try:
        # Validar y parsear coordenadas
        try:
            lat = float(latitud)
            lng = float(longitud)

            # Validar rango de coordenadas
            if not (-90 <= lat <= 90):
                raise ValueError(f"Latitud inválida: {lat}. Debe estar entre -90 y 90")
            if not (-180 <= lng <= 180):
                raise ValueError(f"Longitud inválida: {lng}. Debe estar entre -180 y 180")

        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error en coordenadas: {str(e)}"
            )

        # Validar formato de email básico
        if "@" not in email or "." not in email:
            raise HTTPException(
                status_code=400,
                detail="Formato de email inválido"
            )

        # Generar timestamp del momento del registro
        fecha_registro = datetime.utcnow()

        # Crear ID único para el documento (combinación de VID e ID_acompanante)
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
            print(f"✅ Asistencia de delegado {id_acompanante} para visita {vid} guardada en Firebase")
        except Exception as e:
            print(f"❌ Error guardando en Firebase: {str(e)}")
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
            timestamp=datetime.utcnow().isoformat()
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
    summary="🟢 POST | Registrar Asistencia de Comunidad",
    description="""
## 🟢 POST | Registrar Asistencia de Comunidad

**Propósito**: Registrar la asistencia de un miembro de la comunidad a una visita,
incluyendo información personal, dirección, ubicación GPS y timestamp del registro.

### ✅ Campos requeridos:
- **vid**: ID de la visita (texto)
- **id_asistente_comunidad**: ID único del asistente de la comunidad (texto)
- **nombre_completo**: Nombre completo del asistente (texto)
- **rol_comunidad**: Rol en la comunidad (texto)
- **direccion**: Dirección de residencia (texto)
- **barrio_vereda**: Nombre del barrio o vereda (texto)
- **comuna_corregimiento**: Comuna o corregimiento (texto)
- **telefono**: Número de teléfono de contacto (texto)
- **email**: Correo electrónico (texto)
- **latitud**: Latitud GPS (número como texto)
- **longitud**: Longitud GPS (número como texto)

### ✅ Respuesta exitosa:
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
    direccion: str = Form(..., min_length=1, description="Dirección de residencia"),
    barrio_vereda: str = Form(..., min_length=1, description="Nombre del barrio o vereda"),
    comuna_corregimiento: str = Form(..., min_length=1, description="Comuna o corregimiento"),
    telefono: str = Form(..., min_length=1, description="Número de teléfono de contacto"),
    email: str = Form(..., min_length=1, description="Correo electrónico"),
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
                raise ValueError(f"Latitud inválida: {lat}. Debe estar entre -90 y 90")
            if not (-180 <= lng <= 180):
                raise ValueError(f"Longitud inválida: {lng}. Debe estar entre -180 y 180")

        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error en coordenadas: {str(e)}"
            )

        # Validar formato de email básico
        if "@" not in email or "." not in email:
            raise HTTPException(
                status_code=400,
                detail="Formato de email inválido"
            )

        # Generar timestamp del momento del registro
        fecha_registro = datetime.utcnow()

        # Crear ID único para el documento (combinación de VID e ID_asistente_comunidad)
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
            print(f"✅ Asistencia de comunidad {id_asistente_comunidad} para visita {vid} guardada en Firebase")
        except Exception as e:
            print(f"❌ Error guardando en Firebase: {str(e)}")
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
            timestamp=datetime.utcnow().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error registrando asistencia de comunidad: {str(e)}"
        )


# ==================== ENDPOINT: Registrar Requerimiento ====================#
@router.post(
    "/registrar-requerimiento",
    summary="🟢 POST | Registrar Requerimiento",
    description="""
## 🟢 POST | Registrar Requerimiento

**Propósito**: Registrar un nuevo requerimiento con datos del solicitante,
coordenadas GPS del dispositivo, nota de voz opcional y organismos encargados.
El sistema determina automáticamente el barrio/vereda y comuna/corregimiento
mediante intersección geográfica con los basemaps.

### ✅ Campos requeridos:
- **vid**: ID de la visita (texto)
- **datos_solicitante**: Datos del solicitante en formato JSON string (diccionario con datos de una o más personas)
- **requerimiento**: Descripción del requerimiento (texto)
- **observaciones**: Observaciones adicionales (texto)
- **coords**: Coordenadas GPS en formato GeoJSON Point string `{"type": "Point", "coordinates": [lng, lat]}`
- **organismos_encargados**: Lista de nombres de centros gestores en formato JSON array `["nombre1", "nombre2"]`

### 📥 Campos opcionales:
- **nota_voz**: Archivo de audio (opcional)

### 🔢 RID (ID de Requerimiento):
El sistema genera automáticamente un ID único con formato **REQ-#** donde # es un 
consecutivo incremental dentro de cada visita. Ejemplo: REQ-1, REQ-2, REQ-3...

### 📍 Estado:
Por defecto, el registro se crea con estado "Pendiente".

### 📍 Coordenadas GPS:
Debes enviar las coordenadas como un string JSON en formato GeoJSON Point:
```json
{"type": "Point", "coordinates": [-76.5320, 3.4516]}
```
El sistema automáticamente determinará el barrio/vereda y la comuna/corregimiento
correspondientes usando intersección geográfica.

### 👤 Datos del Solicitante:
Se envía como un diccionario JSON que puede contener datos de una o más personas:
```json
{
    "personas": [
        {"nombre": "María López", "email": "maria@example.com", "telefono": "+57 300 1234567", "centro_gestor": "DAGMA"},
        {"nombre": "Juan Pérez", "email": "juan@example.com", "telefono": "+57 310 9876543"}
    ]
}
```

### 🎤 Nota de Voz:
Si se incluye un archivo de audio, este se sube a S3 y se retorna la URL.

### 📝 Ejemplo de uso con FormData:
```javascript
const coords = JSON.stringify({type: "Point", coordinates: [-76.5320, 3.4516]});
const organismos = JSON.stringify(["DAGMA", "Secretaría de Obras"]);
const datosSolicitante = JSON.stringify({
    personas: [
        {nombre: "María López", email: "maria@example.com", telefono: "+57 300 1234567", centro_gestor: "DAGMA"}
    ]
});

const formData = new FormData();
formData.append('vid', 'VID-1');
formData.append('datos_solicitante', datosSolicitante);
formData.append('requerimiento', 'Solicitud de mejoramiento vial');
formData.append('observaciones', 'Urgente, vía en mal estado');
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

### ✅ Respuesta exitosa:
```json
{
    "success": true,
    "vid": "VID-1",
    "rid": "REQ-1",
    "message": "Requerimiento registrado exitosamente",
    "datos_solicitante": {"personas": [{"nombre": "María López", "email": "maria@example.com"}]},
    "requerimiento": "Solicitud de mejoramiento vial",
    "observaciones": "Urgente, vía en mal estado",
    "barrio_vereda": "San Fernando",
    "comuna_corregimiento": "COMUNA 03",
    "coords": {"type": "Point", "coordinates": [-76.5320, 3.4516]},
    "estado": "Pendiente",
    "nota_voz_url": "https://s3.amazonaws.com/bucket/audio.mp3",
    "fecha_registro": "2026-02-06T15:30:45.123456",
    "organismos_encargados": ["DAGMA", "Secretaría de Obras"],
    "timestamp": "2026-02-06T15:30:45.123456"
}
```
    """,
    response_model=RegistroRequerimientoResponse
)
async def post_registrar_requerimiento(
    vid: str = Form(..., min_length=1, description="ID de la visita"),
    datos_solicitante: str = Form(..., min_length=1, description="Datos del solicitante en formato JSON (diccionario con datos de una o más personas)"),
    tipo_requerimiento: str = Form(..., min_length=1, description="Tipo de requerimiento"),
    requerimiento: str = Form(..., min_length=1, description="Descripción del requerimiento"),
    observaciones: str = Form(..., min_length=1, description="Observaciones adicionales"),
    coords: str = Form(..., description='Coordenadas GPS en formato GeoJSON Point: {"type": "Point", "coordinates": [lng, lat]}'),
    organismos_encargados: str = Form(..., description="Lista de nombres de centros gestores en formato JSON array"),
    nota_voz: Optional[UploadFile] = File(None, description="Archivo de audio opcional")
):
    """
    Registrar un nuevo requerimiento con datos del solicitante y coordenadas GPS.
    El barrio/vereda y comuna/corregimiento se determinan automáticamente por intersección geográfica.
    """
    try:
        # Parsear datos del solicitante
        try:
            datos_solicitante_dict = json.loads(datos_solicitante)
            if not isinstance(datos_solicitante_dict, dict):
                raise ValueError("datos_solicitante debe ser un diccionario JSON")
            if len(datos_solicitante_dict) == 0:
                raise ValueError("datos_solicitante no puede estar vacío")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"Formato de datos_solicitante inválido. Debe ser un diccionario JSON no vacío: {str(e)}"
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
                raise ValueError(f"Latitud inválida: {lat}. Debe estar entre -90 y 90")
            if not (-180 <= lng <= 180):
                raise ValueError(f"Longitud inválida: {lng}. Debe estar entre -180 y 180")
            
            # Normalizar coords con valores validados
            coords_dict = {"type": "Point", "coordinates": [lng, lat]}
            
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
            raise HTTPException(
                status_code=400,
                detail=f'Formato de coords inválido. Debe ser GeoJSON Point: {{"type": "Point", "coordinates": [lng, lat]}}. Error: {str(e)}'
            )
        
        # Geolocalización automática: intersección con basemaps
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
                detail=f"Formato de organismos_encargados inválido. Debe ser un JSON array: {str(e)}"
            )
        
        # Generar RID con consecutivo incremental dentro de cada visita
        try:
            requerimientos_ref = db.collection('requerimientos_dagma')
            requerimientos_visita = requerimientos_ref.where('vid', '==', vid).order_by('rid_number', direction='DESCENDING').limit(1).get()
            
            if len(requerimientos_visita) > 0:
                last_rid_number = requerimientos_visita[0].to_dict().get('rid_number', 0)
                new_rid_number = last_rid_number + 1
            else:
                new_rid_number = 1
            
            rid = f"REQ-{new_rid_number}"
            
        except Exception as e:
            print(f"❌ Error generando RID: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error generando RID: {str(e)}"
            )
        
        # Procesar archivo de audio si se proporciona
        nota_voz_url = None
        if nota_voz and nota_voz.filename:
            try:
                allowed_audio_types = ["audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg", "audio/webm", "audio/m4a", "audio/x-m4a"]
                if nota_voz.content_type not in allowed_audio_types:
                    raise ValueError(f"Tipo de archivo no permitido: {nota_voz.content_type}. Permitidos: {', '.join(allowed_audio_types)}")
                
                audio_content = await nota_voz.read()
                audio_extension = os.path.splitext(nota_voz.filename)[1] or '.mp3'
                audio_filename = f"requerimientos/{vid}/{rid}/nota_voz_{uuid.uuid4().hex}{audio_extension}"
                
                s3_client = get_s3_client()
                bucket_name = os.getenv('AWS_S3_BUCKET_NAME', '360-dagma-photos')
                
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=audio_filename,
                    Body=audio_content,
                    ContentType=nota_voz.content_type
                )
                
                nota_voz_url = f"https://{bucket_name}.s3.amazonaws.com/{audio_filename}"
                print(f"✅ Nota de voz subida a S3: {nota_voz_url}")
                
            except Exception as e:
                print(f"⚠️ Advertencia: Error subiendo nota de voz: {str(e)}")
        
        # Capturar fecha y hora de registro
        fecha_registro = datetime.utcnow()
        
        # Crear ID único para el documento
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
            "barrio_vereda": barrio_vereda,
            "comuna_corregimiento": comuna_corregimiento,
            "coords": coords_dict,
            "estado": "Pendiente",
            "nota_voz_url": nota_voz_url,
            "fecha_registro": fecha_registro.isoformat(),
            "organismos_encargados": organismos_list,
            "created_at": datetime.utcnow().isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Guardar en Firebase
        try:
            db.collection('requerimientos_dagma').document(doc_id).set(requerimiento_data)
            print(f"✅ Requerimiento {rid} para visita {vid} guardado en Firebase")
        except Exception as e:
            print(f"❌ Error guardando en Firebase: {str(e)}")
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
            barrio_vereda=barrio_vereda,
            comuna_corregimiento=comuna_corregimiento,
            coords=coords_dict,
            estado="Pendiente",
            nota_voz_url=nota_voz_url,
            fecha_registro=fecha_registro.isoformat(),
            organismos_encargados=organismos_list,
            timestamp=datetime.utcnow().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error registrando requerimiento: {str(e)}"
        )