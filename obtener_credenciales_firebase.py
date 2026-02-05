"""
Script para guiar la obtención de credenciales de Firebase
Proyecto: dagma-85aad
"""

def print_header():
    print("\n" + "🔑" * 35)
    print("  GUÍA: CÓMO OBTENER CREDENCIALES DE FIREBASE")
    print("  Proyecto: dagma-85aad")
    print("🔑" * 35 + "\n")

def print_step(number, title):
    print(f"\n{'='*70}")
    print(f"  PASO {number}: {title}")
    print('='*70)

def main():
    print_header()
    
    print_step(1, "Acceder a Firebase Console")
    print("""
    1. Abre tu navegador
    2. Ve a: https://console.firebase.google.com/
    3. Inicia sesión con tu cuenta de Google
    """)
    
    print_step(2, "Seleccionar el Proyecto")
    print("""
    1. En la lista de proyectos, busca: "dagma-85aad"
    2. Click en el proyecto para abrirlo
    """)
    
    print_step(3, "Ir a Project Settings")
    print("""
    1. Click en el ícono de ⚙️ (engranaje) en la parte superior izquierda
    2. Selecciona "Project settings" (Configuración del proyecto)
    """)
    
    print_step(4, "Obtener Service Account Key (Para Backend)")
    print("""
    1. En Project Settings, click en la pestaña "Service accounts"
    2. Verás una sección "Firebase Admin SDK"
    3. Click en el botón "Generate new private key"
    4. Aparecerá un mensaje de advertencia
    5. Click en "Generate key"
    6. Se descargará un archivo JSON (ejemplo: dagma-85aad-xxxxx.json)
    
    ⚠️ IMPORTANTE: Este archivo contiene credenciales PRIVADAS
       - Guárdalo en un lugar seguro
       - NO lo subas a GitHub
       - NO lo compartas públicamente
    """)
    
    print_step(5, "Agregar el Service Account a .env")
    print("""
    PowerShell (Windows):
    ---------------------
    # 1. Ir al directorio del proyecto
    cd A:\\programing_workspace\\api-artefacto-360-dagma
    
    # 2. Ver el contenido del archivo descargado (en tu carpeta de Descargas)
    Get-Content "$env:USERPROFILE\\Downloads\\dagma-85aad-*.json"
    
    # 3. Copiar el contenido al portapapeles
    Get-Content "$env:USERPROFILE\\Downloads\\dagma-85aad-*.json" | Set-Clipboard
    
    # 4. Editar .env
    notepad .env
    
    # 5. Pegar el JSON completo en una sola línea:
    # FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account",...todo el json aqui...}
    
    
    Linux/Mac:
    ----------
    # 1. Ver el contenido
    cat ~/Downloads/dagma-85aad-*.json
    
    # 2. Copiar al portapapeles (Mac)
    cat ~/Downloads/dagma-85aad-*.json | pbcopy
    
    # 3. Editar .env
    nano .env
    
    # 4. Pegar: FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
    """)
    
    print_step(6, "Obtener Firebase Client Config (Para Frontend)")
    print("""
    1. En Project Settings, ve a la pestaña "General"
    2. Baja hasta la sección "Your apps" (Tus aplicaciones)
    3. Si no tienes una app web, click en "Add app" (</>) Web
    4. Registra la app con un nombre (ejemplo: "DAGMA Web App")
    5. Verás un bloque de código con firebaseConfig
    
    Copia estos valores:
    -------------------
    const firebaseConfig = {
      apiKey: "AIzaSy...",
      authDomain: "dagma-85aad.firebaseapp.com",
      projectId: "dagma-85aad",
      storageBucket: "dagma-85aad.appspot.com",
      messagingSenderId: "123456789",
      appId: "1:123456789:web:xxxxx"
    };
    
    Estos valores van en el .env del FRONTEND (proyecto Vite):
    ----------------------------------------------------------
    VITE_FIREBASE_API_KEY=AIzaSy...
    VITE_FIREBASE_AUTH_DOMAIN=dagma-85aad.firebaseapp.com
    VITE_FIREBASE_PROJECT_ID=dagma-85aad
    VITE_FIREBASE_STORAGE_BUCKET=dagma-85aad.appspot.com
    VITE_FIREBASE_MESSAGING_SENDER_ID=123456789
    VITE_FIREBASE_APP_ID=1:123456789:web:xxxxx
    """)
    
    print_step(7, "Verificar la Configuración")
    print("""
    Ejecuta el script de verificación:
    
    python verify_config.py
    
    Debe mostrar:
    ✅ FIREBASE_SERVICE_ACCOUNT_JSON encontrada y válida
    ✅ Project ID: dagma-85aad
    ✅ Conexión con Firebase Authentication exitosa
    ✅ Conexión con Firestore exitosa
    """)
    
    print_step(8, "Formato del .env Final")
    print("""
    Tu archivo .env debe verse así:
    
    # Firebase Admin SDK (Backend)
    FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"dagma-85aad","private_key_id":"xxx","private_key":"-----BEGIN PRIVATE KEY-----\\nXXX\\n-----END PRIVATE KEY-----\\n","client_email":"firebase-adminsdk-xxx@dagma-85aad.iam.gserviceaccount.com","client_id":"xxx","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_x509_cert_url":"xxx"}
    
    # AWS S3 (Opcional)
    AWS_ACCESS_KEY_ID=tu_key
    AWS_SECRET_ACCESS_KEY=tu_secret
    AWS_REGION=us-east-1
    S3_BUCKET_NAME=360-dagma-photos
    
    # API Config
    API_ENV=development
    API_HOST=0.0.0.0
    API_PORT=8000
    """)
    
    print("\n" + "="*70)
    print("  ⚠️  RECORDATORIOS DE SEGURIDAD")
    print("="*70)
    print("""
    ✅ El archivo .env ya está en .gitignore
    ✅ Tus credenciales NO se subirán a GitHub
    ❌ NUNCA compartas el Service Account JSON públicamente
    ❌ NO lo incluyas en el código fuente
    ✅ Usa variables de entorno en producción (Railway, etc.)
    """)
    
    print("\n" + "="*70)
    print("  📚 RECURSOS ADICIONALES")
    print("="*70)
    print("""
    📖 Guía completa: CONFIGURACION_VARIABLES_ENTORNO.md
    🔍 Verificación: python verify_config.py
    🔥 Firebase Console: https://console.firebase.google.com/project/dagma-85aad
    """)
    
    print("\n" + "🔑" * 35)
    print("  ¡Listo! Sigue estos pasos para obtener tus credenciales")
    print("🔑" * 35 + "\n")

if __name__ == "__main__":
    main()
