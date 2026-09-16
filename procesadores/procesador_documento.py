# contexto_zai/procesadores/procesador_documento.py -- ProcesadorDocumento: procesa documentos (links, attachments, archivos, URLs).
"""ProcesadorDocumento (v4.2).

Procesa documentos para entregarle contexto al agente. Unifica los
4 mecanismos de ampliación (links del chat, attachments, archivos
externos, URLs) bajo una sola clase que decide según tamaño cómo
procesar el contenido.

Decisión según tamaño:
- **Trivialmente pequeño** (<1K tokens): el agente lo lee directo.
- **Mediano** (1K–50K tokens): un subagente que lee, clasifica y resume.
- **Grande** (>50K tokens): el flujo de 3 niveles (Divisor + Conciliador),
  coordinado por el Orquestador.

Reutiliza:
- ``DocumentoIndexerSubagent`` (su lógica de lectura y clasificación).
- El ``Divisor`` y ``Conciliador`` del flujo de 3 niveles.
- El ``DocumentDelegator`` (la decisión de delegar).

Atómico standalone: importa config, models, pathlib y logging.
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
from pathlib import Path
from typing import Optional

from contexto_zai.config import (
    AMPLIAR_SMALL_FILE_THRESHOLD_TOKENS,
    PARTITION_THRESHOLD_TOKENS,
    WORKSPACE_OUTPUT_DIR,
)
from contexto_zai.models import SubagentTask

logger = logging.getLogger(__name__)

# Umbrales de tamaño (configurables en config.py)
TRIVIAL_THRESHOLD_TOKENS = 1000  # <1K tokens: agente lee directo
MEDIUM_THRESHOLD_TOKENS = PARTITION_THRESHOLD_TOKENS  # >30K tokens (v4.2): 3 niveles


class ProcesadorDocumento:
    """Procesa documentos para entregarle contexto al agente.

    Attributes:
        workspace_dir: Directorio del workspace.
        orquestador: Orquestador para coordinar subagentes con el agente.

    Usage (proceso):
        >>> from contexto_zai.procesadores import ProcesadorDocumento
        >>> proc = ProcesadorDocumento(workspace_dir="/path/to/ws")
        >>> result = proc.procesar(source_type="file", source_path="/path/to/doc.pdf")
        >>> if result.get("needs_agent_read"):
        ...     # El agente lee el archivo directo
        ...     pass
        >>> elif result.get("pending_tasks"):
        ...     # El proceso publicó tareas para que el agente lance subagentes
        ...     pass
    """

    def __init__(
        self,
        workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
        orquestador: Optional[object] = None,
    ) -> None:
        self._workspace_dir = Path(workspace_dir)
        self._orquestador = orquestador  # Se conecta en F4
        logger.debug("ProcesadorDocumento inicializado: %s", self._workspace_dir)

    @property
    def workspace_dir(self) -> Path:
        return self._workspace_dir

    # -- API pública ------------------------------------------------

    def procesar(
        self,
        source_type: str,
        source_path: str,
        jwt: str = "",
        metadata: Optional[dict] = None,
    ) -> dict:
        """Procesa un documento y decide cómo entregarle el contexto al agente.

        Args:
            source_type: "file" o "url".
            source_path: Ruta al archivo o URL.
            jwt: JWT del Director (si es URL de Z.ai).
            metadata: Metadata opcional (título, autor, fecha).

        Returns:
            Dict con:
            - "needs_agent_read": True si el archivo es trivial y el agente lo lee directo.
            - "path": ruta al archivo (si needs_agent_read=True).
            - "tokens_estimados": tokens estimados del documento.
            - "pending_tasks": lista de SubagentTask (si necesita subagente).
            - "error": mensaje de error si falló.
        """
        metadata = metadata or {}

        # 1. Obtener el contenido (bytes)
        content_bytes, filename = self._obtener_contenido(source_type, source_path, jwt)
        if content_bytes is None:
            return {"error": f"No se pudo obtener contenido de {source_path}"}

        # 2. Estimar tokens
        estimated_tokens = len(content_bytes) / 3.5  # aprox 1 token = 3.5 bytes

        # 3. Decidir según tamaño
        if estimated_tokens < TRIVIAL_THRESHOLD_TOKENS:
            return self._procesar_trivial(source_path, filename, estimated_tokens)
        elif estimated_tokens < MEDIUM_THRESHOLD_TOKENS:
            return self._procesar_mediano(filename, content_bytes, estimated_tokens, metadata)
        else:
            return self._procesar_grande(filename, content_bytes, estimated_tokens, metadata, jwt)

    # -- Métodos privados -------------------------------------------

    def _obtener_contenido(
        self,
        source_type: str,
        source_path: str,
        jwt: str,
    ) -> tuple[Optional[bytes], str]:
        """Obtiene el contenido del documento según el tipo de fuente.

        Returns:
            Tupla (content_bytes, filename). (None, "") si falló.
        """
        if source_type == "file":
            file_path = Path(source_path)
            if not file_path.exists():
                logger.error("Archivo no encontrado: %s", source_path)
                return None, ""
            return file_path.read_bytes(), file_path.name

        elif source_type == "url":
            # Descargar con requests
            import requests
            from urllib.parse import urlparse
            try:
                r = requests.get(source_path, timeout=30, stream=True)
                r.raise_for_status()
                parsed = urlparse(source_path)
                filename = Path(parsed.path).name or "documento_descargado"
                return r.content, filename
            except Exception as e:
                logger.error("Error descargando URL %s: %s", source_path, e)
                return None, ""

        else:
            logger.error("source_type no válido: %s", source_type)
            return None, ""

    def _procesar_trivial(self, source_path: str, filename: str, tokens: float) -> dict:
        """Documento trivialmente pequeño: el agente lo lee directo."""
        return {
            "needs_agent_read": True,
            "path": source_path,
            "filename": filename,
            "tokens_estimados": int(tokens),
        }

    def _procesar_mediano(
        self,
        filename: str,
        content_bytes: bytes,
        tokens: float,
        metadata: dict,
    ) -> dict:
        """Documento mediano: un subagente que lee, clasifica y resume.

        Construye un prompt real para que el subagente lea el archivo,
        lo clasifique por temas, y genere un resumen.
        """
        prompt = self._build_documento_prompt(filename, content_bytes, tokens)

        task = SubagentTask(
            task_id=f"documento_{filename[:30]}",
            purpose="documento.mediano",
            prompt=prompt,
            context={
                "filename": filename,
                "tokens_estimados": int(tokens),
                "tamaño": "mediano",
            },
        )
        if self._orquestador is not None:
            self._orquestador.publicar_tareas([task])

        return {
            "needs_agent_read": False,
            "pending_tasks": [task],
            "tokens_estimados": int(tokens),
            "filename": filename,
        }

    def _procesar_grande(
        self,
        filename: str,
        content_bytes: bytes,
        tokens: float,
        metadata: dict,
        jwt: str,
    ) -> dict:
        """Documento grande: divide en lotes y un subagente por lote."""
        from contexto_zai.config import MAX_TOKENS_POR_SUBAGENTE_N2

        num_lotes = max(1, int(tokens / MAX_TOKENS_POR_SUBAGENTE_N2) + 1)
        tasks: list[SubagentTask] = []
        for i in range(num_lotes):
            prompt = self._build_lote_prompt(filename, content_bytes, tokens, i, num_lotes)
            task = SubagentTask(
                task_id=f"documento_grande_{filename[:20]}_lote_{i}",
                purpose="documento.grande",
                prompt=prompt,
                context={
                    "filename": filename,
                    "lote_idx": i,
                    "total_lotes": num_lotes,
                    "tokens_estimados": int(tokens),
                    "tamaño": "grande",
                },
            )
            tasks.append(task)

        if self._orquestador is not None:
            self._orquestador.publicar_tareas(tasks)

        return {
            "needs_agent_read": False,
            "pending_tasks": tasks,
            "tokens_estimados": int(tokens),
            "filename": filename,
            "flujo": "3_niveles",
            "num_lotes": num_lotes,
        }

    def _build_documento_prompt(self, filename: str, content_bytes: bytes, tokens: float) -> str:
        """Construye el prompt para que un subagente lea y clasifique un documento."""
        from contexto_zai.config import ATTACHMENTS_TEMP_DIR
        temp_path = ATTACHMENTS_TEMP_DIR / f"ampliar_{filename.replace(' ', '_')}"
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(content_bytes)

        # v4.3 (Bug 1 fix): formato alineado con DocumentoIndexerSubagent._build_prompt_historico()
        # para que IntegradorRespuestas._parse_temas_documento() (que exige los 3 campos
        # TEMA + DESCRIPCION + SECCIONES) pueda parsear la respuesta correctamente.
        return f"""Eres un subagente indexador de documentos. Tu objetivo es leer
