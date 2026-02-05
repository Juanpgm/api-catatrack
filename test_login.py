"""
Script de prueba para validar la lógica de login
"""
import requests
import json

BASE_URL = "http://localhost:8000"

def test_login_with_token():
    """
    Prueba el endpoint de login con un ID token
    
    NOTA: Este test requiere un ID token válido de Firebase.
    Para obtener uno, debes autenticarte desde el frontend primero.
    """
    print("🔍 Probando endpoint de login...")
    print("=" * 60)
    
    # Este es un token de ejemplo - necesitas reemplazarlo con uno real
    test_payload = {
        "id_token": "YOUR_FIREBASE_ID_TOKEN_HERE"
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/auth/login",
            json=test_payload,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"\n📊 Status Code: {response.status_code}")
        print(f"📝 Response: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 200:
            print("\n✅ Login exitoso!")
        else:
            print("\n❌ Login fallido")
            
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")

def test_validate_session():
    """
    Prueba el endpoint de validación de sesión
    """
    print("\n\n🔍 Probando endpoint de validación de sesión...")
    print("=" * 60)
    
    # Este es un token de ejemplo - necesitas reemplazarlo con uno real
    test_token = "YOUR_FIREBASE_ID_TOKEN_HERE"
    
    try:
        response = requests.post(
            f"{BASE_URL}/auth/validate-session",
            headers={
                "Authorization": f"Bearer {test_token}",
                "Content-Type": "application/json"
            }
        )
        
        print(f"\n📊 Status Code: {response.status_code}")
        print(f"📝 Response: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 200:
            print("\n✅ Sesión válida!")
        else:
            print("\n❌ Sesión inválida")
            
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")

def check_api_health():
    """
    Verifica que la API está corriendo
    """
    print("🔍 Verificando que la API está activa...")
    print("=" * 60)
    
    try:
        response = requests.get(f"{BASE_URL}/health")
        print(f"\n📊 Status Code: {response.status_code}")
        print(f"📝 Response: {json.dumps(response.json(), indent=2)}")
        print("\n✅ API está activa!")
        return True
    except Exception as e:
        print(f"\n❌ Error: La API no está corriendo. {str(e)}")
        print("\n💡 Asegúrate de ejecutar: python run.py")
        return False

if __name__ == "__main__":
    print("\n🚀 SCRIPT DE PRUEBA DE LOGIN")
    print("=" * 60)
    
    # Verificar que la API está corriendo
    if not check_api_health():
        exit(1)
    
    print("\n\n📋 INSTRUCCIONES:")
    print("=" * 60)
    print("1. Para probar el login real, necesitas un ID token válido de Firebase")
    print("2. Puedes obtenerlo autenticándote desde tu frontend")
    print("3. O usando el Firebase SDK en un script separado")
    print("\n4. Los endpoints disponibles son:")
    print("   - POST /auth/login (requiere id_token)")
    print("   - POST /auth/validate-session (requiere Authorization header)")
    print("   - POST /auth/register (para crear nuevos usuarios)")
    print("\n5. Edita este archivo y reemplaza 'YOUR_FIREBASE_ID_TOKEN_HERE'")
    print("   con un token real para probar los endpoints")
    print("=" * 60)
    
    # Descomentar estas líneas cuando tengas un token válido:
    # test_login_with_token()
    # test_validate_session()
