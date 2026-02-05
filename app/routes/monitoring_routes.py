"""
Rutas de monitoreo - Métricas y monitoring
"""
from fastapi import APIRouter
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
from datetime import datetime

router = APIRouter(tags=["Monitoring"])

# Métricas de Prometheus
REQUEST_COUNT = Counter('api_requests_total', 'Total de requests', ['endpoint', 'method', 'status'])
REQUEST_DURATION = Histogram('api_request_duration_seconds', 'Duración de requests')
ACTIVE_REQUESTS = Gauge('api_requests_active', 'Requests activos')
FIREBASE_QUERIES = Counter('api_firebase_queries_total', 'Total de queries a Firestore')
CACHE_HITS = Counter('api_cache_hits_total', 'Total de cache hits')
CACHE_MISSES = Counter('api_cache_misses_total', 'Total de cache misses')

@router.get("/metrics")
async def metrics():
    """
    📊 Endpoint de Métricas de Prometheus
    
    Expone métricas de la aplicación en formato Prometheus para monitoreo APM:
    - api_requests_total: Contador de requests por endpoint, método y status
    - api_request_duration_seconds: Histograma de latencia de requests
    - api_requests_active: Gauge de requests activos
    - api_firebase_queries_total: Contador de queries a Firestore
    - api_cache_hits_total: Contador de cache hits
    - api_cache_misses_total: Contador de cache misses
    
    Usar con Grafana + Prometheus para dashboards de monitoreo
    """
    metrics_data = generate_latest()
    return Response(content=metrics_data, media_type=CONTENT_TYPE_LATEST)
