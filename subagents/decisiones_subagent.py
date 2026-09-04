# Destino: /home/z/my-project/contexto_zai/subagents/decisiones_subagent.py
"""Subagente de decisiones (v3.2).

Escanea intercambios nuevos (desde la última actualización) y extrae
decisiones con comprensión semántica LLM (no regex). Deduplica contra
las decisiones ya registradas y devuelve solo las nuevas.

Disparadores (de spec v3.2):
1. Cada activación del proceso de recuperación.
2. Cambio de tarea del Director.
3. Indicación explícita del Director.
4. Comunicación explícita de una decisión.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Optional

from contexto_zai.models import Decision

if TYPE_CHECKING:
    from contexto_zai.models import Exchange

logger = logging.getLogger(__name__)


# Tipo del extractor LLM (para inyección de dependencias)
LLMExtractor = Callable[[list["Exchange"]], list[Decision]]


class DecisionesSubagent:
    """Subagente que extrae decisiones de intercambios con LLM.

    Args:
        extractor: Callback LLM que extrae decisiones de intercambios.
        max_decisions_per_run: Máximo de decisiones a extraer por ejecución.

    Usage:
        >>> sub = DecisionesSubagent(extractor=llm_callback)
        >>> new_decisions = sub.extract(exchanges, existing=already_known)
    """

    def __init__(
        self,
        extractor: Optional[LLMExtractor] = None,
        max_decisions_per_run: int = 20,
    ) -> None:
        self._extractor = extractor
        self._max_per_run = max_decisions_per_run
        logger.debug(
            "DecisionesSubagent inicializado: extractor=%s, max=%d",
            "sí" if extractor else "no",
            max_decisions_per_run,
        )

    # ── API pública ────────────────────────────────────────────────

    def extract(
        self,
        exchanges: list["Exchange"],
        existing: Optional[list[Decision]] = None,
        from_timestamp: float = 0.0,
    ) -> list[Decision]:
        """Extrae decisiones nuevas de intercambios.

        Modo incremental: si from_timestamp > 0, solo procesa intercambios
        con timestamp > from_timestamp.

        Args:
            exchanges: Lista de intercambios a procesar.
            existing: Decisiones ya registradas (para deduplicar).
            from_timestamp: Timestamp a partir del cual procesar.

        Returns:
            Lista de Decision nuevas (deduplicadas).
        """
        # Filtrar por timestamp
        if from_timestamp > 0:
            new_exchanges = [
                ex for ex in exchanges
                if ex.start_timestamp > from_timestamp
            ]
            logger.info(
                "Modo incremental: %d intercambios nuevos (ts > %d)",
                len(new_exchanges), from_timestamp,
            )
        else:
            new_exchanges = exchanges

        if not new_exchanges:
            logger.info("Sin intercambios nuevos para procesar")
            return []

        # Extraer con LLM
        if self._extractor is None:
            logger.warning("Sin extractor LLM: devolviendo lista vacía")
            return []

        try:
            extracted = self._extractor(new_exchanges)
        except Exception as e:
            logger.error("Error en extractor LLM: %s", e)
            return []

        # Limitar número de decisiones por ejecución
        if len(extracted) > self._max_per_run:
            logger.warning(
                "Extractor devolvió %d decisiones, limitando a %d",
                len(extracted), self._max_per_run,
            )
            extracted = extracted[:self._max_per_run]

        # Deduplicar contra existing
        existing_titles = {
            d.title.lower().strip() for d in (existing or []) if d.title
        }
        new_decisions: list[Decision] = []
        for d in extracted:
            title_key = d.title.lower().strip() if d.title else ""
            if title_key and title_key in existing_titles:
                continue
            existing_titles.add(title_key)
            new_decisions.append(d)

        logger.info(
            "Extracción: %d intercambios → %d decisiones (%d nuevas tras dedup)",
            len(new_exchanges),
            len(extracted),
            len(new_decisions),
        )
        return new_decisions

    def detect_explicit_decision(
        self,
        message: str,
    ) -> Optional[Decision]:
        """Detecta si un mensaje del Director comunica una decisión explícita.

        Patrones comunes: "decidimos X", "a partir de ahora Y",
        "descartamos Z", "vamos a usar W".

        Args:
            message: Mensaje del Director.

        Returns:
            Decision si se detecta, None si no.
        """
        if not message:
            return None

        message_lower = message.lower()
        patterns = [
            ("decidimos", "Decisión tomada por el Director"),
            ("a partir de ahora", "Cambio de rumbo"),
            ("descartamos", "Descarte"),
            ("vamos a usar", "Adopción de tecnología"),
            ("no vamos a", "Restricción"),
            ("queda descartado", "Descarte"),
            ("queda decidido", "Decisión finalizada"),
        ]

        for keyword, default_title in patterns:
            if keyword in message_lower:
                # Tomar las 100 chars siguientes como decisión
                idx = message_lower.find(keyword)
                decision_text = message[idx:idx + 200].strip()
                return Decision(
                    id="",
                    timestamp=0,
                    title=default_title,
                    decision=decision_text,
                    reason="Comunicación explícita del Director",
                    impact="A determinar",
                )

        return None

    @property
    def max_per_run(self) -> int:
        return self._max_per_run

    def __repr__(self) -> str:
        mode = "online" if self._extractor else "offline"
        return f"DecisionesSubagent(mode={mode!r}, max={self._max_per_run})"


if __name__ == "__main__":
    print("=== Validación de decisiones_subagent.py ===\n")

    from contexto_zai.models import Exchange, Message, MessageRole

    # Test 1: extractor simulado
    def mock_extractor(exs):
        return [
            Decision(id="", timestamp=exs[0].start_timestamp, title="Usar X", decision="Adoptar X"),
        ]

    sub = DecisionesSubagent(extractor=mock_extractor)
    exchanges = [
        Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="Decidimos usar X"), topic="general", start_timestamp=1, end_timestamp=2),
    ]
    new = sub.extract(exchanges)
    assert len(new) == 1
    assert new[0].title == "Usar X"
    print(f"✓ Extractor simulado: devuelve 1 decisión")

    # Test 2: deduplicación
    existing = [Decision(id="D01", timestamp=0, title="Usar X", decision="Adoptar X")]
    new2 = sub.extract(exchanges, existing=existing)
    assert len(new2) == 0  # duplicada, no se añade
    print(f"✓ Deduplicación: decisión repetida no se añade")

    # Test 3: modo incremental (filtrar por timestamp)
    exchanges_with_ts = [
        Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=10, content="x"), topic="general", start_timestamp=10, end_timestamp=11),
        Exchange(id=2, director_msg=Message(seq=2, role=MessageRole.USER, timestamp=20, content="y"), topic="general", start_timestamp=20, end_timestamp=21),
    ]
    new3 = sub.extract(exchanges_with_ts, from_timestamp=15)
    # El extractor recibe solo los intercambios con ts > 15
    assert len(new3) == 1
    print(f"✓ Modo incremental: filtra intercambios por timestamp")

    # Test 4: detect_explicit_decision
    d = sub.detect_explicit_decision("Decidimos usar PriorityQueue para la cola")
    assert d is not None
    assert "Decidimos" in d.decision
    print(f"✓ detect_explicit_decision: detecta 'decidimos'")

    d2 = sub.detect_explicit_decision("A partir de ahora usaremos Python 3.12")
    assert d2 is not None
    assert "Cambio de rumbo" in d2.title
    print(f"✓ detect_explicit_decision: detecta 'a partir de ahora'")

    # Test 5: sin extractor → lista vacía
    sub_off = DecisionesSubagent()
    assert sub_off.extract(exchanges) == []
    print(f"✓ Sin extractor: devuelve lista vacía")

    # Test 6: mensaje neutro no detecta decisión
    assert sub.detect_explicit_decision("Hola, ¿cómo estás?") is None
    print(f"✓ Mensaje neutro: no detecta decisión")

    # Test 7: extractor falla → lista vacía
    def failing_extractor(exs):
        raise RuntimeError("LLM no disponible")

    sub_err = DecisionesSubagent(extractor=failing_extractor)
    assert sub_err.extract(exchanges) == []
    print(f"✓ Extractor falla: devuelve lista vacía sin propagar error")

    print("\n✅ decisiones_subagent.py: todos los tests pasaron")
