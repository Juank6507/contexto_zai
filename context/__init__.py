# context/__init__.py -- Paquete de exportacion/importacion de contexto.
"""Paquete de exportacion e importacion de contexto (v3.4).

Permite empaquetar todo el contexto del proyecto en un .zip
y recuperarlo en otro agente de forma integra y automatica.
"""

from contexto_zai.context.exporter import ContextExporter
from contexto_zai.context.importer import ContextImporter

__all__ = ["ContextExporter", "ContextImporter"]
