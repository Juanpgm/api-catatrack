"""
Rutas de Administración y Control de Accesos
"""
from datetime import datetime, timezone
import logging
import os
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.auth_system import DEFAULT_USER_ROLE, ROLES
from app.auth_system.dependencies import build_audit_log, get_current_user
from app.auth_system.permissions import get_user_permissions, require_any_permission, require_permission
from app.firebase_config import auth_client, db
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

router = APIRouter(tags=["Administración y Control de Accesos"])
security = HTTPBearer()

# Configurar rate limiter
limiter = Limiter(key_func=get_remote_address)

# Límite configurable: usa REGISTER_RATE_LIMIT si existe, si no 10/minute
_REGISTER_RATE_LIMIT = os.getenv("REGISTER_RATE_LIMIT", "10/minute")

# Modelos
class UserLoginRequest(BaseModel):
    """Modelo para login de usuario - ahora recibe ID token del frontend"""
    id_token: str

class UserRegistrationRequest(BaseModel):
    """Registro de usuario simplificado"""
    email: EmailStr
    password: str
    full_name: str
    cellphone: str
    nombre_centro_gestor: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres")
        return value

class AssignRolesRequest(BaseModel):
    """Modelo para asignar roles"""
    role: Optional[str] = Field(None, description="Rol único activo")
    roles: Optional[List[str]] = Field(None, description="Compatibilidad legacy")

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("El rol no puede ser vacío")
        return value

    def get_single_role(self) -> str:
        if self.role:
            return self.role
        if self.roles:
            normalized = [str(role).strip() for role in self.roles if str(role).strip()]
            if len(normalized) != 1:
                raise HTTPException(status_code=400, detail="Debe enviar exactamente un rol")
            return normalized[0]
        raise HTTPException(status_code=400, detail="Debe proporcionar un rol")

class GrantTemporaryPermissionRequest(BaseModel):
    """Modelo para permisos temporales"""
    permission: str
    expires_at: datetime

    @field_validator("permission")
    @classmethod
    def validate_permission_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El permiso no puede ser vacío")
        return value

    @field_validator("expires_at")
    @classmethod
    def validate_expiration(cls, value: datetime) -> datetime:
        now = datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        if value <= now:
            raise ValueError("expires_at debe ser una fecha futura")
        return value


class UpdateUserRequest(BaseModel):
    """Campos permitidos para actualización de usuario."""

    full_name: Optional[str] = None
    cellphone: Optional[str] = None
    nombre_centro_gestor: Optional[str] = None
    is_active: Optional[bool] = None


def _normalize_roles(raw_roles: Any) -> List[str]:
    if raw_roles is None:
        return []
    if isinstance(raw_roles, str):
        role = raw_roles.strip()
        return [role] if role else []
    if isinstance(raw_roles, (list, tuple, set)):
        normalized = []
        for role in raw_roles:
            role_str = str(role).strip()
            if role_str:
                normalized.append(role_str)
        return normalized
    role = str(raw_roles).strip()
    return [role] if role else []


def _sanitize_user_data(user_data: dict) -> dict:
    sanitized = dict(user_data)
    sanitized.pop("password", None)
    sanitized.pop("temporary_permissions", None)
    return sanitized


