"""Constantes de roles y permisos."""

DEFAULT_USER_ROLE = "visualizador"

ROLES = {
    "super_admin": {
        "name": "Super Administrador",
        "level": 0,
        "description": "Control total del sistema",
        "permissions": ["*", "manage:users", "manage:roles", "view:audit_logs"],
    },
    "admin_general": {
        "name": "Administrador General",
        "level": 1,
        "description": "Administración general de datos y roles",
        "permissions": ["manage:roles", "view:audit_logs"],
    },
    "admin_centro_gestor": {
        "name": "Administrador Centro Gestor",
        "level": 2,
        "description": "Administración de su centro gestor",
        "permissions": ["manage:roles", "view:audit_logs"],
    },
    "editor_datos": {
        "name": "Editor de Datos",
        "level": 3,
        "description": "Edición de datos",
        "permissions": [],
    },
    "analista": {
        "name": "Analista",
        "level": 4,
        "description": "Análisis de datos",
        "permissions": [],
    },
    "visualizador": {
        "name": "Visualizador",
        "level": 5,
        "description": "Solo lectura básica",
        "permissions": [],
    },
    "publico": {
        "name": "Público",
        "level": 6,
        "description": "Acceso muy limitado",
        "permissions": [],
    },
}
