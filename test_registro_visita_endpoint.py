"""
Script de prueba para el endpoint POST /registrar-visita/
Valida que el endpoint esté registrando correctamente en Firebase
"""
import requests
import json
import time

# URL de la API (ajusta según tu entorno)
API_URL = "http://localhost:8000"
ENDPOINT = f"{API_URL}/registrar-visita/"

def test_registro_visita_endpoint():
    """
    Prueba el endpoint de registro de visita
    """
    print("=" * 80)
    print("🧪 PRUEBA DEL ENDPOINT: POST /registrar-visita/")
    print("=" * 80)
    
    # Preparar datos del formulario con timestamp actual
    timestamp = int(time.time() * 1000)  # Timestamp en milisegundos
    
    form_data = {
        'nombre_up': 'Unidad Centro',
        'nombre_up_detalle': 'Zona Centro - Área 1',
        'barrio_vereda': 'San Fernando',
        'comuna_corregimiento': 'Comuna 3',
        'fecha_visita': str(timestamp)
    }
    
    print("\n📤 Enviando petición al endpoint...")
    print(f"   URL: {ENDPOINT}")
    print(f"   Datos:")
    for key, value in form_data.items():
        if key == 'fecha_visita':
            print(f"      {key}: {value} (timestamp en milisegundos)")
        else:
            print(f"      {key}: {value}")
    
    try:
        response = requests.post(ENDPOINT, data=form_data)
        
        print(f"\n📥 Respuesta recibida:")
        print(f"   Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"\n✅ PRUEBA EXITOSA!")
            print(f"\n📊 Datos de la visita registrada:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
            # Validaciones
            print(f"\n🔍 Validaciones:")
            
            assert result['success'] == True, "❌ Campo 'success' debe ser True"
            print(f"   ✅ success = {result['success']}")
            
            assert 'vid' in result and result['vid'].startswith('VID-'), "❌ Debe tener un VID válido con formato VID-#"
            print(f"   ✅ VID generado: {result['vid']}")
            
            assert result['nombre_up'] == form_data['nombre_up'], "❌ nombre_up no coincide"
            print(f"   ✅ nombre_up: {result['nombre_up']}")
            
            assert result['nombre_up_detalle'] == form_data['nombre_up_detalle'], "❌ nombre_up_detalle no coincide"
            print(f"   ✅ nombre_up_detalle: {result['nombre_up_detalle']}")
            
            assert result['barrio_vereda'] == form_data['barrio_vereda'], "❌ barrio_vereda no coincide"
            print(f"   ✅ barrio_vereda: {result['barrio_vereda']}")
            
            assert result['comuna_corregimiento'] == form_data['comuna_corregimiento'], "❌ comuna_corregimiento no coincide"
            print(f"   ✅ comuna_corregimiento: {result['comuna_corregimiento']}")
            
            assert 'fecha_visita' in result, "❌ Debe incluir fecha_visita"
            print(f"   ✅ fecha_visita: {result['fecha_visita']}")
            
            assert 'timestamp' in result, "❌ Debe incluir timestamp"
            print(f"   ✅ timestamp: {result['timestamp']}")
            
            assert result['message'] == "Visita registrada exitosamente", "❌ Mensaje incorrecto"
            print(f"   ✅ message: {result['message']}")
            
            print(f"\n🎉 TODAS LAS VALIDACIONES PASARON!")
            print(f"\n⚠️ IMPORTANTE: Verifica manualmente en:")
            print(f"   1. Firebase Console > Firestore > visitas_dagma > {result['vid']}")
            print(f"   2. Los datos deben incluir:")
            print(f"      - vid: {result['vid']}")
            print(f"      - vid_number: (número extraído del VID)")
            print(f"      - nombre_up: {result['nombre_up']}")
            print(f"      - nombre_up_detalle: {result['nombre_up_detalle']}")
            print(f"      - barrio_vereda: {result['barrio_vereda']}")
            print(f"      - comuna_corregimiento: {result['comuna_corregimiento']}")
            print(f"      - fecha_visita: {result['fecha_visita']}")
            
        elif response.status_code == 422:
            print(f"❌ ERROR DE VALIDACIÓN (422)")
            print(f"   Detalles: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        else:
            print(f"❌ ERROR {response.status_code}")
            try:
                error_detail = response.json()
                print(f"   Detalles: {json.dumps(error_detail, indent=2, ensure_ascii=False)}")
            except:
                print(f"   Respuesta: {response.text}")
    
    except requests.exceptions.ConnectionError:
        print("❌ ERROR: No se pudo conectar al servidor")
        print(f"   Asegúrate de que el servidor esté corriendo en {API_URL}")
    except Exception as e:
        print(f"❌ ERROR INESPERADO: {str(e)}")

def test_campos_faltantes():
    """
    Prueba que el endpoint valide correctamente campos faltantes
    """
    print("\n" + "=" * 80)
    print("🧪 PRUEBA 2: Validación de campos faltantes")
    print("=" * 80)
    
    # Enviar datos incompletos (sin nombre_up)
    form_data_incompleto = {
        'nombre_up_detalle': 'Zona Centro - Área 1',
        'barrio_vereda': 'San Fernando',
        'comuna_corregimiento': 'Comuna 3',
        'fecha_visita': str(int(time.time() * 1000))
    }
    
    print("\n📤 Enviando petición con datos incompletos (sin nombre_up)...")
    
    try:
        response = requests.post(ENDPOINT, data=form_data_incompleto)
        
        print(f"📥 Respuesta: Status Code {response.status_code}")
        
        if response.status_code == 422:
            print("✅ Validación correcta: El endpoint rechazó datos incompletos")
            error_detail = response.json()
            print(f"   Detalles: {json.dumps(error_detail, indent=2, ensure_ascii=False)}")
        else:
            print(f"❌ ERROR: El endpoint debería retornar 422 para datos incompletos")
            print(f"   Retornó: {response.status_code}")
    
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")

def test_formato_fecha_invalido():
    """
    Prueba que el endpoint valide correctamente el formato de fecha
    """
    print("\n" + "=" * 80)
    print("🧪 PRUEBA 3: Validación de formato de fecha inválido")
    print("=" * 80)
    
    form_data_fecha_invalida = {
        'nombre_up': 'Unidad Centro',
        'nombre_up_detalle': 'Zona Centro - Área 1',
        'barrio_vereda': 'San Fernando',
        'comuna_corregimiento': 'Comuna 3',
        'fecha_visita': 'fecha-invalida'
    }
    
    print("\n📤 Enviando petición con fecha inválida...")
    
    try:
        response = requests.post(ENDPOINT, data=form_data_fecha_invalida)
        
        print(f"📥 Respuesta: Status Code {response.status_code}")
        
        if response.status_code == 400:
            print("✅ Validación correcta: El endpoint rechazó fecha inválida")
            error_detail = response.json()
            print(f"   Detalles: {error_detail.get('detail', '')}")
        else:
            print(f"❌ ERROR: El endpoint debería retornar 400 para fecha inválida")
            print(f"   Retornó: {response.status_code}")
    
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")

if __name__ == "__main__":
    print("\n🚀 INICIANDO PRUEBAS DEL ENDPOINT /registrar-visita/\n")
    
    # Ejecutar pruebas
    test_registro_visita_endpoint()
    test_campos_faltantes()
    test_formato_fecha_invalido()
    
    print("\n" + "=" * 80)
    print("✅ PRUEBAS FINALIZADAS")
    print("=" * 80)
