# Destino: /home/z/my-project/contexto_zai/generation/bloque_generator.py
"""Generador de bloques temáticos (v3.2).

Formatea un ThematicBlock (que puede contener varios temas) como
archivo markdown. Cada intercambio se presenta con su cabecera y
contenido limpio (sin reasoning).

Diferencia respecto a v1.0:
- v1.0 usaba block.name y block.display_name (un bloque = un tema).
- v3.2 usa block.temas (lista de temas en el bloque).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from contexto_zai.processing.content_cleaner import ContentCleaner

if TYPE_CHECKING:
    from contexto_zai.models import ThematicBlock

logger = logging.getLogger(__name__)


class BloqueGenerator:
    """Genera el contenido markdown de un bloque temático.

    Usage:
        >>> gen = BloqueGenerator()
        >>> content = gen.generate(block, cleaner=ContentCleaner())
    """

    def __init__(self) -> None:
        logger.debug("BloqueGenerator inicializado")

    def generate(
        self,
        block: "ThematicBlock",
        cleaner: ContentCleaner,
    ) -> str:
        """Genera el contenido markdown de un bloque.

        Args:
            block: ThematicBlock con intercambios (puede tener varios temas).
            cleaner: ContentCleaner para formatear cada intercambio.

        Returns:
            Contenido markdown del bloque.
        """
        if not block.exchanges:
            logger.warning("Bloque %s sin intercambios", block.filename)
            return f"# Bloque vacío\n\n(Sin intercambios)\n"

        # Cabecera: lista de temas en el bloque
        temas_str = ", ".join(block.temas) if block.temas else "general"
        lines: list[str] = [
            f"# Bloque temático: {temas_str}",
            "",
            f"**Período:** {block.period_str}",
            f"**Intercambios:** {block.exchange_count} "
            f"({block.director_count} del Director, {block.agent_count} del agente)",
            f"**Temas en este archivo:** {len(block.temas)} ({temas_str})",
            f"**Tamaño estimado:** ~{block.estimated_tokens / 1000:.1f}K tokens",
            "",
            "---",
            "",
        ]

        # Cada intercambio formateado
        for i, exchange in enumerate(block.exchanges, start=1):
            formatted = cleaner.format_exchange(exchange, exchange_num=i)
            lines.append(formatted)
            lines.append("")

        content = "\n".join(lines)
        logger.debug(
            "Bloque '%s' generado: %d chars (%.0f tokens), %d intercambios, %d temas",
            block.filename,
            len(content),
            len(content) / 3.5,
            block.exchange_count,
            len(block.temas),
        )
        return content

    def __repr__(self) -> str:
        return "BloqueGenerator()"


if __name__ == "__main__":
    # ── Validación interna de bloque_generator.py ──
    print("=== Validación de bloque_generator.py ===\n")

    from contexto_zai.models import Exchange, Message, MessageRole, ThematicBlock

    gen = BloqueGenerator()
    cleaner = ContentCleaner()

    # Test 1: bloque con un tema
    ex1 = Exchange(
        id=1,
        director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1788482829, content="Ejecuta pytest"),
        agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=1788482830, content="Tests OK")],
        topic="validaciones",
        start_timestamp=1788482829,
        end_timestamp=1788482830,
    )
    block1 = ThematicBlock(filename="bloque_01.md")
    block1.add_exchange(ex1)
    content1 = gen.generate(block1, cleaner)
    assert "validaciones" in content1
    assert "Ejecuta pytest" in content1
    assert "Tests OK" in content1
    assert "1 intercambios" in content1
    print(f"✓ Bloque con 1 tema: {len(content1)} chars")

    # Test 2: bloque con varios temas
    ex2 = Exchange(
        id=2,
        director_msg=Message(seq=3, role=MessageRole.USER, timestamp=1788482900, content="Lee el worklog"),
        agent_msgs=[Message(seq=4, role=MessageRole.ASSISTANT, timestamp=1788482901, content="Worklog leído")],
        topic="configuracion_proyecto",
        start_timestamp=1788482900,
        end_timestamp=1788482901,
    )
    block2 = ThematicBlock(filename="bloque_02.md")
    block2.add_exchange(ex1)  # tema: validaciones
    block2.add_exchange(ex2)  # tema: configuracion_proyecto
    content2 = gen.generate(block2, cleaner)
    assert "validaciones" in content2
    assert "configuracion_proyecto" in content2
    assert "2 intercambios" in content2
    assert "2 temas" in content2
    print(f"✓ Bloque con 2 temas: {len(content2)} chars")

    # Test 3: bloque vacío
    block3 = ThematicBlock(filename="bloque_vacio.md")
    content3 = gen.generate(block3, cleaner)
    assert "Bloque vacío" in content3
    print(f"✓ Bloque vacío: manejado correctamente")

    print("\n✅ bloque_generator.py: todos los tests pasaron")
