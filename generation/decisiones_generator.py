from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contexto_zai.models import Exchange, ThematicBlock

logger = logging.getLogger(__name__)

# Tasa de conversión caracteres → tokens.
_CHARS_PER_TOKEN: float = 3.5

# Patrones que indican una decisión tomada en la conversación.
# Cada tupla contiene (patrón regex, ponderación de confianza).
_DECISION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'\bse decid(?:ió|ió)\b', re.IGNORECASE),
    re.compile(r'\bdecid(?:ió|i|ió)\b', re.IGNORECASE),
    re.compile(r'\bdecisión\b', re.IGNORECASE),
    re.compile(r'\boptamos? por\b', re.IGNORECASE),
    re.compile(r'\bseleccion(?:é|é|amos)\b', re.IGNORECASE),
    re.compile(r'\beleg(?:í|imos|ió)\b', re.IGNORECASE),
    re.compile(r'\bconfirm(?:ó|amos|é)\b', re.IGNORECASE),
    re.compile(r'\bdescart(?:ó|amos|é)\b', re.IGNORECASE),
    re.compile(r'\bse elimin(?:ó|aron)\b', re.IGNORECASE),
    re.compile(r'\bse implement(?:ó|ó|aron)\b', re.IGNORECASE),
    re.compile(r'\bse cre(?:ó|ó|aron)\b', re.IGNORECASE),
    re.compile(r'\bse corrig(?:ió|i|ió)\b', re.IGNORECASE),
    re.compile(r'\bresuelto\b', re.IGNORECASE),
    re.compile(r'\bNO funcion(?:ó|ó)\b', re.IGNORECASE),
    re.compile(r'\brechaz(?:ado|ó)\b', re.IGNORECASE),
    re.compile(r'\bresultado\b', re.IGNORECASE),
    re.compile(r'\bSe elimin(?:ó|ó)\b'),
    re.compile(r'\bRenombrado\b'),
    re.compile(r'\bFix\b'),
]

# Número máximo de caracteres para el título corto de una decisión.
_DECISION_TITLE_MAX_CHARS: int = 80

# Número máximo de caracteres para la descripción de una decisión.
_DECISION_DESC_MAX_CHARS: int = 200

# Número máximo de decisiones a extraer.
_MAX_DECISIONS: int = 50


@dataclass
class _Decision:
    """Decisión extraída de la conversación.

    Estructura interna para almacenar los datos de una decisión
    antes de ser formateada como markdown.

    Attributes:
        title: Título corto de la decisión.
        datetime_str: Fecha y hora de la decisión.
        topic: Tema al que pertenece.
        description: Descripción de 1-2 líneas.
        context: Referencia al exchange y bloque.
        raw_text: Texto original de la oración que contiene la decisión.
    """

    title: str = ""
    datetime_str: str = ""
    topic: str = ""
    description: str = ""
    context: str = ""
    raw_text: str = ""


