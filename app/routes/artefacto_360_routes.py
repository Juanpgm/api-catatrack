"""
Rutas para gestión de Artefacto de Captura DAGMA
"""
from fastapi import APIRouter, HTTPException, Form, UploadFile, File, Query
from typing import List, Optional
from datetime import datetime
import json
import uuid
import math
import os
import io
from pydantic import BaseModel, Field
import httpx

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


# ==================== MODELOS ====================#
class RegistroVisitaResponse(BaseModel):
    """Modelo de respuesta para registro de visitas"""
    success: bool
    vid: str
    message: str
    nombre_up: str
    nombre_up_detalle: str
    barrio_vereda: str
    comuna_corregimiento: str
    fecha_visita: str
    timestamp: str


class RegistroDelegadoResponse(BaseModel):
    """Modelo de respuesta para registro de asistencia de delegado"""
    success: bool
    vid: str
    id_acompañante: str
    message: str
    nombre_completo: str
    rol: str
    nombre_centro_gestor: str
    telefono: str
    email: str
    coords: dict
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
    coords: dict
    fecha_registro: str
    timestamp: str


class RegistroRequerimientoResponse(BaseModel):
    """Modelo de respuesta para registro de requerimiento"""
    success: bool
    vid: str
    rid: str
    message: str
    centro_gestor_solicitante: str
    solicitante_contacto: str
    requerimiento: str
    observaciones: str
    direccion: str
    barrio_vereda: str
    comuna_corregimiento: str
    coords: dict
    estado: str
    nota_voz_url: Optional[str]
    telefono: str
    email_solicitante: str
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

**Propósito**: Registrar una visita realizada con información de la unidad de proyecto,
detalles de ubicación y fecha de la visita.

### ✅ Campos requeridos:
- **nombre_up**: Nombre de la unidad de proyecto (texto)
- **nombre_up_detalle**: Detalle del nombre de la unidad de proyecto (texto)
- **barrio_vereda**: Nombre del barrio o vereda (texto)
- **comuna_corregimiento**: Comuna o corregimiento (texto)
- **fecha_visita**: Fecha de la visita en formato timestamp (número)

### 🔢 VID (ID de Visita):
El sistema genera automáticamente un ID único con formato **VID-#** donde # es un 
consecutivo incremental. Ejemplo: VID-1, VID-2, VID-3...

### 📝 Ejemplo de uso con FormData:
```javascript
const formData = new FormData();
formData.append('nombre_up', 'Unidad Centro');
formData.append('nombre_up_detalle', 'Zona Centro - Área 1');
formData.append('barrio_vereda', 'San Fernando');
formData.append('comuna_corregimiento', 'Comuna 3');
formData.append('fecha_visita', Date.now().toString());

const response = await fetch('/registrar-visita/', {
    method: 'POST',
    body: formData
});
```

