# contexto_zai/processing/__init__.py -- Subpaquete de procesamiento: ExchangeBuilder, ContentCleaner, MessageClassifier, BlockPacker, Subdivider.
"""Sub-paquete de procesamiento del sistema Contexto Z.ai (v3.2).

Contiene los módulos atómicos encargados de construir exchanges,
clasificarlos, limpiar su contenido, empaquetarlos en bloques por
tamaño y subdividir temas grandes en subtemas derivados únicos.
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
for _ in range(5):
    if _os.path.isdir(_os.path.join(_candidate, 'contexto_zai')):
        if _candidate not in _sys.path:
            _sys.path.insert(0, _candidate)
        break
    _candidate = _os.path.dirname(_candidate)
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
