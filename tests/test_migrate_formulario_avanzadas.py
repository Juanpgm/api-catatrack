"""
Tests de las transformaciones puras usadas por el script de migración
one-off de ``Formulario Avanzadas.xlsx`` hacia Firestore
(``scripts/migrate_formulario_avanzadas_transforms.py``).

Todas las funciones bajo prueba son puras (sin dependencia de Firestore ni
de pandas más allá de la detección de NaN): reciben dicts/listas de dicts
"planos" (como los que produce ``DataFrame.to_dict('records')``) y
retornan dicts/listas de dicts + una lista de warnings. Esto permite
probarlas sin mocks de infraestructura.

También incluye un test de compatibilidad que alimenta un documento
"avanzada" + "requerimiento" ya transformado directamente a los modelos
Pydantic reales de ``app.routes.avanzadas_routes`` (``AvanzadaOut`` /
``RequerimientoAvanzadaOut``) para probar que la migración produce datos
que el resto de la API puede leer sin errores de validación.
"""
from __future__ import annotations

import datetime as dt
import math

import pytest

from app.routes.avanzadas_routes import AvanzadaOut, RequerimientoAvanzadaOut
from scripts import migrate_formulario_avanzadas_transforms as tr


NAN = float("nan")


# ──────────────────────────────────────────────────────────────────────────
# Helpers de bajo nivel
# ──────────────────────────────────────────────────────────────────────────

class TestSplitNames:
    def test_splits_comma_separated_names_and_strips(self):
        assert tr.split_names("Cristian Andres Toledo, Rodolfo Ramos Bonilla") == [
            "Cristian Andres Toledo",
            "Rodolfo Ramos Bonilla",
        ]

    def test_single_name_returns_single_item_list(self):
        assert tr.split_names("Ana Maria Carabali") == ["Ana Maria Carabali"]

    def test_nan_returns_empty_list(self):
        assert tr.split_names(NAN) == []

    def test_none_returns_empty_list(self):
        assert tr.split_names(None) == []


class TestNormalizeCelular:
    def test_float_phone_strips_trailing_zero_decimal(self):
        assert tr.normalize_celular(3175783808.0) == "3175783808"

    def test_int_phone_becomes_string(self):
        assert tr.normalize_celular(3165796112) == "3165796112"

    def test_string_phone_is_stripped(self):
        assert tr.normalize_celular("  3001234567  ") == "3001234567"

    def test_nan_becomes_empty_string(self):
        assert tr.normalize_celular(NAN) == ""

    def test_none_becomes_empty_string(self):
        assert tr.normalize_celular(None) == ""


class TestSplitUrls:
    def test_splits_on_pipe_and_strips(self):
        raw = (
            "https://drive.google.com/a | https://drive.google.com/b | "
            "https://drive.google.com/c"
        )
        assert tr.split_urls(raw) == [
            "https://drive.google.com/a",
            "https://drive.google.com/b",
            "https://drive.google.com/c",
        ]

    def test_single_url_returns_single_item_list(self):
        assert tr.split_urls("https://drive.google.com/a") == [
            "https://drive.google.com/a"
        ]

    def test_nan_returns_empty_list(self):
        assert tr.split_urls(NAN) == []

    def test_none_returns_empty_list(self):
        assert tr.split_urls(None) == []


class TestCleanOptionalString:
    def test_nan_becomes_none(self):
        assert tr.clean_optional_str(NAN) is None

    def test_none_stays_none(self):
        assert tr.clean_optional_str(None) is None

    def test_string_is_stripped(self):
        assert tr.clean_optional_str("  3.48, -76.51  ") == "3.48, -76.51"

    def test_empty_string_becomes_none(self):
        assert tr.clean_optional_str("   ") is None


class TestFormatFechaDate:
    def test_datetime_formats_as_iso_date(self):
        assert tr.format_fecha_date(dt.datetime(2026, 5, 6, 0, 0)) == "2026-05-06"

    def test_date_only_formats_as_iso_date(self):
        assert tr.format_fecha_date(dt.date(2026, 6, 13)) == "2026-06-13"

    def test_nan_returns_none(self):
        assert tr.format_fecha_date(NAN) is None


