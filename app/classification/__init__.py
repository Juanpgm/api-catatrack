"""
Subpaquete de clasificación automática de centros gestores
(equivalente al campo `organismos_encargados`) a partir del texto
del requerimiento.

Estrategia: híbrido **reglas léxicas + embeddings multilingües**
(`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`).
"""

from .classifier import clasificar_centros_gestores  # noqa: F401
from .taxonomia import TAXONOMIA, RESPONSABLES_CONOCIDOS  # noqa: F401
