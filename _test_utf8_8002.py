"""Test UTF-8 en puerto 8002."""
import requests, json

BASE = "http://localhost:8002"

# Test 1: UTF-8 endpoint
print("TEST 1: GET /test/utf8")
r = requests.get(f"{BASE}/test/utf8")
ct = r.headers.get("content-type", "")
d = r.json()
print(f"  Status: {r.status_code} | Content-Type: {ct}")
print(f"  español: {d.get('español')}")
assert r.status_code == 200
assert "charset=utf-8" in ct.lower()
assert "ñ" in d.get("español", "")
print("  PASS\n")

# Test 2: Health
print("TEST 2: GET /health")
r = requests.get(f"{BASE}/health")
ct = r.headers.get("content-type", "")
print(f"  Status: {r.status_code} | Content-Type: {ct}")
assert "charset=utf-8" in ct.lower()
print("  PASS\n")

# Test 3: OpenAPI sin mojibake
print("TEST 3: OpenAPI - sin mojibake en endpoints")
r = requests.get(f"{BASE}/openapi.json")
openapi = r.json()
paths_req = [p for p in openapi["paths"] if "requerimiento" in p.lower()]
for path in paths_req:
    for method, info in openapi["paths"][path].items():
        summary = info.get("summary", "")
        desc = info.get("description", "")[:100]
        has_mojibake = "\u00c3" in summary or "\u00c3" in desc
        status = "FAIL" if has_mojibake else "PASS"
        print(f"  {method.upper()} {path}: {summary} [{status}]")
        assert not has_mojibake, f"Mojibake en {path}"
print("  PASS\n")

# Test 4: 404 con charset
print("TEST 4: Error 404 con charset")
r = requests.get(f"{BASE}/no-existe")
ct = r.headers.get("content-type", "")
print(f"  Status: {r.status_code} | Content-Type: {ct}")
assert "charset=utf-8" in ct.lower()
print("  PASS\n")

print("=" * 50)
print("TODOS LOS TESTS PASARON")
print("Caracteres soportados: \u00e1 \u00e9 \u00ed \u00f3 \u00fa \u00f1 \u00fc \u00c1 \u00c9 \u00cd \u00d3 \u00da \u00d1 \u00dc \u00bf \u00a1")
print("Content-Type: application/json; charset=utf-8")
