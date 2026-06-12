"""
Script de prueba para el endpoint PATCH /editar-requerimiento/{req_id}
"""
import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000"

def run_test():
    print("=== Iniciando Prueba de Editar Requerimiento ===")
    
    # 1. Registrar un requerimiento nuevo para tener un ID válido
    coords = json.dumps({"type": "Point", "coordinates": [-76.5320, 3.4516]})
    organismos = json.dumps(["DAGMA"])
    datos_solicitante = json.dumps({
        "personas": [
            {"nombre": "Solicitante Original", "email": "original@example.com", "telefono": "1234567"}
        ]
    })
    
    register_data = {
        "vid": "VID-TEST-EDIT",
        "datos_solicitante": datos_solicitante,
        "tipo_requerimiento": "Poda de arbol",
        "requerimiento": "Descripcion del requerimiento original",
        "observaciones": "Observaciones originales",
        "coords": coords,
        "organismos_encargados": organismos
    }
    
    try:
        print("\n1. Registrando requerimiento original...")
        reg_resp = requests.post(
            f"{BASE_URL}/registrar-requerimiento",
            data=register_data,
            timeout=30
        )
        
        if reg_resp.status_code != 200:
            print(f"[ERROR] Al registrar: {reg_resp.status_code}")
            print(reg_resp.text)
            return
            
        result = reg_resp.json()
        vid = result.get("vid")
        rid = result.get("rid")
        req_id = f"{vid}_{rid}"
        print(f"[OK] Requerimiento registrado exitosamente con ID: {req_id}")
        print(f"   Descripcion original: {result.get('requerimiento')}")
        
        # 2. Editar el requerimiento usando PATCH /editar-requerimiento/{req_id}
        datos_solicitante_editado = json.dumps({
            "personas": [
                {"nombre": "Solicitante Editado", "email": "editado@example.com", "telefono": "9876543"}
            ]
        })
        edit_data = {
            "requerimiento": "Descripcion del requerimiento ACTUALIZADA",
            "observaciones": "Observaciones ACTUALIZADAS",
            "direccion": "Avenida 4N # 10-20",
            "datos_solicitante": datos_solicitante_editado,
            "organismos_encargados": json.dumps(["EMCALI", "DAGMA"])
        }
        
        print(f"\n2. Editando requerimiento {req_id}...")
        edit_resp = requests.patch(
            f"{BASE_URL}/editar-requerimiento/{req_id}",
            data=edit_data,
            timeout=30
        )
        
        print(f"Status Code: {edit_resp.status_code}")
        if edit_resp.status_code == 200:
            edit_result = edit_resp.json()
            print(f"Response: {json.dumps(edit_result, indent=2, ensure_ascii=False)}")
            
            req_data = edit_result.get("requerimiento", {})
            assert req_data.get("requerimiento") == "Descripcion del requerimiento ACTUALIZADA", "La descripcion no se actualizo"
            assert req_data.get("observaciones") == "Observaciones ACTUALIZADAS", "Las observaciones no se actualizaron"
            assert req_data.get("direccion") == "Avenida 4N # 10-20", "La direccion no se actualizo"
            assert req_data.get("organismos_encargados") == ["EMCALI", "DAGMA"], "Los organismos no se actualizaron"
            
            personas = req_data.get("datos_solicitante", {}).get("personas", [])
            assert len(personas) > 0 and personas[0].get("nombre") == "Solicitante Editado", "Los datos del solicitante no se actualizaron"
            
            print("\n[OK] Todos los asserts pasaron. Prueba del endpoint PATCH de edicion exitosa!")
        else:
            print(f"[ERROR] Al editar: {edit_resp.status_code}")
            print(edit_resp.text)
            
    except Exception as e:
        print(f"[ERROR] Ocurrio un error en la prueba: {str(e)}")

if __name__ == "__main__":
    run_test()
