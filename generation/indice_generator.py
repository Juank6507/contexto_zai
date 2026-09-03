from __future__ import annotations

import logging

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contexto_zai.models import ThematicBlock

logger = logging.getLogger(__name__)

# Tasa de conversión caracteres → tokens.
_CHARS_PER_TOKEN: float = 3.5


class IndiceGenerator:
    """Generador del archivo ``01_indice_recuperacion.md``.

    Produce un índice de todos los bloques temáticos disponibles,
    con instrucciones de recuperación, el protocolo a seguir y
    un resumen de las decisiones clave. Este archivo es el punto
    de entrada cuando el agente pierde contexto.

    Args:
        max_chars: Número máximo de caracteres del contenido generado.
            Por defecto 28_000 (8 000 tokens × 3,5 chars/token).
    """

    def __init__(self, max_chars: int = 28_000) -> None:
        """Inicializa el generador del índice de recuperación.

        Args:
            max_chars: Límite de caracteres para el contenido generado.
                Valor por defecto calculado como 8 000 tokens × 3,5.
        """
        self.max_chars = max_chars
        logger.debug(
            "IndiceGenerator inicializado con max_chars=%d",
            self.max_chars,
        )

    def generate(
        self,
        blocks: list[ThematicBlock],
        decisiones_summary: str,
        chat_label: str = "",
    ) -> str:
        """Genera el contenido de ``01_indice_recuperacion.md``.

        Estructura el documento con instrucción de uso, protocolo
        de recuperación de 5 pasos, lista de bloques temáticos
        con metadatos y el resumen de decisiones clave.

        Si el contenido excede ``max_chars``, se truncan las
        descripciones de los bloques y, en último caso, el resumen
        de decisiones.

        Args:
            blocks: Lista de bloques temáticos clasificados.
            decisiones_summary: Resumen compacto de las decisiones
                clave (generado por :class:`DecisionesGenerator`).
            chat_label: Etiqueta descriptiva del chat.

        Returns:
            Contenido markdown del índice de recuperación.
        """
        logger.info(
            "Generando índice de recuperación para %d bloques "
            "(chat_label=%r)",
            len(blocks),
            chat_label,
        )

        # Construir las secciones del documento.
        instruction = self._build_instruction()
        protocol = self._build_protocol()
        blocks_section = self._build_blocks_section(blocks)

        # Ensamblar el documento completo.
        content = self._assemble(
            chat_label=chat_label,
            instruction=instruction,
            protocol=protocol,
            blocks_section=blocks_section,
            decisiones_summary=decisiones_summary,
        )

        # Aplicar truncamiento si es necesario.
        content = self._enforce_char_limit(
            content=content,
            chat_label=chat_label,
            instruction=instruction,
            protocol=protocol,
            blocks_section=blocks_section,
            decisiones_summary=decisiones_summary,
            blocks=blocks,
        )

        logger.info(
            "Índice generado: %d caracteres (%.0f tokens estimados)",
            len(content),
            len(content) / _CHARS_PER_TOKEN,
        )
        return content

    # ── Construcción de secciones ────────────────────────────────

    @staticmethod
    def _build_instruction() -> str:
        """Construye la sección de instrucción del índice.

        Returns:
            Texto de la sección de instrucción.
        """
        logger.debug("Construyendo sección de instrucción")
        return (
            "Si detectas que has perdido contexto de esta sesión, "
            "este archivo\nes tu punto de entrada. Identifica qué tema "
            "necesitas y delega\na un subagente para que lea el bloque "
            "correspondiente."
        )

    @staticmethod
    def _build_protocol() -> str:
        """Construye la sección del protocolo de recuperación.

        Returns:
            Texto del protocolo de recuperación en 5 pasos.
        """
        logger.debug("Construyendo sección de protocolo")
        steps: list[str] = [
            "Lee este archivo (ya lo estás leyendo)",
            "Identifica el bloque relevante para tu tarea actual",
            "Lanza un subagente: Task(prompt=\"Lee {ruta_bloque} y responde: {tu pregunta específica}\")",
            "El subagente devolverá una respuesta concisa (~3-5K tokens)",
            "Si necesitas otro bloque, repite desde el paso 3",
        ]
        lines: list[str] = []
        for i, step in enumerate(steps, start=1):
            lines.append(f"{i}. {step}")
        return "\n".join(lines)

    def _build_blocks_section(
        self, blocks: list[ThematicBlock]
    ) -> str:
        """Construye la sección de bloques disponibles.

        Genera una entrada para cada bloque temático con su nombre
        de archivo, tamaño estimado en tokens, descripción, período
        y conteo de exchanges.

        Args:
            blocks: Lista de bloques temáticos.

        Returns:
            Sección markdown con la lista de bloques.
        """
        logger.debug("Construyendo sección de bloques (%d bloques)", len(blocks))

        if not blocks:
            return "No hay bloques temáticos disponibles."

        entries: list[str] = []
        for block in blocks:
            tokens_k = block.estimated_tokens / 1000
            entry = self._format_block_entry(block, tokens_k)
            entries.append(entry)

        return "\n".join(entries)

    @staticmethod
    def _format_block_entry(
        block: ThematicBlock, tokens_k: float
    ) -> str:
        """Formatea una entrada individual de bloque temático.

        Args:
            block: Bloque temático a formatear.
            tokens_k: Tamaño estimado en miles de tokens.

        Returns:
            Cadena markdown con la entrada del bloque.
        """
        return (
            f"### {block.full_filename} (~{tokens_k:.1f}K tokens)\n"
            f"{block.description}\n"
            f"Período: {block.period_str}\n"
            f"Exchanges: {block.exchange_count} "
            f"({block.director_count} del Director, "
            f"{block.agent_count} del agente)"
        )

    # ── Ensamblaje ───────────────────────────────────────────────

    def _assemble(
        self,
        chat_label: str,
        instruction: str,
        protocol: str,
        blocks_section: str,
        decisiones_summary: str,
    ) -> str:
        """Ensambla todas las secciones en el documento markdown final.

        Args:
            chat_label: Etiqueta del chat.
            instruction: Texto de la sección de instrucción.
            protocol: Texto del protocolo de recuperación.
            blocks_section: Sección de bloques temáticos.
            decisiones_summary: Resumen de decisiones clave.

        Returns:
            Documento markdown completo del índice.
        """
        lines: list[str] = [
            f"# Índice de Recuperación — {chat_label}",
            "",
            "## Instrucción",
            instruction,
            "",
            "## Protocolo de recuperación",
            protocol,
            "",
            "## Bloques disponibles",
            blocks_section,
            "",
            "## Decisiones clave (resumen)",
            decisiones_summary,
            "",
        ]
        return "\n".join(lines)

    # ── Truncamiento ─────────────────────────────────────────────

    def _enforce_char_limit(
        self,
        content: str,
        chat_label: str,
        instruction: str,
        protocol: str,
        blocks_section: str,
        decisiones_summary: str,
        blocks: list[ThematicBlock],
    ) -> str:
        """Aplica truncamiento si el contenido excede ``max_chars``.

        Estrategia de truncamiento por orden de prioridad:

        1. Acortar el resumen de decisiones clave.
        2. Acortar las descripciones de los bloques.
        3. Eliminar el resumen de decisiones si aún no cabe.
        4. Corte duro como último recurso.

        Args:
            content: Contenido completo ya ensamblado.
            chat_label: Etiqueta del chat.
            instruction: Texto de la sección de instrucción.
            protocol: Texto del protocolo de recuperación.
            blocks_section: Sección de bloques temáticos.
            decisiones_summary: Resumen de decisiones clave.
            blocks: Lista de bloques temáticos.

        Returns:
            Contenido dentro del límite de caracteres.
        """
        if len(content) <= self.max_chars:
            return content

        logger.warning(
            "Contenido excede max_chars (%d > %d), aplicando truncamiento",
            len(content),
            self.max_chars,
        )

        # Calcular el espacio que ocupan las partes fijas.
        fixed_template = self._assemble(
            chat_label=chat_label,
            instruction=instruction,
            protocol=protocol,
            blocks_section="",
            decisiones_summary="",
        )
        available = self.max_chars - len(fixed_template)

        if available <= 0:
            logger.error(
                "Las secciones fijas exceden max_chars, "
                "aplicando corte duro"
            )
            return content[: self.max_chars]

        # Paso 1: Truncar el resumen de decisiones.
        truncated_summary = self._truncate_summary(
            decisiones_summary, available * 0.4
        )

        remaining = available - len(truncated_summary)

        # Paso 2: Truncar las descripciones de los bloques si es necesario.
        truncated_blocks = self._truncate_blocks_descriptions(
            blocks, max(0, remaining)
        )

        result = self._assemble(
            chat_label=chat_label,
            instruction=instruction,
            protocol=protocol,
            blocks_section=truncated_blocks,
            decisiones_summary=truncated_summary,
        )

        # Paso 3: Si aún excede, eliminar el resumen de decisiones.
        if len(result) > self.max_chars:
            logger.warning(
                "Aún excede tras truncar decisiones, "
                "eliminando resumen de decisiones"
            )
            result = self._assemble(
                chat_label=chat_label,
                instruction=instruction,
                protocol=protocol,
                blocks_section=truncated_blocks,
                decisiones_summary="(resumen truncado por límite de espacio)",
            )

        # Paso 4: Corte duro de seguridad.
        if len(result) > self.max_chars:
            logger.error(
                "Contenido aún excede tras eliminación de decisiones, "
                "aplicando corte duro"
            )
            result = result[: self.max_chars]

        logger.debug(
            "Índice truncado a %d caracteres", len(result)
        )
        return result

    @staticmethod
    def _truncate_summary(summary: str, max_chars: float) -> str:
        """Trunca el resumen de decisiones al tamaño indicado.

        Busca el último salto de línea antes del límite para no
        cortar a mitad de entrada.

        Args:
            summary: Resumen de decisiones clave.
            max_chars: Número máximo de caracteres permitidos.

        Returns:
            Resumen truncado.
        """
        limit = int(max_chars)
        if len(summary) <= limit:
            return summary

        truncated = summary[:limit]
        last_newline = truncated.rfind("\n")
        if last_newline > limit * 0.5:
            truncated = truncated[:last_newline]
        return truncated.rstrip() + "\n- ... (truncado)"

    @staticmethod
    def _truncate_blocks_descriptions(
        blocks: list[ThematicBlock], max_chars: int
    ) -> str:
        """Genera la sección de bloques con descripciones truncadas.

        Si el espacio disponible es muy reducido, se acortan las
        descripciones de cada bloque o se omiten para maximizar
        la información de metadatos.

        Args:
            blocks: Lista de bloques temáticos.
            max_chars: Espacio máximo disponible para la sección.

        Returns:
            Sección de bloques formateada y truncada.
        """
        if not blocks:
            return ""

        # Si no hay espacio, generar entradas mínimas.
        if max_chars <= 0:
            entries: list[str] = []
            for block in blocks:
                tokens_k = block.estimated_tokens / 1000
                entries.append(
                    f"### {block.full_filename} (~{tokens_k:.1f}K tokens)\n"
                    f"Período: {block.period_str}"
                )
            return "\n".join(entries)

        # Generar entradas completas y truncar la última si excede.
        entries: list[str] = []
        total_len = 0

        for block in blocks:
            tokens_k = block.estimated_tokens / 1000
            entry = (
                f"### {block.full_filename} (~{tokens_k:.1f}K tokens)\n"
                f"{block.description}\n"
                f"Período: {block.period_str}\n"
                f"Exchanges: {block.exchange_count} "
                f"({block.director_count} del Director, "
                f"{block.agent_count} del agente)"
            )

            # Separador entre entradas.
            separator_len = 1 if entries else 0
            needed = len(entry) + separator_len

            if total_len + needed > max_chars and entries:
                # Truncar la descripción del bloque actual.
                remaining = max_chars - total_len - separator_len
                if remaining > 30:
                    tokens_k = block.estimated_tokens / 1000
                    short_entry = (
                        f"### {block.full_filename} (~{tokens_k:.1f}K tokens)\n"
                        f"Período: {block.period_str}"
                    )
                    if len(short_entry) + separator_len <= max_chars - total_len:
                        entries.append(short_entry)
                # No caben más bloques, detenerse.
                break

            entries.append(entry)
            total_len += needed

        return "\n".join(entries)
