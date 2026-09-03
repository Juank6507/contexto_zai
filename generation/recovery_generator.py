from __future__ import annotations

import logging

from typing import TYPE_CHECKING

from contexto_zai.config import (
    DECISIONES_CLAVE_FILENAME,
    ESTADO_ACTUAL_FILENAME,
    INDICE_RECUPERACION_FILENAME,
    TOKEN_LIMITS,
)
from contexto_zai.generation.bloque_generator import BloqueGenerator
from contexto_zai.generation.decisiones_generator import DecisionesGenerator
from contexto_zai.generation.estado_generator import EstadoGenerator
from contexto_zai.generation.indice_generator import IndiceGenerator
from contexto_zai.models import FileCategory, RecoveryFile
from contexto_zai.processing.content_cleaner import ContentCleaner

if TYPE_CHECKING:
    from contexto_zai.models import Exchange, ThematicBlock

logger = logging.getLogger(__name__)


class RecoveryGenerator:
    """Orquestador principal de generación de archivos de recuperación.

    Coordina todos los generadores individuales para producir la
    lista completa de :class:`RecoveryFile` que conforman el
    paquete de recuperación de contexto.

    El orden de generación es:

    1. Decisiones clave (para obtener el resumen).
    2. Estado actual.
    3. Índice de recuperación (usa el resumen de decisiones).
    4. Bloques temáticos (uno por bloque).

    Cada archivo generado incluye su categoría, nombre, contenido
    y límite de tokens según la configuración del sistema.
    """

    def __init__(self) -> None:
        """Inicializa el orquestador de recuperación.

        Crea instancias de todos los generadores individuales y
        un :class:`ContentCleaner` compartido para el formateo
        de los exchanges en los bloques temáticos.
        """
        logger.info("RecoveryGenerator inicializado")

        self._estado_gen = EstadoGenerator(
            max_chars=TOKEN_LIMITS.max_chars_estado,
        )
        self._indice_gen = IndiceGenerator(
            max_chars=TOKEN_LIMITS.max_chars_indice,
        )
        self._decisiones_gen = DecisionesGenerator(
            max_chars=TOKEN_LIMITS.max_chars_decisiones,
        )
        self._bloque_gen = BloqueGenerator()
        self._cleaner = ContentCleaner()

        logger.debug(
            "Generadores creados: estado(%d chars), "
            "indice(%d chars), decisiones(%d chars)",
            TOKEN_LIMITS.max_chars_estado,
            TOKEN_LIMITS.max_chars_indice,
            TOKEN_LIMITS.max_chars_decisiones,
        )

    def generate_all(
        self,
        exchanges: list[Exchange],
        blocks: list[ThematicBlock],
        chat_label: str = "",
    ) -> list[RecoveryFile]:
        """Genera todos los archivos de recuperación.

        Orquesta la generación de los tres archivos principales
        (estado, índice, decisiones) y de todos los bloques
        temáticos. Devuelve una lista de :class:`RecoveryFile`
        con toda la información necesaria para escritura y
        verificación.

        El orden de la lista resultante es:

        1. ``00_estado_actual.md``
        2. ``01_indice_recuperacion.md``
        3. ``02_decisiones_clave.md``
        4. Bloques temáticos (en orden)

        Args:
            exchanges: Lista completa de exchanges.
            blocks: Lista de bloques temáticos clasificados.
            chat_label: Etiqueta descriptiva del chat.

        Returns:
            Lista de :class:`RecoveryFile` con todos los
            archivos generados.
        """
        logger.info(
            "Iniciando generación de archivos de recuperación: "
            "%d exchanges, %d bloques, chat_label=%r",
            len(exchanges),
            len(blocks),
            chat_label,
        )

        recovery_files: list[RecoveryFile] = []

        # 1. Generar decisiones clave primero (necesitamos el resumen).
        logger.debug("Generando decisiones clave")
        decisiones_content, decisiones_summary = (
            self._decisiones_gen.generate(exchanges, blocks)
        )
        decisiones_file = RecoveryFile(
            filename=DECISIONES_CLAVE_FILENAME,
            category=FileCategory.DECISIONES,
            content=decisiones_content,
            token_limit=self._get_token_limit(FileCategory.DECISIONES),
        )
        recovery_files.append(decisiones_file)
        logger.info(
            "Decisiones clave generadas: %d caracteres (%.0f tokens)",
            len(decisiones_content),
            len(decisiones_content) / 3.5,
        )

        # 2. Generar estado actual.
        logger.debug("Generando estado actual")
        estado_content = self._estado_gen.generate(exchanges, chat_label)
        estado_file = RecoveryFile(
            filename=ESTADO_ACTUAL_FILENAME,
            category=FileCategory.ESTADO,
            content=estado_content,
            token_limit=self._get_token_limit(FileCategory.ESTADO),
        )
        recovery_files.append(estado_file)
        logger.info(
            "Estado actual generado: %d caracteres (%.0f tokens)",
            len(estado_content),
            len(estado_content) / 3.5,
        )

        # 3. Generar índice de recuperación (usa resumen de decisiones).
        logger.debug("Generando índice de recuperación")
        indice_content = self._indice_gen.generate(
            blocks=blocks,
            decisiones_summary=decisiones_summary,
            chat_label=chat_label,
        )
        indice_file = RecoveryFile(
            filename=INDICE_RECUPERACION_FILENAME,
            category=FileCategory.INDICE,
            content=indice_content,
            token_limit=self._get_token_limit(FileCategory.INDICE),
        )
        recovery_files.append(indice_file)
        logger.info(
            "Índice de recuperación generado: %d caracteres (%.0f tokens)",
            len(indice_content),
            len(indice_content) / 3.5,
        )

        # 4. Generar cada bloque temático.
        logger.debug("Generando %d bloques temáticos", len(blocks))
        for block in blocks:
            bloque_content = self._bloque_gen.generate(
                block=block,
                cleaner=self._cleaner,
            )
            bloque_file = RecoveryFile(
                filename=block.full_filename,
                category=FileCategory.BLOQUE,
                content=bloque_content,
                token_limit=self._get_token_limit(FileCategory.BLOQUE),
            )
            recovery_files.append(bloque_file)
            logger.debug(
                "Bloque '%s' generado: %d caracteres (%.0f tokens)",
                block.display_name,
                len(bloque_content),
                len(bloque_content) / 3.5,
            )

        logger.info(
            "Generación completa: %d archivos de recuperación",
            len(recovery_files),
        )
        return recovery_files

    def _get_token_limit(self, category: FileCategory) -> int:
        """Mapea una categoría de archivo a su límite de tokens.

        Usa los valores definidos en :data:`TOKEN_LIMITS` del
        módulo de configuración para obtener el límite correcto
        según el tipo de archivo.

        Args:
            category: Categoría del archivo de recuperación.

        Returns:
            Límite máximo de tokens para esa categoría.
        """
        mapping: dict[FileCategory, int] = {
            FileCategory.ESTADO: TOKEN_LIMITS.max_tokens_estado,
            FileCategory.INDICE: TOKEN_LIMITS.max_tokens_indice,
            FileCategory.DECISIONES: TOKEN_LIMITS.max_tokens_decisiones,
            FileCategory.BLOQUE: TOKEN_LIMITS.max_tokens_bloque,
        }

        token_limit = mapping.get(category, 0)

        logger.debug(
            "Token limit para %s: %d", category.value, token_limit
        )
        return token_limit