class DecisionesGenerator:
    """Generador del archivo ``02_decisiones_clave.md``.

    Escanea todos los exchanges de la conversación en busca de
    patrones de decisión y produce un documento estructurado con
    cada decisión encontrada, su fecha, tema y contexto.

    También genera un resumen compacto de una línea por decisión
    para incluirlo en el índice de recuperación.

    Args:
        max_chars: Número máximo de caracteres del contenido completo.
            Por defecto 42_000 (12 000 tokens × 3,5 chars/token).
    """

    def __init__(self, max_chars: int = 42_000) -> None:
        """Inicializa el generador de decisiones clave.

        Args:
            max_chars: Límite de caracteres para el contenido completo.
                Valor por defecto calculado como 12 000 tokens × 3,5.
        """
        self.max_chars = max_chars
        logger.debug(
            "DecisionesGenerator inicializado con max_chars=%d",
            self.max_chars,
        )

    def generate(
        self,
        exchanges: list[Exchange],
        blocks: list[ThematicBlock],
    ) -> tuple[str, str]:
        """Genera el contenido completo y el resumen de decisiones.

        Escanea todos los exchanges en busca de patrones de decisión,
        extrae la información relevante de cada una y produce:

        1. El contenido completo de ``02_decisiones_clave.md``.
        2. Un resumen compacto de una línea por decisión.

        Args:
            exchanges: Lista completa de exchanges de la conversación.
            blocks: Lista de bloques temáticos clasificados.

        Returns:
            Tupla ``(full_content, summary)`` donde ``full_content``
            es el documento markdown completo y ``summary`` es la
            versión condensada para el índice.
        """
        logger.info(
            "Generando decisiones clave para %d exchanges, %d bloques",
            len(exchanges),
            len(blocks),
        )

        # Construir mapa de exchange → bloque para referencia cruzada.
        exchange_to_block = self._build_exchange_block_map(blocks)

        # Extraer decisiones de todos los exchanges.
        decisions = self._extract_all_decisions(
            exchanges, exchange_to_block
        )

        logger.info(
            "Decisiones extraídas: %d", len(decisions)
        )

        if not decisions:
            no_decision_msg = (
                "No se identificaron decisiones explícitas "
                "en la conversación."
            )
            full_content = f"# Decisiones Clave\n\n{no_decision_msg}\n"
            return full_content, no_decision_msg

        # Formatear el contenido completo.
        full_content = self._format_full(decisions)

        # Formatear el resumen.
        summary = self._format_summary(decisions)

        # Aplicar truncamiento al contenido completo si es necesario.
        full_content = self._enforce_char_limit(full_content, decisions)

        logger.info(
            "Decisiones completas: %d caracteres (%.0f tokens), "
            "resumen: %d caracteres",
            len(full_content),
            len(full_content) / _CHARS_PER_TOKEN,
            len(summary),
        )
        return full_content, summary

    # ── Extracción de decisiones ─────────────────────────────────

    def _extract_all_decisions(
        self,
        exchanges: list[Exchange],
        exchange_to_block: dict[int, ThematicBlock],
    ) -> list[_Decision]:
        """Extrae decisiones de todos los exchanges.

        Recorre cada exchange y cada mensaje, buscando patrones
        de decisión. Para cada ocurrencia, se crea un objeto
        ``_Decision`` con la información extraída. Se deduplican
        las decisiones por texto similar.

        Args:
            exchanges: Lista de exchanges a analizar.
            exchange_to_block: Mapeo de ID de exchange a bloque temático.

        Returns:
            Lista de decisiones extraídas y deduplicadas.
        """
        logger.debug("Extrayendo decisiones de %d exchanges", len(exchanges))

        raw_decisions: list[_Decision] = []
        seen_texts: set[str] = set()

        for exchange in exchanges:
            for msg in exchange.all_messages:
                content = msg.content.strip()
                if not content:
                    continue

                found_in_msg = self._find_decisions_in_content(
                    content, exchange, exchange_to_block
                )

                for decision in found_in_msg:
                    # Deduplicar por texto crudo normalizado.
                    dedup_key = decision.raw_text.lower().strip()
                    if dedup_key in seen_texts:
                        logger.debug(
                            "Decisión duplicada omitida: %s",
                            decision.title[:50],
                        )
                        continue
                    seen_texts.add(dedup_key)
                    raw_decisions.append(decision)

        # Ordenar cronológicamente.
        raw_decisions.sort(key=lambda d: d.datetime_str)

        # Limitar al máximo permitido.
        if len(raw_decisions) > _MAX_DECISIONS:
            logger.warning(
                "Demasiadas decisiones (%d), limitando a %d",
                len(raw_decisions),
                _MAX_DECISIONS,
            )
            raw_decisions = raw_decisions[:_MAX_DECISIONS]

        # Numerar las decisiones.
        for i, decision in enumerate(raw_decisions, start=1):
            if not decision.title:
                decision.title = f"Decisión {i}"

        return raw_decisions

    def _find_decisions_in_content(
        self,
        content: str,
        exchange: Exchange,
        exchange_to_block: dict[int, ThematicBlock],
    ) -> list[_Decision]:
        """Busca patrones de decisión dentro de un mensaje.

        Para cada patrón de decisión que coincida, extrae la
        oración que lo contiene y construye un objeto ``_Decision``.

        Args:
            content: Contenido del mensaje.
            exchange: Exchange al que pertenece el mensaje.
            exchange_to_block: Mapeo de ID de exchange a bloque.

        Returns:
            Lista de decisiones encontradas en este mensaje.
        """
        decisions: list[_Decision] = []

        # Dividir en oraciones para contexto más preciso.
        sentences = self._split_sentences(content)

        for sentence in sentences:
            sentence_stripped = sentence.strip()
            if not sentence_stripped:
                continue

            matched = False
            for pattern in _DECISION_PATTERNS:
                if pattern.search(sentence_stripped):
                    matched = True
                    break

            if not matched:
                continue

            # Determinar el bloque temático.
            block = exchange_to_block.get(exchange.id)
            block_filename = block.full_filename if block else "sin bloque"
            topic = block.display_name if block else exchange.topic

            # Extraer título corto de la oración.
            title = self._extract_decision_title(sentence_stripped)

            # Extraer descripción de 1-2 líneas.
            description = self._extract_decision_description(sentence_stripped)

            decision = _Decision(
                title=title,
                datetime_str=exchange.datetime_str,
                topic=topic,
                description=description,
                context=f"Exchange {exchange.id} en {block_filename}",
                raw_text=sentence_stripped,
            )
            decisions.append(decision)

        return decisions

    # ── Formateo ─────────────────────────────────────────────────

    def _format_full(self, decisions: list[_Decision]) -> str:
        """Formatea la lista completa de decisiones como markdown.

        Genera un documento con entradas numeradas (D01, D02, ...)
        para cada decisión, incluyendo fecha, tema, descripción
        y contexto.

        Args:
            decisions: Lista de decisiones extraídas.

        Returns:
            Documento markdown completo de decisiones clave.
        """
        logger.debug("Formateando %d decisiones (completo)", len(decisions))

        lines: list[str] = ["# Decisiones Clave", ""]

        for i, decision in enumerate(decisions, start=1):
            num_str = f"D{i:02d}"
            entry_lines: list[str] = [
                f"## {num_str} — {decision.title}",
                f"- **Cuándo:** {decision.datetime_str}",
                f"- **Tema:** {decision.topic}",
                f"- **Decisión:** {decision.description}",
                f"- **Contexto:** {decision.context}",
            ]
            lines.extend(entry_lines)
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_summary(decisions: list[_Decision]) -> str:
        """Formatea un resumen compacto de las decisiones.

        Genera una línea por decisión en el formato:
        ``- Se decidió X — ver D01``

        Args:
            decisions: Lista de decisiones extraídas.

        Returns:
            Resumen condensado de las decisiones.
        """
        logger.debug("Formateando resumen de %d decisiones", len(decisions))

        lines: list[str] = []
        for i, decision in enumerate(decisions, start=1):
            num_str = f"D{i:02d}"
            line = f"- {decision.description} — ver {num_str}"
            lines.append(line)

        return "\n".join(lines)

    # ── Truncamiento ─────────────────────────────────────────────

    def _enforce_char_limit(
        self, content: str, decisions: list[_Decision]
    ) -> str:
        """Aplica truncamiento si el contenido excede ``max_chars``.

        Elimina decisiones desde la última hacia la primera hasta
        que el contenido encaja en el límite.

        Args:
            decisions: Lista completa de decisiones (para reconstruir).

        Returns:
            Contenido dentro del límite de caracteres.
        """
        if len(content) <= self.max_chars:
            return content

        logger.warning(
            "Contenido de decisiones excede max_chars (%d > %d)",
            len(content),
            self.max_chars,
        )

        # Encabezado fijo.
        header = "# Decisiones Clave\n\n"
        header_len = len(header)
        available = self.max_chars - header_len

        if available <= 0:
            logger.error(
                "El encabezado ya excede max_chars, "
                "aplicando corte duro"
            )
            return content[: self.max_chars]

        # Reconstruir incluyendo decisiones una por una.
        lines: list[str] = [header]
        total = header_len

        for i, decision in enumerate(decisions, start=1):
            num_str = f"D{i:02d}"
            entry = (
                f"## {num_str} — {decision.title}\n"
                f"- **Cuándo:** {decision.datetime_str}\n"
                f"- **Tema:** {decision.topic}\n"
                f"- **Decisión:** {decision.description}\n"
                f"- **Contexto:** {decision.context}\n"
                "\n"
            )

            if total + len(entry) > self.max_chars:
                remaining = len(decisions) - i
                logger.info(
                    "Truncadas %d decisiones por límite de espacio",
                    remaining,
                )
                break

            lines.append(entry)
            total += len(entry)

        return "".join(lines)

    # ── Métodos auxiliares privados ──────────────────────────────

    @staticmethod
    def _build_exchange_block_map(
        blocks: list[ThematicBlock],
    ) -> dict[int, ThematicBlock]:
        """Construye un mapeo de ID de exchange a bloque temático.

        Permite determinar rápidamente a qué bloque pertenece
        un exchange dado.

        Args:
            blocks: Lista de bloques temáticos.

        Returns:
            Diccionario que mapea ``exchange.id`` a su ``ThematicBlock``.
        """
        mapping: dict[int, ThematicBlock] = {}
        for block in blocks:
            for exchange in block.exchanges:
                mapping[exchange.id] = block
        logger.debug(
            "Mapa exchange→bloque construido: %d exchanges mapeados",
            len(mapping),
        )
        return mapping

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Divide un texto en oraciones.

        Usa separadores comunes de oraciones en español e inglés:
        puntos, signos de interrogación y exclamación, seguidos
        de espacio o salto de línea. También divide por líneas
        si las oraciones son muy largas.

        Args:
            text: Texto a dividir en oraciones.

        Returns:
            Lista de oraciones.
        """
        # Primero dividir por separadores de oración.
        sentences = re.split(r'(?<=[.?!])\s+(?=[A-ZÁÉÍÓÚÑ¿¡])', text)

        # Si no se dividió bien o las oraciones son muy largas,
        # intentar una división más agresiva por puntos.
        if len(sentences) <= 1:
            sentences = re.split(r'(?<=[.?!])\s+', text)

        # Si aún no hay división, dividir por doble salto de línea.
        if len(sentences) <= 1 and '\n\n' in text:
            sentences = text.split('\n\n')

        # Si una oración es muy larga (>500 chars), dividirla por puntos.
        result: list[str] = []
        for sentence in sentences:
            if len(sentence) > 500:
                parts = sentence.split('. ')
                result.extend(parts)
            else:
                result.append(sentence)

        return [s.strip() for s in result if s.strip()]

    @staticmethod
    def _extract_decision_title(sentence: str) -> str:
        """Extrae un título corto de una oración de decisión.

        Toma las primeras palabras significativas de la oración
        que contienen el patrón de decisión, truncadas a
        ``_DECISION_TITLE_MAX_CHARS`` caracteres.

        Args:
            sentence: Oración que contiene la decisión.

        Returns:
            Título corto para la decisión.
        """
        # Intentar encontrar la parte que contiene el verbo de decisión.
        for pattern in _DECISION_PATTERNS:
            match = pattern.search(sentence)
            if match:
                # Tomar desde 20 caracteres antes del match.
                start = max(0, match.start() - 20)
                end = min(len(sentence), match.end() + _DECISION_TITLE_MAX_CHARS)
                title = sentence[start:end].strip()
                # Capitalizar primera letra.
                if title:
                    title = title[0].upper() + title[1:]
                # Eliminar punto final si existe.
                title = title.rstrip('.').strip()
                if len(title) > _DECISION_TITLE_MAX_CHARS:
                    title = title[: _DECISION_TITLE_MAX_CHARS - 3].rstrip() + "..."
                return title

        # Fallback: primeras palabras de la oración.
        title = sentence.strip().rstrip('.')
        if len(title) > _DECISION_TITLE_MAX_CHARS:
            title = title[: _DECISION_TITLE_MAX_CHARS - 3].rstrip() + "..."
        return title

    @staticmethod
    def _extract_decision_description(sentence: str) -> str:
        """Extrae una descripción de 1-2 líneas de la oración de decisión.

        Limpia la oración y la trunca a ``_DECISION_DESC_MAX_CHARS``
        caracteres, eliminando código y artefactos de formato.

        Args:
            sentence: Oración que contiene la decisión.

        Returns:
            Descripción limpia y truncada.
        """
        # Limpiar la oración: eliminar backticks, código inline.
        cleaned = re.sub(r'``[^`]*``', '', sentence)
        cleaned = re.sub(r'`[^`]*`', '', cleaned)
        # Eliminar múltiples espacios.
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        # Eliminar punto final.
        cleaned = cleaned.rstrip('.').strip()

        if len(cleaned) > _DECISION_DESC_MAX_CHARS:
            cleaned = (
                cleaned[: _DECISION_DESC_MAX_CHARS - 3].rstrip() + "..."
            )

        return cleaned
