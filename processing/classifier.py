"""Módulo de clasificación temática de exchanges.

Clasifica cada exchange en un tema basándose en la coincidencia
de palabras clave del mensaje del Director. Soporta reglas por defecto
importadas desde la configuración y adición/remisión dinámica de
reglas de clasificación.
"""

from __future__ import annotations

import logging

from contexto_zai.config import DEFAULT_THEME_RULES
from contexto_zai.models import ClassificationRule, Exchange

logger = logging.getLogger(__name__)


class MessageClassifier:
    """Clasifica exchanges por tema usando reglas de palabras clave.

    Cada regla contiene una lista de palabras clave. La clasificación
    se realiza contando coincidencias (case-insensitive) del contenido
    del mensaje del Director contra las palabras clave de cada regla.
    El tema con mayor puntuación gana. En caso de empate se privilegia
    el tema del exchange anterior (continuidad). Si ningún tema supera
    una puntuación > 1, se clasifica como ``"general"``.

    Example::

        classifier = MessageClassifier()
        classified = classifier.classify(exchanges)
    """

    def __init__(self, rules: list[ClassificationRule] | None = None) -> None:
        """Inicializa el clasificador con las reglas proporcionadas o las por defecto.

        Args:
            rules: Lista opcional de :class:`ClassificationRule`. Si es
                ``None``, se importan las :data:`DEFAULT_THEME_RULES` de
                :mod:`contexto_zai.config` y se convierten a objetos
                :class:`ClassificationRule`.
        """
        self._rules: dict[str, ClassificationRule] = {}

        if rules is None:
            logger.info("No se proporcionaron reglas; cargando DEFAULT_THEME_RULES desde config")
            self._rules = self._convert_default_rules()
        else:
            for rule in rules:
                self._rules[rule.name] = rule
            logger.info("Cargadas %d reglas de clasificación personalizadas", len(self._rules))

        # Asegurar que "general" siempre existe
        if "general" not in self._rules:
            self._rules["general"] = ClassificationRule(
                name="general",
                display_name="General",
                keywords=[],
                block_filename="bloque_general.md",
                description="Mensajes que no clasifican en ningún tema específico.",
            )

        logger.debug("Reglas de clasificación disponibles: %s", list(self._rules.keys()))

    # ── API pública ──────────────────────────────────────────────

    def classify(self, exchanges: list[Exchange]) -> dict[str, list[Exchange]]:
        """Clasifica una lista de exchanges por tema.

        Para cada exchange se puntúan todas las reglas contando las
        coincidencias de palabras clave (case-insensitive) en el
        contenido del mensaje del Director. El tema con mayor
        puntuación gana. Los empates se resuelven dando prioridad
        al tema del exchange anterior (continuidad temática). Si
        ningún tema obtiene puntuación > 1, se asigna ``"general"``.

        Args:
            exchanges: Lista de exchanges a clasificar.

        Returns:
            Diccionario que mapea el nombre del tema a la lista de
            exchanges clasificados bajo ese tema. Se modifica el
            campo ``topic`` de cada exchange in-place.
        """
        logger.info("Clasificando %d exchanges por tema", len(exchanges))

        result: dict[str, list[Exchange]] = {}
        previous_topic: str = "general"

        for idx, exchange in enumerate(exchanges):
            scored = self._score_exchange(exchange)
            topic = self._break_tie(scored, previous_topic)

            # Si ningún tema tiene puntuación > 1, forzar "general"
            top_score = scored[0][1] if scored else 0
            if top_score <= 1:
                topic = "general"
                logger.debug(
                    "Exchange %d: puntuación máxima %d <= 1, asignando 'general'",
                    exchange.id,
                    top_score,
                )

            # Asignar tema al exchange
            exchange.topic = topic
            previous_topic = topic

            # Agrupar en el diccionario de resultados
            if topic not in result:
                result[topic] = []
            result[topic].append(exchange)

            logger.debug(
                "Exchange %d clasificado como '%s' (puntuaciones: %s)",
                exchange.id,
                topic,
                scored[:3],
            )

        # Resumen
        summary = {k: len(v) for k, v in result.items()}
        logger.info("Clasificación completada: %s", summary)
        return result

    def add_rule(self, rule: ClassificationRule) -> None:
        """Añade una nueva regla de clasificación.

        Si ya existe una regla con el mismo nombre, se sobrescribe.

        Args:
            rule: :class:`ClassificationRule` a añadir.
        """
        self._rules[rule.name] = rule
        logger.info(
            "Regla de clasificación añadida/actualizada: '%s' (%d keywords)",
            rule.name,
            len(rule.keywords),
        )

    def remove_rule(self, name: str) -> None:
        """Elimina una regla de clasificación por nombre.

        No se puede eliminar la regla ``"general"`` ya que es el
        tema de respaldo obligatorio.

        Args:
            name: Nombre de la regla a eliminar.

        Raises:
            ValueError: Si se intenta eliminar la regla "general"
                o si el nombre no existe.
        """
        if name == "general":
            raise ValueError("No se puede eliminar la regla de clasificación 'general'")

        if name not in self._rules:
            raise ValueError(f"No existe una regla de clasificación con nombre '{name}'")

        del self._rules[name]
        logger.info("Regla de clasificación eliminada: '%s'", name)

    def get_rules(self) -> list[ClassificationRule]:
        """Devuelve todas las reglas de clasificación actuales.

        Returns:
            Lista de :class:`ClassificationRule` registradas.
        """
        return list(self._rules.values())

    # ── API interna ─────────────────────────────────────────────

    def _score_exchange(self, exchange: Exchange) -> list[tuple[str, int]]:
        """Puntúa un exchange contra todas las reglas de clasificación.

        Para cada regla, cuenta cuántas de sus palabras clave aparecen
        (case-insensitive) en el contenido del mensaje del Director.

        Args:
            exchange: Exchange a puntuar.

        Returns:
            Lista de tuplas ``(topic_name, score)`` ordenadas de
            mayor a menor puntuación.
        """
        director_content = exchange.director_msg.content.lower()
        scores: list[tuple[str, int]] = []

        for rule_name, rule in self._rules.items():
            score = 0
            for keyword in rule.keywords:
                if keyword.lower() in director_content:
                    score += 1
            scores.append((rule_name, score))

        # Ordenar descendentemente por puntuación
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def _break_tie(
        self,
        candidates: list[tuple[str, int]],
        previous_topic: str,
    ) -> str:
        """Resuelve empates en la puntuación de clasificación.

        Si hay múltiples candidatos con la misma puntuación máxima,
        se prioriza el tema del exchange anterior (``previous_topic``)
        si está entre los candidatos empatados. Esto otorga continuidad
        temática a la conversación.

        Args:
            candidates: Lista de ``(topic_name, score)`` ya ordenada
                descendentemente. El primer elemento tiene la puntuación
                máxima.
            previous_topic: Tema del exchange inmediatamente anterior.

        Returns:
            Nombre del tema ganante tras resolver el empate.
        """
        if not candidates:
            return "general"

        top_score = candidates[0][1]

        # Filtrar solo los candidatos con la puntuación máxima
        tied = [name for name, score in candidates if score == top_score]

        if len(tied) == 1:
            return tied[0]

        # Empate: preferir el tema anterior si está en los candidatos
        if previous_topic in tied:
            logger.debug(
                "Empate entre %s resuelto por continuidad: '%s'",
                tied,
                previous_topic,
            )
            return previous_topic

        # Si no hay continuidad posible, devolver el primero (orden original)
        logger.debug("Empate entre %s sin continuidad; se usa '%s'", tied, tied[0])
        return tied[0]

    # ── Conversión de reglas por defecto ─────────────────────────

    @staticmethod
    def _convert_default_rules() -> dict[str, ClassificationRule]:
        """Convierte las :data:`DEFAULT_THEME_RULES` de config a
        objetos :class:`ClassificationRule`.

        Los :class:`~contexto_zai.config.ThemeRule` son dataclasses con
        un campo ``block_prefix``, mientras que :class:`ClassificationRule`
        usa ``block_filename``. La conversión añade la extensión ``.md``
        al prefijo.

        Returns:
            Diccionario mapeando ``rule.name`` a la
            :class:`ClassificationRule` correspondiente.
        """
        rules: dict[str, ClassificationRule] = {}
        for theme in DEFAULT_THEME_RULES:
            filename = f"{theme.block_prefix}.md"
            rule = ClassificationRule(
                name=theme.name,
                display_name=theme.display_name,
                keywords=list(theme.keywords),
                block_filename=filename,
                description=theme.description,
            )
            rules[rule.name] = rule
        return rules
