"""
Script de prueba para el endpoint POST /registrar-requerimiento
Registra 15 requerimientos asociados aleatoriamente a visitas existentes en la colección "visitas".
Verifica que se guarden correctamente en la colección "requerimientos" (requerimientos_dagma).
"""
import requests
import json
import random
import time

BASE_URL = "http://localhost:8000"

# ==================== 15 EJEMPLOS DE REQUERIMIENTOS ====================

EJEMPLOS_REQUERIMIENTOS = [
    {
        "datos_solicitante": {
            "personas": [
                {"nombre": "María López García", "email": "maria.lopez@example.com", "telefono": "+57 300 1234567", "centro_gestor": "DAGMA"}
            ]
        },
        "tipo_requerimiento": "Ambiental",
        "requerimiento": "Solicitud de poda de árboles en vía pública",
        "observaciones": "Árboles con ramas caídas que obstruyen el paso peatonal en la Calle 5 con Carrera 23",
        "coords": {"type": "Point", "coordinates": [-76.5320, 3.4516]},
        "organismos_encargados": ["DAGMA", "Planeación Municipal"]
    },
    {
        "datos_solicitante": {
            "personas": [
                {"nombre": "Juan Carlos Pérez", "email": "jcperez@example.com", "telefono": "+57 310 9876543", "centro_gestor": "Secretaría de Obras"}
            ]
        },
        "tipo_requerimiento": "Infraestructura",
        "requerimiento": "Reparación de baches en vía principal",
        "observaciones": "Baches profundos que generan accidentes vehiculares frecuentes en la Avenida 3 Norte",
        "coords": {"type": "Point", "coordinates": [-76.5280, 3.4620]},
        "organismos_encargados": ["Secretaría de Obras Públicas", "Secretaría de Tránsito"]
    },
    {
        "datos_solicitante": {
            "personas": [
                {"nombre": "Ana María Gómez", "email": "ana.gomez@example.com", "telefono": "+57 315 5551234"},
                {"nombre": "Pedro Ramírez", "email": "pedro.ramirez@example.com", "telefono": "+57 320 6667890"}
            ]
        },
        "tipo_requerimiento": "Salud Pública",
        "requerimiento": "Fumigación contra mosquitos en zona verde",
        "observaciones": "Aumento de casos de dengue reportados por los vecinos del sector, aguas estancadas visibles",
        "coords": {"type": "Point", "coordinates": [-76.5225, 3.4380]},
        "organismos_encargados": ["Secretaría de Salud", "DAGMA"]
    },
    {
        "datos_solicitante": {
            "personas": [
                {"nombre": "Luz Marina Torres", "email": "luz.torres@example.com", "telefono": "+57 301 2223344", "centro_gestor": "Alcaldía"}
            ]
        },
        "tipo_requerimiento": "Seguridad",
        "requerimiento": "Instalación de luminarias en parque público",
        "observaciones": "Parque completamente oscuro en horas nocturnas, reportes frecuentes de robos",
        "coords": {"type": "Point", "coordinates": [-76.5400, 3.4450]},
        "organismos_encargados": ["EMCALI", "Secretaría de Seguridad"]
    },
    {
        "datos_solicitante": {
            "personas": [
                {"nombre": "Carlos Eduardo Martínez", "email": "carlos.martinez@example.com", "telefono": "+57 312 7778899"}
            ]
        },
        "tipo_requerimiento": "Educación",
        "requerimiento": "Mejoramiento de infraestructura escolar",
        "observaciones": "Techo con filtraciones severas en la Institución Educativa del barrio, aulas inundadas en época de lluvias",
        "coords": {"type": "Point", "coordinates": [-76.5150, 3.4700]},
        "organismos_encargados": ["Secretaría de Educación", "Infraestructura y Valorización"]
    },
    {
        "datos_solicitante": {
            "personas": [
                {"nombre": "Sandra Patricia Muñoz", "email": "sandra.munoz@example.com", "telefono": "+57 318 1112233", "centro_gestor": "DAGMA"},
                {"nombre": "Roberto Díaz", "email": "roberto.diaz@example.com", "telefono": "+57 305 4445566"}
            ]
        },
        "tipo_requerimiento": "Ambiental",
        "requerimiento": "Limpieza de caño contaminado",
        "observaciones": "Vertimientos de aguas residuales al caño principal, malos olores afectan a los residentes",
        "coords": {"type": "Point", "coordinates": [-76.5100, 3.4550]},
        "organismos_encargados": ["DAGMA", "EMCALI", "Secretaría de Salud"]
    },
    {
        "datos_solicitante": {
            "personas": [
                {"nombre": "Gloria Esperanza Caicedo", "email": "gloria.caicedo@example.com", "telefono": "+57 316 9990011"}
            ]
        },
        "tipo_requerimiento": "Tránsito",
        "requerimiento": "Señalización vial en intersección peligrosa",
        "observaciones": "Cruce sin semáforo ni señales de pare, accidentes recurrentes reportados por la comunidad",
        "coords": {"type": "Point", "coordinates": [-76.5350, 3.4480]},
        "organismos_encargados": ["Secretaría de Tránsito"]
    },
    {
        "datos_solicitante": {
            "personas": [
                {"nombre": "Diego Fernando Vargas", "email": "diego.vargas@example.com", "telefono": "+57 322 3334455", "centro_gestor": "Secretaría de Vivienda"}
            ]
        },
        "tipo_requerimiento": "Vivienda",
        "requerimiento": "Reubicación de familias en zona de riesgo",
        "observaciones": "12 familias ubicadas en ladera con alto riesgo de deslizamiento según informe técnico",
        "coords": {"type": "Point", "coordinates": [-76.5450, 3.4350]},
        "organismos_encargados": ["Secretaría de Vivienda", "Planeación Municipal", "Bomberos"]
    },
    {
        "datos_solicitante": {
            "personas": [
                {"nombre": "Marta Lucía Ospina", "email": "marta.ospina@example.com", "telefono": "+57 300 5556677"}
            ]
        },
        "tipo_requerimiento": "Recreación",
        "requerimiento": "Mantenimiento de cancha deportiva",
        "observaciones": "Cancha de fútbol sin mantenimiento hace más de un año, grama deteriorada y arcos rotos",
        "coords": {"type": "Point", "coordinates": [-76.5200, 3.4600]},
        "organismos_encargados": ["IMRD", "Secretaría de Cultura"]
    },
    {
        "datos_solicitante": {
            "personas": [
                {"nombre": "Andrés Felipe Ríos", "email": "andres.rios@example.com", "telefono": "+57 311 6667788"},
                {"nombre": "Camila Andrea Suárez", "email": "camila.suarez@example.com", "telefono": "+57 319 8889900"}
            ]
        },
        "tipo_requerimiento": "Desarrollo Social",
        "requerimiento": "Programa de alimentación escolar para familias vulnerables",
        "observaciones": "Comunidad con altos índices de desnutrición infantil según reportes de la ESE local",
        "coords": {"type": "Point", "coordinates": [-76.5180, 3.4420]},
        "organismos_encargados": ["Secretaría de Desarrollo", "Secretaría de Salud", "Secretaría de Educación"]
    },
    {
        "datos_solicitante": {
            "personas": [
                {"nombre": "Héctor Fabio Londoño", "email": "hector.londono@example.com", "telefono": "+57 304 1122334", "centro_gestor": "EMCALI"}
            ]
        },
        "tipo_requerimiento": "Servicios Públicos",
        "requerimiento": "Reparación de red de alcantarillado colapsada",
        "observaciones": "Alcantarilla desbordada que inunda las calles del barrio cuando llueve, afecta 3 manzanas",
        "coords": {"type": "Point", "coordinates": [-76.5270, 3.4530]},
        "organismos_encargados": ["EMCALI"]
    },
    {
        "datos_solicitante": {
            "personas": [
                {"nombre": "Patricia Elena Castro", "email": "patricia.castro@example.com", "telefono": "+57 317 2233445"}
            ]
        },
        "tipo_requerimiento": "Cultura",
        "requerimiento": "Rehabilitación de casa de la cultura del barrio",
        "observaciones": "Edificación patrimonial con daños estructurales, riesgo de colapso parcial",
        "coords": {"type": "Point", "coordinates": [-76.5310, 3.4470]},
        "organismos_encargados": ["Secretaría de Cultura", "Infraestructura y Valorización"]
    },
    {
        "datos_solicitante": {
            "personas": [
                {"nombre": "Fernando José Mejía", "email": "fernando.mejia@example.com", "telefono": "+57 321 3344556"},
                {"nombre": "Isabel Cristina Henao", "email": "isabel.henao@example.com", "telefono": "+57 313 5566778", "centro_gestor": "Planeación"}
            ]
        },
        "tipo_requerimiento": "Planeación",
        "requerimiento": "Regulación de construcciones ilegales en zona protegida",
        "observaciones": "Construcciones sin licencia en zona de protección ambiental del río Cañaveralejo",
        "coords": {"type": "Point", "coordinates": [-76.5380, 3.4390]},
        "organismos_encargados": ["Planeación Municipal", "DAGMA", "Alcaldía de Cali"]
    },
    {
        "datos_solicitante": {
            "personas": [
                {"nombre": "Rosa Elvira Palacios", "email": "rosa.palacios@example.com", "telefono": "+57 306 6677889"}
            ]
        },
        "tipo_requerimiento": "Emergencias",
        "requerimiento": "Atención de emergencia por incendio forestal",
        "observaciones": "Incendio activo en ladera del cerro, amenaza viviendas aledañas, se requiere pronta intervención",
        "coords": {"type": "Point", "coordinates": [-76.5420, 3.4300]},
        "organismos_encargados": ["Bomberos", "DAGMA", "Secretaría de Seguridad"]
    },
    {
        "datos_solicitante": {
            "personas": [
                {"nombre": "Jaime Alberto Restrepo", "email": "jaime.restrepo@example.com", "telefono": "+57 309 7788990", "centro_gestor": "Secretaría de Tránsito"},
                {"nombre": "Liliana Marcela Quintero", "email": "liliana.quintero@example.com", "telefono": "+57 314 8899001"}
            ]
        },
        "tipo_requerimiento": "Movilidad",
        "requerimiento": "Construcción de cicloruta en avenida principal",
        "observaciones": "Alta demanda de ciclistas sin infraestructura adecuada, 3 accidentes fatales en el último semestre",
        "coords": {"type": "Point", "coordinates": [-76.5250, 3.4650]},
        "organismos_encargados": ["Secretaría de Tránsito", "Infraestructura y Valorización", "Planeación Municipal"]
    },
]