un documento y generar un índice estructurado que permita al agente principal
saber de qué trata sin haberlo leído.

## Archivo a leer

- {temp_path}

## Tu tarea

1. Lee el archivo con la herramienta Read.
2. Identifica los temas principales que se discuten en el documento.
3. Para cada tema, indica su nombre en snake_case, una descripción corta, y
   las secciones del documento donde se trata (separadas por comas).
4. Genera un resumen breve del documento (máximo 500 caracteres).

## Formato de respuesta EXACTO

TEMA: <nombre_snake_case>
DESCRIPCION: <descripción corta del tema>
SECCIONES: <sección1, sección2, sección3>

TEMA: <nombre_snake_case>
DESCRIPCION: <descripción corta>
SECCIONES: <sección1, sección2>

RESUMEN: <resumen breve del documento, máximo 500 caracteres>

Reglas:
- Nombres de tema en snake_case (sin espacios, sin acentos).
- Máximo 5 temas.
- Cada tema debe tener al menos 1 sección.
- El resumen debe ser conciso y revelador (no genérico).

Respuesta:"""

    def _build_lote_prompt(self, filename: str, content_bytes: bytes, tokens: float,
                           lote_idx: int, total_lotes: int) -> str:
        """Construye el prompt para que un subagente procese un lote del documento."""
        from contexto_zai.config import ATTACHMENTS_TEMP_DIR
        temp_path = ATTACHMENTS_TEMP_DIR / f"ampliar_{filename.replace(' ', '_')}"
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(content_bytes)

        # Calcular qué porción del archivo leer (por líneas)
        try:
            content_str = content_bytes.decode("utf-8", errors="replace")
            lines = content_str.split("\n")
            total_lines = len(lines)
            lines_per_lote = max(1, total_lines // total_lotes)
            start_line = lote_idx * lines_per_lote
            end_line = min((lote_idx + 1) * lines_per_lote, total_lines)
        except Exception:
            start_line = 0
            end_line = 0

        # v4.3 (Bug 1 fix): formato alineado con DocumentoIndexerSubagent._build_prompt_historico()
        # para que IntegradorRespuestas._parse_temas_documento() pueda parsear la respuesta.
        return f"""Eres un subagente indexador de documentos. Estás procesando
