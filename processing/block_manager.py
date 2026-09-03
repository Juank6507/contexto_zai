"""Módulo de gestión de bloques temáticos.

Toma los exchanges clasificados por tema y los agrupa en
:class:`ThematicBlock`, subdividiendo los bloques que exceden
el límite de caracteres por bloque (70K tokens × 3.5 chars/token).
"""

from __future__ import annotations

import logging

from contexto_zai.models import ClassificationRule, Exchange, ThematicBlock
from contexto_zai.processing.content_cleaner import ContentCleaner

logger = logging.getLogger(__name__)

# Límite por defecto: 70 000 tokens × 3.5 chars/token = 245 000 chars
DEFAULT_MAX_CHARS_PER_BLOCK = 245_000


class BlockManager:
    """Gestiona la creación y subdivisión de bloques temáticos.

    Cada bloque temático contiene todos los exchanges clasificados
    bajo un mismo tema. Si el contenido formateado de un bloque
    excede ``max_chars_per_block``, se subdivide en partes
    numeradas (parte 1, parte 2, …).

    Example::

        manager = BlockManager()
        blocks = manager.create_blocks(classified, rules_dict, cleaner)
    """

    def __init__(self, max_chars_per_block: int = DEFAULT_MAX_CHARS_PER_BLOCK) -> None:
        """Inicializa el gestor de bloques.

        Args:
            max_chars_per_block: Límite máximo de caracteres por bloque.
                Por defecto 245 000 (equivalente a ~70K tokens con tasa
                de conversión chars/3.5).
        """
        self.max_chars_per_block = max_chars_per_block
        logger.debug(
            "BlockManager inicializado con max_chars_per_block=%d",
            self.max_chars_per_block,
        )

    def create_blocks(
        self,
        classified: dict[str, list[Exchange]],
        rules: dict[str, ClassificationRule],
        cleaner: ContentCleaner,
    ) -> list[ThematicBlock]:
        """Crea bloques temáticos a partir de exchanges clasificados.

        Para cada tema en el diccionario ``classified``, se crea un
        :class:`ThematicBlock` utilizando los metadatos de la regla
        correspondiente (nombre, display_name, filename, descripción).
        Si un tema no tiene exchanges, se salta. Los bloques que
        exceden el límite de caracteres se subdividen automáticamente.

        Args:
            classified: Diccionario que mapea nombres de tema a listas
                de exchanges clasificados bajo ese tema.
            rules: Diccionario que mapea nombres de tema a sus
                :class:`ClassificationRule` correspondientes.
            cleaner: Instancia de :class:`ContentCleaner` usada para
                estimar el tamaño de los bloques formateados.

        Returns:
            Lista de :class:`ThematicBlock` listos para serialización.
            Puede incluir bloques subdivididos con ``part_number`` > 1.
        """
        logger.info(
            "Creando bloques temáticos para %d temas",
            len(classified),
        )

        blocks: list[ThematicBlock] = []

        for topic_name, exchanges in classified.items():
            if not exchanges:
                logger.debug("Tema '%s' sin exchanges, se omite", topic_name)
                continue

            # Obtener la regla para este tema; fallback a "general"
            rule = rules.get(topic_name)
            if rule is None:
                logger.warning(
                    "No se encontró regla para el tema '%s'; se usan valores por defecto",
                    topic_name,
                )
                rule = ClassificationRule(
                    name=topic_name,
                    display_name=topic_name.capitalize(),
                    block_filename=f"bloque_{topic_name}.md",
                    description="",
                )

            block = ThematicBlock(
                name=rule.name,
                display_name=rule.display_name,
                filename=rule.block_filename,
                description=rule.description,
                exchanges=exchanges,
                part_number=1,
            )

            # Verificar si el bloque necesita subdivisión
            sub_blocks = self._subdivide_if_needed(block, cleaner)
            blocks.extend(sub_blocks)

            if len(sub_blocks) > 1:
                logger.info(
                    "Tema '%s': subdividido en %d partes",
                    topic_name,
                    len(sub_blocks),
                )
            else:
                logger.debug(
                    "Tema '%s': 1 bloque (%d exchanges)",
                    topic_name,
                    len(exchanges),
                )

        logger.info(
            "%d bloques temáticos creados en total",
            len(blocks),
        )
        return blocks

    def _subdivide_if_needed(
        self,
        block: ThematicBlock,
        cleaner: ContentCleaner,
    ) -> list[ThematicBlock]:
        """Subdivide un bloque si su contenido formateado excede el límite.

        Calcula el total de caracteres del bloque tras limpieza y
        formateo markdown. Si es menor o igual al límite, devuelve
        el bloque original en una lista unitaria.

        Si excede el límite, divide la lista de exchanges en fragmentos
        que cada uno se mantenga por debajo del límite. Cada fragmento
        se convierte en un nuevo :class:`ThematicBlock` con
        ``part_number`` incrementado y un nombre de archivo que incluye
        ``_parte{N}``.

        La subdivisión es greedy: se van añadiendo exchanges a la parte
        actual hasta que añadir el siguiente exchange la haría exceder
        el límite, en cuyo caso se inicia una nueva parte.

        Args:
            block: :class:`ThematicBlock` original a verificar.
            cleaner: Instancia de :class:`ContentCleaner` para estimar
                el tamaño formateado.

        Returns:
            Lista con el bloque original si no necesita subdivisión,
            o la lista de sub-bloques si fue subdividido.
        """
        total_chars = self._estimate_block_chars(block, cleaner)
        logger.debug(
            "Bloque '%s': %d chars estimados (límite: %d)",
            block.name,
            total_chars,
            self.max_chars_per_block,
        )

        if total_chars <= self.max_chars_per_block:
            return [block]

        logger.info(
            "Bloque '%s' excede el límite (%d > %d); iniciando subdivisión",
            block.name,
            total_chars,
            self.max_chars_per_block,
        )

        sub_blocks: list[ThematicBlock] = []
        current_exchanges: list[Exchange] = []
        current_chars = 0
        part_number = 0

        for exchange in block.exchanges:
            exchange_formatted = cleaner.format_exchange(exchange)
            exchange_chars = len(exchange_formatted)

            # Si añadir este exchange supera el límite y ya hay exchanges
            # en la parte actual, cerrar la parte y empezar una nueva.
            if current_exchanges and (current_chars + exchange_chars > self.max_chars_per_block):
                part_number += 1
                sub_block = ThematicBlock(
                    name=block.name,
                    display_name=block.display_name,
                    filename=block.filename,
                    description=block.description,
                    exchanges=list(current_exchanges),
                    part_number=part_number,
                )
                sub_blocks.append(sub_block)
                logger.debug(
                    "Parte %d del bloque '%s' creada: %d exchanges, %d chars",
                    part_number,
                    block.name,
                    len(current_exchanges),
                    current_chars,
                )
                current_exchanges = []
                current_chars = 0

            current_exchanges.append(exchange)
            current_chars += exchange_chars

        # Cerrar la última parte
        if current_exchanges:
            part_number += 1
            sub_block = ThematicBlock(
                name=block.name,
                display_name=block.display_name,
                filename=block.filename,
                description=block.description,
                exchanges=list(current_exchanges),
                part_number=part_number,
            )
            sub_blocks.append(sub_block)
            logger.debug(
                "Parte %d del bloque '%s' creada: %d exchanges, %d chars",
                part_number,
                block.name,
                len(current_exchanges),
                current_chars,
            )

        logger.info(
            "Bloque '%s' subdividido en %d partes",
            block.name,
            len(sub_blocks),
        )
        return sub_blocks

    def _estimate_block_chars(
        self,
        block: ThematicBlock,
        cleaner: ContentCleaner,
    ) -> int:
        """Estima el total de caracteres de un bloque tras formateo.

        Formatea cada exchange del bloque usando
        :meth:`ContentCleaner.format_exchange` y suma las longitudes
        de los strings resultantes. Esto da una estimación precisa
        del tamaño final del archivo markdown que contendrá el bloque,
        incluyendo la sobrecarga de los encabezados y separadores.

        Args:
            block: :class:`ThematicBlock` cuyo tamaño se desea estimar.
            cleaner: Instancia de :class:`ContentCleaner` para formatear
                los exchanges.

        Returns:
            Número total de caracteres estimados para el contenido
            formateado del bloque.
        """
        total = 0
        for exchange in block.exchanges:
            formatted = cleaner.format_exchange(exchange)
            total += len(formatted)

        logger.debug(
            "Estimación de caracteres para bloque '%s': %d (%d exchanges)",
            block.name,
            total,
            len(block.exchanges),
        )
        return total
