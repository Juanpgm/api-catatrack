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
    
    # Coordenadas en formato GeoJSON Point (punto dentro de Cali)
    coords = json.dumps({"type": "Point", "coordinates": [-76.5320, 3.4516]})
    organismos = json.dumps(["DAGMA", "Secretaría de Obras Públicas", "Planeación Municipal"])
    datos_solicitante = json.dumps({
        "personas": [
            {"nombre": "María López García", "email": "maria.lopez@example.com", "telefono": "+57 300 1234567", "centro_gestor": "DAGMA"}
        ]
    })
    
    data = {
        "vid": "VID-1",
        "datos_solicitante": datos_solicitante,
        "requerimiento": "Solicitud de mejoramiento vial en la Calle 5",
        "observaciones": "La vía presenta baches profundos que dificultan el tránsito vehicular",
        "coords": coords,
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
            result = response.json()
            print(f"  barrio_vereda (auto): {result.get('barrio_vereda')}")
            print(f"  comuna_corregimiento (auto): {result.get('comuna_corregimiento')}")
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
    
    coords = json.dumps({"type": "Point", "coordinates": [-76.5320, 3.4516]})
    organismos = json.dumps(["DAGMA", "Alcaldía Municipal"])
    datos_solicitante = json.dumps({
        "personas": [
            {"nombre": "Juan Pérez", "email": "juan.perez@example.com", "telefono": "+57 310 9876543"},
            {"nombre": "Ana Gómez", "email": "ana.gomez@example.com", "centro_gestor": "Secretaría de Salud"}
        ]
    })
    
    data = {
        "vid": "VID-1",
        "datos_solicitante": datos_solicitante,
        "requerimiento": "Solicitud de fumigación en zona verde",
        "observaciones": "Presencia de mosquitos y plagas en el parque",
        "coords": coords,
        "organismos_encargados": organismos
    }
    
    # Crear un archivo de audio de prueba (simulado)
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
    coords_invalidas = json.dumps({"type": "Point", "coordinates": [200.0, 95.0]})
    organismos = json.dumps(["DAGMA"])
    datos_solicitante = json.dumps({"personas": [{"nombre": "Test Usuario"}]})
    
    data = {
        "vid": "VID-1",
        "datos_solicitante": datos_solicitante,
        "requerimiento": "Test",
        "observaciones": "Test",
        "coords": coords_invalidas,
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
    
    coords = json.dumps({"type": "Point", "coordinates": [-76.5320, 3.4516]})
    organismos = json.dumps(["DAGMA"])
    datos_solicitante = json.dumps({"personas": [{"nombre": "Usuario Test"}]})
    
    # Crear 3 requerimientos para la misma visita
    for i in range(1, 4):
        data = {
            "vid": "VID-TEST",
            "datos_solicitante": datos_solicitante,
            "requerimiento": f"Requerimiento de prueba {i}",
            "observaciones": f"Observación {i}",
            "coords": coords,
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