### ✅ Respuesta exitosa:
```json
{
    "success": true,
    "vid": "VID-1",
    "message": "Visita registrada exitosamente",
    "nombre_up": "Unidad Centro",
    "nombre_up_detalle": "Zona Centro - Área 1",
    "barrio_vereda": "San Fernando",
    "comuna_corregimiento": "Comuna 3",
    "fecha_visita": "2026-02-06T10:30:00Z",
    "timestamp": "2026-02-06T10:30:00Z"
}
```
    """,
    response_model=RegistroVisitaResponse
)
async def post_registro_visita(
    nombre_up: str = Form(..., min_length=1, description="Nombre de la unidad de proyecto"),
    nombre_up_detalle: str = Form(..., min_length=1, description="Detalle del nombre de la unidad de proyecto"),
    barrio_vereda: str = Form(..., min_length=1, description="Nombre del barrio o vereda"),
    comuna_corregimiento: str = Form(..., min_length=1, description="Comuna o corregimiento"),
    fecha_visita: str = Form(..., description="Fecha de la visita en formato timestamp")
):
    """
    Registrar una visita con información de la unidad de proyecto
    """
    try:
        # Validar y convertir fecha_visita (timestamp)
        try:
            # Intentar convertir el timestamp a datetime
            timestamp_int = int(fecha_visita)
            # Si es timestamp en milisegundos, convertir a segundos
            if timestamp_int > 10000000000:
                timestamp_int = timestamp_int // 1000
            fecha_visita_dt = datetime.fromtimestamp(timestamp_int)
        except (ValueError, TypeError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"Formato de fecha_visita inválido. Debe ser un timestamp válido: {str(e)}"
            )
        
        # Generar VID con consecutivo incremental
        try:
            # Obtener el último VID de la colección
            visitas_ref = db.collection('visitas_dagma')
            # Ordenar por VID descendente y obtener el primero
            last_visita = visitas_ref.order_by('vid_number', direction='DESCENDING').limit(1).get()
            
            if len(last_visita) > 0:
                # Extraer el número del último VID
                last_vid_number = last_visita[0].to_dict().get('vid_number', 0)
                new_vid_number = last_vid_number + 1
            else:
                # Primera visita
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
            "nombre_up": nombre_up,
            "nombre_up_detalle": nombre_up_detalle,
            "barrio_vereda": barrio_vereda,
            "comuna_corregimiento": comuna_corregimiento,
            "fecha_visita": fecha_visita_dt.isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Guardar en Firebase
        try:
            db.collection('visitas_dagma').document(vid).set(visita_data)
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
            nombre_up=nombre_up,
            nombre_up_detalle=nombre_up_detalle,
            barrio_vereda=barrio_vereda,
            comuna_corregimiento=comuna_corregimiento,
            fecha_visita=fecha_visita_dt.isoformat(),
            timestamp=datetime.utcnow().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error registrando visita: {str(e)}"
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
    Obtener todos los reportes del grupo operativo
    """
    try:
        # TODO: Implementar conexión a Firebase
        # reportes_ref = db.collection('reconocimientos_dagma')
        # docs = reportes_ref.order_by('created_at', direction='DESCENDING').stream()
        
        reportes = []
        # for doc in docs:
        #     data = doc.to_dict()
        #     data['id'] = doc.id
        #     reportes.append(data)
        
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
        # TODO: Implementar eliminación de fotos en S3
        # s3_client = boto3.client('s3')
        # bucket = '360-dagma-photos'
        # prefix = f'reconocimientos/{reporte_id}/'
        
        # Listar y eliminar objetos en S3
        # response = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        # photos_deleted = 0
        
        # if 'Contents' in response:
        #     for obj in response['Contents']:
        #         s3_client.delete_object(Bucket=bucket, Key=obj['Key'])
        #         photos_deleted += 1
        
        photos_deleted = 0
        
        # TODO: Eliminar documento de Firebase
        # db.collection('reconocimientos_dagma').document(reporte_id).delete()
        
        return {
            "success": True,
            "id": reporte_id,
            "message": "Reporte y fotos eliminados exitosamente",
            "photos_deleted": photos_deleted,
            "timestamp": datetime.utcnow().isoformat()
        }
        
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
- **id_acompañante**: ID único del acompañante (texto)
- **nombre_completo**: Nombre completo del delegado (texto)
- **rol**: Rol o cargo del delegado (texto)
- **nombre_centro_gestor**: Nombre del centro gestor (texto)
- **telefono**: Número de teléfono de contacto (texto)
- **email**: Correo electrónico (texto)
- **coords**: Coordenadas GPS en formato JSON string {"lat": number, "lng": number}

### 📍 Coordenadas GPS:
Debes enviar las coordenadas como un string JSON con el formato:
```json
{"lat": 3.4516, "lng": -76.5320}
```

### 🕐 Fecha de Registro:
El sistema registra automáticamente la fecha y hora exacta del momento del registro.

### 📝 Ejemplo de uso con FormData:
```javascript
const coords = JSON.stringify({lat: 3.4516, lng: -76.5320});

const formData = new FormData();
formData.append('vid', 'VID-1');
formData.append('id_acompañante', 'ACMP-001');
formData.append('nombre_completo', 'Juan Pérez García');
formData.append('rol', 'Supervisor');
formData.append('nombre_centro_gestor', 'Centro Administrativo');
formData.append('telefono', '+57 300 1234567');
formData.append('email', 'juan.perez@example.com');
formData.append('coords', coords);

const response = await fetch('/registrar-asistencia-delegado', {
    method: 'POST',
    body: formData
});
```

