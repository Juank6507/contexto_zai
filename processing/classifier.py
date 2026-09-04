# Destino: /home/z/my-project/contexto_zai/processing/classifier.py
"""Clasificador temático de intercambios (v3.2).

Asigna un tema a cada intercambio basándose en las palabras clave
del mensaje del Director. Devuelve el tema, no un bloque (la
agrupación en bloques por tamaño la hace BlockPacker).

Diferencia respecto a v1.0:
- En v1.0 el clasificador devolvía bloques (un bloque por tema).
- En v3.2 el clasificador solo asigna temas; BlockPacker agrupa
  varios temas en un archivo hasta llenar el límite de tokens.

Reglas de asignación:
- Contar cuántas keywords de cada tema aparecen en el mensaje del
  Director (no del agente).
- El tema con más coincidencias gana.
- En caso de empate, el tema del intercambio anterior tiene prioridad
  (continuidad temática).
- Si ningún tema supera 1 coincidencia, clasificar como "general".

Atómico standalone: importa config y models, nada más del proyecto.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from contexto_zai.config import DEFAULT_THEME_RULES, ThemeRule
from contexto_zai.models import Exchange

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClassificationResult:
    """Resultado de clasificar un intercambio.

    Attributes:
        tema: Nombre interno del tema asignado.
        matched_keywords: Lista de keywords que coincidieron.
        score: Número de coincidencias del tema ganador.
        previous_topic: Tema del intercambio anterior (para desempate).
    """

    tema: str
    matched_keywords: list[str]
    score: int
    previous_topic: Optional[str] = None


class MessageClassifier:
    """Clasifica intercambios en temas léxicos.

    Args:
        rules: Lista de ThemeRule a usar. Si None, usa DEFAULT_THEME_RULES.

    Usage:
        >>> classifier = MessageClassifier()
        >>> result = classifier.classify(exchange, previous_topic="validaciones")
        >>> print(result.tema)
    """

    def __init__(
        self,
        rules: Optional[list[ThemeRule]] = None,
    ) -> None:
        self._rules = rules if rules is not None else DEFAULT_THEME_RULES
        # Mapa nombre -> regla para acceso rápido
        self._rules_map: dict[str, ThemeRule] = {r.name: r for r in self._rules}
        logger.debug("MessageClassifier inicializado con %d reglas", len(self._rules))

    # ── API pública ────────────────────────────────────────────────

    def classify(
        self,
        exchange: Exchange,
        previous_topic: Optional[str] = None,
    ) -> ClassificationResult:
        """Clasifica un intercambio en un tema.

        Args:
            exchange: Intercambio a clasificar (usa el mensaje del Director).
            previous_topic: Tema del intercambio anterior, para desempate.

        Returns:
            ClassificationResult con el tema asignado y detalles.
        """
        director_text = exchange.director_msg.content.lower()
        scores: dict[str, tuple[int, list[str]]] = {}

        for rule in self._rules:
            if not rule.keywords:
                # La regla "general" se salta (siempre es fallback)
                continue
            matched = [kw for kw in rule.keywords if kw.lower() in director_text]
            if matched:
                scores[rule.name] = (len(matched), matched)

        if not scores:
            # Sin coincidencias → general
            return ClassificationResult(
                tema="general",
                matched_keywords=[],
                score=0,
                previous_topic=previous_topic,
            )

        # Encontrar el tema con máximo score
        max_score = max(s for s, _ in scores.values())
        # Empates: todos los temas con score == max_score
        winners = [name for name, (s, _) in scores.items() if s == max_score]

        if len(winners) == 1:
            # Ganador único
            tema = winners[0]
            matched = scores[tema][1]
        else:
            # Empate: priorizar previous_topic si está entre los ganadores
            if previous_topic and previous_topic in winners:
                tema = previous_topic
                matched = scores[tema][1]
            else:
                # Si no, coger el primero alfabéticamente (determinístico)
                tema = sorted(winners)[0]
                matched = scores[tema][1]

        logger.debug(
            "Exchange %d clasificado como '%s' (score=%d, prev=%s)",
            exchange.id,
            tema,
            max_score,
            previous_topic,
        )

        return ClassificationResult(
            tema=tema,
            matched_keywords=matched,
            score=max_score,
            previous_topic=previous_topic,
        )

    def classify_exchanges(
        self,
        exchanges: list[Exchange],
    ) -> list[Exchange]:
        """Clasifica una lista de intercambios y muta el tema de cada uno.

        Mantiene continuidad temática: el tema del intercambio N
        se usa como previous_topic para el intercambio N+1.

        Args:
            exchanges: Lista de intercambios a clasificar.

        Returns:
            La misma lista con los temas asignados (mutada in-place).
        """
        previous_topic: Optional[str] = None
        for ex in exchanges:
            result = self.classify(ex, previous_topic=previous_topic)
            ex.topic = result.tema
            previous_topic = result.tema
        logger.info(
            "Clasificados %d intercambios. Distribución de temas: %s",
            len(exchanges),
            self._topic_distribution(exchanges),
        )
        return exchanges

    def get_rule(self, name: str) -> Optional[ThemeRule]:
        """Devuelve la regla con el nombre dado, o None si no existe."""
        return self._rules_map.get(name)

    def get_rules(self) -> list[ThemeRule]:
        """Devuelve todas las reglas del clasificador."""
        return list(self._rules)

    # ── Métodos privados ───────────────────────────────────────────

    @staticmethod
    def _topic_distribution(
        exchanges: list[Exchange],
    ) -> dict[str, int]:
        """Cuenta intercambios por tema."""
        dist: dict[str, int] = {}
        for ex in exchanges:
            dist[ex.topic] = dist.get(ex.topic, 0) + 1
        return dist

    def __repr__(self) -> str:
        return f"MessageClassifier(rules={len(self._rules)})"


if __name__ == "__main__":
    # ── Validación interna de classifier.py (atómico standalone) ──
    print("=== Validación de classifier.py ===\n")

    from contexto_zai.models import Message, MessageRole

    cl = MessageClassifier()

    # Test 1: clasificación básica por keyword
    ex1 = Exchange(
        id=1,
        director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="Ejecuta el pytest de server.py y valida los tests"),
        topic="",
        start_timestamp=1,
        end_timestamp=2,
    )
    r1 = cl.classify(ex1)
    assert r1.tema == "validaciones", f"Esperaba 'validaciones', obtuve '{r1.tema}'"
    assert r1.score >= 2  # "pytest", "valida", "tests" coinciden
    print(f"✓ Clasificación básica: tema='{r1.tema}', score={r1.score}")

    # Test 2: tema "configuracion_proyecto" por worklog/repo
    ex2 = Exchange(
        id=2,
        director_msg=Message(seq=2, role=MessageRole.USER, timestamp=3, content="Lee el worklog y el repositorio del proyecto"),
        topic="",
        start_timestamp=3,
        end_timestamp=4,
    )
    r2 = cl.classify(ex2)
    assert r2.tema == "configuracion_proyecto", f"Esperaba 'configuracion_proyecto', obtuve '{r2.tema}'"
    print(f"✓ Tema configuracion_proyecto: tema='{r2.tema}', score={r2.score}")

    # Test 3: sin coincidencias → general
    ex3 = Exchange(
        id=3,
        director_msg=Message(seq=3, role=MessageRole.USER, timestamp=5, content="Hola, ¿cómo estás?"),
        topic="",
        start_timestamp=5,
        end_timestamp=6,
    )
    r3 = cl.classify(ex3)
    assert r3.tema == "general"
    assert r3.score == 0
    print(f"✓ Sin coincidencias: tema='general'")

    # Test 4: continuidad temática (empate se resuelve con previous_topic)
    ex_empate = Exchange(
        id=4,
        director_msg=Message(seq=4, role=MessageRole.USER, timestamp=7, content="test pytest validaciones"),
        topic="",
        start_timestamp=7,
        end_timestamp=8,
    )
    # Sin previous_topic: 'validaciones' gana por tener más keywords
    r_sin = cl.classify(ex_empate)
    # Con previous_topic="general": si 'validaciones' gana solo, no cambia
    r_con = cl.classify(ex_empate, previous_topic="general")
    assert r_sin.tema == r_con.tema == "validaciones"
    print(f"✓ Continuidad: tema='{r_sin.tema}' con/sin previous_topic")

    # Test 5: clasificación de lista con continuidad
    exchanges = [ex1, ex2, ex3]
    cl.classify_exchanges(exchanges)
    assert exchanges[0].topic == "validaciones"
    assert exchanges[1].topic == "configuracion_proyecto"
    assert exchanges[2].topic == "general"
    print(f"✓ Clasificación en lote con continuidad: OK")

    # Test 6: get_rule y get_rules
    rule = cl.get_rule("validaciones")
    assert rule is not None and rule.name == "validaciones"
    assert cl.get_rule("no_existe") is None
    all_rules = cl.get_rules()
    assert len(all_rules) >= 7
    print(f"✓ get_rule / get_rules: {len(all_rules)} reglas accesibles")

    print("\n✅ classifier.py: todos los tests pasaron")