def obtener_vids_existentes():
    """Obtiene los VIDs de visitas existentes en la colección 'visitas'"""
    print("📋 Consultando visitas existentes...")
    try:
        response = requests.get(f"{BASE_URL}/obtener-visitas-programadas/", timeout=15)
        if response.status_code == 200:
            data = response.json()
            visitas = data.get("visitas", [])
            vids = [v["vid"] for v in visitas if "vid" in v]
            print(f"   ✅ Se encontraron {len(vids)} visitas: {vids}")
            return vids
        else:
            print(f"   ⚠️ Error consultando visitas: {response.status_code}")
            return []
    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        return []


def registrar_requerimiento(ejemplo, vid, numero):
    """Registra un requerimiento individual"""
    print(f"\n{'─' * 60}")
    print(f"📝 Requerimiento #{numero} → Asociado a {vid}")
    print(f"   Tipo: {ejemplo['tipo_requerimiento']}")
    print(f"   Desc: {ejemplo['requerimiento'][:60]}...")

    data = {
        "vid": vid,
        "datos_solicitante": json.dumps(ejemplo["datos_solicitante"]),
        "tipo_requerimiento": ejemplo["tipo_requerimiento"],
        "requerimiento": ejemplo["requerimiento"],
        "observaciones": ejemplo["observaciones"],
        "coords": json.dumps(ejemplo["coords"]),
        "organismos_encargados": json.dumps(ejemplo["organismos_encargados"]),
    }

    try:
        response = requests.post(
            f"{BASE_URL}/registrar-requerimiento",
            data=data,
            timeout=30,
        )

        print(f"   Status Code: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ Registrado exitosamente:")
            print(f"      VID: {result.get('vid')}")
            print(f"      RID: {result.get('rid')}")
            print(f"      Estado: {result.get('estado')}")
            print(f"      Barrio/Vereda: {result.get('barrio_vereda')}")
            print(f"      Comuna/Corregimiento: {result.get('comuna_corregimiento')}")
            print(f"      Organismos: {result.get('organismos_encargados')}")
            print(f"      Fecha registro: {result.get('fecha_registro')}")

            # Validaciones
            assert result.get("success") is True, "success debe ser True"
            assert result.get("vid") == vid, f"VID debe ser {vid}"
            assert result.get("rid", "").startswith("REQ-"), "RID debe tener formato REQ-#"
            assert result.get("estado") == "Pendiente", "Estado debe ser Pendiente"
            assert result.get("requerimiento") == ejemplo["requerimiento"], "Requerimiento no coincide"
            assert result.get("organismos_encargados") is not None, "Debe tener organismos_encargados"
            assert result.get("fecha_registro") is not None, "Debe tener fecha_registro"
            assert result.get("timestamp") is not None, "Debe tener timestamp"
            print(f"   ✅ Todas las validaciones pasaron")
            return result
        else:
            error_detail = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            print(f"   ❌ Error: {json.dumps(error_detail, indent=2, ensure_ascii=False) if isinstance(error_detail, dict) else error_detail}")
            return None

    except requests.exceptions.ConnectionError:
        print(f"   ❌ No se pudo conectar al servidor en {BASE_URL}")
        return None
    except Exception as e:
        print(f"   ❌ Error inesperado: {str(e)}")
        return None