class TestColombiaIsoFromFecha:
    def test_attaches_colombia_offset(self):
        result = tr.colombia_iso_from_fecha(dt.datetime(2026, 5, 6, 0, 0))
        assert result == "2026-05-06T00:00:00-05:00"

    def test_different_date_produces_different_iso(self):
        result = tr.colombia_iso_from_fecha(dt.datetime(2026, 6, 13, 9, 30))
        assert result == "2026-06-13T09:30:00-05:00"

    def test_nan_returns_none(self):
        assert tr.colombia_iso_from_fecha(NAN) is None


class TestSlugifyCategoriaKey:
    def test_builds_deterministic_slug(self):
        assert tr.slugify_categoria_key("DAGMA", "Tratamiento Fitosanitario (Árbol)") == (
            "dagma__tratamiento-fitosanitario-arbol"
        )

    def test_same_input_is_idempotent(self):
        a = tr.slugify_categoria_key("UAESP", "Luminaria encendida (Día)")
        b = tr.slugify_categoria_key("UAESP", "Luminaria encendida (Día)")
        assert a == b

    def test_different_categoria_gives_different_slug(self):
        a = tr.slugify_categoria_key("DAGMA", "Poda de árboles")
        b = tr.slugify_categoria_key("DAGMA", "Extracción de raíces")
        assert a != b


class TestParseEvaluaciones:
    def test_parses_json_array_of_objects(self):
        raw = '[{"org":"UAESP","calif":"Bueno"},{"org":"DAGMA","calif":"Regular"}]'
        assert tr.parse_evaluaciones(raw) == [
            {"org": "UAESP", "calif": "Bueno"},
            {"org": "DAGMA", "calif": "Regular"},
        ]

    def test_invalid_json_returns_empty_list(self):
        assert tr.parse_evaluaciones("not json") == []

    def test_nan_returns_empty_list(self):
        assert tr.parse_evaluaciones(NAN) == []


# ──────────────────────────────────────────────────────────────────────────
# build_asistentes_by_avanzada
# ──────────────────────────────────────────────────────────────────────────

class TestBuildAsistentesByAvanzada:
    def test_groups_asistentes_by_client_id(self):
        rows = [
            {
                "ClientId": "cid-1",
                "Nombre Participante": "Juan Perez",
                "Organismo": "DAGMA - Depto",
                "Celular": 3175783808.0,
                "Correo": "juan@test.com",
            },
            {
                "ClientId": "cid-1",
                "Nombre Participante": "Ana Gomez",
                "Organismo": "UAESP - Unidad",
                "Celular": 3165796112,
                "Correo": "ana@test.com",
            },
            {
                "ClientId": "cid-2",
                "Nombre Participante": "Otro",
                "Organismo": "DAGMA",
                "Celular": NAN,
                "Correo": "otro@test.com",
            },
        ]
        grouped, warnings = tr.build_asistentes_by_avanzada(rows)
        assert grouped == {
            "cid-1": [
                {
                    "nombre": "Juan Perez",
                    "organismo": "DAGMA - Depto",
                    "celular": "3175783808",
                    "correo": "juan@test.com",
                },
                {
                    "nombre": "Ana Gomez",
                    "organismo": "UAESP - Unidad",
                    "celular": "3165796112",
                    "correo": "ana@test.com",
                },
            ],
            "cid-2": [
                {
                    "nombre": "Otro",
                    "organismo": "DAGMA",
                    "celular": "",
                    "correo": "otro@test.com",
                },
            ],
        }
        assert warnings == []

    def test_skips_row_with_missing_client_id_and_warns(self):
        rows = [
            {
                "ClientId": NAN,
                "Nombre Participante": "Sin avanzada",
                "Organismo": "DAGMA",
                "Celular": 123,
                "Correo": "x@test.com",
            }
        ]
        grouped, warnings = tr.build_asistentes_by_avanzada(rows)
        assert grouped == {}
        assert len(warnings) == 1
        assert "ClientId" in warnings[0]


# ──────────────────────────────────────────────────────────────────────────
# build_requerimientos (incluye asignación de req_index)
# ──────────────────────────────────────────────────────────────────────────

