"""
Verificación de conectividad y permisos del bucket S3 catatrack-photos
ARN: arn:aws:s3:::catatrack-photos
Prueba las mismas operaciones que usa la API en producción.
"""
import boto3
import gzip
import os
import uuid
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"

print("=" * 60)
print("VERIFICACION S3 — arn:aws:s3:::catatrack-photos")
print("=" * 60)

bucket  = os.getenv("S3_BUCKET_NAME", "catatrack-photos")
region  = os.getenv("AWS_REGION", "us-east-1")
key_id  = os.getenv("AWS_ACCESS_KEY_ID", "")
secret  = os.getenv("AWS_SECRET_ACCESS_KEY", "")

print(f"\n  Bucket  : {bucket}")
print(f"  Region  : {region}")
print(f"  Key ID  : {key_id[:8]}***" if key_id else f"  Key ID  : {FAIL} NO CONFIGURADA")
print(f"  Secret  : {'***' if secret else FAIL + ' NO CONFIGURADA'}")
print()

if not key_id or not secret:
    print(f"{FAIL} Credenciales de AWS no encontradas en .env")
    raise SystemExit(1)

s3 = boto3.client(
    "s3",
    aws_access_key_id=key_id,
    aws_secret_access_key=secret,
    region_name=region,
)

results = {}

# 1. HEAD BUCKET — Verifica que el bucket existe y tenemos acceso
print("1) Verificando acceso al bucket...")
try:
    s3.head_bucket(Bucket=bucket)
    print(f"   {PASS} Bucket '{bucket}' existe y es accesible")
    results["head_bucket"] = True
except ClientError as e:
    code = e.response["Error"]["Code"]
    msg  = e.response["Error"]["Message"]
    print(f"   {FAIL} head_bucket: {code} — {msg}")
    results["head_bucket"] = False
    raise SystemExit(1)

# 2. PUT OBJECT — Sube un archivo comprimido (igual que nota_voz en la API)
test_key = f"test-conexion/smoke_test_{uuid.uuid4().hex}.txt.gz"
raw_data   = b"catatrack smoke test OK"
compressed = gzip.compress(raw_data)
print(f"\n2) Subiendo objeto de prueba (gzip, igual que nota_voz)...")
print(f"   Key    : {test_key}")
print(f"   Tamaño : {len(raw_data)} bytes -> {len(compressed)} bytes (gzip)")
try:
    s3.put_object(
        Bucket=bucket,
        Key=test_key,
        Body=compressed,
        ContentType="audio/mpeg",
        ContentEncoding="gzip",
    )
    url = f"https://{bucket}.s3.amazonaws.com/{test_key}"
    print(f"   {PASS} Objeto subido: {url}")
    results["put_object"] = True
except ClientError as e:
    code = e.response["Error"]["Code"]
    msg  = e.response["Error"]["Message"]
    print(f"   {FAIL} put_object: {code} — {msg}")
    results["put_object"] = False

# 3. HEAD OBJECT — Verifica metadatos del objeto subido
print(f"\n3) Verificando metadatos del objeto (HEAD)...")
try:
    meta = s3.head_object(Bucket=bucket, Key=test_key)
    print(f"   {PASS} ContentType     : {meta['ContentType']}")
    print(f"   {PASS} ContentEncoding : {meta.get('ContentEncoding', 'N/A')}")
    print(f"   {PASS} ContentLength   : {meta['ContentLength']} bytes")
    print(f"   {PASS} ETag            : {meta['ETag']}")
    results["head_object"] = True
except ClientError as e:
    print(f"   {FAIL} head_object: {e.response['Error']['Code']}")
    results["head_object"] = False

# 4. LIST OBJECTS — Verifica permisos de listado
print(f"\n4) Listando objetos en test-conexion/...")
try:
    resp  = s3.list_objects_v2(Bucket=bucket, Prefix="test-conexion/")
    count = len(resp.get("Contents", []))
    print(f"   {PASS} {count} objeto(s) en el prefijo 'test-conexion/'")
    results["list_objects"] = True
except ClientError as e:
    print(f"   {FAIL} list_objects_v2: {e.response['Error']['Code']}")
    results["list_objects"] = False

# 5. DELETE OBJECT — Limpia el archivo de prueba
print(f"\n5) Eliminando objeto de prueba...")
try:
    s3.delete_object(Bucket=bucket, Key=test_key)
    print(f"   {PASS} Objeto de prueba eliminado")
    results["delete_object"] = True
except ClientError as e:
    print(f"   {FAIL} delete_object: {e.response['Error']['Code']}")
    results["delete_object"] = False

# Resumen
print("\n" + "=" * 60)
all_ok = all(results.values())
for op, ok in results.items():
    print(f"  {'✅' if ok else '❌'} {op}")
print("=" * 60)
if all_ok:
    print("\n RESULTADO: Todas las operaciones S3 funcionan correctamente")
    print(f" La API puede subir y eliminar archivos en '{bucket}'")
else:
    failed = [k for k, v in results.items() if not v]
    print(f"\n RESULTADO: Algunas operaciones fallaron: {', '.join(failed)}")
    print(" Revisa los permisos IAM del usuario catatrack-api")
