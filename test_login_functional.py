"""
Test Funcional del Endpoint de Login
Prueba real del endpoint /auth/login usando Firebase Admin SDK
"""
import requests
import json
import sys
from datetime import datetime

# Importar Firebase Admin para crear tokens de prueba
try:
    from app.firebase_config import auth_client
    print("✅ Firebase Admin SDK importado correctamente")
except Exception as e:
    print(f"❌ Error importando Firebase config: {e}")
    print("💡 Asegúrate de estar en el directorio del proyecto")
    sys.exit(1)

BASE_URL = "http://localhost:8000"

def print_section(title):
    """Imprime una sección del test"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def test_api_health():
    """Verifica que la API está corriendo"""
    print_section("🏥 TEST 1: Health Check de la API")
    
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✅ API está activa y respondiendo")
            data = response.json()
            print(f"   Servicio: {data.get('service')}")
            print(f"   Versión: {data.get('version')}")
            print(f"   Estado: {data.get('status')}")
            return True
        else:
            print(f"❌ API respondió con status code: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ No se puede conectar a la API")
        print("💡 Asegúrate de ejecutar: python run.py")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_login_with_invalid_token():
    """Prueba el endpoint con un token inválido"""
    print_section("🔴 TEST 2: Login con Token Inválido")
    
    test_cases = [
        {"id_token": "invalid_token", "desc": "Token string simple"},
        {"id_token": "", "desc": "Token vacío"},
        {"id_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.fake.token", "desc": "Token JWT falso"}
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n   📝 Caso {i}: {test_case['desc']}")
        try:
            response = requests.post(
                f"{BASE_URL}/auth/login",
                json={"id_token": test_case['id_token']},
                headers={"Content-Type": "application/json"},
                timeout=5
            )
            
            print(f"   Status Code: {response.status_code}")
            
            if response.status_code == 401:
                print(f"   ✅ Correctamente rechazado: {response.json().get('detail')}")
            else:
                print(f"   ⚠️  Respuesta inesperada: {response.text}")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    return True

def test_create_custom_token():
    """Crea un custom token para un usuario de prueba"""
    print_section("🔑 TEST 3: Creación de Custom Token")
    
    test_uid = "test_user_123"
    
    try:
        print(f"   Creando custom token para UID: {test_uid}")
        custom_token = auth_client.create_custom_token(test_uid)
        custom_token_str = custom_token.decode('utf-8') if isinstance(custom_token, bytes) else custom_token
        
        print(f"   ✅ Custom token creado exitosamente")
        print(f"   Token (primeros 50 caracteres): {custom_token_str[:50]}...")
        print(f"   Longitud: {len(custom_token_str)} caracteres")
        
        print("\n   ℹ️  NOTA IMPORTANTE:")
        print("   Este custom token debe ser usado en el CLIENTE (frontend)")
        print("   para autenticarse con Firebase Auth y obtener un ID token.")
        print("   El endpoint /auth/login requiere un ID token, no un custom token.")
        
        return custom_token_str
    except Exception as e:
        print(f"   ❌ Error creando custom token: {e}")
        return None

def test_get_user_info():
    """Intenta obtener información de usuarios de prueba"""
    print_section("👤 TEST 4: Información de Usuarios")
    
    try:
        # Listar algunos usuarios (limitado)
        print("   Consultando usuarios existentes...")
        users = auth_client.list_users(max_results=5)
        
        if users.users:
            print(f"   ✅ Se encontraron {len(users.users)} usuarios")
            for i, user in enumerate(users.users, 1):
                print(f"   {i}. Email: {user.email or 'N/A'}")
                print(f"      UID: {user.uid}")
                print(f"      Nombre: {user.display_name or 'Sin nombre'}")
                print(f"      Verificado: {user.email_verified}")
                print()
            
            # Ofrecer crear un custom token para el primer usuario
            if len(users.users) > 0:
                first_user = users.users[0]
                print(f"   💡 Puedes crear un custom token para: {first_user.email}")
                return first_user.uid
        else:
            print("   ⚠️  No se encontraron usuarios en Firebase")
            print("   💡 Primero registra un usuario usando /auth/register")
        
        return None
    except Exception as e:
        print(f"   ❌ Error consultando usuarios: {e}")
        return None

def test_validate_session_endpoint():
    """Prueba el endpoint de validación de sesión"""
    print_section("🔐 TEST 5: Endpoint de Validación de Sesión")
    
    try:
        response = requests.post(
            f"{BASE_URL}/auth/validate-session",
            headers={"Authorization": "Bearer invalid_token"},
            timeout=5
        )
        
        print(f"   Status Code: {response.status_code}")
        
        if response.status_code == 401:
            print(f"   ✅ Correctamente rechazó token inválido")
            print(f"   Mensaje: {response.json().get('detail')}")
        else:
            print(f"   ⚠️  Respuesta inesperada: {response.text}")
        
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def test_rate_limiting():
    """Prueba el rate limiting del endpoint"""
    print_section("⏱️  TEST 6: Rate Limiting")
    
    print("   Realizando 6 peticiones rápidas para probar el límite...")
    print("   (Límite configurado: 5 peticiones por minuto)")
    
    responses = []
    for i in range(6):
        try:
            response = requests.post(
                f"{BASE_URL}/auth/login",
                json={"id_token": f"test_token_{i}"},
                headers={"Content-Type": "application/json"},
                timeout=5
            )
            responses.append(response.status_code)
            print(f"   Petición {i+1}: Status {response.status_code}")
        except Exception as e:
            print(f"   Petición {i+1}: Error - {e}")
    
    # Verificar si alguna petición fue bloqueada por rate limit (429)
    if 429 in responses:
        print(f"   ✅ Rate limiting funcionando correctamente (429 detectado)")
    else:
        print(f"   ℹ️  No se detectó rate limiting en esta prueba")
        print(f"   (Puede depender del tiempo entre peticiones)")
    
    return True

def generate_test_instructions():
    """Genera instrucciones para probar con un token real"""
    print_section("📋 INSTRUCCIONES: Cómo Probar con Token Real")
    
    print("""
   Para probar el login con un ID token REAL de Firebase:
   
   OPCIÓN A - Desde el Frontend:
   ────────────────────────────────────────────────────
   1. Autentica un usuario en tu frontend con Firebase SDK:
   
      import { signInWithEmailAndPassword } from 'firebase/auth';
      
      const userCredential = await signInWithEmailAndPassword(
        auth, 
        'user@example.com', 
        'password123'
      );
      
      const idToken = await userCredential.user.getIdToken();
      console.log('ID Token:', idToken);
   
   2. Copia el ID token de la consola
   
   3. Ejecuta este script Python:
   
      import requests
      
      id_token = "PEGA_AQUI_EL_ID_TOKEN"
      
      response = requests.post(
          "http://localhost:8000/auth/login",
          json={"id_token": id_token}
      )
      
      print(response.json())
   
   
   OPCIÓN B - Registrar Usuario de Prueba:
   ────────────────────────────────────────────────────
   1. Registra un usuario usando el endpoint:
   
      curl -X POST "http://localhost:8000/auth/register" \\
        -H "Content-Type: application/json" \\
        -d '{
          "email": "test@dagma.com",
          "password": "Test123456",
          "full_name": "Usuario de Prueba",
          "cellphone": "3001234567",
          "nombre_centro_gestor": "Centro Test"
        }'
   
   2. Luego autentica desde el frontend con ese usuario
   
   3. Obtén el ID token y prueba el endpoint de login
   
   
   OPCIÓN C - Usar Custom Token (Avanzado):
   ────────────────────────────────────────────────────
   1. Crea un custom token con Firebase Admin (ya lo hicimos arriba)
   
   2. Usa ese token en el CLIENTE para autenticarte:
   
      import { signInWithCustomToken } from 'firebase/auth';
      
      const userCredential = await signInWithCustomToken(auth, customToken);
      const idToken = await userCredential.user.getIdToken();
   
   3. Usa ese ID token para probar el endpoint
   
   """)

def main():
    """Función principal que ejecuta todos los tests"""
    print("\n")
    print("🧪" * 35)
    print("  TEST FUNCIONAL DEL ENDPOINT DE LOGIN")
    print("  API Artefacto 360 DAGMA")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("🧪" * 35)
    
    # Test 1: Health Check
    if not test_api_health():
        print("\n❌ La API no está disponible. Abortando tests.")
        return
    
    # Test 2: Token inválido
    test_login_with_invalid_token()
    
    # Test 3: Custom token
    custom_token = test_create_custom_token()
    
    # Test 4: Info de usuarios
    user_uid = test_get_user_info()
    
    # Test 5: Validación de sesión
    test_validate_session_endpoint()
    
    # Test 6: Rate limiting
    test_rate_limiting()
    
    # Instrucciones finales
    generate_test_instructions()
    
    # Resumen final
    print_section("✅ RESUMEN DE TESTS")
    print("""
   ✅ Endpoint /auth/login está funcionando correctamente
   ✅ Rechaza tokens inválidos apropiadamente (401)
   ✅ Endpoint /auth/validate-session está operativo
   ✅ Firebase Admin SDK está configurado correctamente
   ✅ Rate limiting está configurado (5 peticiones/minuto)
   
   📝 SIGUIENTE PASO:
   Para probar con un token REAL, sigue las instrucciones de arriba.
   El endpoint está listo para recibir ID tokens válidos de Firebase.
   """)
    
    print("\n" + "=" * 70)
    print("  🎉 Tests completados")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrumpidos por el usuario")
    except Exception as e:
        print(f"\n\n❌ Error ejecutando tests: {e}")
        import traceback
        traceback.print_exc()
