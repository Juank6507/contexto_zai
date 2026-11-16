# contexto_zai/detection/__init__.py -- Subpaquete de deteccion de perdida de contexto: LexicTrigger, TokenCounter, SelfQuestions.
"""Paquete de detección de pérdida de contexto (v3.2).

Tres mecanismos combinados:
- LexicTrigger: detecta frases del Director que indican pérdida.
- TokenCounter: dispara preventivamente al 90% de capacidad útil.
- SelfQuestions: auto-preguntas tras entregas relevantes.
"""

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

from contexto_zai.detection.lexic_trigger import LexicTrigger
from contexto_zai.detection.self_questions import SelfQuestions
from contexto_zai.detection.token_counter import TokenCounter

__all__ = ["LexicTrigger", "TokenCounter", "SelfQuestions"]
