"""
Test script: verifica que POST /registrar-requerimiento suba fotos a S3
y que GET /obtener-requerimientos devuelva documentos_con_enlaces con presigned URLs.
"""
import requests
import json
import io
import os
import time

BASE_URL = "http://localhost:8000"


def _make_fake_image(name="test_foto.jpg", size=1024, content_type="image/jpeg"):
    """Genera un archivo fake en memoria."""
    content = b"\xff\xd8\xff\xe0" + os.urandom(size - 4)  # JPEG magic bytes + random
    return (name, content, content_type)


def test_post_con_fotos():
    """POST /registrar-requerimiento con fotos => deben subirse a S3."""
    print("\n=== Test 1: POST con fotos adjuntas ===")

    coords = json.dumps({"type": "Point", "coordinates": [-76.5320, 3.4516]})
    organismos = json.dumps(["DAGMA"])
    datos_solicitante = json.dumps({
        "personas": [{"nombre": "Test S3 Fotos", "email": "test@example.com",
                       "telefono": "+57 300 0000000", "centro_gestor": "DAGMA"}]
    })

    data = {
        "vid": "VID-TEST-S3",
        "datos_solicitante": datos_solicitante,
        "tipo_requerimiento": "Ambiental",
        "requerimiento": "Prueba de subida de fotos al bucket S3",
        "observaciones": "Test automatizado - se puede borrar",
        "coords": coords,
        "organismos_encargados": organismos,
        "direccion": "Calle 5 # 10-20, Barrio San Fernando",
    }

    # Crear dos fotos fake
    foto1 = _make_fake_image("foto_arbol.jpg", 2048, "image/jpeg")
    foto2 = _make_fake_image("evidencia.png", 1536, "image/png")

    files = [
        ("fotos", foto1),
        ("fotos", foto2),
    ]

    try:
        resp = requests.post(f"{BASE_URL}/registrar-requerimiento", data=data,
                             files=files, timeout=30)
        print(f"Status: {resp.status_code}")
        result = resp.json()
        print(json.dumps(result, indent=2, ensure_ascii=False))

        if resp.status_code != 200:
            print("❌ POST falló")
            return None

        # Verificar documentos_urls en la respuesta
        docs = result.get("documentos_urls")
        if docs and len(docs) == 2:
            print(f"✅ documentos_urls tiene {len(docs)} documentos")
            for d in docs:
                print(f"   - {d['filename']}  ({d['size']} bytes)  s3_key={d['s3_key']}")
        else:
            print(f"❌ Se esperaban 2 documentos_urls, se obtuvieron: {docs}")

        return result

    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def test_post_sin_fotos():
    """POST sin fotos => backward compatible, documentos_urls debe ser null."""
    print("\n=== Test 2: POST sin fotos (backward compatible) ===")

    coords = json.dumps({"type": "Point", "coordinates": [-76.5320, 3.4516]})
    organismos = json.dumps(["DAGMA"])
    datos_solicitante = json.dumps({
        "personas": [{"nombre": "Test Sin Fotos", "email": "test2@example.com",
                       "telefono": "+57 300 1111111", "centro_gestor": "DAGMA"}]
    })

    data = {
        "vid": "VID-TEST-S3",
        "datos_solicitante": datos_solicitante,
        "tipo_requerimiento": "Ambiental",
        "requerimiento": "Prueba sin fotos",
        "observaciones": "Sin adjuntos",
        "coords": coords,
        "organismos_encargados": organismos,
    }

    try:
        resp = requests.post(f"{BASE_URL}/registrar-requerimiento", data=data, timeout=30)
        print(f"Status: {resp.status_code}")
        result = resp.json()
        if resp.status_code == 200:
            docs = result.get("documentos_urls")
            if docs is None:
                print("✅ documentos_urls es null (correcto para sin fotos)")
            else:
                print(f"⚠️ documentos_urls debería ser null, es: {docs}")
        else:
            print(f"❌ POST falló: {result}")
    except Exception as e:
        print(f"❌ Error: {e}")


