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
# Soporta Estructura A (<workspace>/contexto_zai/) y Estructura B (workspace=contexto_zai/)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
_package_root = None
for _ in range(10):
    if not _os.path.isfile(_os.path.join(_candidate, '__init__.py')):
        break  # salimos del paquete
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
        attachments_indexados: list = None,
        workspace_dir: Optional[Path | str] = None,  # v6.3 F2
    ) -> str:
        """Genera el contenido markdown del índice de recuperación.

        Args:
            blocks: Lista de ThematicBlock generados.
            chat_label: Etiqueta del chat.
            metadata: Metadata con el mapeo tema->archivo (opcional).
                Si se proporciona, se usa para construir la tabla.
                Si no, se construye a partir de los blocks.
            decisiones_summary: Resumen de decisiones (opcional).
            attachments_indexados: Lista de DocumentoIndexResult con
                documentos indexados por subagente (v3.5).
            workspace_dir: v6.3 F2 — Directorio del workspace. Si se pasa,
                se incluyen los bloque_*.md preexistentes que no estén en la
                lista `blocks` (típicamente de chats anteriores).

        Returns:
            Contenido markdown del índice.
        """
        # v6.3 F2: incluir bloques de chats anteriores preexistentes
        if workspace_dir:
            blocks = self._incluir_bloques_anteriores(blocks, workspace_dir)

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
        for tema, archivos in sorted(tema_a_archivo.items()):
            # Buscar el bloque que contiene este tema para obtener tokens
            tokens_str = self._find_tokens_for_tema(tema, blocks)
            # v6.0: archivos puede ser str (legacy) o list[str] (multi-bloque)
            if isinstance(archivos, list):
                archivos_str = ", ".join(f"`{a}`" for a in archivos)
            else:
                archivos_str = f"`{archivos}`"
            lines.append(f"| `{tema}` | {archivos_str} | ~{tokens_str} |")

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
                lines.append(f"- **{padre}** se subdividio en: {', '.join(f'`{s}`' for s in subtemas)}")
            lines.append("")

        # v3.3 + v6.6 F6: seccion de scripts versionados.
        # v6.6 F6: ampliar detección — un tema es "script versionado" si:
        #   - su nombre contiene un sufijo de script (patrón antiguo), O
        #   - el bloque correspondiente contiene bloques de código con
        #     extensiones de archivo (.py, .ts, .tsx, .js, .json, .sh, .bat, .ps1)
        # v6.6 F6: eliminar la referencia al archivo _grafos_cambios.json que
        # nunca se crea en ningún flujo (Bug 5 — enlace muerto).
        script_temas = self._detectar_scripts_versionados(tema_a_archivo, blocks)
        if script_temas:
            lines.extend([
                "## Scripts versionados (v3.3)",
                "",
            ])
            for tema in sorted(script_temas):
                archivos = tema_a_archivo[tema]
                if isinstance(archivos, list):
                    archivos_str = ", ".join(f"`{a}`" for a in archivos)
                else:
                    archivos_str = f"`{archivos}`"
                # v6.6 F6: eliminada la referencia a _grafos_cambios.json (Bug 5)
                lines.append(f"- `{tema}` -> {archivos_str}")
            lines.append("")

        # v3.5: sección de documentos indexados (attachments)
        if attachments_indexados:
            lines.extend([
                "## Documentos indexados (v3.5)",
                "",
                "Documentos adjuntos por el Director e indexados por subagentes efímeros.",
                "El agente principal no consumió su contexto con estos documentos; solo tiene",
                "el resumen. Si necesitas detalle de una sección, lanza un subagente para releerla.",
                "",
                "| Documento | Temas | Resumen | Ruta |",
                "|-----------|-------|---------|------|",
            ])
            for doc in attachments_indexados:
                # doc es un DocumentoIndexResult
                if not getattr(doc, "success", False):
                    continue
                temas_str = ", ".join(
                    f"`{t.tema}`" for t in doc.temas_detectados[:3]
                )
                if len(doc.temas_detectados) > 3:
                    temas_str += f" (+{len(doc.temas_detectados) - 3} más)"
                resumen_corto = doc.resumen_breve[:80].replace("|", "\\|").replace("\n", " ")
                if len(doc.resumen_breve) > 80:
                    resumen_corto += "..."
                ruta = str(getattr(doc, "archivo_indexado_path", "")).replace("|", "\\|")
                lines.append(
                    f"| `{doc.filename}` | {temas_str} | {resumen_corto} | `{ruta}` |"
                )
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
    ) -> dict[str, list[str]]:
        """Construye el mapeo tema -> lista de archivos (v6.0 multi-bloque).

        Prioriza la metadata si se proporciona (es la fuente de verdad).
        Si no, lo construye a partir de los bloques.
        """
        if metadata and metadata.tema_a_archivo:
            return {k: list(v) for k, v in metadata.tema_a_archivo.items()}

        # Construir desde los bloques
        mapping: dict[str, list[str]] = {}
        for b in blocks:
            for tema in b.temas:
                if tema not in mapping:
                    mapping[tema] = []
                if b.filename not in mapping[tema]:
                    mapping[tema].append(b.filename)
        return mapping

    def _detectar_scripts_versionados(
        self,
        tema_a_archivo: dict,
        blocks: list["ThematicBlock"],
    ) -> list[str]:
        """v6.6 F6 (Bug 6 fix): Detecta temas que son scripts versionados.

        Un tema se considera script versionado si:
        1. Su nombre contiene un sufijo de script (patrón v3.3 antiguo):
           _server, _router, _config, _auth, _pipeline, _client, _bloque, _seccion.
        2. O el bloque físico correspondiente contiene bloques de código con
           extensiones de archivo (.py, .ts, .tsx, .js, .json, .sh, .bat, .ps1).
        """
        _SUFIJOS_SCRIPT = [
            "_server", "_router", "_config", "_auth", "_pipeline",
            "_client", "_bloque", "_seccion",
        ]
        import re as _re
        _CODE_BLOCK_PATTERN = _re.compile(
            r"^```(?:python|py|typescript|ts|tsx|javascript|js|json|bash|sh|bat|powershell|ps1|yaml|yml)",
            _re.MULTILINE,
        )
        archivos_a_inspeccionar: set = set()
        for archivos in tema_a_archivo.values():
            if isinstance(archivos, list):
                archivos_a_inspeccionar.update(archivos)
            elif isinstance(archivos, str):
                archivos_a_inspeccionar.add(archivos)
        archivos_con_codigo: set = set()
        ws = getattr(self, '_workspace_dir_cache', None)
        for filename in archivos_a_inspeccionar:
            contenido = None
            if ws:
                from pathlib import Path as _Path
                ruta = _Path(ws) / filename
                if ruta.exists():
                    try:
                        contenido = ruta.read_text(encoding="utf-8")
                    except Exception:
                        contenido = None
            if contenido and _CODE_BLOCK_PATTERN.search(contenido):
                archivos_con_codigo.add(filename)
        script_temas: list[str] = []
        for tema, archivos in tema_a_archivo.items():
            if any(suf in tema for suf in _SUFIJOS_SCRIPT):
                script_temas.append(tema)
                continue
            archivos_lista = archivos if isinstance(archivos, list) else [archivos]
            if any(a in archivos_con_codigo for a in archivos_lista):
                script_temas.append(tema)
        return script_temas

    def _find_tokens_for_tema(
        self,
        tema: str,
        blocks: list["ThematicBlock"],
    ) -> str:
        """Encuentra los tokens aproximados del archivo que contiene el tema.

        v6.6 F6 (Bug 2 fix): si no encuentra el bloque en la lista de blocks,
        busca en el workspace con glob bloque_*.md (no bloque_externo_* que
        ya no se usa tras la normalización).
        """
        for b in blocks:
            if tema in b.temas:
                return f"{b.estimated_tokens / 1000:.1f}K"
        # v6.6 F6: buscar en workspace si el bloque no está en la lista
        if hasattr(self, '_workspace_dir_cache') and self._workspace_dir_cache:
            from pathlib import Path as _Path
            ws = _Path(self._workspace_dir_cache)
            if ws.exists():
                for p in ws.glob("bloque_*.md"):
                    try:
                        content = p.read_text(encoding="utf-8")
                        if len(content) < 100:
                            continue
                        if tema in content:
                            return f"{len(content) / 3500:.1f}K"
                    except Exception:
                        continue
        return "?"

    def _incluir_bloques_anteriores(
        self,
        blocks: list["ThematicBlock"],
        workspace_dir: Path | str,
    ) -> list["ThematicBlock"]:
        """v6.3 F2: Incluye bloques físicos preexistentes del workspace.

        Escanea workspace_dir en busca de bloque_*.md que no estén en la
        lista `blocks` actual (típicamente de chats anteriores fusionados
        manualmente). Los añade a la lista con sus temas leídos del header.

        Args:
            blocks: Lista de ThematicBlock generados en esta corrida.
            workspace_dir: Directorio del workspace.

        Returns:
            Lista ampliada con los bloques preexistentes añadidos al final.
        """
        from pathlib import Path as _Path
        ws = _Path(workspace_dir)
        if not ws.exists():
            return blocks

        existing_filenames = {b.filename for b in blocks}
        added = 0
        for p in sorted(ws.glob("bloque_*.md")):
            if p.name in existing_filenames:
                continue
            # Leer temas del header del bloque preexistente
            try:
                content = p.read_text(encoding="utf-8")
                temas = []
                for line in content.split("\n"):
                    if line.startswith("# Bloque tematico:") or line.startswith("# Bloque temático:"):
                        temas_str = line.split(":", 1)[1].strip()
                        temas = [t.strip() for t in temas_str.split(",")]
                        break
                if not temas:
                    temas = ["anterior"]
                # Crear ThematicBlock sin exchanges (solo para el índice)
                from contexto_zai.models import ThematicBlock as _TB
                block = _TB(filename=p.name, temas=temas)
                blocks.append(block)
                added += 1
            except Exception as e:
                logger.warning("v6.3 F2: no se pudo leer bloque preexistente %s: %s", p.name, e)

        if added > 0:
            logger.info("v6.3 F2: %d bloque(s) de chats anteriores incluidos en el índice", added)
        return blocks

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
