# contexto_zai/verification/__init__.py -- Subpaquete de verificacion: exporta Verifier.
"""Paquete de verificación del sistema Contexto Z.ai.

Exporta la clase principal `Verifier` encargada de validar
que los archivos de recuperación cumplen con los límites de tokens.
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

from contexto_zai.verification.verifier import Verifier

__all__ = ["Verifier"]
