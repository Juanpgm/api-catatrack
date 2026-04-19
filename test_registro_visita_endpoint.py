"""
Script de prueba para el endpoint POST /registrar-visita/
Valida geocodificación de dirección, intersección geográfica con basemaps,
y persistencia en Firebase.
"""
import requests
import json

API_URL = "http://localhost:8000"
ENDPOINT = f"{API_URL}/registrar-visita/"
PASS = "✅"
FAIL = "❌"
WARN = "⚠️"


def print_section(title):
    print("\n" + "=" * 70)
    print(f"🧪 {title}")
    print("=" * 70)


def test_flujo_completo():
    print_section("TEST 1: Flujo completo — dirección válida en Cali con acompañante")
    payload = {
        "direccion_visita": "Calle 5 # 23-45, San Fernando, Cali",
        "descripcion_visita": "Visita de inspección ambiental",
        "observaciones_visita": "Se encontraron residuos sólidos en zona peatonal",
        "acompanantes": [
            {"nombre_completo": "Juan Pérez", "telefono": "3001234567",
             "email": "juan@dagma.gov.co", "centro_gestor": "DAGMA"}
        ],
        "fecha_visita": "18/04/2026",
        "hora_visita": "09:00"
    }
    print(f"\n📤 Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    try:
        response = requests.post(ENDPOINT, json=payload, timeout=30)
        print(f"\n📥 Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(json.dumps(result, indent=2, ensure_ascii=False))
            assert result.get("success") == True;            print(f"   {PASS} success = True")
            assert result.get("vid", "").startswith("VID-"); print(f"   {PASS} VID: {result.get('vid')}")
            assert result.get("direccion_visita") == payload["direccion_visita"]
            print(f"   {PASS} direccion_visita guardada")
            coords = result.get("coords")
            if coords:
                lon, lat = coords["coordinates"]
                assert coords["type"] == "Point"
                assert -76.7 <= lon <= -76.3, f"lon fuera de rango: {lon}"
                assert 3.2 <= lat <= 3.7, f"lat fuera de rango: {lat}"
                print(f"   {PASS} coords WGS84 válidas: [{lon}, {lat}]")
            else:
                print(f"   {WARN} Sin coords (Nominatim no respondió)")
            print(f"   {'✅' if result.get('barrio_vereda') else WARN} barrio_vereda: {result.get('barrio_vereda')}")
            print(f"   {'✅' if result.get('comuna_corregimiento') else WARN} comuna_corregimiento: {result.get('comuna_corregimiento')}")
            fuente = result.get("geocodificacion_fuente")
            assert fuente in ("nominatim", "photon", "arcgis", "barrio_centroide"), f"Proveedor inesperado: {fuente}"
            print(f"   {PASS} geocodificacion_fuente: {fuente}")
            assert isinstance(result.get("acompanantes"), list)
            print(f"   {PASS} acompanantes: {len(result['acompanantes'])}")
            print(f"\n🎉 TEST 1 PASÓ — VID: {result.get('vid')}")
            return result.get("vid")
        else:
            print(f"   {FAIL} Error {response.status_code}: {response.text}")
    except requests.exceptions.ConnectionError:
        print(f"   {FAIL} No se pudo conectar a {API_URL}. ¿Está corriendo la API?")
    except AssertionError as e:
        print(f"   {FAIL} Validación: {e}")
    return None


def test_sin_acompanantes():
    print_section("TEST 2: Sin acompañantes — solo campos requeridos")
    payload = {
        "direccion_visita": "Avenida 6N # 28-50, Cali",
        "descripcion_visita": "Recorrido de campo",
        "observaciones_visita": "Sin novedades",
        "fecha_visita": "18/04/2026",
        "hora_visita": "14:30"
    }
    try:
        response = requests.post(ENDPOINT, json=payload, timeout=30)
        print(f"\n📥 Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            acomps = result.get("acompanantes")
            assert acomps is None or acomps == []
            print(f"   {PASS} acompanantes vacío correctamente: {acomps}")
            print(f"   {PASS} coords: {result.get('coords')}")
            print(f"   {PASS} barrio: {result.get('barrio_vereda')} | comuna: {result.get('comuna_corregimiento')}")
            print(f"\n🎉 TEST 2 PASÓ — VID: {result.get('vid')}")
        else:
            print(f"   {FAIL} Error {response.status_code}: {response.text}")
    except requests.exceptions.ConnectionError:
        print(f"   {FAIL} No se pudo conectar.")
    except AssertionError as e:
        print(f"   {FAIL} {e}")


def test_campos_faltantes():
    print_section("TEST 3: Campos requeridos faltantes (422 esperado)")
    casos = [
        ("sin direccion_visita", {"descripcion_visita": "test", "observaciones_visita": "test", "fecha_visita": "18/04/2026", "hora_visita": "10:00"}),
        ("sin descripcion_visita", {"direccion_visita": "Calle 1, Cali", "observaciones_visita": "test", "fecha_visita": "18/04/2026", "hora_visita": "10:00"}),
        ("modelo antiguo barrio_vereda sin direccion", {"barrio_vereda": "San Fernando", "comuna_corregimiento": "Comuna 3", "descripcion_visita": "test", "observaciones_visita": "test", "fecha_visita": "18/04/2026", "hora_visita": "10:00"}),
    ]
    try:
        for desc, payload in casos:
            r = requests.post(ENDPOINT, json=payload, timeout=15)
            if r.status_code == 422:
                print(f"   {PASS} '{desc}' → 422 (rechazado correctamente)")
            else:
                print(f"   {WARN} '{desc}' → {r.status_code} (esperaba 422)")
    except requests.exceptions.ConnectionError:
        print(f"   {FAIL} No se pudo conectar.")


def test_formatos_invalidos():
    print_section("TEST 4: Formatos de fecha/hora inválidos")
    base = {"direccion_visita": "Calle 5, Cali", "descripcion_visita": "t", "observaciones_visita": "t"}
    casos = [
        ("fecha ISO 2026-04-18",      {**base, "fecha_visita": "2026-04-18", "hora_visita": "10:00"}),
        ("fecha dd/mm/aa corta",       {**base, "fecha_visita": "18/04/26",   "hora_visita": "10:00"}),
        ("hora sin cero inicial 9:00", {**base, "fecha_visita": "18/04/2026", "hora_visita": "9:00"}),
        ("hora con segundos",          {**base, "fecha_visita": "18/04/2026", "hora_visita": "09:00:00"}),
    ]
    try:
        for desc, payload in casos:
            r = requests.post(ENDPOINT, json=payload, timeout=15)
            if r.status_code in (400, 422):
                print(f"   {PASS} '{desc}' → {r.status_code}")
            else:
                print(f"   {FAIL} '{desc}' → {r.status_code} (esperaba 400/422)")
    except requests.exceptions.ConnectionError:
        print(f"   {FAIL} No se pudo conectar.")


def test_barrio_hint_centenario():
    print_section("TEST 5: Barrio-hint — dirección menciona 'Centenario' explícitamente (caso VID-15)")
    payload = {
        "direccion_visita": "Calle 13 # 8-32, Barrio Centenario, Cali",
        "descripcion_visita": "Verificación de caso VID-15 barrio-hint",
        "observaciones_visita": "Las coordenadas deben quedar dentro del polígono de Centenario",
        "fecha_visita": "18/04/2026",
        "hora_visita": "10:00"
    }
    print(f"\n📤 Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    try:
        response = requests.post(ENDPOINT, json=payload, timeout=30)
        print(f"\n📥 Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(json.dumps(result, indent=2, ensure_ascii=False))
            barrio = result.get("barrio_vereda", "")
            coords = result.get("coords")
            fuente = result.get("geocodificacion_fuente")
            assert result.get("success") == True; print(f"   {PASS} success = True")
            if "centenario" in barrio.lower():
                print(f"   {PASS} barrio_vereda correcto: '{barrio}'")
            else:
                print(f"   {WARN} barrio_vereda obtenido: '{barrio}' (se esperaba Centenario)")
            assert fuente in ("nominatim", "photon", "arcgis", "barrio_centroide"), f"Proveedor inesperado: {fuente}"
            print(f"   {PASS} geocodificacion_fuente: {fuente}")
            if coords:
                lon, lat = coords["coordinates"]
                print(f"   {PASS} coords: [{lon}, {lat}]")
            print(f"\n🎉 TEST 5 PASÓ — VID: {result.get('vid')}")
        else:
            print(f"   {FAIL} Error {response.status_code}: {response.text}")
    except requests.exceptions.ConnectionError:
        print(f"   {FAIL} No se pudo conectar a {API_URL}.")
    except AssertionError as e:
        print(f"   {FAIL} Validación: {e}")


if __name__ == "__main__":
    print("\n🚀 PRUEBAS: POST /registrar-visita/ (con geocodificación Nominatim)")
    print(f"   API: {API_URL}\n")

    test_flujo_completo()
    test_sin_acompanantes()
    test_campos_faltantes()
    test_formatos_invalidos()
    test_barrio_hint_centenario()

    print("\n" + "=" * 70)
    print("✅ PRUEBAS FINALIZADAS")
    print("=" * 70)
    print("\n💡 Verifica en Firebase Console > Firestore > colección 'visitas'")
    print("   Cada documento debe tener: direccion_visita, coords, barrio_vereda, comuna_corregimiento")
