"""
Configuración de Firebase Admin SDK
"""
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore, auth
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Obtener el contenido JSON de la clave de servicio
SERVICE_ACCOUNT_JSON = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')

if not SERVICE_ACCOUNT_JSON:
    raise ValueError("FIREBASE_SERVICE_ACCOUNT_JSON no está configurada en el archivo .env")

# Parsear el JSON
try:
    service_account_info = json.loads(SERVICE_ACCOUNT_JSON)
except json.JSONDecodeError:
    raise ValueError("FIREBASE_SERVICE_ACCOUNT_JSON no es un JSON válido")

# Inicializar Firebase Admin SDK
cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred)

# Obtener referencias a los servicios
db = firestore.client()
auth_client = auth

print("Firebase inicializado correctamente")