# contexto_zai/metadata/__init__.py -- Subpaquete de metadata: gestor del archivo _metadata.json.
"""Paquete de metadata del sistema Contexto Z.ai (v3.2).

Contiene el gestor de la metadata de recuperación (_metadata.json).
"""

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

from contexto_zai.metadata.manager import MetadataManager

__all__ = ["MetadataManager"]
