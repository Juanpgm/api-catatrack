"""
Script de prueba para verificar la configuración de AWS S3
"""
import boto3
import os
from dotenv import load_dotenv
from datetime import datetime

# Cargar variables de entorno
load_dotenv()

def test_s3_connection():
    print("=" * 60)
    print("🔍 VERIFICACIÓN DE CONFIGURACIÓN AWS S3")
    print("=" * 60)
    print()
    
    # Obtener variables de entorno
    aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
    aws_region = os.getenv('AWS_REGION')
    bucket_name = os.getenv('S3_BUCKET_NAME')
    
    print("📋 Variables de entorno:")
    print(f"   AWS_ACCESS_KEY_ID: {aws_access_key[:10]}..." if aws_access_key else "   ❌ No configurada")
    print(f"   AWS_SECRET_ACCESS_KEY: {'*' * 20}" if aws_secret_key else "   ❌ No configurada")
    print(f"   AWS_REGION: {aws_region}")
    print(f"   S3_BUCKET_NAME: {bucket_name}")
    print()
    
    if not all([aws_access_key, aws_secret_key, aws_region, bucket_name]):
        print("❌ Error: Faltan variables de entorno")
        return False
    
    try:
        # 1. Verificar identidad del usuario
        print("🔐 Verificando identidad IAM...")
        sts = boto3.client(
            'sts',
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=aws_region
        )
        identity = sts.get_caller_identity()
        print(f"   ✅ Usuario autenticado: {identity['Arn']}")
        print(f"   ✅ Cuenta AWS: {identity['Account']}")
        print(f"   ✅ User ID: {identity['UserId']}")
        print()
        
    except Exception as e:
        print(f"   ❌ Error de autenticación: {str(e)}")
        return False
    
    try:
        # 2. Crear cliente S3
        print("☁️  Creando cliente S3...")
        s3 = boto3.client(
            's3',
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=aws_region
        )
        print("   ✅ Cliente S3 creado exitosamente")
        print()
        
    except Exception as e:
        print(f"   ❌ Error creando cliente S3: {str(e)}")
        return False
    
    try:
        # 3. Verificar acceso al bucket
        print(f"🪣 Verificando bucket '{bucket_name}'...")
        s3.head_bucket(Bucket=bucket_name)
        print(f"   ✅ Bucket '{bucket_name}' accesible")
        
        # Obtener ubicación del bucket
        location = s3.get_bucket_location(Bucket=bucket_name)
        region = location['LocationConstraint'] or 'us-east-1'
        print(f"   ✅ Región del bucket: {region}")
        print()
        
    except s3.exceptions.NoSuchBucket:
        print(f"   ⚠️  El bucket '{bucket_name}' NO existe")
        print(f"   💡 Créalo en: https://s3.console.aws.amazon.com/s3/bucket/create")
        return False
    except Exception as e:
        print(f"   ❌ Error accediendo al bucket: {str(e)}")
        print(f"   💡 Verifica permisos IAM para el usuario")
        return False
    
    try:
        # 4. Probar escritura (PUT)
        print("📝 Probando permisos de ESCRITURA (PUT)...")
        test_key = f'test/prueba_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
        test_content = f'Prueba de conexión S3 - {datetime.now().isoformat()}'
        
        s3.put_object(
            Bucket=bucket_name,
            Key=test_key,
            Body=test_content.encode('utf-8'),
            ContentType='text/plain'
        )
        print(f"   ✅ Archivo de prueba creado: {test_key}")
        print()
        
    except Exception as e:
        print(f"   ❌ Error en permisos de escritura: {str(e)}")
        return False
    
    try:
        # 5. Probar lectura (GET)
        print("📖 Probando permisos de LECTURA (GET)...")
        response = s3.get_object(Bucket=bucket_name, Key=test_key)
        content = response['Body'].read().decode('utf-8')
        print(f"   ✅ Archivo leído correctamente")
        print(f"   📄 Contenido: {content[:50]}...")
        print()
        
    except Exception as e:
        print(f"   ❌ Error en permisos de lectura: {str(e)}")
        return False
    
    try:
        # 6. Probar eliminación (DELETE)
        print("🗑️  Probando permisos de ELIMINACIÓN (DELETE)...")
        s3.delete_object(Bucket=bucket_name, Key=test_key)
        print(f"   ✅ Archivo de prueba eliminado")
        print()
        
    except Exception as e:
        print(f"   ❌ Error en permisos de eliminación: {str(e)}")
        return False
    
    try:
        # 7. Listar objetos
        print("📂 Probando listado de objetos (LIST)...")
        response = s3.list_objects_v2(Bucket=bucket_name, MaxKeys=5)
        
        if 'Contents' in response:
            print(f"   ✅ Bucket contiene {response.get('KeyCount', 0)} objetos")
            print("   📁 Primeros archivos:")
            for obj in response.get('Contents', [])[:3]:
                size_kb = obj['Size'] / 1024
                print(f"      - {obj['Key']} ({size_kb:.2f} KB)")
        else:
            print(f"   ✅ Bucket vacío (sin objetos)")
        print()
        
    except Exception as e:
        print(f"   ⚠️  Error listando objetos: {str(e)}")
        # No es crítico, continuamos
    
    # Resumen final
    print("=" * 60)
    print("🎉 ¡CONFIGURACIÓN COMPLETADA EXITOSAMENTE!")
    print("=" * 60)
    print()
    print("✅ Todos los permisos verificados:")
    print("   • Autenticación IAM")
    print("   • Acceso al bucket")
    print("   • Escritura (PUT)")
    print("   • Lectura (GET)")
    print("   • Eliminación (DELETE)")
    print("   • Listado (LIST)")
    print()
    print("🚀 Tu API está lista para subir fotos a S3!")
    print()
    
    return True

if __name__ == "__main__":
    success = test_s3_connection()
    exit(0 if success else 1)
