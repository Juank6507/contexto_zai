# Destino: /home/z/my-project/contexto_zai/generation/recovery_generator.py
"""Orquestador de generación de archivos de recuperación (v3.2).

Coordina los 4 generadores individuales para producir la lista
completa de RecoveryFile:
1. Decisiones (primero, para obtener el resumen)
2. Estado actual
3. Índice (usa el resumen de decisiones)
4. Bloques temáticos (uno por bloque)

Cada archivo generado incluye su categoría, nombre, contenido y
límite de tokens según la configuración.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

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
    from contexto_zai.models import Exchange, RecoveryMetadata, ThematicBlock

logger = logging.getLogger(__name__)


class RecoveryGenerator:
    """Orquestador de generación de archivos de recuperación.

    Coordina todos los generadores para producir la lista completa
    de RecoveryFile que conforman el paquete de recuperación.

    Usage:
        >>> gen = RecoveryGenerator()
        >>> files = gen.generate_all(exchanges, blocks, chat_label="CZAI")
    """

    def __init__(
        self,
        estado_generator: Optional[EstadoGenerator] = None,
        indice_generator: Optional[IndiceGenerator] = None,
        decisiones_generator: Optional[DecisionesGenerator] = None,
        bloque_generator: Optional[BloqueGenerator] = None,
        cleaner: Optional[ContentCleaner] = None,
    ) -> None:
        self._estado_gen = estado_generator or EstadoGenerator()
        self._indice_gen = indice_generator or IndiceGenerator()
        self._decisiones_gen = decisiones_generator or DecisionesGenerator()
        self._bloque_gen = bloque_generator or BloqueGenerator()
        self._cleaner = cleaner or ContentCleaner()
        logger.debug("RecoveryGenerator inicializado")

    # ── API pública ────────────────────────────────────────────────

    def generate_all(
        self,
        exchanges: list["Exchange"],
        blocks: list["ThematicBlock"],
        chat_label: str = "",
        metadata: Optional["RecoveryMetadata"] = None,
        existing_decisions_content: Optional[str] = None,
        from_timestamp: float = 0.0,
    ) -> list[RecoveryFile]:
        """Genera todos los archivos de recuperación.

        Args:
            exchanges: Lista completa de intercambios.
            blocks: Lista de bloques temáticos.
            chat_label: Etiqueta del chat.
            metadata: Metadata con mapeo tema→archivo (para el índice).
            existing_decisions_content: Contenido previo de 02_decisiones_clave.md
                (para modo incremental de decisiones).
            from_timestamp: Si > 0, las decisiones solo se procesan para
                intercambios nuevos (modo incremental).

        Returns:
            Lista de RecoveryFile con todos los archivos generados.
        """
        recovery_files: list[RecoveryFile] = []

        # 1. Decisiones (primero, para obtener el resumen)
        logger.debug("Generando decisiones clave")
        decisiones_content, decisiones_summary = self._decisiones_gen.generate(
            exchanges,
            from_timestamp=from_timestamp,
        )
        recovery_files.append(
            RecoveryFile(
                filename=DECISIONES_CLAVE_FILENAME,
                category=FileCategory.DECISIONES,
                content=decisiones_content,
                token_limit=self._get_token_limit(FileCategory.DECISIONES),
            )
        )

        # 2. Estado actual
        logger.debug("Generando estado actual")
        estado_content = self._estado_gen.generate(exchanges, chat_label=chat_label)
        recovery_files.append(
            RecoveryFile(
                filename=ESTADO_ACTUAL_FILENAME,
                category=FileCategory.ESTADO,
                content=estado_content,
                token_limit=self._get_token_limit(FileCategory.ESTADO),
            )
        )

        # 3. Índice (usa metadata y resumen de decisiones)
        logger.debug("Generando índice")
        indice_content = self._indice_gen.generate(
            blocks=blocks,
            chat_label=chat_label,
            metadata=metadata,
            decisiones_summary=decisiones_summary,
        )
        recovery_files.append(
            RecoveryFile(
                filename=INDICE_RECUPERACION_FILENAME,
                category=FileCategory.INDICE,
                content=indice_content,
                token_limit=self._get_token_limit(FileCategory.INDICE),
            )
        )

        # 4. Bloques temáticos (uno por bloque)
        logger.debug("Generando %d bloques temáticos", len(blocks))
        for block in blocks:
            bloque_content = self._bloque_gen.generate(
                block=block,
                cleaner=self._cleaner,
            )
            recovery_files.append(
                RecoveryFile(
                    filename=block.full_filename,
                    category=FileCategory.BLOQUE,
                    content=bloque_content,
                    token_limit=self._get_token_limit(FileCategory.BLOQUE),
                )
            )

        logger.info(
            "Generación completa: %d archivos (3 principales + %d bloques)",
            len(recovery_files), len(blocks),
        )
        return recovery_files

    def __repr__(self) -> str:
        return "RecoveryGenerator()"

    # ── Métodos privados ───────────────────────────────────────────

    def _get_token_limit(self, category: FileCategory) -> int:
        """Mapea una categoría a su límite de tokens."""
        mapping = {
            FileCategory.ESTADO: TOKEN_LIMITS.max_tokens_estado,
            FileCategory.INDICE: TOKEN_LIMITS.max_tokens_indice,
            FileCategory.DECISIONES: TOKEN_LIMITS.max_tokens_decisiones,
            FileCategory.BLOQUE: TOKEN_LIMITS.max_tokens_bloque,
        }
        return mapping.get(category, 0)


if __name__ == "__main__":
    # ── Validación interna de recovery_generator.py ──
    print("=== Validación de recovery_generator.py ===\n")

    from contexto_zai.models import (
        Exchange,
        Message,
        MessageRole,
        ThematicBlock,
    )

    gen = RecoveryGenerator()

    # Test 1: generación completa
    exchanges = [
        Exchange(
            id=1,
            director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1788482829, content="Ejecuta pytest de server.py"),
            agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=1788482830, content="5 passed")],
            topic="validaciones",
            start_timestamp=1788482829,
            end_timestamp=1788482830,
        ),
        Exchange(
            id=2,
            director_msg=Message(seq=3, role=MessageRole.USER, timestamp=1788482900, content="Lee el worklog"),
            agent_msgs=[Message(seq=4, role=MessageRole.ASSISTANT, timestamp=1788482901, content="Worklog leído")],
            topic="configuracion_proyecto",
            start_timestamp=1788482900,
            end_timestamp=1788482901,
        ),
    ]
    block1 = ThematicBlock(filename="bloque_01.md")
    block1.add_exchange(exchanges[0])
    block1.add_exchange(exchanges[1])

    files = gen.generate_all(exchanges, [block1], chat_label="Test")

    # Debe haber 4 archivos: estado, indice, decisiones, bloque_01
    assert len(files) == 4
    filenames = [f.filename for f in files]
    assert "00_estado_actual.md" in filenames
    assert "01_indice_recuperacion.md" in filenames
    assert "02_decisiones_clave.md" in filenames
    assert "bloque_01.md" in filenames
    print(f"✓ 4 archivos generados: {filenames}")

    # Test 2: estado tiene 8 secciones
    estado_file = next(f for f in files if f.filename == "00_estado_actual.md")
    for section in ["D1", "D2", "D3", "D4", "A1", "A2", "A3", "A4"]:
        assert f"Sección {section}" in estado_file.content, f"Falta sección {section}"
    print(f"✓ Estado con 8 secciones")

    # Test 3: índice tiene tabla mapeo
    indice_file = next(f for f in files if f.filename == "01_indice_recuperacion.md")
    assert "Mapeo tema → archivo" in indice_file.content
    assert "validaciones" in indice_file.content
    print(f"✓ Índice con mapeo tema → archivo")

    # Test 4: decisiones en modo offline (sin extractor)
    dec_file = next(f for f in files if f.filename == "02_decisiones_clave.md")
    assert "Sin decisiones registradas" in dec_file.content
    print(f"✓ Decisiones en modo offline (placeholder)")

    # Test 5: bloque con intercambio formateado
    bloque_file = next(f for f in files if f.filename == "bloque_01.md")
    assert "Ejecuta pytest de server.py" in bloque_file.content
    assert "5 passed" in bloque_file.content
    print(f"✓ Bloque con intercambios formateados")

    # Test 6: todos los archivos tienen token_limit correcto
    assert estado_file.token_limit == 20_000
    assert indice_file.token_limit == 8_000
    assert dec_file.token_limit == 12_000
    assert bloque_file.token_limit == 70_000
    print(f"✓ Límites v3.2: estado=20K, indice=8K, decisiones=12K, bloque=70K")

    print("\n✅ recovery_generator.py: todos los tests pasaron")