class TestBuildRequerimientos:
    def _row(self, **overrides):
        base = {
            "Fecha": dt.datetime(2026, 5, 9, 0, 0),
            "Nombre Avanzada": "Primera avanzada - Via Cristo Rey",
            "Estrategia": "Plan de Choque",
            "Entidad": "EMCALI - Empresas Municipales de Cali",
            "Categoría": "Otro – EMCALI",
            "Requerimiento": "Instalación de cableado eléctrico irregular",
            "Ubicación": "Kr 4B entre Cl 12 Oe y 13 Oe, Cali",
            "Evidencia fotográfica": "https://drive.google.com/a | https://drive.google.com/b",
            "Coordenadas": "3.445444, -76.552381",
            "ClientId": "cid-1",
            "ReqIndex": NAN,
        }
        base.update(overrides)
        return base

    def test_assigns_sequential_req_index_per_avanzada_in_row_order(self):
        rows = [self._row(ClientId="cid-1"), self._row(ClientId="cid-1"), self._row(ClientId="cid-2")]
        docs, warnings = tr.build_requerimientos(rows)
        assert warnings == []
        ids_and_index = sorted(
            (d["avanzada_client_id"], d["req_index"]) for d in docs.values()
        )
        assert ids_and_index == [("cid-1", 0), ("cid-1", 1), ("cid-2", 0)]

    def test_doc_id_is_client_id_underscore_req_index(self):
        rows = [self._row(ClientId="cid-1")]
        docs, _ = tr.build_requerimientos(rows)
        assert list(docs.keys()) == ["cid-1_0"]

    def test_doc_fields_match_target_model(self):
        rows = [self._row(ClientId="cid-1")]
        docs, _ = tr.build_requerimientos(rows)
        doc = docs["cid-1_0"]
        assert doc["avanzada_client_id"] == "cid-1"
        assert doc["req_index"] == 0
        assert doc["entidad"] == "EMCALI - Empresas Municipales de Cali"
        assert doc["categoria"] == "Otro – EMCALI"
        assert doc["categoria_personalizada"] is None
        assert doc["requerimiento"] == "Instalación de cableado eléctrico irregular"
        assert doc["ubicacion"] == "Kr 4B entre Cl 12 Oe y 13 Oe, Cali"
        assert doc["coordenadas"] == "3.445444, -76.552381"
        assert doc["fotos_urls"] == [
            "https://drive.google.com/a",
            "https://drive.google.com/b",
        ]
        assert doc["fecha"] == "2026-05-09"
        assert doc["nombre_avanzada"] == "Primera avanzada - Via Cristo Rey"
        assert doc["estrategia"] == "Plan de Choque"
        assert doc["created_at"] == "2026-05-09T00:00:00-05:00"

    def test_skips_row_with_missing_client_id_and_warns(self):
        rows = [self._row(ClientId=NAN)]
        docs, warnings = tr.build_requerimientos(rows)
        assert docs == {}
        assert len(warnings) == 1
        assert "ClientId" in warnings[0]


# ──────────────────────────────────────────────────────────────────────────
# build_avanzadas
# ──────────────────────────────────────────────────────────────────────────

