from __future__ import annotations

import logging

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contexto_zai.models import ThematicBlock

    from contexto_zai.processing.content_cleaner import ContentCleaner

logger = logging.getLogger(__name__)

# Tasa de conversión caracteres → tokens.
_CHARS_PER_TOKEN: float = 3.5


class BloqueGenerator:
    """Generador de contenido markdown para un bloque temático.

    Toma un :class:`ThematicBlock` y un :class:`ContentCleaner` y
    produce el documento markdown completo del bloque, incluyendo
    el encabezado con metadatos y todos los exchanges formateados.

    La generación delega el formateo de cada exchange individual
    al ``ContentCleaner`` proporcionado.
    """

    def __init__(self) -> None:
        """Inicializa el generador de bloques temáticos.

        No requiere parámetros de configuración. El tamaño
        máximo de cada bloque está controlado por el
        :class:`BlockManager` durante la fase de procesamiento.
        """
        logger.debug("BloqueGenerator inicializado")

    def generate(
        self,
        block: ThematicBlock,
        cleaner: ContentCleaner,
    ) -> str:
        """Genera el contenido markdown de un bloque temático.

        Produce un documento con:

        - Título del bloque (``# {display_name}``).
        - Metadatos: período, número de exchanges, tamaño estimado.
        - Separador horizontal.
        - Cada exchange formateado por ``cleaner.format_exchange()``.

        Args:
            block: Bloque temático con sus exchanges.
            cleaner: Instancia de :class:`ContentCleaner` para
                formatear los exchanges individuales.

        Returns:
            Contenido markdown completo del bloque temático.
        """
        logger.info(
            "Generando bloque '%s' (%d exchanges, %d chars)",
            block.display_name,
            block.exchange_count,
            block.total_chars,
        )

        # Construir el encabezado con metadatos.
        header = self._build_header(block)

        # Formatear cada exchange.
        exchanges_content = self._format_all_exchanges(block, cleaner)

        # Ensamblar el documento.
        content = self._assemble(header, exchanges_content)

        logger.info(
            "Bloque '%s' generado: %d caracteres (%.0f tokens estimados)",
            block.display_name,
            len(content),
            len(content) / _CHARS_PER_TOKEN,
        )
        return content

    # ── Construcción del encabezado ──────────────────────────────

    @staticmethod
    def _build_header(block: ThematicBlock) -> str:
        """Construye el encabezado del bloque con metadatos.

        Incluye el título, período, conteo de mensajes y tamaño
        estimado en tokens.

        Args:
            block: Bloque temático.

        Returns:
            Encabezado markdown del bloque.
        """
        logger.debug(
            "Construyendo encabezado para bloque '%s'",
            block.display_name,
        )

        tokens_k = block.estimated_tokens / 1000

        lines: list[str] = [
            f"# {block.display_name}",
            f"**Período:** {block.period_str}",
            (
                f"**Mensajes:** {block.exchange_count} exchanges "
                f"({block.director_count} del Director, "
                f"{block.agent_count} del agente)"
            ),
            f"**Tamaño estimado:** ~{tokens_k:.1f}K tokens",
            "---",
        ]

        return "\n".join(lines)

    # ── Formateo de exchanges ────────────────────────────────────

    def _format_all_exchanges(
        self,
        block: ThematicBlock,
        cleaner: ContentCleaner,
    ) -> str:
        """Formatea todos los exchanges del bloque usando el cleaner.

        Itera sobre los exchanges del bloque y delega el formateo
        de cada uno al ``ContentCleaner.format_exchange()``. Los
        exchanges se numeran secuencialmente dentro del bloque.

        Args:
            block: Bloque temático con sus exchanges.
            cleaner: Instancia de :class:`ContentCleaner`.

        Returns:
            Contenido markdown con todos los exchanges formateados.
        """
        logger.debug(
            "Formateando %d exchanges para bloque '%s'",
            block.exchange_count,
            block.display_name,
        )

        if not block.exchanges:
            logger.debug(
                "Bloque '%s' no tiene exchanges", block.display_name
            )
            return "(sin exchanges en este bloque)"

        parts: list[str] = []

        for idx, exchange in enumerate(block.exchanges, start=1):
            logger.debug(
                "Formateando exchange %d/%d (id=%d) del bloque '%s'",
                idx,
                block.exchange_count,
                exchange.id,
                block.display_name,
            )
            formatted = cleaner.format_exchange(exchange, exchange_num=idx)
            parts.append(formatted)

        result = "\n\n".join(parts)

        logger.debug(
            "Exchanges formateados: %d caracteres",
            len(result),
        )
        return result

    # ── Ensamblaje ───────────────────────────────────────────────

    @staticmethod
    def _assemble(header: str, exchanges_content: str) -> str:
        """Ensambla el encabezado y los exchanges en el documento final.

        Args:
            header: Encabezado markdown con metadatos.
            exchanges_content: Contenido de los exchanges formateados.

        Returns:
            Documento markdown completo del bloque.
        """
        return f"{header}\n\n{exchanges_content}\n"
