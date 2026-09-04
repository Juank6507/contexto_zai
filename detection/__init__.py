# contexto_zai/detection/__init__.py -- Subpaquete de deteccion de perdida de contexto: LexicTrigger, TokenCounter, SelfQuestions.
"""Paquete de detección de pérdida de contexto (v3.2).

Tres mecanismos combinados:
- LexicTrigger: detecta frases del Director que indican pérdida.
- TokenCounter: dispara preventivamente al 90% de capacidad útil.
- SelfQuestions: auto-preguntas tras entregas relevantes.
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

from contexto_zai.detection.lexic_trigger import LexicTrigger
from contexto_zai.detection.self_questions import SelfQuestions
from contexto_zai.detection.token_counter import TokenCounter

__all__ = ["LexicTrigger", "TokenCounter", "SelfQuestions"]
