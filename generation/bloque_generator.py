# contexto_zai/generation/bloque_generator.py -- Generador de bloques tematicos: formatea un ThematicBlock como markdown con varios temas.
"""Generador de bloques temáticos (v3.2).

Formatea un ThematicBlock (que puede contener varios temas) como
archivo markdown. Cada intercambio se presenta con su cabecera y
contenido limpio (sin reasoning).

Diferencia respecto a v1.0:
- v1.0 usaba block.name y block.display_name (un bloque = un tema).
- v3.2 usa block.temas (lista de temas en el bloque).
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
for _ in range(5):
    if _os.path.isdir(_os.path.join(_candidate, 'contexto_zai')):
        if _candidate not in _sys.path:
            _sys.path.insert(0, _candidate)
        break
    _candidate = _os.path.dirname(_candidate)
else:
    _parent = _os.path.dirname(_here)
    if _parent not in _sys.path:
        _sys.path.insert(0, _parent)

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
            return f"# Bloque vacio\n\n(Sin intercambios)\n"

        # Cabecera: lista de temas en el bloque
        temas_str = ", ".join(block.temas) if block.temas else "general"
        lines: list[str] = [
            f"# Bloque tematico: {temas_str}",
            "",
            f"**Periodo:** {block.period_str}",
            f"**Intercambios:** {block.exchange_count} "
            f"({block.director_count} del Director, {block.agent_count} del agente)",
            f"**Temas en este archivo:** {len(block.temas)} ({temas_str})",
            f"**Tamano estimado:** ~{block.estimated_tokens / 1000:.1f}K tokens",
        ]

        # v3.3: si hay temas que parecen scripts, anadir nota de versionado
        script_temas = [
            t for t in block.temas
            if "_server" in t or "_router" in t or "_config" in t
            or "_auth" in t or "_pipeline" in t or "_client" in t
            or "_bloque" in t or "_seccion" in t
        ]
        if script_temas:
            lines.extend([
                "",
                f"**Scripts versionados:** {len(script_temas)} "
                f"({', '.join(script_temas)})",
                f"Ver grafo de cambios en `_grafos_cambios.json` para retroceder a versiones anteriores.",
            ])

        lines.extend([
            "",
            "---",
            "",
        ])

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
    # Compatibilidad Windows: reconfigurar stdout/stderr a UTF-8
    import io as _io, sys as _sys
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
        if hasattr(_sys.stderr, 'buffer') and 'utf' not in (getattr(_sys.stderr, 'encoding', '') or '').lower():
            _sys.stderr = _io.TextIOWrapper(_sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass
    # -- Validación interna de bloque_generator.py --
    print("=== Validacion de bloque_generator.py ===\n")

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
    # Cabecera del bloque debe contener "Intercambios" y el numero 1
    assert "Intercambios" in content1 or "intercambios" in content1.lower()
    assert "1" in content1
    print(f"[OK] Bloque con 1 tema: {len(content1)} chars")

    # Test 2: bloque con varios temas
    ex2 = Exchange(
        id=2,
        director_msg=Message(seq=3, role=MessageRole.USER, timestamp=1788482900, content="Lee el worklog"),
        agent_msgs=[Message(seq=4, role=MessageRole.ASSISTANT, timestamp=1788482901, content="Worklog leido")],
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
    # Debe indicar 2 intercambios y 2 temas en el archivo
    assert "Intercambios:** 2" in content2 or "intercambios:** 2" in content2.lower()
    assert "Temas en este archivo:** 2" in content2
    print(f"[OK] Bloque con 2 temas: {len(content2)} chars")

    # Test 3: bloque vacio
    block3 = ThematicBlock(filename="bloque_vacio.md")
    content3 = gen.generate(block3, cleaner)
    assert "Bloque vacio" in content3 or "vac" in content3.lower()
    print(f"[OK] Bloque vacio: manejado correctamente")

    print("\n[PASS] bloque_generator.py: todos los tests pasaron")
