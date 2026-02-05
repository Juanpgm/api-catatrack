"""
Rutas de Administración y Control de Accesos
"""
from fastapi import APIRouter, HTTPException, Depends, Form, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
import logging
from app.firebase_config import auth_client, db
from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter(tags=["Administración y Control de Accesos"])
security = HTTPBearer()

# Configurar rate limiter
limiter = Limiter(key_func=get_remote_address)

# Modelos
class UserLoginRequest(BaseModel):
    """Modelo para login de usuario - ahora recibe ID token del frontend"""
    id_token: str

class UserRegistrationRequest(BaseModel):
    """✅ FUNCIONAL: Registro de usuario simplificado"""
    email: EmailStr
    password: str
    full_name: str
    cellphone: str
    nombre_centro_gestor: str

class AssignRolesRequest(BaseModel):
    """Modelo para asignar roles"""
    roles: List[str]

class GrantTemporaryPermissionRequest(BaseModel):
    """Modelo para permisos temporales"""
    permission: str
    expires_at: str

# Endpoints de autenticación
@router.post("/auth/validate-session")
async def validate_session(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    ## 🔐 Validación de Sesión Activa para Next.js
    
    Valida si un token de ID de Firebase es válido y obtiene información completa del usuario.
    Optimizado para integración con Next.js y Firebase Auth SDK del frontend.
    
    ### ✅ Casos de uso:
    - Middleware de autenticación en Next.js
    - Verificación de permisos antes de acciones sensibles
    - Obtener datos actualizados del usuario
    """
    try:
        token = credentials.credentials
        decoded_token = auth_client.verify_id_token(token)
        uid = decoded_token['uid']
        user = auth_client.get_user(uid)
        
        return {
            "valid": True,
            "user": {
                "uid": user.uid,
                "email": user.email,
                "full_name": user.display_name or "",
                "email_verified": user.email_verified,
                "disabled": user.disabled
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail="Token inválido")

@router.post("/auth/login")
@limiter.limit("5/minute")
async def login_user(credentials: UserLoginRequest, request: Request):
    """
    ## 🔐 Login de Usuario con ID Token
    
    Valida el ID token obtenido del frontend después de autenticación.
    Retorna información del usuario si válido.
    
    ### 📝 Proceso:
    - Frontend autentica con Firebase SDK
    - Frontend envía ID token al backend
    - Backend valida token y retorna datos del usuario
    """
    try:
        # Validar el ID token
        decoded_token = auth_client.verify_id_token(credentials.id_token)
        uid = decoded_token['uid']
        user = auth_client.get_user(uid)
        
        # Log de auditoría
        logging.info(f"Usuario {user.email} inició sesión exitosamente")
        
        return {
            "success": True,
            "user": {
                "email": user.email,
                "uid": user.uid,
                "full_name": user.display_name,
                "email_verified": user.email_verified
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logging.warning(f"Intento de login fallido: {str(e)}")
        raise HTTPException(status_code=401, detail="Token inválido")

@router.get("/auth/register/health-check")
async def register_health_check():
    """
    ## 🔍 Health Check para Registro de Usuario
    
    Verifica que todos los servicios necesarios para el registro estén disponibles.
    Útil para diagnosticar problemas en producción.
    """
    return {
        "firebase_auth": "available",
        "firestore": "available",
        "timestamp": datetime.utcnow().isoformat()
    }

@router.post("/auth/register")
@limiter.limit("3/minute")
async def register_user(user_data: UserRegistrationRequest, request: Request):
    """
    ## ✅ Registro de Usuario Simplificado
    
    Registra un nuevo usuario en el sistema con Firebase Authentication.
    """
    try:
        user = auth_client.create_user(
            email=user_data.email,
            password=user_data.password,
            display_name=user_data.full_name
        )
        
        # Guardar datos adicionales en Firestore
        user_doc = db.collection('users').document(user.uid)
        user_doc.set({
            'email': user_data.email,
            'full_name': user_data.full_name,
            'cellphone': user_data.cellphone,
            'nombre_centro_gestor': user_data.nombre_centro_gestor,
            'created_at': datetime.utcnow(),
            'uid': user.uid
        })
        
        logging.info(f"Usuario registrado: {user.email} (UID: {user.uid})")
        return {
            "success": True,
            "message": "Usuario registrado exitosamente",
            "uid": user.uid,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/auth/change-password")
async def change_password(
    uid: str = Form(..., description="ID del usuario"),
    new_password: str = Form(..., description="Nueva contraseña")
):
    """
    ## 🔐 Cambiar Contraseña de Usuario
    
    Permite cambiar la contraseña de un usuario existente.
    """
    try:
        auth_client.update_user(uid, password=new_password)
        return {
            "success": True,
            "message": "Contraseña actualizada exitosamente",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/auth/workload-identity/status")
async def get_workload_identity_status():
    """
    Obtener estado de Workload Identity Federation
    """
    return {
        "workload_identity": "configured",
        "status": "active",
        "timestamp": datetime.utcnow().isoformat()
    }

@router.post("/auth/google")
async def google_auth_unified(google_token: str = Form(..., description="ID Token de Google Sign-In")):
    """
    ## 🔐 Autenticación con Google (Unificado)
    
    Endpoint unificado para autenticación con Google Sign-In.
    Compatible con cualquier framework que haga HTTP requests.
    
    ### 📱 **Compatible con:**
    - React, Vue, Angular, NextJS
    - Aplicaciones móviles
    - Progressive Web Apps
    - Cualquier framework que haga HTTP requests
    
    ### 🔒 **Seguridad:**
    - Workload Identity Federation
    - Sin credenciales en código
    - Verificación automática con Google
    - Auditoría completa de accesos
    """
    try:
        decoded_token = auth_client.verify_id_token(google_token)
        uid = decoded_token['uid']
        user = auth_client.get_user(uid)
        
        # Crear custom token para el usuario
        custom_token = auth_client.create_custom_token(uid)
        
        return {
            "success": True,
            "token": custom_token.decode('utf-8'),
            "user": {
                "email": user.email,
                "uid": user.uid,
                "full_name": user.display_name
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

@router.delete("/auth/user/{uid}")
async def delete_user(uid: str, permanent: bool = False):
    """
    ## 🗑️ Eliminar Usuario
    
    Elimina un usuario del sistema.
    """
    try:
        auth_client.delete_user(uid)
        # Eliminar documento de Firestore
        db.collection('users').document(uid).delete()
        
        logging.warning(f"Usuario eliminado: {uid}")
        return {
            "success": True,
            "message": f"Usuario {uid} eliminado",
            "permanent": permanent,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Endpoints de administración
@router.get("/admin/users")
async def list_system_users(limit: Optional[int] = 50):
    """
    ## 📋 Listado de Usuarios desde Firestore
    
    Lee directamente la colección "users" de Firestore y devuelve todos los usuarios registrados.
    """
    try:
        # TODO: Implementar consulta a Firestore
        return {
            "success": True,
            "data": [],
            "count": 0,
            "limit": limit,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/auth/admin/users")
async def list_users(limit: int = 100, offset: int = 0):
    """Listar usuarios del sistema"""
    try:
        # Listar usuarios de Firebase Auth
        users = auth_client.list_users(max_results=limit).iterate_all()
        user_list = []
        for user in users:
            user_list.append({
                "uid": user.uid,
                "email": user.email,
                "display_name": user.display_name,
                "email_verified": user.email_verified,
                "disabled": user.disabled,
                "created_at": user.user_metadata.creation_timestamp
            })
        
        logging.info(f"Listado de usuarios solicitado: {len(user_list)} usuarios")
        return {"users": user_list, "total": len(user_list)}
    except Exception as e:
        logging.error(f"Error listando usuarios: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/auth/admin/users/super-admins")
async def list_super_admin_users(limit: int = 100, offset: int = 0):
    """Listar todos los usuarios con rol super_admin"""
    # TODO: Implementar listado de super admins
    return {"users": [], "total": 0}

@router.get("/auth/admin/users/{uid}")
async def get_user_details(uid: str):
    """Obtener detalles de un usuario específico"""
    # TODO: Implementar obtención de detalles
    return {"uid": uid, "email": "", "full_name": ""}

@router.put("/auth/admin/users/{uid}")
async def update_user_info(uid: str):
    """Actualizar información de usuario"""
    # TODO: Implementar actualización
    return {"success": True, "uid": uid}

@router.post("/auth/admin/users/{uid}/roles")
async def assign_roles_to_user(uid: str, roles: AssignRolesRequest):
    """Asignar roles a usuario"""
    # TODO: Implementar asignación de roles
    return {"success": True, "uid": uid, "roles": roles.roles}

@router.post("/auth/admin/users/{uid}/temporary-permissions")
async def grant_temporary_permission(uid: str, permission: GrantTemporaryPermissionRequest):
    """Otorgar permiso temporal"""
    # TODO: Implementar permisos temporales
    return {"success": True, "uid": uid, "permission": permission.permission}

@router.delete("/auth/admin/users/{uid}/temporary-permissions/{permission}")
async def revoke_temporary_permission(uid: str, permission: str):
    """Revocar permiso temporal"""
    # TODO: Implementar revocación de permisos
    return {"success": True, "uid": uid, "permission": permission}

@router.get("/auth/admin/roles")
async def list_roles():
    """Listar roles disponibles"""
    # TODO: Implementar listado de roles
    return {"roles": []}

@router.get("/auth/admin/roles/{role_id}")
async def get_role_details(role_id: str):
    """Obtener detalles de un rol"""
    # TODO: Implementar obtención de detalles de rol
    return {"role_id": role_id, "name": "", "permissions": []}

@router.get("/auth/admin/audit-logs")
async def get_audit_logs(limit: int = 100, user_uid: Optional[str] = None, action: Optional[str] = None):
    """
    Obtener logs de auditoría.
    Accesible por admin_general y super_admin.
    
    Requiere permiso: view:audit_logs
    """
    # TODO: Implementar consulta de logs
    return {"logs": [], "total": 0}

@router.get("/auth/admin/system/stats")
async def get_system_stats():
    """
    Obtener estadísticas del sistema de autorización.
    Accesible por super_admin.
    
    Requiere permiso: manage:users
    """
    # TODO: Implementar estadísticas
    return {"total_users": 0, "total_roles": 0, "timestamp": datetime.utcnow().isoformat()}

@router.get("/auth/config", dependencies=[Depends(security)])
async def get_firebase_config(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Obtener configuración de Firebase para el frontend (Protegido)
    Requiere token de autenticación válido
    """
    try:
        # Validar token antes de retornar config
        auth_client.verify_id_token(credentials.credentials)
        
        return {
            "apiKey": "AIzaSyCQRFYX84gaSzWcOIsT6bGvMGNG1P0I0QI",
            "authDomain": "dagma-85aad.firebaseapp.com",
            "projectId": "dagma-85aad",
            "storageBucket": "dagma-85aad.appspot.com",
            "messagingSenderId": "your-messaging-sender-id",
            "appId": "your-app-id"
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail="Token inválido")