def test_get_documentos_con_enlaces():
    """GET /obtener-requerimientos?vid=VID-TEST-S3 => documentos_con_enlaces con presigned URLs."""
    print("\n=== Test 3: GET con documentos_con_enlaces ===")

    try:
        resp = requests.get(f"{BASE_URL}/obtener-requerimientos",
                            params={"vid": "VID-TEST-S3"}, timeout=30)
        print(f"Status: {resp.status_code}")
        result = resp.json()

        if resp.status_code != 200:
            print(f"❌ GET falló: {result}")
            return

        reqs = result.get("requerimientos", [])
        print(f"Total requerimientos para VID-TEST-S3: {len(reqs)}")

        found_docs = False
        for r in reqs:
            docs = r.get("documentos_con_enlaces", [])
            total = r.get("total_documentos", 0)
            rid = r.get("rid", "?")
            print(f"\n  RID={rid}  total_documentos={total}")
            if docs:
                found_docs = True
                for d in docs:
                    print(f"    - {d['filename']}  ({d.get('size',0)} bytes)  content_type={d.get('content_type')}")
                    # Verificar que las URLs presignadas están presentes
                    has_urls = all(k in d for k in ("url_descarga", "url_visualizar", "url_presigned"))
                    if has_urls:
                        print(f"      url_descarga: {d['url_descarga'][:80]}...")
                        print(f"      url_visualizar: {d['url_visualizar'][:80]}...")
                    else:
                        print(f"      ❌ Faltan URLs presignadas: {list(d.keys())}")

        if found_docs:
            print("\n✅ documentos_con_enlaces con presigned URLs verificados")
        else:
            print("\n⚠️ No se encontraron documentos - puede que el POST previo no haya subido fotos")

    except Exception as e:
        print(f"❌ Error: {e}")


def test_presigned_url_accessible():
    """Descarga un documento via presigned URL para verificar accesibilidad."""
    print("\n=== Test 4: Verificar accesibilidad de presigned URL ===")

    try:
        resp = requests.get(f"{BASE_URL}/obtener-requerimientos",
                            params={"vid": "VID-TEST-S3"}, timeout=30)
        if resp.status_code != 200:
            print("❌ No se pudo obtener requerimientos")
            return

        reqs = resp.json().get("requerimientos", [])
        for r in reqs:
            for d in r.get("documentos_con_enlaces", []):
                url = d.get("url_descarga")
                if url:
                    # Show signing region
                    import urllib.parse as up
                    qs = up.parse_qs(up.urlparse(url).query)
                    cred = qs.get("X-Amz-Credential", ["?"])[0]
                    region = cred.split("/")[2] if "/" in cred else cred
                    print(f"  Signing region: {region}")
                    print(f"  File: {d['filename']}")
                    dl = requests.get(url, timeout=15)
                    print(f"  HTTP status: {dl.status_code}")
                    if dl.status_code == 200 and len(dl.content) > 0:
                        print(f"  ✅ Presigned URL accesible ({len(dl.content)} bytes)")
                    else:
                        print(f"  ❌ Error: {dl.text[:200]}")
                    return
        print("⚠️ No se encontró ningún documento para verificar URL")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    print("=" * 70)
    print("TEST: S3 Documents en registrar/obtener-requerimientos")
    print("=" * 70)

    # Test 1: POST con fotos
    result = test_post_con_fotos()

    # Test 2: POST sin fotos (backward compatible)
    test_post_sin_fotos()

    # Pequeña pausa para propagación
    time.sleep(1)

    # Test 3: GET con documentos_con_enlaces
    test_get_documentos_con_enlaces()

    # Test 4: Verificar que presigned URL funciona
    test_presigned_url_accessible()

    print("\n" + "=" * 70)
    print("TESTS COMPLETADOS")
    print("=" * 70)