def verificar_requerimientos_en_firebase(resultados):
    """Verifica que los requerimientos se guardaron consultando la colección"""
    print(f"\n{'=' * 60}")
    print("🔍 VERIFICACIÓN: Consultando requerimientos guardados...")
    print(f"{'=' * 60}")

    # Agrupar por VID
    por_vid = {}
    for r in resultados:
        vid = r["vid"]
        if vid not in por_vid:
            por_vid[vid] = []
        por_vid[vid].append(r["rid"])

    print(f"\n📊 Resumen de requerimientos por visita:")
    for vid, rids in sorted(por_vid.items()):
        print(f"   {vid}: {len(rids)} requerimientos → {', '.join(sorted(rids))}")

    print(f"\n   Total registrado: {len(resultados)} requerimientos")
    print(f"   Distribución en {len(por_vid)} visitas diferentes")


def main():
    print("=" * 60)
    print("🧪 TEST: Registrar 15 Requerimientos")
    print("   Colección destino: requerimientos (requerimientos_dagma)")
    print("   Asociados aleatoriamente a visitas existentes")
    print("=" * 60)

    # 1. Obtener visitas existentes
    vids = obtener_vids_existentes()

    if not vids:
        print("\n⚠️ No se encontraron visitas existentes.")
        print("   Usando VIDs por defecto: VID-1, VID-2, VID-3")
        vids = ["VID-1", "VID-2", "VID-3"]

    # 2. Registrar los 15 requerimientos
    print(f"\n{'=' * 60}")
    print(f"🚀 Registrando 15 requerimientos...")
    print(f"   VIDs disponibles: {vids}")
    print(f"{'=' * 60}")

    resultados_exitosos = []
    resultados_fallidos = []

    for i, ejemplo in enumerate(EJEMPLOS_REQUERIMIENTOS, 1):
        vid_aleatorio = random.choice(vids)
        resultado = registrar_requerimiento(ejemplo, vid_aleatorio, i)

        if resultado:
            resultados_exitosos.append(resultado)
        else:
            resultados_fallidos.append(i)

        # Pequeña pausa para no saturar
        time.sleep(0.3)

    # 3. Resumen final
    print(f"\n{'=' * 60}")
    print(f"📊 RESUMEN FINAL")
    print(f"{'=' * 60}")
    print(f"   ✅ Exitosos: {len(resultados_exitosos)}/15")
    print(f"   ❌ Fallidos: {len(resultados_fallidos)}/15")

    if resultados_fallidos:
        print(f"   Números fallidos: {resultados_fallidos}")

    if resultados_exitosos:
        verificar_requerimientos_en_firebase(resultados_exitosos)

    # 4. Verificación final
    print(f"\n{'=' * 60}")
    if len(resultados_exitosos) == 15:
        print("🎉 TODAS LAS PRUEBAS PASARON - 15/15 requerimientos registrados")
    elif len(resultados_exitosos) > 0:
        print(f"⚠️ PRUEBAS PARCIALES - {len(resultados_exitosos)}/15 registrados")
    else:
        print("❌ TODAS LAS PRUEBAS FALLARON")
    print(f"{'=' * 60}")

    print(f"\n📌 Verifica manualmente en Firebase Console:")
    print(f"   Firestore > colección 'requerimientos_dagma'")
    print(f"   Cada documento debe tener: vid, rid, datos_solicitante, requerimiento,")
    print(f"   observaciones, coords, barrio_vereda, comuna_corregimiento,")
    print(f"   estado='Pendiente', organismos_encargados, fecha_registro, timestamp")


if __name__ == "__main__":
    main()