class TestBuildAvanzadas:
    def _row(self, **overrides):
        base = {
            "No": 1,
            "Fecha": dt.datetime(2026, 5, 6, 0, 0),
            "Nombre Avanzada": "Comuna 2 - (Urb. La Flora - Vipasa)",
            "Estrategia": "Plan de Choque",
            "Sector": "Migración Colombia",
            "Comuna/Corregimiento": "COMUNA 2",
            "Barrio/Vereda": "La Flora",
            "Dirección": "Av. 3AN # 50N -20, Vipasa, Cali",
            "Coordenadas": "3.483293, -76.515065",
            "Encargados": "Cristian Andres Toledo, Rodolfo Ramos Bonilla",
            "ClientId": "56f7fc52-27f0-40a2-98ff-fd8a182d1187",
            "Unnamed: 11": "https://drive.google.com/file/d/xyz/view",
        }
        base.update(overrides)
        return base

    def test_builds_doc_with_joined_asistentes_and_req_count(self):
        rows = [self._row()]
        asistentes_by_id = {
            "56f7fc52-27f0-40a2-98ff-fd8a182d1187": [
                {"nombre": "Juan", "organismo": "DAGMA", "celular": "300", "correo": "j@t.com"}
            ]
        }
        req_counts = {"56f7fc52-27f0-40a2-98ff-fd8a182d1187": 3}
        docs, warnings = tr.build_avanzadas(rows, asistentes_by_id, req_counts)
        assert warnings == []
        doc = docs["56f7fc52-27f0-40a2-98ff-fd8a182d1187"]
        assert doc["client_id"] == "56f7fc52-27f0-40a2-98ff-fd8a182d1187"
        assert doc["numero"] == 1
        assert doc["fecha"] == "2026-05-06"
        assert doc["nombre_avanzada"] == "Comuna 2 - (Urb. La Flora - Vipasa)"
        assert doc["estrategia"] == "Plan de Choque"
        assert doc["sector"] == "Migración Colombia"
        assert doc["comuna"] == "COMUNA 2"
        assert doc["barrio"] == "La Flora"
        assert doc["direccion"] == "Av. 3AN # 50N -20, Vipasa, Cali"
        assert doc["coordenadas"] == "3.483293, -76.515065"
        assert doc["encargados"] == ["Cristian Andres Toledo", "Rodolfo Ramos Bonilla"]
        assert doc["asistentes"] == [
            {"nombre": "Juan", "organismo": "DAGMA", "celular": "300", "correo": "j@t.com"}
        ]
        assert doc["foto_equipo_url"] is None
        assert doc["informe_url"] == "https://drive.google.com/file/d/xyz/view"
        assert doc["requerimientos_count"] == 3
        assert doc["created_by"] == "migracion-excel"
        assert doc["created_at"] == "2026-05-06T00:00:00-05:00"
        assert doc["updated_at"] == "2026-05-06T00:00:00-05:00"

    def test_avanzada_without_asistentes_or_requerimientos_gets_empty_defaults(self):
        rows = [self._row(ClientId="cid-solo")]
        docs, warnings = tr.build_avanzadas(rows, {}, {})
        assert warnings == []
        doc = docs["cid-solo"]
        assert doc["asistentes"] == []
        assert doc["requerimientos_count"] == 0

    def test_skips_row_with_missing_client_id_and_warns(self):
        rows = [self._row(ClientId=NAN)]
        docs, warnings = tr.build_avanzadas(rows, {}, {})
        assert docs == {}
        assert len(warnings) == 1
        assert "ClientId" in warnings[0]


# ──────────────────────────────────────────────────────────────────────────
# build_categorias_personalizadas
# ──────────────────────────────────────────────────────────────────────────

class TestBuildCategoriasPersonalizadas:
    def test_builds_doc_with_deterministic_slug_id(self):
        rows = [
            {
                "Entidad": "DAGMA",
                "Categoria": "Tratamiento Fitosanitario (Árbol)",
                "Fecha": dt.datetime(2026, 5, 6, 10, 43, 12),
            }
        ]
        docs, warnings = tr.build_categorias_personalizadas(rows)
        assert warnings == []
        expected_id = tr.slugify_categoria_key("DAGMA", "Tratamiento Fitosanitario (Árbol)")
        assert expected_id in docs
        doc = docs[expected_id]
        assert doc["entidad"] == "DAGMA"
        assert doc["categoria"] == "Tratamiento Fitosanitario (Árbol)"
        assert doc["fecha"] == "2026-05-06"

    def test_two_different_rows_produce_two_docs(self):
        rows = [
            {"Entidad": "DAGMA", "Categoria": "A", "Fecha": dt.datetime(2026, 1, 1)},
            {"Entidad": "UAESP", "Categoria": "B", "Fecha": dt.datetime(2026, 1, 2)},
        ]
        docs, warnings = tr.build_categorias_personalizadas(rows)
        assert warnings == []
        assert len(docs) == 2

    def test_skips_row_missing_entidad_and_warns(self):
        rows = [{"Entidad": NAN, "Categoria": "A", "Fecha": dt.datetime(2026, 1, 1)}]
        docs, warnings = tr.build_categorias_personalizadas(rows)
        assert docs == {}
        assert len(warnings) == 1


