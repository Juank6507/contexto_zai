# contexto_zai/procesadores/procesador_consulta.py -- ProcesadorConsulta: responde preguntas del agente sobre bloques.
"""ProcesadorConsulta (v4.2).

Responde preguntas del agente sobre bloques temáticos. Reutiliza
la lógica de ``query_context`` (M8) que ya funciona, y la conecta
con el Orquestador para coordinar la ejecución de subagentes.

Regla de eficiencia:
- **Cabe en un subagente** (<100K tokens): un solo subagente que lee
  los bloques y responde.
- **No cabe** (>100K tokens): divide en lotes, un subagente por lote,
  consolida al final.

Reutiliza:
- La lógica de ``query_context`` (M8) para identificar bloques candidatos.
- El ``Orquestador`` para coordinar la ejecución.

Atómico standalone: importa config, models, pathlib, logging y json.
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


import json
import logging
import re
from pathlib import Path
from typing import Optional

from contexto_zai.config import (
    QUERY_DIRECT_MODE_THRESHOLD_TOKENS,
    QUERY_MAX_RESULTS,
    WORKSPACE_OUTPUT_DIR,
)
from contexto_zai.models import SubagentTask

logger = logging.getLogger(__name__)

# Stop words para keyword search
_STOP_WORDS = {
    "que", "de", "la", "el", "en", "y", "a", "los", "las", "del",
    "para", "con", "por", "es", "se", "un", "una", "como", "cual",
    "cuales", "sobre", "al",
}


class ProcesadorConsulta:
    """Responde preguntas del agente sobre bloques.

    Attributes:
        workspace_dir: Directorio del workspace con los bloques.
        orquestador: Orquestador para coordinar subagentes.

    Usage (proceso):
        >>> from contexto_zai.procesadores import ProcesadorConsulta
        >>> proc = ProcesadorConsulta(workspace_dir="/path/to/ws", orquestador=orch)
        >>> result = proc.procesar(pregunta="¿Qué se decidió sobre JWT?")
        >>> if result.get("pending_tasks"):
        ...     # El agente lanzará los subagentes
        ...     pass
    """

    def __init__(
        self,
        workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
        orquestador: Optional[object] = None,
    ) -> None:
        self._workspace_dir = Path(workspace_dir)
        self._orquestador = orquestador  # Se conecta en F4
        logger.debug("ProcesadorConsulta inicializado: %s", self._workspace_dir)

    @property
    def workspace_dir(self) -> Path:
        return self._workspace_dir

    # -- API pública ------------------------------------------------

    def procesar(
        self,
        pregunta: str,
        max_results: int = QUERY_MAX_RESULTS,
    ) -> dict:
        """Procesa una pregunta del agente sobre bloques.

        Identifica bloques candidatos por keyword search, decide según
        tamaño si cabe en un subagente o hay que dividir, prepara las
        tareas, y las publica vía el Orquestador.

        Args:
            pregunta: Pregunta concreta del agente.
            max_results: Máximo de bloques a consultar.

        Returns:
            Dict con:
            - "pending_tasks": lista de SubagentTask (1 para modo directo, N para distribuido).
            - "bloques_candidatos": lista de nombres de bloques.
            - "total_tokens": tamaño total estimado de los bloques.
            - "modo": "directo" o "distribuido".
            - "error": mensaje de error si falló.
        """
        # 1. Verificar que el contexto existe
        indice_path = self._workspace_dir / "01_indice_recuperacion.md"
        metadata_path = self._workspace_dir / "_metadata.json"
        if not indice_path.exists():
            return {"error": "No hay contexto recuperado. Ejecuta pipeline.run() primero."}

        # 2. Leer metadata
        tema_a_archivo = self._leer_metadata(metadata_path)

        # 3. Buscar bloques candidatos
        bloques_candidatos = self._buscar_candidatos(
            pregunta, tema_a_archivo, indice_path, max_results
        )

        if not bloques_candidatos:
            return {"error": "No hay información relevante en los archivos de recuperación."}

        # 4. Calcular tamaño total
        bloques_info = []
        total_chars = 0
        for filename in bloques_candidatos:
            bloque_path = self._workspace_dir / filename
            if bloque_path.exists():
                content = bloque_path.read_text(encoding="utf-8")
                chars = len(content)
                tokens_estimados = int(chars / 3.5)
                total_chars += chars
                bloques_info.append({
                    "filename": filename,
                    "path": str(bloque_path),
                    "chars": chars,
                    "tokens_estimados": tokens_estimados,
                })

        total_tokens = int(total_chars / 3.5)

        # 5. Decidir modo según tamaño
        if total_tokens < QUERY_DIRECT_MODE_THRESHOLD_TOKENS:
            return self._procesar_directo(pregunta, bloques_info, total_tokens)
        else:
            return self._procesar_distribuido(pregunta, bloques_info, total_tokens)

    # -- Métodos privados -------------------------------------------

    def _leer_metadata(self, metadata_path: Path) -> dict:
        """Lee tema_a_archivo de _metadata.json."""
        if not metadata_path.exists():
            return {}
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            return metadata.get("tema_a_archivo", {})
        except (json.JSONDecodeError, ValueError):
            return {}

    def _buscar_candidatos(
        self,
        pregunta: str,
        tema_a_archivo: dict,
        indice_path: Path,
        max_results: int,
    ) -> list[str]:
        """Busca bloques candidatos por keyword search."""
        pregunta_lower = pregunta.lower()
        question_words = re.findall(r"[a-záéíóúñ_]+", pregunta_lower)
        question_words = [w for w in question_words if len(w) > 2 and w not in _STOP_WORDS]

        # Buscar en nombres de temas
        bloques_candidatos: dict[str, list[str]] = {}
        for tema, archivo in tema_a_archivo.items():
            tema_lower = tema.lower()
            for word in question_words:
                if word in tema_lower:
                    bloques_candidatos.setdefault(archivo, []).append(tema)
                    break

        # Buscar en contenido del índice
        if not bloques_candidatos:
            indice_lower = indice_path.read_text(encoding="utf-8").lower()
            for tema, archivo in tema_a_archivo.items():
                for word in question_words:
                    if word in indice_lower:
                        bloques_candidatos.setdefault(archivo, []).append(tema)
                        break

        # Limitar a max_results bloques
        return list(bloques_candidatos.keys())[:max_results]

    def _procesar_directo(
        self,
        pregunta: str,
        bloques_info: list[dict],
        total_tokens: int,
    ) -> dict:
        """Modo directo: un solo subagente que lee los bloques y responde."""
        bloques_paths = "\n".join(f"- {b['path']}" for b in bloques_info)
        prompt = (
            f"Eres un subagente que responde a una consulta del agente principal.\n\n"
            f"## Pregunta\n\n{pregunta}\n\n"
            f"## Archivos a leer\n\n{bloques_paths}\n\n"
            f"## Instrucciones\n\n"
            f"1. Lee los archivos con la herramienta Read.\n"
            f"2. Busca información relevante para responder a la pregunta.\n"
            f"3. Si encuentras información, respóndela de forma completa.\n"
            f"4. Si no encuentras nada relevante, responde exactamente: "
            f"\"No hay información relevante en este bloque.\"\n\n"
            f"Respuesta:"
        )

        task = SubagentTask(
            task_id="consulta_directa",
            purpose="consulta.bloque",
            prompt=prompt,
            context={
                "pregunta": pregunta,
                "bloques": [b["filename"] for b in bloques_info],
                "total_tokens": total_tokens,
                "modo": "directo",
            },
        )

        if self._orquestador is not None:
            self._orquestador.publicar_tareas([task])

        return {
            "pending_tasks": [task],
            "bloques_candidatos": [b["filename"] for b in bloques_info],
            "total_tokens": total_tokens,
            "modo": "directo",
        }

    def _procesar_distribuido(
        self,
        pregunta: str,
        bloques_info: list[dict],
        total_tokens: int,
    ) -> dict:
        """Modo distribuido: un subagente por lote."""
        # Dividir en lotes que quepan en ~100K tokens
        lote_size_tokens = QUERY_DIRECT_MODE_THRESHOLD_TOKENS
        lotes: list[list[dict]] = []
        lote_actual: list[dict] = []
        lote_tokens = 0

        for b in bloques_info:
            if lote_tokens + b["tokens_estimados"] > lote_size_tokens and lote_actual:
                lotes.append(lote_actual)
                lote_actual = []
                lote_tokens = 0
            lote_actual.append(b)
            lote_tokens += b["tokens_estimados"]
        if lote_actual:
            lotes.append(lote_actual)

        tasks: list[SubagentTask] = []
        for i, lote in enumerate(lotes):
            bloques_paths = "\n".join(f"- {b['path']}" for b in lote)
            prompt = (
                f"Eres un subagente que responde a una consulta del agente principal.\n\n"
                f"## Pregunta\n\n{pregunta}\n\n"
                f"## Archivos a leer (lote {i+1}/{len(lotes)})\n\n{bloques_paths}\n\n"
                f"## Instrucciones\n\n"
                f"1. Lee los archivos con la herramienta Read.\n"
                f"2. Busca información relevante.\n"
                f"3. Devuelve tu respuesta.\n\n"
                f"Respuesta:"
            )
            task = SubagentTask(
                task_id=f"consulta_distribuida_lote_{i}",
                purpose="consulta.bloque",
                prompt=prompt,
                context={
                    "pregunta": pregunta,
                    "bloques": [b["filename"] for b in lote],
                    "lote_idx": i,
                    "total_lotes": len(lotes),
                    "modo": "distribuido",
                },
            )
            tasks.append(task)

        if self._orquestador is not None:
            self._orquestador.publicar_tareas(tasks)

        return {
            "pending_tasks": tasks,
            "bloques_candidatos": [b["filename"] for b in bloques_info],
            "total_tokens": total_tokens,
            "modo": "distribuido",
            "num_lotes": len(lotes),
        }

    def __repr__(self) -> str:
        return f"ProcesadorConsulta(workspace_dir={self._workspace_dir!r})"


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

    print("=== Validacion de procesador_consulta.py ===\n")

    import tempfile

    # Test 1: sin contexto recuperado
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorConsulta(workspace_dir=tmpdir)
        result = proc.procesar(pregunta="¿qué se decidió?")
        assert "error" in result
        print(f"[OK] sin contexto: error reportado")

    # Test 2: consulta con contexto simulado (modo directo)
    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear contexto simulado
        (Path(tmpdir) / "01_indice_recuperacion.md").write_text("# Índice\n\n## jwt\n", encoding="utf-8")
        (Path(tmpdir) / "_metadata.json").write_text(json.dumps({
            "tema_a_archivo": {"jwt_autenticacion": "bloque_01.md"}
        }), encoding="utf-8")
        (Path(tmpdir) / "bloque_01.md").write_text("Contenido sobre JWT y autenticación.", encoding="utf-8")

        proc = ProcesadorConsulta(workspace_dir=tmpdir)
        result = proc.procesar(pregunta="¿qué se decidió sobre jwt?")
        assert "error" not in result
        assert result["modo"] == "directo"
        assert len(result["pending_tasks"]) == 1
        assert result["pending_tasks"][0].purpose == "consulta.bloque"
        print(f"[OK] modo directo: {len(result['pending_tasks'])} tarea, {result['total_tokens']} tokens")

    # Test 3: consulta con muchos bloques (modo distribuido)
    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear contexto con bloques grandes para forzar modo distribuido
        # Cada bloque ~40K tokens, 5 bloques = 200K > 100K umbral
        (Path(tmpdir) / "01_indice_recuperacion.md").write_text("# Índice\n\n## jwt\n", encoding="utf-8")
        metadata = {"tema_a_archivo": {}}
        for i in range(5):
            metadata["tema_a_archivo"][f"jwt_tema_{i}"] = f"bloque_{i:02d}.md"
            # Cada bloque ~40K tokens (~140K chars)
            (Path(tmpdir) / f"bloque_{i:02d}.md").write_text("jwt " * 35000, encoding="utf-8")
        (Path(tmpdir) / "_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

        proc = ProcesadorConsulta(workspace_dir=tmpdir)
        # max_results=5 para que tome todos los bloques
        result = proc.procesar(pregunta="¿qué se decidió sobre jwt?", max_results=5)
        assert result["modo"] == "distribuido", f"Esperaba distribuido, got {result.get('modo')} (tokens={result.get('total_tokens')})"
        assert result["num_lotes"] >= 1
        assert len(result["pending_tasks"]) >= 1
        print(f"[OK] modo distribuido: {result['num_lotes']} lotes, {len(result['pending_tasks'])} tareas")

    # Test 4: sin bloques candidatos
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "01_indice_recuperacion.md").write_text("# Índice\n", encoding="utf-8")
        (Path(tmpdir) / "_metadata.json").write_text(json.dumps({"tema_a_archivo": {}}), encoding="utf-8")
        proc = ProcesadorConsulta(workspace_dir=tmpdir)
        result = proc.procesar(pregunta="¿qué se decidió sobre xyz?")
        assert "error" in result
        print(f"[OK] sin candidatos: error reportado")

    # Test 5: con orquestador, publica tareas
    with tempfile.TemporaryDirectory() as tmpdir:
        from contexto_zai.coordinador import Orquestador
        orch = Orquestador(workspace_dir=tmpdir)
        (Path(tmpdir) / "01_indice_recuperacion.md").write_text("# Índice\n\n## jwt\n", encoding="utf-8")
        (Path(tmpdir) / "_metadata.json").write_text(json.dumps({
            "tema_a_archivo": {"jwt_autenticacion": "bloque_01.md"}
        }), encoding="utf-8")
        (Path(tmpdir) / "bloque_01.md").write_text("Contenido sobre JWT.", encoding="utf-8")

        proc = ProcesadorConsulta(workspace_dir=tmpdir, orquestador=orch)
        proc.procesar(pregunta="¿qué sobre jwt?")
        assert orch.hay_tareas_pendientes()
        print(f"[OK] con orquestador: publica tareas")

    # Test 6: respeta max_results
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "01_indice_recuperacion.md").write_text("# Índice\n\n## jwt\n", encoding="utf-8")
        metadata = {"tema_a_archivo": {}}
        for i in range(5):
            metadata["tema_a_archivo"][f"jwt_tema_{i}"] = f"bloque_{i:02d}.md"
            (Path(tmpdir) / f"bloque_{i:02d}.md").write_text("jwt", encoding="utf-8")
        (Path(tmpdir) / "_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

        proc = ProcesadorConsulta(workspace_dir=tmpdir)
        result = proc.procesar(pregunta="¿jwt?", max_results=2)
        assert len(result["bloques_candidatos"]) <= 2
        print(f"[OK] max_results: {len(result['bloques_candidatos'])} candidatos")

    # Test 7: repr
    proc_repr = ProcesadorConsulta(workspace_dir="/tmp/test_repr")
    assert "ProcesadorConsulta" in repr(proc_repr)
    print(f"[OK] repr: {proc_repr!r}")

    print("\n[PASS] procesador_consulta.py: todos los tests pasaron")
