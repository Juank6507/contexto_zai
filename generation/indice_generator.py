# contexto_zai/generation/indice_generator.py -- Generador del archivo 01_indice_recuperacion.md con tabla mapeo tema->archivo.
"""Generador del archivo 01_indice_recuperacion.md (v3.2).

Produce el índice con el mapeo explícito `tema -> archivo`, no
solo una lista de bloques por descripción como en v1.0.

Diferencia crítica respecto a v1.0:
- v1.0: lista de bloques por descripción.
- v3.2: tabla `tema -> archivo` consultable, incluyendo subtemas
  derivados de subdivisiones.

Tamaño máximo: 8K tokens (~28KB chars).
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
from typing import TYPE_CHECKING, Optional

from contexto_zai.config import TOKEN_LIMITS
from contexto_zai.models import RecoveryMetadata

if TYPE_CHECKING:
    from contexto_zai.models import ThematicBlock

logger = logging.getLogger(__name__)

class IndiceGenerator:
    """Genera el archivo 01_indice_recuperacion.md con mapeo tema->archivo.

    Args:
        max_chars: Límite máximo de caracteres (por defecto 28K).

    Usage:
        >>> gen = IndiceGenerator()
        >>> content = gen.generate(blocks=[...], metadata=meta, chat_label="CZAI")
    """

    def __init__(
        self,
        max_chars: int = TOKEN_LIMITS.max_chars_indice,
    ) -> None:
        self._max_chars = max_chars
        logger.debug("IndiceGenerator inicializado: max_chars=%d", max_chars)

    # -- API pública ------------------------------------------------

    def generate(
        self,
        blocks: list["ThematicBlock"],
        chat_label: str = "",
        metadata: Optional[RecoveryMetadata] = None,
        decisiones_summary: str = "",
    ) -> str:
        """Genera el contenido markdown del índice de recuperación.

        Args:
            blocks: Lista de ThematicBlock generados.
            chat_label: Etiqueta del chat.
            metadata: Metadata con el mapeo tema->archivo (opcional).
                Si se proporciona, se usa para construir la tabla.
                Si no, se construye a partir de los blocks.
            decisiones_summary: Resumen de decisiones (opcional).

        Returns:
            Contenido markdown del índice.
        """
        # Construir mapeo tema -> archivo
        tema_a_archivo = self._build_tema_a_archivo(blocks, metadata)

        # Construir contenido
        lines: list[str] = [
            f"# Índice de Recuperación -- {chat_label or 'Chat'}",
            "",
            "## Instrucción",
            "",
            "Si detectas que has perdido contexto, este archivo es tu punto de entrada.",
            "Identifica qué tema necesitas y delega a un subagente para que lea el archivo",
            "correspondiente.",
            "",
            "## Protocolo de recuperación",
            "",
            "1. Lee este archivo (ya lo estás leyendo).",
            "2. Lee `00_estado_actual.md` para saber dónde quedaste (contexto del tema activo).",
            "3. Si necesitas otro tema, identifica aquí en qué archivo está.",
            "4. Lanza un subagente con una **pregunta concreta** sobre ese tema.",
            "5. El subagente devolverá una respuesta concisa.",
            "6. Si necesitas otro tema, repite desde el paso 3.",
            "",
            "## Mapeo tema -> archivo",
            "",
            "| Tema | Archivo | Tokens aprox. |",
            "|------|---------|---------------|",
        ]

        # Filas de la tabla
        for tema, archivo in sorted(tema_a_archivo.items()):
            # Buscar el bloque que contiene este tema para obtener tokens
            tokens_str = self._find_tokens_for_tema(tema, blocks)
            lines.append(f"| `{tema}` | `{archivo}` | ~{tokens_str} |")

        lines.extend([
            "",
            "## Resumen de bloques",
            "",
        ])

        for b in blocks:
            temas_str = ", ".join(f"`{t}`" for t in b.temas)
            lines.append(
                f"### `{b.filename}` (~{b.estimated_tokens / 1000:.1f}K tokens)"
            )
            lines.append(f"- **Temas:** {temas_str}")
            lines.append(f"- **Intercambios:** {b.exchange_count}")
            lines.append(f"- **Período:** {b.period_str}")
            lines.append("")

        # Resumen de decisiones (si se proporciona)
        if decisiones_summary:
            lines.extend([
                "## Decisiones clave (resumen)",
                "",
                decisiones_summary.strip(),
                "",
            ])

        # Subtemas derivados (si hay en metadata)
        if metadata and metadata.subtemas_derivados:
            lines.extend([
                "## Subtemas derivados (subdivisiones)",
                "",
            ])
            for padre, subtemas in metadata.subtemas_derivados.items():
                lines.append(f"- **{padre}** se subdividió en: {', '.join(f'`{s}`' for s in subtemas)}")
            lines.append("")

        content = "\n".join(lines)

        # Truncar si excede el límite
        if len(content) > self._max_chars:
            logger.warning(
                "Indice excede limite (%d > %d chars), truncando",
                len(content), self._max_chars,
            )
            content = content[:self._max_chars - 50] + "\n\n... (truncado por límite)\n"

        logger.info(
            "Indice generado: %d chars (%.0f tokens), %d temas mapeados",
            len(content), len(content) / 3.5, len(tema_a_archivo),
        )
        return content

    @property
    def max_chars(self) -> int:
        return self._max_chars

    def __repr__(self) -> str:
        return f"IndiceGenerator(max_chars={self._max_chars})"

    # -- Métodos privados -------------------------------------------

    def _build_tema_a_archivo(
        self,
        blocks: list["ThematicBlock"],
        metadata: Optional[RecoveryMetadata],
    ) -> dict[str, str]:
        """Construye el mapeo tema -> archivo.

        Prioriza la metadata si se proporciona (es la fuente de verdad).
        Si no, lo construye a partir de los bloques.
        """
        if metadata and metadata.tema_a_archivo:
            return dict(metadata.tema_a_archivo)

        # Construir desde los bloques
        mapping: dict[str, str] = {}
        for b in blocks:
            for tema in b.temas:
                if tema in mapping and mapping[tema] != b.filename:
                    logger.warning(
                        "Tema '%s' aparece en multiples archivos: %s y %s "
                        "(violacion de unicidad)",
                        tema, mapping[tema], b.filename,
                    )
                mapping[tema] = b.filename
        return mapping

    def _find_tokens_for_tema(
        self,
        tema: str,
        blocks: list["ThematicBlock"],
    ) -> str:
        """Encuentra los tokens aproximados del archivo que contiene el tema."""
        for b in blocks:
            if tema in b.temas:
                return f"{b.estimated_tokens / 1000:.1f}K"
        return "?"

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
    # -- Validación interna de indice_generator.py --
    print("=== Validacion de indice_generator.py ===\n")

    from contexto_zai.models import Exchange, Message, MessageRole, ThematicBlock

    gen = IndiceGenerator()

    # Test 1: tabla tema -> archivo presente
    ex1 = Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="test"), topic="validaciones", start_timestamp=1, end_timestamp=2)
    ex2 = Exchange(id=2, director_msg=Message(seq=2, role=MessageRole.USER, timestamp=3, content="worklog"), topic="configuracion_proyecto", start_timestamp=3, end_timestamp=4)
    b1 = ThematicBlock(filename="bloque_01.md")
    b1.add_exchange(ex1)
    b1.add_exchange(ex2)
    b2 = ThematicBlock(filename="bloque_02.md")
    b2.add_exchange(Exchange(id=3, director_msg=Message(seq=3, role=MessageRole.USER, timestamp=5, content="x"), topic="general", start_timestamp=5, end_timestamp=6))

    content = gen.generate([b1, b2], chat_label="Test")

    # Verificar tabla mapeo
    assert "Mapeo tema -> archivo" in content
    assert "| Tema | Archivo |" in content
    assert "`validaciones`" in content
    assert "`bloque_01.md`" in content
    assert "`configuracion_proyecto`" in content
    assert "`general`" in content
    assert "`bloque_02.md`" in content
    print(f"[OK] Tabla tema -> archivo con todos los temas")

    # Test 2: protocolo de recuperación presente
    assert "Protocolo de recuperación" in content
    assert "00_estado_actual.md" in content
    assert "subagente" in content.lower()
    print(f"[OK] Protocolo de recuperacion documentado")

    # Test 3: resumen de bloques
    assert "Resumen de bloques" in content
    assert "bloque_01.md" in content
    assert "Temas:" in content
    print(f"[OK] Resumen de bloques con temas listados")

    # Test 4: con metadata
    from contexto_zai.models import RecoveryMetadata
    meta = RecoveryMetadata(chat_id="abc", share_id="def")
    meta.registrar_tema("validaciones", "bloque_01.md")
    meta.registrar_tema("configuracion_proyecto", "bloque_01.md")
    meta.registrar_tema("general", "bloque_02.md")
    meta.registrar_subtema("validaciones", "validaciones_server", "bloque_03.md")

    content2 = gen.generate([b1, b2], chat_label="Test", metadata=meta)
    assert "Subtemas derivados" in content2
    assert "validaciones_server" in content2
    print(f"[OK] Subtemas derivados documentados desde metadata")

    # Test 5: con resumen de decisiones
    content3 = gen.generate([b1, b2], chat_label="Test", decisiones_summary="- D01: usar X\n- D02: descartar Y")
    assert "Decisiones clave (resumen)" in content3
    assert "D01: usar X" in content3
    print(f"[OK] Resumen de decisiones incluido")

    print("\n[PASS] indice_generator.py: todos los tests pasaron")
