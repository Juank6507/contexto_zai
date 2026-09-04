# Destino: /home/z/my-project/contexto_zai/detection/self_questions.py
"""Auto-preguntas tras entregas relevantes (v3.2).

Después de cada entrega importante, el agente se hace tres preguntas
internas:
- ¿Sé en qué archivo estoy trabajando?
- ¿Sé qué decidimos sobre esto?
- ¿Sé qué sigue?

Si alguna falla, dispara la recuperación.

Atómico standalone: importa config, nada más del proyecto.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from contexto_zai.config import SELF_QUESTIONS

if TYPE_CHECKING:
    from contexto_zai.models import Exchange

logger = logging.getLogger(__name__)


@dataclass
class SelfQuestionResult:
    """Resultado de las auto-preguntas.

    Attributes:
        answers: Respuestas a cada pregunta (None si no se puede responder).
        failures: Lista de preguntas que fallaron (sin respuesta).
        should_trigger: True si alguna pregunta falló.
    """

    answers: dict[str, Optional[str]] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    @property
    def should_trigger(self) -> bool:
        """True si alguna pregunta falló."""
        return len(self.failures) > 0


class SelfQuestions:
    """Hace auto-preguntas tras entregas para detectar pérdida de contexto.

    El agente proporciona respuestas a cada pregunta. Si alguna no se
    puede responder, se dispara la recuperación.

    Usage:
        >>> sq = SelfQuestions()
        >>> result = sq.ask(
        ...     archivo_actual="server.py",
        ...     decision_actual="usar PriorityQueue",
        ...     siguiente_paso="continuar tests",
        ... )
        >>> if result.should_trigger:
        ...     # disparar recuperación
    """

    def __init__(
        self,
        questions: Optional[list[str]] = None,
    ) -> None:
        self._questions = questions if questions is not None else SELF_QUESTIONS
        logger.debug(
            "SelfQuestions inicializado: %d preguntas", len(self._questions)
        )

    # ── API pública ────────────────────────────────────────────────

    def ask(
        self,
        archivo_actual: Optional[str] = None,
        decision_actual: Optional[str] = None,
        siguiente_paso: Optional[str] = None,
    ) -> SelfQuestionResult:
        """Hace las auto-preguntas y devuelve el resultado.

        Args:
            archivo_actual: Respuesta a "¿sé en qué archivo estoy?".
            decision_actual: Respuesta a "¿sé qué decidimos?".
            siguiente_paso: Respuesta a "¿sé qué sigue?".

        Returns:
            SelfQuestionResult con respuestas y fallos.
        """
        answers = {
            self._questions[0]: archivo_actual,
            self._questions[1]: decision_actual,
            self._questions[2]: siguiente_paso,
        } if len(self._questions) >= 3 else {}

        failures = [
            q for q, a in answers.items()
            if a is None or a.strip() == ""
        ]

        result = SelfQuestionResult(answers=answers, failures=failures)

        if result.should_trigger:
            logger.info(
                "Self-preguntas: %d/%d fallaron → disparar recuperación",
                len(failures), len(answers),
            )
        else:
            logger.debug(
                "Self-preguntas: todas respondidas, no disparar"
            )

        return result

    def ask_from_context(
        self,
        current_file: Optional[str] = None,
        known_decisions: Optional[list[str]] = None,
        next_action: Optional[str] = None,
        current_topic: Optional[str] = None,
    ) -> SelfQuestionResult:
        """Hace auto-preguntas infiriendo respuestas del contexto.

        Variante más rica: intenta inferir respuestas a partir de
        datos del contexto del agente (archivo actual, decisiones
        conocidas, próxima acción, tema actual).

        Args:
            current_file: Archivo en el que el agente está trabajando.
            known_decisions: Lista de decisiones que el agente recuerda.
            next_action: Próxima acción planeada.
            current_topic: Tema actual (si se conoce).

        Returns:
            SelfQuestionResult.
        """
        # Inferir archivo actual
        archivo = current_file if current_file else None

        # Inferir decisión actual
        decision = (
            known_decisions[-1] if known_decisions
            else (f"Tema: {current_topic}" if current_topic else None)
        )

        # Siguiente paso
        siguiente = next_action

        return self.ask(
            archivo_actual=archivo,
            decision_actual=decision,
            siguiente_paso=siguiente,
        )

    @property
    def questions(self) -> list[str]:
        """Lista de preguntas."""
        return list(self._questions)

    def __repr__(self) -> str:
        return f"SelfQuestions(questions={len(self._questions)})"


if __name__ == "__main__":
    # ── Validación interna de self_questions.py ──
    print("=== Validación de self_questions.py ===\n")

    sq = SelfQuestions()

    # Test 1: todas respondidas → no dispara
    result = sq.ask(
        archivo_actual="server.py",
        decision_actual="usar PriorityQueue",
        siguiente_paso="continuar tests",
    )
    assert not result.should_trigger
    assert len(result.failures) == 0
    print(f"✓ Todas respondidas: no dispara")

    # Test 2: ninguna respondida → dispara
    result2 = sq.ask()
    assert result2.should_trigger
    assert len(result2.failures) == 3
    print(f"✓ Ninguna respondida: dispara ({len(result2.failures)} fallos)")

    # Test 3: una falla → dispara
    result3 = sq.ask(
        archivo_actual="server.py",
        decision_actual=None,  # falla
        siguiente_paso="continuar",
    )
    assert result3.should_trigger
    assert len(result3.failures) == 1
    print(f"✓ Una falla: dispara")

    # Test 4: respuesta vacía cuenta como falla
    result4 = sq.ask(
        archivo_actual="server.py",
        decision_actual="   ",  # solo espacios
        siguiente_paso="continuar",
    )
    assert result4.should_trigger
    print(f"✓ Respuesta vacía: cuenta como falla")

    # Test 5: ask_from_context con contexto completo
    result5 = sq.ask_from_context(
        current_file="planner.py",
        known_decisions=["Usar PriorityQueue", "Tests con pytest"],
        next_action="Refactorizar cola",
        current_topic="planificador",
    )
    assert not result5.should_trigger
    print(f"✓ ask_from_context con contexto: no dispara")

    # Test 6: ask_from_context sin contexto
    result6 = sq.ask_from_context()
    assert result6.should_trigger
    print(f"✓ ask_from_context sin contexto: dispara")

    # Test 7: ask_from_context parcial
    result7 = sq.ask_from_context(current_file="server.py")
    # Solo archivo, falta decisión y siguiente paso
    assert result7.should_trigger
    assert len(result7.failures) == 2
    print(f"✓ ask_from_context parcial: dispara ({len(result7.failures)} fallos)")

    # Test 8: preguntas por defecto cargadas
    assert len(sq.questions) == 3
    print(f"✓ Preguntas por defecto: {sq.questions}")

    print("\n✅ self_questions.py: todos los tests pasaron")