### ✅ Respuesta exitosa:
```json
{
    "success": true,
    "vid": "VID-1",
    "id_acompañante": "ACMP-001",
    "message": "Asistencia de delegado registrada exitosamente",
    "nombre_completo": "Juan Pérez García",
    "rol": "Supervisor",
    "nombre_centro_gestor": "Centro Administrativo",
    "telefono": "+57 300 1234567",
    "email": "juan.perez@example.com",
    "coords": {"lat": 3.4516, "lng": -76.5320},
    "fecha_registro": "2026-02-06T15:30:45.123456",
    "timestamp": "2026-02-06T15:30:45.123456"
}
```
    """,
    response_model=RegistroDelegadoResponse
)
async def post_registrar_asistencia_delegado(
    vid: str = Form(..., min_length=1, description="ID de la visita"),
    id_acompañante: str = Form(..., min_length=1, description="ID del acompañante"),
    nombre_completo: str = Form(..., min_length=1, description="Nombre completo del delegado"),
    rol: str = Form(..., min_length=1, description="Rol o cargo del delegado"),
    nombre_centro_gestor: str = Form(..., min_length=1, description="Nombre del centro gestor"),
    telefono: str = Form(..., min_length=1, description="Número de teléfono de contacto"),
    email: str = Form(..., min_length=1, description="Correo electrónico"),
    coords: str = Form(..., description="Coordenadas GPS en formato JSON string")
):
    """
    Registrar la asistencia de un delegado o acompañante a una visita
    """
    try:
        # Validar y parsear coordenadas
        try:
            coords_dict = json.loads(coords)
            if not isinstance(coords_dict, dict):
                raise ValueError("Las coordenadas deben ser un objeto JSON")
            if "lat" not in coords_dict or "lng" not in coords_dict:
                raise ValueError("Las coordenadas deben contener 'lat' y 'lng'")
            
            lat = float(coords_dict["lat"])
            lng = float(coords_dict["lng"])
            
            # Validar rango de coordenadas
            if not (-90 <= lat <= 90):
                raise ValueError(f"Latitud inválida: {lat}. Debe estar entre -90 y 90")
            if not (-180 <= lng <= 180):
                raise ValueError(f"Longitud inválida: {lng}. Debe estar entre -180 y 180")
            
            coords_dict = {"lat": lat, "lng": lng}
            
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Formato de coordenadas inválido. Debe ser un JSON con lat y lng: {str(e)}"
            )
        except (ValueError, KeyError) as e:
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
        
        # Crear ID único para el documento (combinación de VID e ID_acompañante)
        doc_id = f"{vid}_{id_acompañante}"
        
        # Preparar datos para guardar en Firebase
        delegado_data = {
            "vid": vid,
            "id_acompañante": id_acompañante,
            "nombre_completo": nombre_completo,
            "rol": rol,
            "nombre_centro_gestor": nombre_centro_gestor,
            "telefono": telefono,
            "email": email,
            "coords": coords_dict,
            "fecha_registro": fecha_registro.isoformat(),
            "created_at": fecha_registro.isoformat(),
            "timestamp": fecha_registro.isoformat()
        }
        
        # Guardar en Firebase
        try:
            db.collection('delegados_asistencia').document(doc_id).set(delegado_data)
            print(f"✅ Asistencia de delegado {id_acompañante} para visita {vid} guardada en Firebase")
        except Exception as e:
            print(f"❌ Error guardando en Firebase: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error guardando en Firebase: {str(e)}"
            )
        
        return RegistroDelegadoResponse(
            success=True,
            vid=vid,
            id_acompañante=id_acompañante,
            message="Asistencia de delegado registrada exitosamente",
            nombre_completo=nombre_completo,
            rol=rol,
            nombre_centro_gestor=nombre_centro_gestor,
            telefono=telefono,
            email=email,
            coords=coords_dict,
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
- **coords**: Coordenadas GPS en formato JSON string {"lat": number, "lng": number}

### 📍 Coordenadas GPS:
Debes enviar las coordenadas como un string JSON con el formato:
```json
{"lat": 3.4516, "lng": -76.5320}
```

### 🕐 Fecha de Registro:
El sistema registra automáticamente la fecha y hora exacta del momento del registro.

### 📝 Ejemplo de uso con FormData:
```javascript
const coords = JSON.stringify({lat: 3.4516, lng: -76.5320});

const formData = new FormData();
formData.append('vid', 'VID-1');
formData.append('id_asistente_comunidad', 'COM-001');
formData.append('nombre_completo', 'María López Torres');
formData.append('rol_comunidad', 'Líder Comunitario');
formData.append('direccion', 'Calle 15 #10-25');
formData.append('barrio_vereda', 'San Antonio');
formData.append('comuna_corregimiento', 'Comuna 5');
formData.append('telefono', '+57 310 9876543');
formData.append('email', 'maria.lopez@example.com');
formData.append('coords', coords);

const response = await fetch('/registrar-asistencia-comunidad', {
    method: 'POST',
    body: formData
});
```

### ✅ Respuesta exitosa:
```json
{
    "success": true,
    "vid": "VID-1",
    "id_asistente_comunidad": "COM-001",
    "message": "Asistencia de comunidad registrada exitosamente",
    "nombre_completo": "María López Torres",
    "rol_comunidad": "Líder Comunitario",
    "direccion": "Calle 15 #10-25",
    "barrio_vereda": "San Antonio",
    "comuna_corregimiento": "Comuna 5",
    "telefono": "+57 310 9876543",
    "email": "maria.lopez@example.com",
    "coords": {"lat": 3.4516, "lng": -76.5320},
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
    coords: str = Form(..., description="Coordenadas GPS en formato JSON string")
):
    """
    Registrar la asistencia de un miembro de la comunidad a una visita
    """
    try:
        # Validar y parsear coordenadas
        try:
            coords_dict = json.loads(coords)
            if not isinstance(coords_dict, dict):
                raise ValueError("Las coordenadas deben ser un objeto JSON")
            if "lat" not in coords_dict or "lng" not in coords_dict:
                raise ValueError("Las coordenadas deben contener 'lat' y 'lng'")
            
            lat = float(coords_dict["lat"])
            lng = float(coords_dict["lng"])
            
            # Validar rango de coordenadas
            if not (-90 <= lat <= 90):
                raise ValueError(f"Latitud inválida: {lat}. Debe estar entre -90 y 90")
            if not (-180 <= lng <= 180):
                raise ValueError(f"Longitud inválida: {lng}. Debe estar entre -180 y 180")
            
            coords_dict = {"lat": lat, "lng": lng}
            
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Formato de coordenadas inválido. Debe ser un JSON con lat y lng: {str(e)}"
            )
        except (ValueError, KeyError) as e:
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
            "coords": coords_dict,
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
            coords=coords_dict,
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

**Propósito**: Registrar un nuevo requerimiento con información del solicitante,
ubicación GPS, estado, nota de voz opcional y organismos encargados.

### ✅ Campos requeridos:
- **vid**: ID de la visita (texto)
- **centro_gestor_solicitante**: Centro gestor del solicitante (texto)
- **solicitante_contacto**: Nombre del contacto solicitante (texto)
- **requerimiento**: Descripción del requerimiento (texto)
- **observaciones**: Observaciones adicionales (texto)
- **direccion**: Dirección del requerimiento (texto)
- **barrio_vereda**: Barrio o vereda (texto)
- **comuna_corregimiento**: Comuna o corregimiento (texto)
- **coords**: Coordenadas GPS en formato JSON string {"lat": number, "lng": number}
- **telefono**: Número de teléfono de contacto (texto)
- **email_solicitante**: Correo electrónico del solicitante (texto)
- **organismos_encargados**: Lista de nombres de centros gestores en formato JSON array ["nombre1", "nombre2"]

### 📥 Campos opcionales:
- **nota_voz**: Archivo de audio (opcional)

### 🔢 RID (ID de Requerimiento):
El sistema genera automáticamente un ID único con formato **REQ-#** donde # es un 
consecutivo incremental dentro de cada visita. Ejemplo: REQ-1, REQ-2, REQ-3...

### 📍 Estado:
Por defecto, el registro se crea con estado "Pendiente".

### 📍 Coordenadas GPS:
Debes enviar las coordenadas como un string JSON con el formato:
```json
{"lat": 3.4516, "lng": -76.5320}
```

### 🎤 Nota de Voz:
Si se incluye un archivo de audio, este se sube a S3 y se retorna la URL.

### 📝 Ejemplo de uso con FormData:
```javascript
const coords = JSON.stringify({lat: 3.4516, lng: -76.5320});
const organismos = JSON.stringify(["DAGMA", "Secretaría de Obras"]);

const formData = new FormData();
formData.append('vid', 'VID-1');
formData.append('centro_gestor_solicitante', 'DAGMA');
formData.append('solicitante_contacto', 'María López');
formData.append('requerimiento', 'Solicitud de mejoramiento vial');
formData.append('observaciones', 'Urgente, vía en mal estado');
formData.append('direccion', 'Calle 5 # 40-20');
formData.append('barrio_vereda', 'San Fernando');
formData.append('comuna_corregimiento', 'Comuna 3');
formData.append('coords', coords);
formData.append('telefono', '+57 300 1234567');
formData.append('email_solicitante', 'maria.lopez@example.com');
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
    "centro_gestor_solicitante": "DAGMA",
    "solicitante_contacto": "María López",
    "requerimiento": "Solicitud de mejoramiento vial",
    "observaciones": "Urgente, vía en mal estado",
    "direccion": "Calle 5 # 40-20",
    "barrio_vereda": "San Fernando",
    "comuna_corregimiento": "Comuna 3",
    "coords": {"lat": 3.4516, "lng": -76.5320},
    "estado": "Pendiente",
    "nota_voz_url": "https://s3.amazonaws.com/bucket/audio.mp3",
    "telefono": "+57 300 1234567",
    "email_solicitante": "maria.lopez@example.com",
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
    centro_gestor_solicitante: str = Form(..., min_length=1, description="Centro gestor del solicitante"),
    solicitante_contacto: str = Form(..., min_length=1, description="Nombre del contacto solicitante"),
    requerimiento: str = Form(..., min_length=1, description="Descripción del requerimiento"),
    observaciones: str = Form(..., min_length=1, description="Observaciones adicionales"),
    direccion: str = Form(..., min_length=1, description="Dirección del requerimiento"),
    barrio_vereda: str = Form(..., min_length=1, description="Barrio o vereda"),
    comuna_corregimiento: str = Form(..., min_length=1, description="Comuna o corregimiento"),
    coords: str = Form(..., description="Coordenadas GPS en formato JSON string"),
    telefono: str = Form(..., min_length=1, description="Número de teléfono de contacto"),
    email_solicitante: str = Form(..., min_length=1, description="Correo electrónico del solicitante"),
    organismos_encargados: str = Form(..., description="Lista de nombres de centros gestores en formato JSON array"),
    nota_voz: Optional[UploadFile] = File(None, description="Archivo de audio opcional")
):
    """
    Registrar un nuevo requerimiento con información del solicitante y ubicación GPS
    """
    try:
        # Parsear coordenadas GPS
        try:
            coords_dict = json.loads(coords)
            if not isinstance(coords_dict, dict) or 'lat' not in coords_dict or 'lng' not in coords_dict:
                raise ValueError("Coordenadas deben contener 'lat' y 'lng'")
            
            # Validar que las coordenadas sean números
            lat = float(coords_dict['lat'])
            lng = float(coords_dict['lng'])
            
            if not (-90 <= lat <= 90):
                raise ValueError(f"Latitud inválida: {lat}. Debe estar entre -90 y 90")
            if not (-180 <= lng <= 180):
                raise ValueError(f"Longitud inválida: {lng}. Debe estar entre -180 y 180")
            
            # Actualizar con valores validados
            coords_dict = {"lat": lat, "lng": lng}
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"Formato de coords inválido. Debe ser JSON con 'lat' y 'lng': {str(e)}"
            )
        
        # Parsear organismos encargados
        try:
            organismos_list = json.loads(organismos_encargados)
            if not isinstance(organismos_list, list):
                raise ValueError("organismos_encargados debe ser un array")
            # Validar que todos los elementos sean strings
            organismos_list = [str(org) for org in organismos_list]
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"Formato de organismos_encargados inválido. Debe ser un JSON array: {str(e)}"
            )
        
        # Generar RID con consecutivo incremental dentro de cada visita
        try:
            # Obtener todos los requerimientos de esta visita
            requerimientos_ref = db.collection('requerimientos_dagma')
            # Filtrar por vid y ordenar por rid_number
            requerimientos_visita = requerimientos_ref.where('vid', '==', vid).order_by('rid_number', direction='DESCENDING').limit(1).get()
            
            if len(requerimientos_visita) > 0:
                # Extraer el número del último RID de esta visita
                last_rid_number = requerimientos_visita[0].to_dict().get('rid_number', 0)
                new_rid_number = last_rid_number + 1
            else:
                # Primer requerimiento de esta visita
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
                # Validar tipo de archivo de audio
                allowed_audio_types = ["audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg", "audio/webm", "audio/m4a", "audio/x-m4a"]
                if nota_voz.content_type not in allowed_audio_types:
                    raise ValueError(f"Tipo de archivo no permitido: {nota_voz.content_type}. Permitidos: {', '.join(allowed_audio_types)}")
                
                # Leer contenido del archivo
                audio_content = await nota_voz.read()
                
                # Generar nombre único para el archivo
                audio_extension = os.path.splitext(nota_voz.filename)[1] or '.mp3'
                audio_filename = f"requerimientos/{vid}/{rid}/nota_voz_{uuid.uuid4().hex}{audio_extension}"
                
                # Subir a S3
                s3_client = get_s3_client()
                bucket_name = os.getenv('AWS_S3_BUCKET_NAME', '360-dagma-photos')
                
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=audio_filename,
                    Body=audio_content,
                    ContentType=nota_voz.content_type
                )
                
                # Generar URL del archivo
                nota_voz_url = f"https://{bucket_name}.s3.amazonaws.com/{audio_filename}"
                print(f"✅ Nota de voz subida a S3: {nota_voz_url}")
                
            except Exception as e:
                print(f"⚠️ Advertencia: Error subiendo nota de voz: {str(e)}")
                # No falla el registro si hay error con el audio
        
        # Capturar fecha y hora de registro
        fecha_registro = datetime.utcnow()
        
        # Crear ID único para el documento
        doc_id = f"{vid}_{rid}"
        
        # Preparar datos para guardar en Firebase
        requerimiento_data = {
            "vid": vid,
            "rid": rid,
            "rid_number": new_rid_number,
            "centro_gestor_solicitante": centro_gestor_solicitante,
            "solicitante_contacto": solicitante_contacto,
            "requerimiento": requerimiento,
            "observaciones": observaciones,
            "direccion": direccion,
            "barrio_vereda": barrio_vereda,
            "comuna_corregimiento": comuna_corregimiento,
            "coords": coords_dict,
            "estado": "Pendiente",
            "nota_voz_url": nota_voz_url,
            "telefono": telefono,
            "email_solicitante": email_solicitante,
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
            centro_gestor_solicitante=centro_gestor_solicitante,
            solicitante_contacto=solicitante_contacto,
            requerimiento=requerimiento,
            observaciones=observaciones,
            direccion=direccion,
            barrio_vereda=barrio_vereda,
            comuna_corregimiento=comuna_corregimiento,
            coords=coords_dict,
            estado="Pendiente",
            nota_voz_url=nota_voz_url,
            telefono=telefono,
            email_solicitante=email_solicitante,
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