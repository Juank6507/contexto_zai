# contexto_zai/processing/__init__.py -- Subpaquete de procesamiento: ExchangeBuilder, ContentCleaner, MessageClassifier, BlockPacker, Subdivider.
"""Sub-paquete de procesamiento del sistema Contexto Z.ai (v3.2).

Contiene los módulos atómicos encargados de construir exchanges,
clasificarlos, limpiar su contenido, empaquetarlos en bloques por
tamaño y subdividir temas grandes en subtemas derivados únicos.
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
# Soporta Estructura A (<workspace>/contexto_zai/) y Estructura B (workspace=contexto_zai/)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
_package_root = None
for _ in range(10):
    if not _os.path.isfile(_os.path.join(_candidate, '__init__.py')):
        break  # salimos del paquete
    _parent = _os.path.dirname(_candidate)
    if not _os.path.isfile(_os.path.join(_parent, '__init__.py')):
        _package_root = _candidate
        break
    _candidate = _parent
if _package_root:
    _workspace = _os.path.dirname(_package_root)
    if _workspace not in _sys.path:
        _sys.path.insert(0, _workspace)
else:
    _parent = _os.path.dirname(_here)
    if _parent not in _sys.path:
        _sys.path.insert(0, _parent)

from contexto_zai.processing.block_packer import BlockPacker
from contexto_zai.processing.classifier import MessageClassifier
from contexto_zai.processing.content_cleaner import ContentCleaner
from contexto_zai.processing.exchange_builder import ExchangeBuilder
from contexto_zai.processing.subdivider import Subdivider

__all__ = [
    "ExchangeBuilder",
    "ContentCleaner",
    "MessageClassifier",
    "BlockPacker",
    "Subdivider",
]
