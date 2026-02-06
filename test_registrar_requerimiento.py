"""
Script de prueba para el endpoint POST /registrar-requerimiento
"""
import requests
import json
from datetime import datetime

# URL base de la API (ajustar según tu entorno)
BASE_URL = "http://localhost:8000"  # Cambiar si es necesario

def test_registrar_requerimiento_sin_audio():
    """
    Prueba el endpoint sin archivo de audio
    """
    print("\n=== Prueba 1: Registrar requerimiento SIN nota de voz ===")
    
    # Preparar datos
    coords = json.dumps({"lat": 3.4516, "lng": -76.5320})
    organismos = json.dumps(["DAGMA", "Secretaría de Obras Públicas", "Planeación Municipal"])
    
    data = {
        "vid": "VID-1",
        "centro_gestor_solicitante": "DAGMA",
        "solicitante_contacto": "María López García",
        "requerimiento": "Solicitud de mejoramiento vial en la Calle 5",
        "observaciones": "La vía presenta baches profundos que dificultan el tránsito vehicular",
        "direccion": "Calle 5 # 40-20",
        "barrio_vereda": "San Fernando",
        "comuna_corregimiento": "Comuna 3",
        "coords": coords,
        "telefono": "+57 300 1234567",
        "email_solicitante": "maria.lopez@example.com",
        "organismos_encargados": organismos
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/registrar-requerimiento",
            data=data,
            timeout=30
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        
        if response.status_code == 200:
            print("✅ Prueba exitosa!")
        else:
            print("❌ Prueba falló")
            
    except Exception as e:
        print(f"❌ Error en la prueba: {str(e)}")


def test_registrar_requerimiento_con_audio():
    """
    Prueba el endpoint CON archivo de audio
    """
    print("\n=== Prueba 2: Registrar requerimiento CON nota de voz ===")
    
    # Preparar datos
    coords = json.dumps({"lat": 3.4516, "lng": -76.5320})
    organismos = json.dumps(["DAGMA", "Alcaldía Municipal"])
    
    data = {
        "vid": "VID-1",
        "centro_gestor_solicitante": "Secretaría de Salud",
        "solicitante_contacto": "Juan Pérez",
        "requerimiento": "Solicitud de fumigación en zona verde",
        "observaciones": "Presencia de mosquitos y plagas en el parque",
        "direccion": "Carrera 10 # 25-30",
        "barrio_vereda": "El Poblado",
        "comuna_corregimiento": "Comuna 5",
        "coords": coords,
        "telefono": "+57 310 9876543",
        "email_solicitante": "juan.perez@example.com",
        "organismos_encargados": organismos
    }
    
    # Crear un archivo de audio de prueba (simulado)
    # En producción, aquí usarías un archivo de audio real
    audio_content = b"fake audio content for testing"
    files = {
        "nota_voz": ("test_audio.mp3", audio_content, "audio/mpeg")
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/registrar-requerimiento",
            data=data,
            files=files,
            timeout=30
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        
        if response.status_code == 200:
            print("✅ Prueba exitosa!")
        else:
            print("❌ Prueba falló")
            
    except Exception as e:
        print(f"❌ Error en la prueba: {str(e)}")


def test_validaciones():
    """
    Prueba validaciones del endpoint
    """
    print("\n=== Prueba 3: Validaciones (coords inválidas) ===")
    
    # Coordenadas inválidas (fuera de rango)
    coords_invalidas = json.dumps({"lat": 95.0, "lng": 200.0})
    organismos = json.dumps(["DAGMA"])
    
    data = {
        "vid": "VID-1",
        "centro_gestor_solicitante": "DAGMA",
        "solicitante_contacto": "Test Usuario",
        "requerimiento": "Test",
        "observaciones": "Test",
        "direccion": "Test",
        "barrio_vereda": "Test",
        "comuna_corregimiento": "Test",
        "coords": coords_invalidas,
        "telefono": "123456",
        "email_solicitante": "test@test.com",
        "organismos_encargados": organismos
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/registrar-requerimiento",
            data=data,
            timeout=30
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        
        if response.status_code == 400:
            print("✅ Validación funcionó correctamente (rechazó coords inválidas)")
        else:
            print("⚠️ Se esperaba error 400")
            
    except Exception as e:
        print(f"❌ Error en la prueba: {str(e)}")


def test_rid_incremental():
    """
    Prueba el incremento automático del RID
    """
    print("\n=== Prueba 4: Incremento automático de RID ===")
    
    coords = json.dumps({"lat": 3.4516, "lng": -76.5320})
    organismos = json.dumps(["DAGMA"])
    
    # Crear 3 requerimientos para la misma visita
    for i in range(1, 4):
        data = {
            "vid": "VID-TEST",
            "centro_gestor_solicitante": "DAGMA",
            "solicitante_contacto": f"Usuario Test {i}",
            "requerimiento": f"Requerimiento de prueba {i}",
            "observaciones": f"Observación {i}",
            "direccion": f"Dirección {i}",
            "barrio_vereda": "Test",
            "comuna_corregimiento": "Test",
            "coords": coords,
            "telefono": "123456",
            "email_solicitante": f"test{i}@test.com",
            "organismos_encargados": organismos
        }
        
        try:
            response = requests.post(
                f"{BASE_URL}/registrar-requerimiento",
                data=data,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"Requerimiento {i} - RID: {result.get('rid')}")
            else:
                print(f"❌ Error en requerimiento {i}: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Error en requerimiento {i}: {str(e)}")


if __name__ == "__main__":
    print("=== PRUEBAS DEL ENDPOINT /registrar-requerimiento ===")
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"API Base URL: {BASE_URL}")
    print("\nAsegúrate de que la API esté corriendo antes de ejecutar las pruebas.")
    print("Puedes cambiar BASE_URL si tu API está en otra dirección.\n")
    
    # Ejecutar pruebas
    test_registrar_requerimiento_sin_audio()
    test_validaciones()
    test_rid_incremental()
    
    print("\n=== PRUEBAS COMPLETADAS ===")
    print("\nNOTA: La prueba con audio requiere configuración de S3.")
    print("Para probarla, descomenta la siguiente línea:")
    print("# test_registrar_requerimiento_con_audio()")
