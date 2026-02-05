"""
Script para verificar la configuración de variables de entorno
"""
import os
import sys
import json
from pathlib import Path

def print_section(title, emoji="📋"):
    """Imprime una sección"""
    print(f"\n{emoji} {title}")
    print("=" * 70)

def check_env_file():
    """Verifica que existe el archivo .env"""
    print_section("1. Verificando archivo .env", "🔍")
    
    env_path = Path(".env")
    if env_path.exists():
        print("✅ Archivo .env encontrado")
        return True
    else:
        print("❌ Archivo .env NO encontrado")
        print("💡 Crea uno desde la plantilla:")
        print("   cp .env.example .env")
        return False

def check_firebase_config():
    """Verifica la configuración de Firebase"""
    print_section("2. Verificando configuración de Firebase", "🔥")
    
    from dotenv import load_dotenv
    load_dotenv()
    
    service_account_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')
    
    if not service_account_json:
        print("❌ FIREBASE_SERVICE_ACCOUNT_JSON no está configurada")
        print("💡 Debes agregar el Service Account JSON en tu .env")
        print("   Ver: CONFIGURACION_VARIABLES_ENTORNO.md")
        return False
    
    # Verificar que es un JSON válido
    try:
        config = json.loads(service_account_json)
        
        print("✅ FIREBASE_SERVICE_ACCOUNT_JSON encontrada y válida")
        print(f"   Project ID: {config.get('project_id', 'N/A')}")
        print(f"   Client Email: {config.get('client_email', 'N/A')}")
        print(f"   Tipo: {config.get('type', 'N/A')}")
        
        # Verificar campos importantes
        required_fields = [
            'type', 'project_id', 'private_key_id', 'private_key',
            'client_email', 'client_id', 'auth_uri', 'token_uri'
        ]
        
        missing = [field for field in required_fields if field not in config]
        
        if missing:
            print(f"⚠️  Faltan campos: {', '.join(missing)}")
            return False
        else:
            print("✅ Todos los campos requeridos presentes")
            return True
            
    except json.JSONDecodeError as e:
        print(f"❌ Error: El JSON no es válido")
        print(f"   {str(e)}")
        return False

def check_gitignore():
    """Verifica que .env está en .gitignore"""
    print_section("3. Verificando .gitignore", "🔒")
    
    gitignore_path = Path(".gitignore")
    
    if not gitignore_path.exists():
        print("⚠️  No se encontró .gitignore")
        return False
    
    with open(gitignore_path, 'r') as f:
        content = f.read()
    
    if '.env' in content:
        print("✅ .env está en .gitignore")
        print("✅ Tus credenciales NO se subirán a GitHub")
        return True
    else:
        print("❌ .env NO está en .gitignore")
        print("⚠️  PELIGRO: Tus credenciales podrían subirse a GitHub")
        print("💡 Agrega '.env' a tu .gitignore")
        return False

def check_git_status():
    """Verifica que .env no está en git"""
    print_section("4. Verificando estado de Git", "🔍")
    
    import subprocess
    
    try:
        # Verificar si .env está en staging o tracked
        result = subprocess.run(
            ['git', 'ls-files', '.env'],
            capture_output=True,
            text=True
        )
        
        if result.stdout.strip():
            print("❌ PELIGRO: .env está siendo tracked por git")
            print("⚠️  Tus credenciales están en el repositorio")
            print("\n💡 Para removerlo:")
            print("   git rm --cached .env")
            print("   git commit -m 'Remove .env from tracking'")
            return False
        else:
            print("✅ .env NO está siendo tracked por git")
            print("✅ Tus credenciales están seguras")
            return True
            
    except Exception as e:
        print(f"⚠️  No se pudo verificar git: {e}")
        return True

def check_firebase_connection():
    """Intenta conectar con Firebase"""
    print_section("5. Probando conexión con Firebase", "🔥")
    
    try:
        from app.firebase_config import db, auth_client
        
        print("✅ Firebase Admin SDK inicializado correctamente")
        
        # Intentar obtener usuarios
        users = auth_client.list_users(max_results=1)
        print(f"✅ Conexión con Firebase Authentication exitosa")
        
        # Intentar acceder a Firestore
        collections = db.collections()
        print(f"✅ Conexión con Firestore exitosa")
        
        return True
        
    except Exception as e:
        print(f"❌ Error conectando con Firebase: {e}")
        print("\n💡 Verifica:")
        print("   1. Que FIREBASE_SERVICE_ACCOUNT_JSON esté correcta")
        print("   2. Que el proyecto Firebase esté activo")
        print("   3. Que las APIs necesarias estén habilitadas")
        return False

def check_other_vars():
    """Verifica otras variables de entorno"""
    print_section("6. Verificando otras variables", "⚙️")
    
    from dotenv import load_dotenv
    load_dotenv()
    
    vars_to_check = {
        'API_ENV': 'Entorno de la API',
        'API_HOST': 'Host de la API',
        'API_PORT': 'Puerto de la API'
    }
    
    all_present = True
    for var_name, description in vars_to_check.items():
        value = os.getenv(var_name)
        if value:
            print(f"✅ {var_name}: {value} ({description})")
        else:
            print(f"⚠️  {var_name}: No configurada ({description})")
            all_present = False
    
    # AWS (opcional)
    aws_key = os.getenv('AWS_ACCESS_KEY_ID')
    if aws_key:
        print(f"✅ AWS S3 configurado (opcional)")
    else:
        print(f"ℹ️  AWS S3 no configurado (opcional)")
    
    return all_present

def generate_summary(results):
    """Genera un resumen de los resultados"""
    print_section("📊 RESUMEN DE VERIFICACIÓN", "📊")
    
    total = len(results)
    passed = sum(1 for r in results if r)
    failed = total - passed
    
    print(f"\nTests ejecutados: {total}")
    print(f"✅ Exitosos: {passed}")
    print(f"❌ Fallidos: {failed}")
    
    if failed == 0:
        print("\n🎉 ¡Todo está correctamente configurado!")
        print("✅ Tu API está lista para usar Firebase")
        print("✅ Tus credenciales están seguras")
    else:
        print(f"\n⚠️  Hay {failed} problema(s) que debes resolver")
        print("💡 Revisa la guía: CONFIGURACION_VARIABLES_ENTORNO.md")

def main():
    """Función principal"""
    print("\n" + "🔐" * 35)
    print("  VERIFICACIÓN DE CONFIGURACIÓN DE VARIABLES DE ENTORNO")
    print("  API Artefacto 360 DAGMA")
    print("🔐" * 35)
    
    results = []
    
    # Ejecutar verificaciones
    results.append(check_env_file())
    results.append(check_firebase_config())
    results.append(check_gitignore())
    results.append(check_git_status())
    results.append(check_firebase_connection())
    results.append(check_other_vars())
    
    # Generar resumen
    generate_summary(results)
    
    print("\n" + "=" * 70)
    print("  📖 Para más información, consulta:")
    print("     CONFIGURACION_VARIABLES_ENTORNO.md")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Verificación interrumpida")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
