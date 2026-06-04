"""
Script para transcribir audios existentes en la colección requerimientos
que tienen nota_voz_url en S3 pero no tienen transcripciones guardadas.
"""
import os
import gzip
import boto3
import tempfile
from dotenv import load_dotenv
load_dotenv(override=True)

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore

# Inicializar Firebase
if not firebase_admin._apps:
    cred_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if cred_json:
        import json
        cred = credentials.Certificate(json.loads(cred_json))
    else:
        cred = credentials.Certificate("catatrack-42467becdc69.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()


def get_s3_client():
    from botocore.config import Config as BotoConfig
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name=os.getenv('AWS_REGION', 'us-east-2'),
        config=BotoConfig(signature_version='s3v4')
    )


def descargar_audio_s3(s3_url: str) -> tuple[bytes, str]:
    """
    Descarga el audio desde S3. Si está comprimido (.gz), lo descomprime.
    Retorna (audio_bytes, filename)
    """
    bucket_name = os.getenv('S3_BUCKET_NAME', 'catatrack-photos')
    # Extraer la key desde la URL
    prefix = f"https://{bucket_name}.s3.amazonaws.com/"
    if s3_url.startswith(prefix):
        s3_key = s3_url[len(prefix):]
    else:
        raise ValueError(f"URL de S3 inesperada: {s3_url}")

    print(f"  📥 Descargando S3 key: {s3_key}")
    s3 = get_s3_client()
    response = s3.get_object(Bucket=bucket_name, Key=s3_key)
    raw_bytes = response['Body'].read()
    print(f"  📦 Descargados {len(raw_bytes)} bytes")

    filename = s3_key.rsplit('/', 1)[-1]

    # Descomprimir si es gzip
    if filename.endswith('.gz'):
        print(f"  🗜️ Descomprimiendo gzip...")
        raw_bytes = gzip.decompress(raw_bytes)
        filename = filename[:-3]  # quitar .gz
        print(f"  📦 Descomprimido: {len(raw_bytes)} bytes → {filename}")

    return raw_bytes, filename


def transcribir_con_whisper(audio_bytes: bytes, filename: str, language: str = "es") -> dict | None:
    """Transcribe audio usando faster-whisper (local, gratuito)."""
    try:
        from faster_whisper import WhisperModel
        model_size = os.getenv("WHISPER_MODEL_SIZE", "base")
        print(f"  🔄 Cargando modelo faster-whisper '{model_size}'...")
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        print(f"  ✅ Modelo cargado")

        ext = os.path.splitext(filename)[1] or ".wav"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            segments, info = model.transcribe(tmp_path, language=language, beam_size=5)
            texto = " ".join(seg.text.strip() for seg in segments)
        finally:
            os.unlink(tmp_path)

        result = {
            "archivo": filename,
            "transcripcion": texto,
            "idioma": info.language,
            "duracion_segundos": round(info.duration, 2),
        }
        print(f"  ✅ Transcripción: {len(texto)} chars, {info.duration:.1f}s")
        print(f"  📝 Texto: {texto[:200]}{'...' if len(texto) > 200 else ''}")
        return result

    except Exception as e:
        print(f"  ❌ Error transcribiendo: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    print("🔍 Buscando requerimientos con audio sin transcripción...\n")
    docs = db.collection('requerimientos').get()
    total = 0
    con_audio = 0
    sin_transcripcion = 0
    actualizados = 0

    for doc in docs:
        total += 1
        data = doc.to_dict() or {}
        nota_voz_url = data.get('nota_voz_url')
        transcripciones = data.get('transcripciones', [])

        if not nota_voz_url:
            continue
        con_audio += 1

        # Verificar si ya tiene transcripción
        if transcripciones and len(transcripciones) > 0 and any(
            t.get('transcripcion') for t in transcripciones
        ):
            print(f"✅ {doc.id}: ya tiene transcripción, omitiendo")
            continue

        sin_transcripcion += 1
        print(f"\n🎙️ Procesando: {doc.id}")
        print(f"   URL: {nota_voz_url}")

        try:
            audio_bytes, filename = descargar_audio_s3(nota_voz_url)
            transcripcion = transcribir_con_whisper(audio_bytes, filename)

            if transcripcion:
                nuevas_transcripciones = [transcripcion]
                doc.reference.update({
                    "transcripciones": nuevas_transcripciones
                })
                print(f"  💾 Guardado en Firebase: {doc.id}")
                actualizados += 1
            else:
                print(f"  ⚠️ No se pudo transcribir: {doc.id}")

        except Exception as e:
            print(f"  ❌ Error procesando {doc.id}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n📊 Resumen:")
    print(f"   Total requerimientos: {total}")
    print(f"   Con audio: {con_audio}")
    print(f"   Sin transcripción: {sin_transcripcion}")
    print(f"   Actualizados: {actualizados}")


if __name__ == "__main__":
    main()