una porción de un documento grande.

## Archivo a leer

- {temp_path}

## Lote

Lote {lote_idx + 1} de {total_lotes}.
Lee las líneas {start_line + 1} a {end_line} del archivo (de {total_lines} líneas totales).

## Tu tarea

1. Lee el archivo con la herramienta Read (solo las líneas indicadas).
2. Identifica los temas principales de esta porción.
3. Para cada tema, indica su nombre en snake_case, una descripción corta, y
   las secciones donde se trata (separadas por comas).
4. Genera un resumen breve de esta porción (máximo 200 caracteres).

## Formato de respuesta EXACTO

TEMA: <nombre_snake_case>
DESCRIPCION: <descripción corta del tema>
SECCIONES: <sección1, sección2>

TEMA: <nombre_snake_case>
DESCRIPCION: <descripción corta>
SECCIONES: <sección1, sección2>

RESUMEN: <resumen breve de la porción>

Reglas:
- Nombres de tema en snake_case (sin espacios, sin acentos).
- Máximo 3 temas por porción.

Respuesta:"""

    def __repr__(self) -> str:
        return f"ProcesadorDocumento(workspace_dir={self._workspace_dir!r})"


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

    print("=== Validacion de procesador_documento.py ===\n")

    import tempfile

    # Test 1: documento trivial (<1K tokens)
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorDocumento(workspace_dir=tmpdir)
        # Crear archivo pequeño
        small_file = Path(tmpdir) / "small.txt"
        small_file.write_text("Hola mundo", encoding="utf-8")
        result = proc.procesar(source_type="file", source_path=str(small_file))
        assert result["needs_agent_read"]
        assert result["tokens_estimados"] < 1000
        print(f"[OK] documento trivial: needs_agent_read=True, {result['tokens_estimados']} tokens")

    # Test 2: documento mediano (1K–50K tokens)
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorDocumento(workspace_dir=tmpdir)
        # Crear archivo mediano (~5K tokens = ~17.5K chars)
        medium_file = Path(tmpdir) / "medium.txt"
        medium_file.write_text("x" * 17500, encoding="utf-8")
        result = proc.procesar(source_type="file", source_path=str(medium_file))
        assert not result["needs_agent_read"]
        assert "pending_tasks" in result
        assert len(result["pending_tasks"]) == 1
        assert result["pending_tasks"][0].purpose == "documento.mediano"
        print(f"[OK] documento mediano: {len(result['pending_tasks'])} tarea, {result['tokens_estimados']} tokens")

    # Test 3: documento grande (>50K tokens)
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorDocumento(workspace_dir=tmpdir)
        # Crear archivo grande (~60K tokens = ~210K chars)
        large_file = Path(tmpdir) / "large.txt"
        large_file.write_text("x" * 210000, encoding="utf-8")
        result = proc.procesar(source_type="file", source_path=str(large_file))
        assert not result["needs_agent_read"]
        assert result.get("flujo") == "3_niveles"
        assert result["num_lotes"] >= 1
        print(f"[OK] documento grande: flujo 3_niveles, {result['num_lotes']} lotes, {result['tokens_estimados']} tokens")

    # Test 4: archivo no encontrado
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorDocumento(workspace_dir=tmpdir)
        result = proc.procesar(source_type="file", source_path="/no/existe.txt")
        assert "error" in result
        print(f"[OK] archivo no encontrado: error reportado")

    # Test 5: source_type inválido
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorDocumento(workspace_dir=tmpdir)
        result = proc.procesar(source_type="invalid", source_path="x")
        assert "error" in result
        print(f"[OK] source_type inválido: error reportado")

    # Test 6: con orquestador, publica tareas
    with tempfile.TemporaryDirectory() as tmpdir:
        from contexto_zai.coordinador import Orquestador
        orch = Orquestador(workspace_dir=tmpdir)
        proc = ProcesadorDocumento(workspace_dir=tmpdir, orquestador=orch)
        medium_file = Path(tmpdir) / "medium.txt"
        medium_file.write_text("x" * 17500, encoding="utf-8")
        proc.procesar(source_type="file", source_path=str(medium_file))
        assert orch.hay_tareas_pendientes()
        tareas = orch.leer_tareas_pendientes()
        assert len(tareas) == 1
        assert tareas[0].purpose == "documento.mediano"
        print(f"[OK] con orquestador: publica {len(tareas)} tarea(s)")

    # Test 7: repr
    proc_repr = ProcesadorDocumento(workspace_dir="/tmp/test_repr")
    assert "ProcesadorDocumento" in repr(proc_repr)
    print(f"[OK] repr: {proc_repr!r}")

    # Test 8 (F0.3 v4.3): _build_documento_prompt pide los 3 campos TEMA+DESCRIPCION+SECCIONES
    # Bug 1 fix: el prompt debe alinearse con el parser _parse_temas_documento() del IntegradorRespuestas,
    # que exige los 3 campos. Antes solo pedia TEMA+DESCRIPCION, lo que hacia que el parser fallara.
    proc_test = ProcesadorDocumento(workspace_dir="/tmp/test_prompts")
    content = b"contenido de prueba del documento"
    prompt_doc = proc_test._build_documento_prompt("test.txt", content, 100)
    assert "TEMA:" in prompt_doc
    assert "DESCRIPCION:" in prompt_doc
    assert "SECCIONES:" in prompt_doc, "F0.3: el prompt de documento debe pedir SECCIONES"
    # El orden debe ser TEMA → DESCRIPCION → SECCIONES (igual que DocumentoIndexerSubagent)
    idx_tema = prompt_doc.find("TEMA:")
    idx_desc = prompt_doc.find("DESCRIPCION:")
    idx_secc = prompt_doc.find("SECCIONES:")
    assert 0 <= idx_tema < idx_desc < idx_secc, \
        f"F0.3: orden esperado TEMA<DESCRIPCION<SECCIONES, got {idx_tema},{idx_desc},{idx_secc}"
    print(f"[OK] _build_documento_prompt pide TEMA+DESCRIPCION+SECCIONES (alineado con parser)")

    # Test 9 (F0.3 v4.3): _build_lote_prompt tambien pide los 3 campos
    prompt_lote = proc_test._build_lote_prompt("test.txt", content, 100, 0, 2)
    assert "TEMA:" in prompt_lote
    assert "DESCRIPCION:" in prompt_lote
    assert "SECCIONES:" in prompt_lote, "F0.3: el prompt de lote debe pedir SECCIONES"
    idx_tema = prompt_lote.find("TEMA:")
    idx_desc = prompt_lote.find("DESCRIPCION:")
    idx_secc = prompt_lote.find("SECCIONES:")
    assert 0 <= idx_tema < idx_desc < idx_secc, \
        f"F0.3: orden esperado TEMA<DESCRIPCION<SECCIONES, got {idx_tema},{idx_desc},{idx_secc}"
    print(f"[OK] _build_lote_prompt pide TEMA+DESCRIPCION+SECCIONES (alineado con parser)")

    print("\n[PASS] procesador_documento.py: todos los tests pasaron")