# ──────────────────────────────────────────────────────────────────────────
# Nuevas colecciones (JornadasIntegrales / Compromisos / Seguimientos / Encuestas)
# ──────────────────────────────────────────────────────────────────────────

class TestBuildJornadas:
    def test_builds_doc_from_row(self):
        rows = [
            {
                "No": 1,
                "Fecha": dt.datetime(2026, 6, 13, 0, 0),
                "ClientId": "jor_bbf4cf01-f948-4508-82dc-5b905a8f1612",
                "Nombre Jornada": "Comuna 2 - Panadería Kuty, Bosque",
                "Sector/Punto Reconocimiento": NAN,
                "Punto Encuentro": "Panadería Kuty, Bosque",
                "Direccion Punto Encuentro": "Av 6 N #46-49, El Bosque, Cali",
                "Coordenadas Encuentro": "3.484, -76.526",
                "Comuna/Corregimiento": "COMUNA 2",
                "Barrio/Vereda": "El Bosque",
                "Direcciones Recuperadas": "Avenida 6A N entre Calle 45 N - 47 N",
                "Estado": "completada",
                "Asistencia Aproximada": 100,
                "Observaciones Generales": "Todo bien",
                "Peticiones Comunidad": NAN,
                "URL Croquis": NAN,
                "URL Informe PDF": "https://drive.google.com/informe",
                "Creado": dt.datetime(2026, 6, 12, 19, 59, 39),
                "Actualizado": dt.datetime(2026, 6, 18, 10, 12, 25),
            }
        ]
        docs, warnings = tr.build_jornadas(rows)
        assert warnings == []
        doc = docs["jor_bbf4cf01-f948-4508-82dc-5b905a8f1612"]
        assert doc["nombre_jornada"] == "Comuna 2 - Panadería Kuty, Bosque"
        assert doc["sector_punto_reconocimiento"] is None
        assert doc["estado"] == "completada"
        assert doc["asistencia_aproximada"] == 100
        assert doc["fecha"] == "2026-06-13"
        assert doc["creado"] == dt.datetime(2026, 6, 12, 19, 59, 39, tzinfo=dt.timezone.utc)
        assert doc["actualizado"] == dt.datetime(2026, 6, 18, 10, 12, 25, tzinfo=dt.timezone.utc)

    def test_skips_row_missing_client_id(self):
        rows = [{"ClientId": NAN, "No": 1, "Fecha": dt.datetime(2026, 1, 1)}]
        docs, warnings = tr.build_jornadas(rows)
        assert docs == {}
        assert len(warnings) == 1


class TestBuildCompromisos:
    def test_builds_doc_with_normalized_phone_and_urls(self):
        rows = [
            {
                "No": 1,
                "Fecha": dt.datetime(2026, 6, 12, 20, 8, 10),
                "ClientId": "com_8bb04a0c-c45c-4990-8031-6d5965dbb9d1",
                "JornadaClientId": "jor_bbf4cf01-f948-4508-82dc-5b905a8f1612",
                "Nombre Jornada": "Comuna 2 - Panadería Kuty, Bosque",
                "Organismo": "UAESP - Unidad",
                "Oferta/Servicio": "Recuperación de zonas verdes",
                "Responsable Organismo": "UAESP",
                "Celular Responsable": 3001234567.0,
                "Tipo": "cualitativo",
                "Compromiso": "Recuperacion y limpieza",
                "Unidad Medida": "Jornada",
                "Meta Cuantitativa": 0,
                "Estado Seguimiento": "ok",
                "Estado Verificacion Campo": "cumple",
                "Fecha Verificacion": dt.datetime(2026, 6, 18, 0, 0),
                "Responsable Verificacion": NAN,
                "Representante Organismo": "Jaime Restrepo",
                "Resultado Obtenido": 0,
                "Comentario Verificacion": "Se realizó la recuperación",
                "Fotos Verificacion": "https://drive.google.com/a | https://drive.google.com/b",
                "Creado": dt.datetime(2026, 6, 12, 20, 8, 10),
                "Actualizado": dt.datetime(2026, 6, 18, 9, 51, 43),
            }
        ]
        docs, warnings = tr.build_compromisos(rows)
        assert warnings == []
        doc = docs["com_8bb04a0c-c45c-4990-8031-6d5965dbb9d1"]
        assert doc["jornada_client_id"] == "jor_bbf4cf01-f948-4508-82dc-5b905a8f1612"
        assert doc["celular_responsable"] == "3001234567"
        assert doc["fotos_verificacion"] == [
            "https://drive.google.com/a",
            "https://drive.google.com/b",
        ]
        assert doc["fecha_verificacion"] == "2026-06-18"

    def test_skips_row_missing_client_id(self):
        rows = [{"ClientId": NAN, "No": 1, "Fecha": dt.datetime(2026, 1, 1)}]
        docs, warnings = tr.build_compromisos(rows)
        assert docs == {}
        assert len(warnings) == 1


