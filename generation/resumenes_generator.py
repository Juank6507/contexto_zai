# contexto_zai/generation/resumenes_generator.py -- Generador del índice de resúmenes (Sistema 2 de indexado v4.4).
"""Generador del archivo ``04_resumenes_bloques.md`` (v4.4).

Sistema 2 de indexado: recolecta los resúmenes de todos los bloques
(del chat + externos) en un solo archivo legible. El agente puede
leer este archivo SIN lanzar subagentes para responder preguntas
genéricas.

Los resúmenes provienen de:
- Bloques del chat: el subagente modo ``RESUMEN_TRUNCADO`` los genera
  (o se extraen del primer párrafo del bloque).
- Bloques externos (``bloque_externo_*.md``): el campo ``RESUMEN:``
  que el subagente indexador escribió al indexar el documento.

Atómico standalone: importa config, models, pathlib y logging.
Auto-tests en ``__main__``.
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
_package_root = None
for _ in range(10):
    if not _os.path.isfile(_os.path.join(_candidate, '__init__.py')):
        break
    _parent = _os.path.dirname(_candidate)
    if not _os.path.isfile(_os.path.join(_parent, '__init__.py')):
        _package_root = _candidate
        break
    _candidate = _parent
if _package_root:
    _workspace = _os.path.dirname(_package_root)
    if _workspace not in _sys.path:
        _sys.path.insert(0, _workspace)
else:
    _parent = _os.path.dirname(_here)
    if _parent not in _sys.path:
        _sys.path.insert(0, _parent)

import logging
import re
from pathlib import Path
from typing import Optional

from contexto_zai.config import WORKSPACE_OUTPUT_DIR

logger = logging.getLogger(__name__)


class ResumenesGenerator:
    """Genera ``04_resumenes_bloques.md`` con los resúmenes de todos los bloques.

    Usage:
        >>> gen = ResumenesGenerator()
        >>> gen.generate(workspace_dir="/path/to/ws")
        >>> # 04_resumenes_bloques.md creado en el workspace
    """

    def __init__(self) -> None:
        logger.debug("ResumenesGenerator inicializado")

    def generate(
        self,
        workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
    ) -> str:
        """Genera el contenido del archivo de resúmenes.

        Lee todos los bloques del workspace (``bloque_*.md`` y
        ``bloque_externo_*.md``), extrae el resumen de cada uno, y
        los compila en un archivo markdown.

        Args:
            workspace_dir: Directorio del workspace.

        Returns:
            Contenido markdown del archivo ``04_resumenes_bloques.md``.
        """
        ws = Path(workspace_dir)
        bloques = self._listar_bloques(ws)

        if not bloques:
            logger.info("ResumenesGenerator: no hay bloques en %s", ws)
            return "# Resúmenes de bloques\n\n(Sin bloques indexados)\n"

        lineas: list[str] = ["# Resúmenes de bloques", ""]
        lineas.append(f"_{len(bloques)} bloques indexados_")
        lineas.append("")
        lineas.append("---")
        lineas.append("")

        for bloque_path in sorted(bloques):
            filename = bloque_path.name
            resumen = self._extraer_resumen(bloque_path)
            if resumen:
                lineas.append(f"## {filename}")
                lineas.append("")
                lineas.append(resumen)
                lineas.append("")
            else:
                lineas.append(f"## {filename}")
                lineas.append("")
                lineas.append("_(sin resumen disponible)_")
                lineas.append("")

        content = "\n".join(lineas)
        self._escribir(ws, content)
        logger.info(
            "ResumenesGenerator: 04_resumenes_bloques.md generado (%d bloques, %d chars)",
            len(bloques), len(content),
        )
        return content

    def _listar_bloques(self, ws: Path) -> list[Path]:
        """Lista todos los archivos de bloque en el workspace."""
        bloques = list(ws.glob("bloque_*.md")) + list(ws.glob("bloque_externo_*.md"))
        # Deduplicar (por si acaso)
        vistos = set()
        unicos = []
        for b in bloques:
            if b.name not in vistos:
                vistos.add(b.name)
                unicos.append(b)
        return unicos

    def _extraer_resumen(self, bloque_path: Path) -> Optional[str]:
        """Extrae el resumen de un bloque.

        Busca el campo ``RESUMEN:`` en el contenido del bloque (lo escribió
        el subagente indexador para bloques externos). Si no lo encuentra,
        extrae el primer párrafo no vacío que no sea un header markdown.
        """
        try:
            content = bloque_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("No se pudo leer bloque %s: %s", bloque_path.name, e)
            return None

        # Buscar "RESUMEN:" al inicio de línea (formato del subagente indexador)
        match = re.search(r"^RESUMEN:\s*(.+?)(?=\n\n|\n##|\Z)", content, re.MULTILINE | re.DOTALL)
        if match:
            return match.group(1).strip()

        # Fallback: primer párrafo no vacío que no sea header
        parrafos = content.split("\n\n")
        for parrafo in parrafos:
            limpio = parrafo.strip()
            if not limpio:
                continue
            if limpio.startswith("#"):
                continue
            if limpio.startswith("**"):
                continue
            if limpio.startswith("---"):
                continue
            # Truncar a 500 chars
            if len(limpio) > 500:
                return limpio[:497] + "..."
            return limpio

        return None

    def _escribir(self, ws: Path, content: str) -> None:
        """Escribe el archivo ``04_resumenes_bloques.md`` en el workspace."""
        path = ws / "04_resumenes_bloques.md"
        ws.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


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
    # -- Validación interna de resumenes_generator.py (atómico standalone) --
    print("=== Validacion de resumenes_generator.py ===\n")

    import tempfile

    # Test 1: generar con bloques que tienen RESUMEN:
    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear bloques con RESUMEN:
        (Path(tmpdir) / "bloque_01.md").write_text(
            "# Bloque 01\n\nRESUMEN: Este bloque trata sobre autenticación JWT y tokens.\n\n## Tema 1\n\nContenido...",
            encoding="utf-8",
        )
        (Path(tmpdir) / "bloque_externo_doc_lote_0.md").write_text(
            "# Bloque externo\n\nRESUMEN: Documento sobre el sistema de validaciones.\n\nTEMA: validaciones\n",
            encoding="utf-8",
        )
        gen = ResumenesGenerator()
        content = gen.generate(workspace_dir=tmpdir)
        assert "autenticación JWT" in content
        assert "sistema de validaciones" in content
        assert "bloque_01.md" in content
        assert "bloque_externo_doc_lote_0.md" in content
        # Verificar que el archivo se escribió
        assert (Path(tmpdir) / "04_resumenes_bloques.md").exists()
        print(f"[OK] Genera 04_resumenes_bloques.md con resúmenes de bloques (2 bloques)")

    # Test 2: bloque sin RESUMEN: usa primer párrafo como fallback
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "bloque_01.md").write_text(
            "# Bloque 01\n\n**Tema activo:** general\n\nEste es el primer párrafo del bloque que sirve como resumen cuando no hay RESUMEN: explícito.\n\n## Sección D1\n\nContenido...",
            encoding="utf-8",
        )
        gen = ResumenesGenerator()
        content = gen.generate(workspace_dir=tmpdir)
        assert "primer párrafo del bloque" in content
        print(f"[OK] Fallback: usa primer párrafo cuando no hay RESUMEN:")

    # Test 3: workspace vacío
    with tempfile.TemporaryDirectory() as tmpdir:
        gen = ResumenesGenerator()
        content = gen.generate(workspace_dir=tmpdir)
        assert "Sin bloques indexados" in content
        print(f"[OK] Workspace vacío: mensaje apropiado")

    # Test 4: resumen se trunca a 500 chars
    with tempfile.TemporaryDirectory() as tmpdir:
        texto_largo = "x" * 800
        (Path(tmpdir) / "bloque_01.md").write_text(
            f"# Bloque\n\n{texto_largo}\n", encoding="utf-8",
        )
        gen = ResumenesGenerator()
        content = gen.generate(workspace_dir=tmpdir)
        # El resumen debe estar truncado
        # Buscar el resumen en el contenido generado
        assert "..." in content  # el truncado añade "..."
        print(f"[OK] Resumen truncado a 500 chars")

    print("\n[PASS] resumenes_generator.py: todos los tests pasaron")
