"""Paquete de detección de pérdida de contexto (v3.2).

Tres mecanismos combinados:
- LexicTrigger: detecta frases del Director que indican pérdida.
- TokenCounter: dispara preventivamente al 90% de capacidad útil.
- SelfQuestions: auto-preguntas tras entregas relevantes.
"""

from contexto_zai.detection.lexic_trigger import LexicTrigger
from contexto_zai.detection.self_questions import SelfQuestions
from contexto_zai.detection.token_counter import TokenCounter

__all__ = ["LexicTrigger", "TokenCounter", "SelfQuestions"]
