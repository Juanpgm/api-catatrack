"""
Módulo unificado de almacenamiento S3 — CataTrack.

Single source of truth para credenciales/bucket y operaciones de S3
usadas por los módulos de captura (Avanzadas Diagnósticas, Jornadas
Integrales, Seguimiento/Kanban). Reemplaza la lógica duplicada que
antes vivía inline en cada archivo de rutas.

Formato de key: ``{modulo}/{client_id}/{categoria}/{uuid}_{safe_name}``
donde ``modulo`` ∈ {avanzadas, jornadas, seguimiento}. ``categoria``
puede incluir subrutas (p. ej. ``requerimientos/0``).
"""
from __future__ import annotations

import os
import re
import uuid
from typing import Optional

import boto3
from botocore.config import Config as BotoConfig
from dotenv import load_dotenv

_CONTENT_TYPE_POR_EXTENSION = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".heic": "image/heic",
    ".pdf": "application/pdf", ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".ogg": "audio/ogg", ".webm": "audio/webm", ".m4a": "audio/mp4",
    ".gz": "application/gzip",
}


def bucket_name() -> str:
    """Nombre del bucket S3, centralizado a partir de la variable de entorno."""
    return os.getenv("S3_BUCKET_NAME", "catatrack-photos")


def get_s3_client():
    """Crea un cliente de S3 con las credenciales del entorno.

    Fuente única: antes duplicado en ``artefacto_360_routes.get_s3_client``.
    """
    load_dotenv(override=True)

    aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_region = os.getenv("AWS_REGION", "us-east-2")

    if not aws_access_key or not aws_secret_key:
        raise ValueError(
            "Credenciales de AWS no configuradas. Verifica AWS_ACCESS_KEY_ID y AWS_SECRET_ACCESS_KEY"
        )

    return boto3.client(
        "s3",
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        region_name=aws_region,
        config=BotoConfig(signature_version="s3v4"),
    )


def _safe_filename(filename: str) -> str:
    return re.sub(r"[^\w.\-]", "_", filename or "archivo")


def build_key(modulo: str, client_id: str, categoria: str, filename: str) -> str:
    """Construye la key S3: ``{modulo}/{client_id}/{categoria}/{uuid}_{safe_name}``."""
    safe_name = _safe_filename(filename)
    return f"{modulo}/{client_id}/{categoria}/{uuid.uuid4().hex}_{safe_name}"


def upload_file(
    content: bytes,
    *,
    modulo: str,
    client_id: str,
    categoria: str,
    filename: str,
    content_type: Optional[str] = None,
    s3_client=None,
    bucket: Optional[str] = None,
) -> dict:
    """Sube ``content`` a S3 y retorna la forma enriquecida (legacy-compatible):
    ``{filename, s3_key, s3_url, content_type, size}``.
    """
    client = s3_client or get_s3_client()
    bucket_ = bucket or bucket_name()
    s3_key = build_key(modulo, client_id, categoria, filename)
    ct = content_type or "application/octet-stream"

    client.put_object(Bucket=bucket_, Key=s3_key, Body=content, ContentType=ct)

    return {
        "filename": filename,
        "s3_key": s3_key,
        "s3_url": f"https://{bucket_}.s3.amazonaws.com/{s3_key}",
        "content_type": ct,
        "size": len(content),
    }


def delete_keys(keys: list, s3_client=None, bucket: Optional[str] = None) -> None:
    """Elimina una lista de keys S3. Best-effort: nunca propaga errores."""
    if not keys:
        return
    try:
        client = s3_client or get_s3_client()
        bucket_ = bucket or bucket_name()
        objects = [{"Key": k} for k in keys]
        for i in range(0, len(objects), 1000):
            client.delete_objects(Bucket=bucket_, Delete={"Objects": objects[i : i + 1000]})
    except Exception:
        pass


def delete_prefix(prefix: str, s3_client=None, bucket: Optional[str] = None) -> int:
    """Elimina todos los objetos bajo ``prefix``. Best-effort: retorna 0 en error."""
    deleted = 0
    try:
        client = s3_client or get_s3_client()
        bucket_ = bucket or bucket_name()
        response = client.list_objects_v2(Bucket=bucket_, Prefix=prefix)
        contents = response.get("Contents", [])
        if not contents:
            return 0
        objects = [{"Key": obj["Key"]} for obj in contents]
        for i in range(0, len(objects), 1000):
            client.delete_objects(Bucket=bucket_, Delete={"Objects": objects[i : i + 1000]})
        deleted = len(objects)
    except Exception:
        return 0
    return deleted


def list_documents(prefix: str, expiration: int = 3600, s3_client=None, bucket: Optional[str] = None) -> list:
    """Lista objetos bajo ``prefix`` y genera URLs presignadas (descarga/visualización).

    Generalización de la legacy ``_listar_documentos_s3`` (que recibía
    ``vid``/``rid`` en vez de un ``prefix`` directo).
    """
    bucket_ = bucket or bucket_name()

    if s3_client is None:
        try:
            s3_client = get_s3_client()
        except Exception:
            return []

    try:
        response = s3_client.list_objects_v2(Bucket=bucket_, Prefix=prefix)
    except Exception:
        return []

    documentos = []
    for obj in response.get("Contents", []):
        key = obj["Key"]
        filename = key.rsplit("/", 1)[-1] if "/" in key else key
        ext = os.path.splitext(filename)[1].lower()
        content_type = _CONTENT_TYPE_POR_EXTENSION.get(ext, "application/octet-stream")
        s3_url = f"https://{bucket_}.s3.amazonaws.com/{key}"

        try:
            url_descarga = s3_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": bucket_,
                    "Key": key,
                    "ResponseContentDisposition": f'attachment; filename="{filename}"',
                },
                ExpiresIn=expiration,
            )
        except Exception:
            url_descarga = s3_url

        try:
            url_visualizar = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket_, "Key": key, "ResponseContentDisposition": "inline"},
                ExpiresIn=expiration,
            )
        except Exception:
            url_visualizar = s3_url

        last_modified = obj.get("LastModified")
        documentos.append({
            "filename": filename,
            "s3_key": key,
            "s3_url": s3_url,
            "content_type": content_type,
            "size": obj.get("Size", 0),
            "upload_date": last_modified.isoformat() if last_modified else None,
            "url_descarga": url_descarga,
            "url_visualizar": url_visualizar,
            "url_presigned": url_visualizar,
            "url_expiration_seconds": expiration,
        })
    return documentos


def presign_url(
    s3_key: str,
    expiration: int = 3600,
    disposition: str = "inline",
    s3_client=None,
    bucket: Optional[str] = None,
) -> str:
    """Genera una URL presignada para ``s3_key``. Retorna la URL pública sin firmar si falla."""
    client = s3_client or get_s3_client()
    bucket_ = bucket or bucket_name()
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_, "Key": s3_key, "ResponseContentDisposition": disposition},
            ExpiresIn=expiration,
        )
    except Exception:
        return f"https://{bucket_}.s3.amazonaws.com/{s3_key}"
