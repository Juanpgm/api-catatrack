"""Rutas FastAPI para reverse geocoding (coordenada → dirección)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.geocoding.reverse import reverse_geocode

router = APIRouter(prefix="/api", tags=["Geocoding"])


class ReverseGeocodeRequest(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitud en WGS84")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitud en WGS84")
    usar_nominatim: bool = Field(
        default=True,
        description="Si True, enriquece con Nominatim /reverse (puede tardar ~1s).",
    )


class ViaInfo(BaseModel):
    tipo: Optional[str] = None
    numero: Optional[str] = None
    nombre: Optional[str] = None
    nombre_catastral: Optional[str] = None
    clase: Optional[str] = None
    distancia_m: Optional[float] = None
    soporte_cruces: Optional[int] = None
    inferida: Optional[bool] = None


class CruceInfo(BaseModel):
    nombre: Optional[str] = None
    distancia_m: Optional[float] = None


class Coordenada(BaseModel):
    lat: float
    lon: float


class VerificacionInfo(BaseModel):
    score: int
    nivel: str
    advertencias: list[str] = []


class ReverseGeocodeResponse(BaseModel):
    success: bool
    coordenada: Coordenada
    dentro_de_cali: bool
    barrio_vereda: Optional[str] = None
    comuna_corregimiento: Optional[str] = None
    via: Optional[ViaInfo] = None
    cruce_mas_cercano: Optional[CruceInfo] = None
    direccion_legible: str
    direccion_osm: Optional[str] = None
    osm: Optional[dict] = None
    fuentes: list[str]
    verificacion: Optional[VerificacionInfo] = None


@router.post(
    "/reverse-geocode",
    response_model=ReverseGeocodeResponse,
    summary="Reverse geocoding: coordenada → dirección estructurada (Cali)",
)
async def reverse_geocode_endpoint(
    payload: ReverseGeocodeRequest,
):
    """
    Convierte (lat, lon) en una dirección legible combinando los basemaps
    catastrales de Cali (barrios, comunas, ejes viales, cruces) con un
    enriquecimiento opcional de Nominatim. Pensado para autollenar el campo
    `direccion_visita` tras capturar la posición GPS del usuario.
    """
    try:
        return await reverse_geocode(
            payload.lat, payload.lon, usar_nominatim=payload.usar_nominatim
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get(
    "/reverse-geocode",
    response_model=ReverseGeocodeResponse,
    summary="Reverse geocoding (GET) — útil desde Swagger / curl",
)
async def reverse_geocode_get(
    lat: float = Query(..., ge=-90.0, le=90.0),
    lon: float = Query(..., ge=-180.0, le=180.0),
    usar_nominatim: bool = Query(default=True),
):
    try:
        return await reverse_geocode(lat, lon, usar_nominatim=usar_nominatim)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
