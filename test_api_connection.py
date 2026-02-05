"""
Script para probar la conectividad con el API de Railway
"""
import requests
import json

def test_api_endpoint():
    """Prueba el endpoint de parques"""
    
    print("\n" + "="*70)
    print("  🧪 TEST DE CONECTIVIDAD CON API RAILWAY")
    print("="*70 + "\n")
    
    url = "https://web-production-2d737.up.railway.app/init/parques"
    
    print(f"🌐 URL: {url}")
    print(f"📡 Método: GET\n")
    
    try:
        # Hacer la petición
        print("⏳ Enviando petición...")
        response = requests.get(url, timeout=10)
        
        print(f"✅ Status Code: {response.status_code}")
        
        # Verificar headers
        print(f"\n📋 Headers importantes:")
        cors_headers = {
            'Access-Control-Allow-Origin': response.headers.get('Access-Control-Allow-Origin', 'No configurado'),
            'Access-Control-Allow-Methods': response.headers.get('Access-Control-Allow-Methods', 'No configurado'),
            'Access-Control-Allow-Headers': response.headers.get('Access-Control-Allow-Headers', 'No configurado'),
            'Access-Control-Allow-Credentials': response.headers.get('Access-Control-Allow-Credentials', 'No configurado'),
            'Content-Type': response.headers.get('Content-Type', 'No configurado'),
        }
        
        for header, value in cors_headers.items():
            print(f"  • {header}: {value}")
        
        # Parsear respuesta
        if response.status_code == 200:
            data = response.json()
            print(f"\n✅ Respuesta JSON válida:")
            print(f"  • Success: {data.get('success')}")
            print(f"  • Count: {data.get('count')}")
            print(f"  • Data items: {len(data.get('data', []))}")
            print(f"  • Timestamp: {data.get('timestamp')}")
            
            if data.get('data'):
                print(f"\n📦 Primer parque (ejemplo):")
                first_park = data['data'][0]
                print(f"  • ID: {first_park.get('id', 'N/A')}")
                # Mostrar algunas propiedades del primer parque
                for key in list(first_park.keys())[:5]:
                    value = first_park[key]
                    if isinstance(value, str) and len(str(value)) > 50:
                        print(f"  • {key}: {str(value)[:50]}...")
                    else:
                        print(f"  • {key}: {value}")
            
            print("\n" + "="*70)
            print("  ✅ API FUNCIONANDO CORRECTAMENTE")
            print("="*70 + "\n")
            
            return True
        else:
            print(f"\n❌ Error en la respuesta:")
            print(response.text)
            return False
            
    except requests.exceptions.Timeout:
        print(f"\n❌ Error: Timeout - El servidor tardó demasiado en responder")
        return False
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Error: No se pudo conectar con el servidor")
        return False
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Error en la petición: {e}")
        return False
    except json.JSONDecodeError:
        print(f"\n❌ Error: La respuesta no es un JSON válido")
        print(f"Respuesta recibida: {response.text[:200]}...")
        return False

def test_cors_preflight():
    """Prueba la petición OPTIONS (preflight) de CORS"""
    
    print("\n" + "="*70)
    print("  🔍 TEST DE CORS PREFLIGHT (OPTIONS)")
    print("="*70 + "\n")
    
    url = "https://web-production-2d737.up.railway.app/init/parques"
    
    headers = {
        'Origin': 'http://localhost:5174',
        'Access-Control-Request-Method': 'GET',
        'Access-Control-Request-Headers': 'content-type'
    }
    
    print(f"🌐 URL: {url}")
    print(f"📡 Método: OPTIONS")
    print(f"🔑 Origin: {headers['Origin']}\n")
    
    try:
        response = requests.options(url, headers=headers, timeout=10)
        
        print(f"✅ Status Code: {response.status_code}\n")
        print(f"📋 CORS Headers en respuesta:")
        
        cors_headers = {
            'Access-Control-Allow-Origin': response.headers.get('Access-Control-Allow-Origin', '❌ No configurado'),
            'Access-Control-Allow-Methods': response.headers.get('Access-Control-Allow-Methods', '❌ No configurado'),
            'Access-Control-Allow-Headers': response.headers.get('Access-Control-Allow-Headers', '❌ No configurado'),
            'Access-Control-Allow-Credentials': response.headers.get('Access-Control-Allow-Credentials', '❌ No configurado'),
        }
        
        all_ok = True
        for header, value in cors_headers.items():
            status = "✅" if "❌" not in str(value) else "❌"
            print(f"  {status} {header}: {value}")
            if "❌" in str(value):
                all_ok = False
        
        if all_ok:
            print("\n" + "="*70)
            print("  ✅ CORS CONFIGURADO CORRECTAMENTE")
            print("="*70 + "\n")
        else:
            print("\n" + "="*70)
            print("  ⚠️  CORS NO ESTÁ COMPLETAMENTE CONFIGURADO")
            print("="*70)
            print("\n💡 Solución:")
            print("  1. Asegúrate de que el backend incluya localhost:5174 en allow_origins")
            print("  2. Reinicia el servidor del backend")
            print("  3. Vuelve a probar\n")
        
        return all_ok
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False

if __name__ == "__main__":
    print("\n🚀 INICIANDO TESTS DE API\n")
    
    # Test 1: Petición GET normal
    test1 = test_api_endpoint()
    
    # Test 2: Preflight CORS
    test2 = test_cors_preflight()
    
    # Resumen
    print("\n" + "="*70)
    print("  📊 RESUMEN DE TESTS")
    print("="*70)
    print(f"\n  API Endpoint (GET): {'✅ PASS' if test1 else '❌ FAIL'}")
    print(f"  CORS Preflight (OPTIONS): {'✅ PASS' if test2 else '❌ FAIL'}")
    
    if test1 and test2:
        print("\n  🎉 TODO FUNCIONANDO CORRECTAMENTE")
        print("\n  💡 Si aún tienes problemas en el navegador:")
        print("     1. Limpia la caché del navegador (Ctrl+Shift+Del)")
        print("     2. Abre en una ventana de incógnito")
        print("     3. Verifica la consola del navegador (F12)")
    elif test1 and not test2:
        print("\n  ⚠️  API funciona pero CORS tiene problemas")
        print("\n  💡 Solución:")
        print("     1. Actualiza app/main.py con los orígenes correctos")
        print("     2. Reinicia el backend: python run.py")
    else:
        print("\n  ❌ HAY PROBLEMAS CON LA API")
        print("\n  💡 Verifica:")
        print("     1. Que la API esté corriendo")
        print("     2. Que la URL sea correcta")
        print("     3. Que no haya errores en los logs del backend")
    
    print("\n" + "="*70 + "\n")