class TestBuildSeguimientos:
    def test_resolves_jornada_client_id_via_compromiso(self):
        rows = [
            {
                "No": 1,
                "Fecha": dt.datetime(2026, 6, 12, 20, 14, 32),
                "ClientId": "seg_4fda1874-aa3c-4a90-a0e2-65c4e899209c",
                "CompromisoClientId": "com_8bb04a0c-c45c-4990-8031-6d5965dbb9d1",
                "Fecha Seguimiento": dt.datetime(2026, 6, 13, 0, 0),
                "Estado": "ok",
                "Responsable Seguimiento": "Leonardo y Victor",
                "Comentario Seguimiento": "OK",
                "Creado": dt.datetime(2026, 6, 12, 20, 14, 32),
            }
        ]
        compromiso_to_jornada = {
            "com_8bb04a0c-c45c-4990-8031-6d5965dbb9d1": "jor_bbf4cf01-f948-4508-82dc-5b905a8f1612"
        }
        docs, warnings = tr.build_seguimientos(rows, compromiso_to_jornada)
        assert warnings == []
        doc = docs["seg_4fda1874-aa3c-4a90-a0e2-65c4e899209c"]
        assert doc["compromiso_client_id"] == "com_8bb04a0c-c45c-4990-8031-6d5965dbb9d1"
        assert doc["jornada_client_id"] == "jor_bbf4cf01-f948-4508-82dc-5b905a8f1612"
        assert doc["fecha_seguimiento"] == "2026-06-13"

    def test_unresolvable_compromiso_sets_jornada_client_id_none_and_warns(self):
        rows = [
            {
                "No": 1,
                "Fecha": dt.datetime(2026, 6, 12, 20, 14, 32),
                "ClientId": "seg_orphan",
                "CompromisoClientId": "com_does_not_exist",
                "Fecha Seguimiento": dt.datetime(2026, 6, 13, 0, 0),
                "Estado": "ok",
                "Responsable Seguimiento": "X",
                "Comentario Seguimiento": "Y",
                "Creado": dt.datetime(2026, 6, 12, 20, 14, 32),
            }
        ]
        docs, warnings = tr.build_seguimientos(rows, {})
        doc = docs["seg_orphan"]
        assert doc["jornada_client_id"] is None
        assert len(warnings) == 1
        assert "com_does_not_exist" in warnings[0]


class TestBuildEncuestas:
    def test_parses_evaluaciones_json_into_array(self):
        rows = [
            {
                "No": 1,
                "Fecha": dt.datetime(2026, 6, 18, 9, 58, 49),
                "ClientId": "enc_857bd1af-064b-4bc5-acb0-3c03b340d97c",
                "JornadaClientId": "jor_bbf4cf01-f948-4508-82dc-5b905a8f1612",
                "Nombre Participante": "Juan Perez",
                "Comuna": "COMUNA 2",
                "Barrio": "La Campiña",
                "Evaluaciones": '[{"org":"UAESP","calif":"Bueno"},{"org":"DAGMA","calif":"Regular"}]',
                "Comentario Final": "Muy Bueno",
                "Creado": dt.datetime(2026, 6, 18, 9, 58, 49),
            }
        ]
        docs, warnings = tr.build_encuestas(rows)
        assert warnings == []
        doc = docs["enc_857bd1af-064b-4bc5-acb0-3c03b340d97c"]
        assert doc["evaluaciones"] == [
            {"org": "UAESP", "calif": "Bueno"},
            {"org": "DAGMA", "calif": "Regular"},
        ]
        assert doc["comentario_final"] == "Muy Bueno"

    def test_skips_row_missing_client_id(self):
        rows = [{"ClientId": NAN, "No": 1, "Fecha": dt.datetime(2026, 1, 1)}]
        docs, warnings = tr.build_encuestas(rows)
        assert docs == {}
        assert len(warnings) == 1


