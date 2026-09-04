"""Sub-paquete de procesamiento del sistema Contexto Z.ai (v3.2).

Contiene los módulos atómicos encargados de construir exchanges,
clasificarlos, limpiar su contenido, empaquetarlos en bloques por
tamaño y subdividir temas grandes en subtemas derivados únicos.
"""

from __future__ import annotations

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
