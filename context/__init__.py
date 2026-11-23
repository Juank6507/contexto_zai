from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
_package_root = None
for _ in range(10):
    if not _os.path.isfile(_os.path.join(_candidate, '__init__.py')):
        break
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

# context/__init__.py -- Paquete de exportacion/importacion de contexto.
"""Paquete de exportacion e importacion de contexto (v3.4).

Permite empaquetar todo el contexto del proyecto en un .zip
y recuperarlo en otro agente de forma integra y automatica.
"""

from contexto_zai.context.exporter import ContextExporter
from contexto_zai.context.importer import ContextImporter

__all__ = ["ContextExporter", "ContextImporter"]
