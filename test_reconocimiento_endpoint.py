"""
Script de prueba para el endpoint POST /grupo-operativo/reconocimiento
Valida que el endpoint esté registrando correctamente en Firebase y S3
"""
import requests
import json
import os
from pathlib import Path

# URL de la API (ajusta según tu entorno)
API_URL = "http://localhost:8000"
ENDPOINT = f"{API_URL}/grupo-operativo/reconocimiento"

def create_test_image(filename="test_image.jpg"):
    """
    Crea una imagen de prueba simple (1x1 pixel JPEG)
    """
    from PIL import Image
    img = Image.new('RGB', (100, 100), color='red')
    img.save(filename)
    return filename

def test_reconocimiento_endpoint():
    """
    Prueba el endpoint de reconocimiento
    """
    print("=" * 80)
    print("🧪 PRUEBA DEL ENDPOINT: POST /grupo-operativo/reconocimiento")
    print("=" * 80)
    
    # Crear imágenes de prueba
    try:
        from PIL import Image
        test_image1 = create_test_image("test_photo1.jpg")
        test_image2 = create_test_image("test_photo2.jpg")
        print("✅ Imágenes de prueba creadas")
    except ImportError:
        print("⚠️ PIL/Pillow no instalado. Usando archivos existentes si los hay.")
        test_image1 = "test_photo1.jpg"
        test_image2 = "test_photo2.jpg"
        if not os.path.exists(test_image1):
            print("❌ No se encontraron imágenes de prueba. Por favor, instala Pillow: pip install Pillow")
            return
    
    # Preparar datos del formulario
    form_data = {
        'tipo_intervencion': 'Mantenimiento',
        'descripcion_intervencion': 'Poda de árboles en zona verde del parque',
        'direccion': 'Calle 5 #10-20, Cali, Valle del Cauca',
        'observaciones': 'Trabajo completado satisfactoriamente. Se realizó limpieza posterior.',
        'coordinates_type': 'Point',
        'coordinates_data': '[-76.5225, 3.4516]'  # Coordenadas de Cali, Colombia
    }
    
    # Preparar archivos
    files = [
        ('photos', (test_image1, open(test_image1, 'rb'), 'image/jpeg')),
        ('photos', (test_image2, open(test_image2, 'rb'), 'image/jpeg'))
    ]
    
    print("\n📤 Enviando petición al endpoint...")
    print(f"   URL: {ENDPOINT}")
    print(f"   Datos: {json.dumps(form_data, indent=2, ensure_ascii=False)}")
    print(f"   Fotos: 2 archivos")
    
    try:
        response = requests.post(ENDPOINT, data=form_data, files=files)
        
        print(f"\n📥 Respuesta recibida:")
        print(f"   Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"\n✅ PRUEBA EXITOSA!")
            print(f"\n📊 Datos del reconocimiento registrado:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
            # Validaciones
            print(f"\n🔍 Validaciones:")
            assert result['success'] == True, "❌ Campo 'success' debe ser True"
            print(f"   ✅ success = {result['success']}")
            
            assert 'id' in result and result['id'], "❌ Debe tener un ID válido"
            print(f"   ✅ ID generado: {result['id']}")
            
            assert 'coordinates' in result, "❌ Debe incluir coordenadas"
            print(f"   ✅ Coordenadas: {result['coordinates']}")
            
            assert 'photosUrl' in result and len(result['photosUrl']) == 2, "❌ Debe tener 2 URLs de fotos"
            print(f"   ✅ {len(result['photosUrl'])} fotos subidas")
            for i, url in enumerate(result['photosUrl'], 1):
                print(f"      {i}. {url}")
            
            assert result['photos_uploaded'] == 2, "❌ Contador de fotos incorrecto"
            print(f"   ✅ Contador de fotos: {result['photos_uploaded']}")
            
            print(f"\n🎉 TODAS LAS VALIDACIONES PASARON!")
            print(f"\n⚠️ IMPORTANTE: Verifica manualmente en:")
            print(f"   1. Firebase Console > Firestore > reconocimientos_dagma > {result['id']}")
            print(f"   2. AWS S3 Console > Bucket: 360-dagma-photos > reconocimientos/{result['id']}/")
            
        else:
            print(f"\n❌ PRUEBA FALLIDA!")
            print(f"   Respuesta: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Error: No se pudo conectar a {API_URL}")
        print(f"   Asegúrate de que la API esté corriendo con: python run.py")
    except Exception as e:
        print(f"\n❌ Error durante la prueba: {str(e)}")
    finally:
        # Cerrar archivos
        for _, file_tuple in files:
            file_tuple[1].close()
        
        # Limpiar archivos de prueba
        try:
            if os.path.exists(test_image1):
                os.remove(test_image1)
            if os.path.exists(test_image2):
                os.remove(test_image2)
            print("\n🧹 Archivos de prueba eliminados")
        except:
            pass
    
    print("\n" + "=" * 80)

# ==================== PRUEBAS DE VALIDACIÓN ====================

def test_validation_invalid_geometry_type():
    """Probar validación de tipo de geometría inválido"""
    print("\n🧪 Prueba: Tipo de geometría inválido")
    
    form_data = {
        'tipo_intervencion': 'Mantenimiento',
        'descripcion_intervencion': 'Test',
        'direccion': 'Test',
        'coordinates_type': 'InvalidType',
        'coordinates_data': '[-76.5225, 3.4516]'
    }
    
    test_image = create_test_image("temp.jpg")
    files = [('photos', (test_image, open(test_image, 'rb'), 'image/jpeg'))]
    
    response = requests.post(ENDPOINT, data=form_data, files=files)
    files[0][1][1].close()
    os.remove(test_image)
    
    assert response.status_code == 400, "Debería rechazar tipo de geometría inválido"
    print("✅ Validación de tipo de geometría funcionando correctamente")

def test_validation_invalid_coordinates():
    """Probar validación de coordenadas inválidas"""
    print("\n🧪 Prueba: Coordenadas fuera de rango")
    
    form_data = {
        'tipo_intervencion': 'Mantenimiento',
        'descripcion_intervencion': 'Test',
        'direccion': 'Test',
        'coordinates_type': 'Point',
        'coordinates_data': '[-200, 3.4516]'  # Longitud inválida
    }
    
    test_image = create_test_image("temp.jpg")
    files = [('photos', (test_image, open(test_image, 'rb'), 'image/jpeg'))]
    
    response = requests.post(ENDPOINT, data=form_data, files=files)
    files[0][1][1].close()
    os.remove(test_image)
    
    assert response.status_code == 400, "Debería rechazar coordenadas fuera de rango"
    print("✅ Validación de coordenadas funcionando correctamente")

def test_validation_no_photos():
    """Probar validación de fotos requeridas"""
    print("\n🧪 Prueba: Sin fotos")
    
    form_data = {
        'tipo_intervencion': 'Mantenimiento',
        'descripcion_intervencion': 'Test',
        'direccion': 'Test',
        'coordinates_type': 'Point',
        'coordinates_data': '[-76.5225, 3.4516]'
    }
    
    response = requests.post(ENDPOINT, data=form_data)
    
    assert response.status_code == 422, "Debería requerir fotos"
    print("✅ Validación de fotos requeridas funcionando correctamente")

if __name__ == "__main__":
    try:
        # Prueba principal
        test_reconocimiento_endpoint()
        
        # Pruebas de validación
        print("\n\n" + "=" * 80)
        print("🧪 PRUEBAS DE VALIDACIÓN")
        print("=" * 80)
        
        try:
            test_validation_invalid_geometry_type()
        except Exception as e:
            print(f"⚠️ Prueba de geometría fallida: {e}")
        
        try:
            test_validation_invalid_coordinates()
        except Exception as e:
            print(f"⚠️ Prueba de coordenadas fallida: {e}")
        
        try:
            test_validation_no_photos()
        except Exception as e:
            print(f"⚠️ Prueba de fotos fallida: {e}")
            
    except KeyboardInterrupt:
        print("\n\n⚠️ Prueba cancelada por el usuario")