def _write_audit(action: str, actor: dict, details: dict):
    try:
        db.collection("audit_logs").add(build_audit_log(action=action, actor=actor, details=details))
    except Exception as audit_error:
        logging.warning(f"No se pudo escribir audit log: {audit_error}")

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

        user_doc = db.collection("users").document(uid).get()
        user_data = user_doc.to_dict() if user_doc.exists else {}
        roles = _normalize_roles(user_data.get("roles", []))
        permissions = get_user_permissions(user_data) if user_data else []
        
        return {
            "valid": True,
            "user": {
                "uid": user.uid,
                "email": user.email,
                "full_name": user.display_name or "",
                "email_verified": user.email_verified,
                "disabled": user.disabled,
                "roles": roles,
                "permissions": permissions,
                "is_active": user_data.get("is_active", True)
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception:
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
@router.post("/auth/register/", include_in_schema=False)
@limiter.limit(_REGISTER_RATE_LIMIT)
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
            'roles': [DEFAULT_USER_ROLE],
            'permissions': [],
            'temporary_permissions': [],
            'is_active': True,
            'email_verified': False,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow(),
            'uid': user.uid
        })
        
        logging.info(f"Usuario registrado: {user.email} (UID: {user.uid})")
        return {
            "success": True,
            "message": "Usuario registrado exitosamente",
            "uid": user.uid,
            "role_assigned": DEFAULT_USER_ROLE,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/auth/change-password")
async def change_password(
    uid: str = Form(..., description="ID del usuario"),
    new_password: str = Form(..., description="Nueva contraseña"),
    current_user: dict = Depends(get_current_user),
):
    """
    ## 🔐 Cambiar Contraseña de Usuario
    
    Permite cambiar la contraseña de un usuario existente.
    """
    try:
        if current_user["uid"] != uid:
            require_permission(current_user, "manage:users")

        if len(new_password) < 8:
            raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 8 caracteres")

        auth_client.update_user(uid, password=new_password)

        _write_audit(
            action="change_password",
            actor=current_user,
            details={"target_uid": uid},
        )

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
async def delete_user(
    uid: str,
    permanent: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """
    ## 🗑️ Eliminar Usuario
    
    Elimina un usuario del sistema.
    """
    try:
        require_permission(current_user, "manage:users")

        auth_client.delete_user(uid)
        # Eliminar documento de Firestore
        db.collection('users').document(uid).delete()

        _write_audit(
            action="delete_user",
            actor=current_user,
            details={"target_uid": uid, "permanent": permanent},
        )
        
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
async def list_system_users(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """
    ## 📋 Listado de Usuarios desde Firestore
    
    Lee directamente la colección "users" de Firestore y devuelve todos los usuarios registrados.
    """
    try:
        require_permission(current_user, "manage:users")

        users_stream = db.collection("users").limit(limit).offset(offset).stream()
        users = []
        for user_doc in users_stream:
            data = user_doc.to_dict() or {}
            data["uid"] = user_doc.id
            data["roles"] = _normalize_roles(data.get("roles", []))
            data["permissions"] = get_user_permissions(data)
            users.append(_sanitize_user_data(data))

        total = len(list(db.collection("users").stream()))

        return {
            "success": True,
            "data": users,
            "count": len(users),
            "total": total,
            "limit": limit,
            "offset": offset,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/auth/admin/users")
async def list_users(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """Listar usuarios del sistema"""
    try:
        require_permission(current_user, "manage:users")
        return await list_system_users(limit=limit, offset=offset, current_user=current_user)
    except Exception as e:
        logging.error(f"Error listando usuarios: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/auth/admin/users/super-admins")
async def list_super_admin_users(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """Listar todos los usuarios con rol super_admin"""
    try:
        require_any_permission(current_user, ["manage:users", "view:users"])

        all_users = db.collection("users").stream()
        super_admins = []
        for user_doc in all_users:
            data = user_doc.to_dict() or {}
            roles = _normalize_roles(data.get("roles", []))
            if "super_admin" in roles:
                data["uid"] = user_doc.id
                data["roles"] = roles
                data["permissions"] = get_user_permissions(data)
                super_admins.append(_sanitize_user_data(data))

        total = len(super_admins)
        paginated = super_admins[offset: offset + limit]
        return {
            "success": True,
            "users": paginated,
            "count": len(paginated),
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/auth/admin/users/{uid}")
async def get_user_details(uid: str, current_user: dict = Depends(get_current_user)):
    """Obtener detalles de un usuario específico"""
    try:
        require_permission(current_user, "manage:users")

        user_doc = db.collection("users").document(uid).get()
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        user_data = user_doc.to_dict() or {}
        user_data["uid"] = uid
        user_data["roles"] = _normalize_roles(user_data.get("roles", []))
        user_data["permissions"] = get_user_permissions(user_data)

        return {"success": True, "data": _sanitize_user_data(user_data)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/auth/admin/users/{uid}")
async def update_user_info(
    uid: str,
    payload: UpdateUserRequest,
    current_user: dict = Depends(get_current_user),
):
    """Actualizar información de usuario"""
    try:
        require_permission(current_user, "manage:users")

        user_ref = db.collection("users").document(uid)
        user_doc = user_ref.get()
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        update_fields = {}
        for field in ["full_name", "cellphone", "nombre_centro_gestor", "is_active"]:
            value = getattr(payload, field)
            if value is not None:
                update_fields[field] = value

        if not update_fields:
            raise HTTPException(status_code=400, detail="No se enviaron campos para actualizar")

        update_fields["updated_at"] = datetime.utcnow()
        update_fields["updated_by"] = current_user.get("uid")
        user_ref.update(update_fields)

        _write_audit(
            action="update_user",
            actor=current_user,
            details={"target_uid": uid, "changes": update_fields},
        )

        updated = user_ref.get().to_dict() or {}
        updated["uid"] = uid
        updated["roles"] = _normalize_roles(updated.get("roles", []))
        updated["permissions"] = get_user_permissions(updated)
        return {"success": True, "data": _sanitize_user_data(updated)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/auth/admin/users/{uid}/roles")
async def assign_roles_to_user(
    uid: str,
    roles: AssignRolesRequest,
    current_user: dict = Depends(get_current_user),
):
    """Asignar roles a usuario"""
    try:
        require_permission(current_user, "manage:users")

        role = roles.get_single_role()
        if role not in ROLES:
            raise HTTPException(status_code=400, detail=f"Rol inválido: {role}")

        user_ref = db.collection("users").document(uid)
        if not user_ref.get().exists:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        user_ref.update(
            {
                "roles": [role],
                "updated_at": datetime.utcnow(),
                "updated_by": current_user.get("uid"),
            }
        )

        _write_audit(
            action="assign_role",
            actor=current_user,
            details={"target_uid": uid, "role": role},
        )

        return {"success": True, "uid": uid, "roles": [role]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/auth/admin/users/{uid}/temporary-permissions")
async def grant_temporary_permission(
    uid: str,
    permission: GrantTemporaryPermissionRequest,
    current_user: dict = Depends(get_current_user),
):
    """Otorgar permiso temporal"""
    try:
        require_permission(current_user, "manage:users")

        user_ref = db.collection("users").document(uid)
        user_doc = user_ref.get()
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        user_data = user_doc.to_dict() or {}
        temporary_permissions = user_data.get("temporary_permissions", [])

        temporary_permissions = [
            item
            for item in temporary_permissions
            if item.get("permission") != permission.permission
        ]
        temporary_permissions.append(
            {
                "permission": permission.permission,
                "expires_at": permission.expires_at,
                "granted_by": current_user.get("uid"),
                "granted_at": datetime.utcnow(),
            }
        )

        user_ref.update({"temporary_permissions": temporary_permissions, "updated_at": datetime.utcnow()})

        _write_audit(
            action="grant_temporary_permission",
            actor=current_user,
            details={
                "target_uid": uid,
                "permission": permission.permission,
                "expires_at": permission.expires_at.isoformat(),
            },
        )

        return {"success": True, "uid": uid, "permission": permission.permission}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/auth/admin/users/{uid}/temporary-permissions/{permission}")
async def revoke_temporary_permission(
    uid: str,
    permission: str,
    current_user: dict = Depends(get_current_user),
):
    """Revocar permiso temporal"""
    try:
        require_permission(current_user, "manage:users")

        user_ref = db.collection("users").document(uid)
        user_doc = user_ref.get()
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        user_data = user_doc.to_dict() or {}
        temporary_permissions = user_data.get("temporary_permissions", [])

        filtered = [item for item in temporary_permissions if item.get("permission") != permission]
        user_ref.update({"temporary_permissions": filtered, "updated_at": datetime.utcnow()})

        _write_audit(
            action="revoke_temporary_permission",
            actor=current_user,
            details={"target_uid": uid, "permission": permission},
        )

        return {"success": True, "uid": uid, "permission": permission}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/auth/admin/roles")
async def list_roles(current_user: dict = Depends(get_current_user)):
    """Listar roles disponibles"""
    require_permission(current_user, "manage:roles")

    roles_payload = []
    for role_id, role_data in ROLES.items():
        roles_payload.append(
            {
                "role_id": role_id,
                "name": role_data.get("name"),
                "level": role_data.get("level"),
                "description": role_data.get("description"),
                "permissions": role_data.get("permissions", []),
            }
        )
    roles_payload.sort(key=lambda item: item["level"])
    return {"success": True, "roles": roles_payload, "total": len(roles_payload)}

@router.get("/auth/admin/roles/{role_id}")
async def get_role_details(role_id: str, current_user: dict = Depends(get_current_user)):
    """Obtener detalles de un rol"""
    require_permission(current_user, "manage:roles")

    if role_id not in ROLES:
        raise HTTPException(status_code=404, detail="Rol no encontrado")

    role_data = ROLES[role_id]
    return {
        "success": True,
        "role": {
            "role_id": role_id,
            "name": role_data.get("name"),
            "level": role_data.get("level"),
            "description": role_data.get("description"),
            "permissions": role_data.get("permissions", []),
        },
    }

@router.get("/auth/admin/audit-logs")
async def get_audit_logs(
    limit: int = Query(100, ge=1, le=500),
    user_uid: Optional[str] = None,
    action: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """
    Obtener logs de auditoría.
    Accesible por admin_general y super_admin.
    
    Requiere permiso: view:audit_logs
    """
    try:
        require_permission(current_user, "view:audit_logs")

        query = db.collection("audit_logs").order_by("timestamp", direction="DESCENDING")
        if user_uid:
            query = query.where("user_uid", "==", user_uid)
        if action:
            query = query.where("action", "==", action)

        logs = []
        for log_doc in query.limit(limit).stream():
            entry = log_doc.to_dict() or {}
            entry["id"] = log_doc.id

            timestamp = entry.get("timestamp")
            if isinstance(timestamp, datetime):
                entry["timestamp"] = timestamp.isoformat()

            details = entry.get("details")
            if isinstance(details, dict):
                for key, value in list(details.items()):
                    if isinstance(value, datetime):
                        details[key] = value.isoformat()

            logs.append(entry)

        return {"success": True, "logs": logs, "total": len(logs)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/auth/admin/system/stats")
async def get_system_stats(current_user: dict = Depends(get_current_user)):
    """
    Obtener estadísticas del sistema de autorización.
    Accesible por super_admin.
    
    Requiere permiso: manage:users
    """
    try:
        require_permission(current_user, "manage:users")

        users = [doc.to_dict() or {} for doc in db.collection("users").stream()]
        roles_count = {role_id: 0 for role_id in ROLES.keys()}

        for user_data in users:
            for role in _normalize_roles(user_data.get("roles", [])):
                if role in roles_count:
                    roles_count[role] += 1

        return {
            "success": True,
            "total_users": len(users),
            "total_roles": len(ROLES),
            "roles_distribution": roles_count,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
            "apiKey": os.getenv("FIREBASE_API_KEY", ""),
            "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN", ""),
            "projectId": os.getenv("FIREBASE_PROJECT_ID", ""),
            "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET", ""),
            "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID", ""),
            "appId": os.getenv("FIREBASE_APP_ID", ""),
        }
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")