# ──────────────────────────────────────────────────────────────────────────
# Compatibilidad con los modelos Pydantic reales de la ruta /avanzadas
# ──────────────────────────────────────────────────────────────────────────

class TestPydanticCompatibility:
    def test_transformed_avanzada_and_requerimiento_validate_against_real_models(self):
        avanzada_rows = [
            {
                "No": 1,
                "Fecha": dt.datetime(2026, 5, 6, 0, 0),
                "Nombre Avanzada": "Comuna 2 - (Urb. La Flora - Vipasa)",
                "Estrategia": "Plan de Choque",
                "Sector": "Migración Colombia",
                "Comuna/Corregimiento": "COMUNA 2",
                "Barrio/Vereda": "La Flora",
                "Dirección": "Av. 3AN # 50N -20, Vipasa, Cali",
                "Coordenadas": "3.483293, -76.515065",
                "Encargados": "Cristian Andres Toledo, Rodolfo Ramos Bonilla",
                "ClientId": "56f7fc52-27f0-40a2-98ff-fd8a182d1187",
                "Unnamed: 11": "https://drive.google.com/file/d/xyz/view",
            }
        ]
        asistencia_rows = [
            {
                "ClientId": "56f7fc52-27f0-40a2-98ff-fd8a182d1187",
                "Nombre Participante": "Juan Pérez",
                "Organismo": "DAGMA - Departamento Administrativo de Gestión del Medio Ambiente",
                "Celular": 3175783808.0,
                "Correo": "juan@test.com",
            }
        ]
        requerimiento_rows = [
            {
                "Fecha": dt.datetime(2026, 5, 6, 0, 0),
                "Nombre Avanzada": "Comuna 2 - (Urb. La Flora - Vipasa)",
                "Estrategia": "Plan de Choque",
                "Entidad": "EMCALI - Empresas Municipales de Cali",
                "Categoría": "Otro – EMCALI",
                "Requerimiento": "Cableado irregular",
                "Ubicación": "Cra 1 con Calle 2",
                "Evidencia fotográfica": "https://drive.google.com/a",
                "Coordenadas": "3.48, -76.51",
                "ClientId": "56f7fc52-27f0-40a2-98ff-fd8a182d1187",
                "ReqIndex": NAN,
            }
        ]

        asistentes_by_id, a_warn = tr.build_asistentes_by_avanzada(asistencia_rows)
        req_docs, r_warn = tr.build_requerimientos(requerimiento_rows)
        req_counts = tr.count_requerimientos_by_avanzada(req_docs)
        av_docs, av_warn = tr.build_avanzadas(avanzada_rows, asistentes_by_id, req_counts)
        assert a_warn == r_warn == av_warn == []

        req_out_list = [
            RequerimientoAvanzadaOut(id=doc_id, **doc) for doc_id, doc in req_docs.items()
        ]
        assert len(req_out_list) == 1

        av_doc = av_docs["56f7fc52-27f0-40a2-98ff-fd8a182d1187"]
        avanzada_out = AvanzadaOut(
            id="56f7fc52-27f0-40a2-98ff-fd8a182d1187",
            requerimientos=req_out_list,
            **av_doc,
        )
        assert avanzada_out.nombre_avanzada == "Comuna 2 - (Urb. La Flora - Vipasa)"
        assert avanzada_out.requerimientos_count == 1
        assert avanzada_out.asistentes[0].celular == "3175783808"
        assert avanzada_out.requerimientos[0].entidad == "EMCALI - Empresas Municipales de Cali"
