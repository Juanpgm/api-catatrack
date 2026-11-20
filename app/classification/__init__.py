"""
Subpaquete de clasificación automática de centros gestores
(equivalente al campo `organismos_encargados`) a partir del texto
del requerimiento.

Estrategia: **reglas léxicas deterministas** (`rules.py` + `taxonomia.py`).
"""

from .classifier import clasificar_centros_gestores  # noqa: F401
from .taxonomia import TAXONOMIA, RESPONSABLES_CONOCIDOS  # noqa: F401
