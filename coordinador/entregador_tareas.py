# contexto_zai/coordinador/entregador_tareas.py -- EntregadorTareas: el proceso le entrega al agente las tareas que necesita.
"""EntregadorTareas (v4.2).

El proceso publica las tareas (prompts) que necesita que el agente
ejecute con subagentes. El agente lee esas tareas y lanza los
subagentes con el Task tool.

El "lugar accesible" es un archivo en el workspace
(``_pending_tasks.json``), no un mini-servicio HTTP. Simples,
inspeccionables, sin polling.

Atómico standalone: importa config, models y pathlib. Nada más.
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
from pathlib import Path
from typing import Optional

from contexto_zai.config import WORKSPACE_OUTPUT_DIR
from contexto_zai.models import SubagentTask

logger = logging.getLogger(__name__)

# Nombre del archivo donde se publican las tareas pendientes.
PENDING_TASKS_FILENAME = "_pending_tasks.json"


class EntregadorTareas:
    """Publica y lee tareas pendientes para que el agente las ejecute.

    El proceso publica tareas (``SubagentTask``) en ``_pending_tasks.json``
    dentro del workspace. El agente lee ese archivo para saber qué
    subagentes lanzar.

    Attributes:
        workspace_dir: Directorio del workspace donde vive _pending_tasks.json.

    Usage (proceso):
        >>> from contexto_zai.coordinador import EntregadorTareas
        >>> from contexto_zai.models import SubagentTask
        >>> entregador = EntregadorTareas(workspace_dir="/path/to/ws")
        >>> tareas = [SubagentTask(task_id="estado_d4", prompt="...")]
        >>> entregador.publicar(tareas)

    Usage (agente):
        >>> tareas = entregador.leer()
        >>> for t in tareas:
        ...     # lanzar subagente con t.prompt
        ...     pass
    """

    def __init__(self, workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR) -> None:
        self._workspace_dir = Path(workspace_dir)
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("EntregadorTareas inicializado: %s", self._workspace_dir)

    @property
    def workspace_dir(self) -> Path:
        return self._workspace_dir

    @property
    def pending_tasks_path(self) -> Path:
        """Ruta del archivo _pending_tasks.json."""
        return self._workspace_dir / PENDING_TASKS_FILENAME

    # -- API pública ------------------------------------------------

    def publicar(self, tasks: list[SubagentTask]) -> None:
        """Publica una lista de tareas para que el agente las ejecute.

        Si ya hay tareas pendientes, las añade a las existentes (no reemplaza).
        Esto permite que múltiples procesadores publiquen tareas en el mismo
        ciclo de pipeline.run().

        Args:
            tasks: Lista de SubagentTask a publicar.
        """
        if not tasks:
            logger.debug("publicar: lista vacía, no se hace nada")
            return

        # Leer tareas existentes (si las hay)
        existing = self.leer()
        all_tasks = existing + tasks

        # Serializar a JSON
        data = {
            "tasks": [
                {
                    "task_id": t.task_id,
                    "purpose": t.purpose,
                    "prompt": t.prompt,
                    "context": t.context,
                }
                for t in all_tasks
            ],
            "total": len(all_tasks),
        }

        # Escribir atómicamente (write temp + rename)
        tmp_path = self.pending_tasks_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(self.pending_tasks_path)

        logger.info(
            "EntregadorTareas: publicadas %d tareas (total pendientes: %d)",
            len(tasks), len(all_tasks),
        )

    def leer(self) -> list[SubagentTask]:
        """Lee las tareas pendientes.

        Returns:
            Lista de SubagentTask. Vacía si no hay archivo o está vacío.
        """
        if not self.pending_tasks_path.exists():
            return []

        try:
            data = json.loads(self.pending_tasks_path.read_text(encoding="utf-8"))
            tasks_data = data.get("tasks", [])
            return [
                SubagentTask(
                    task_id=t["task_id"],
                    purpose=t.get("purpose", ""),
                    prompt=t.get("prompt", ""),
                    context=t.get("context", {}),
                )
                for t in tasks_data
            ]
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Error leyendo %s: %s", self.pending_tasks_path, e)
            return []

    def limpiar(self) -> None:
        """Borra el archivo de tareas pendientes tras aplicar las respuestas."""
        if self.pending_tasks_path.exists():
            self.pending_tasks_path.unlink()
            logger.debug("EntregadorTareas: borrado %s", self.pending_tasks_path)

    def hay_tareas_pendientes(self) -> bool:
        """Verifica si hay tareas pendientes publicadas."""
        return self.pending_tasks_path.exists() and self.pending_tasks_path.stat().st_size > 10

    def total_pendientes(self) -> int:
        """Devuelve el número de tareas pendientes."""
        return len(self.leer())

    def __repr__(self) -> str:
        return f"EntregadorTareas(workspace_dir={self._workspace_dir!r})"


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

    print("=== Validacion de entregador_tareas.py ===\n")

    import tempfile

    # Test 1: publicar y leer tareas
    with tempfile.TemporaryDirectory() as tmpdir:
        ent = EntregadorTareas(workspace_dir=tmpdir)
        tareas = [
            SubagentTask(task_id="estado_d4", purpose="estado.d4", prompt="prompt D4",
                         context={"section": "D4"}),
            SubagentTask(task_id="decisiones_lote_0", purpose="decisiones", prompt="prompt dec",
                         context={"lote_idx": 0}),
        ]
        ent.publicar(tareas)
        assert ent.hay_tareas_pendientes(), "Debería haber tareas pendientes"
        assert ent.total_pendientes() == 2
        leidas = ent.leer()
        assert len(leidas) == 2
        assert leidas[0].task_id == "estado_d4"
        assert leidas[1].prompt == "prompt dec"
        print(f"[OK] publicar+leer: {len(leidas)} tareas, ids={[t.task_id for t in leidas]}")

    # Test 2: publicar añade a existentes (no reemplaza)
    with tempfile.TemporaryDirectory() as tmpdir:
        ent = EntregadorTareas(workspace_dir=tmpdir)
        ent.publicar([SubagentTask(task_id="t1", prompt="p1")])
        ent.publicar([SubagentTask(task_id="t2", prompt="p2")])
        assert ent.total_pendientes() == 2, f"Debería tener 2, got {ent.total_pendientes()}"
        print(f"[OK] publicar añade: {ent.total_pendientes()} tareas tras 2 publicaciones")

    # Test 3: leer en workspace vacío devuelve lista vacía
    with tempfile.TemporaryDirectory() as tmpdir:
        ent = EntregadorTareas(workspace_dir=tmpdir)
        assert ent.leer() == []
        assert not ent.hay_tareas_pendientes()
        assert ent.total_pendientes() == 0
        print(f"[OK] workspace vacío: 0 tareas")

    # Test 4: limpiar borra el archivo
    with tempfile.TemporaryDirectory() as tmpdir:
        ent = EntregadorTareas(workspace_dir=tmpdir)
        ent.publicar([SubagentTask(task_id="t1", prompt="p1")])
        assert ent.hay_tareas_pendientes()
        ent.limpiar()
        assert not ent.hay_tareas_pendientes()
        assert ent.total_pendientes() == 0
        print(f"[OK] limpiar: archivo borrado, 0 tareas")

    # Test 5: publicar lista vacía no hace nada
    with tempfile.TemporaryDirectory() as tmpdir:
        ent = EntregadorTareas(workspace_dir=tmpdir)
        ent.publicar([])
        assert not ent.hay_tareas_pendientes()
        print(f"[OK] publicar lista vacía: no crea archivo")

    # Test 6: archivo corrupto devuelve lista vacía (no crash)
    with tempfile.TemporaryDirectory() as tmpdir:
        ent = EntregadorTareas(workspace_dir=tmpdir)
        ent.pending_tasks_path.write_text("{{invalid json", encoding="utf-8")
        assert ent.leer() == []
        print(f"[OK] archivo corrupto: devuelve lista vacía")

    # Test 7: escritura atómica (no queda archivo .tmp)
    with tempfile.TemporaryDirectory() as tmpdir:
        ent = EntregadorTareas(workspace_dir=tmpdir)
        ent.publicar([SubagentTask(task_id="t1", prompt="p1")])
        tmp_files = list(Path(tmpdir).glob("*.tmp"))
        assert len(tmp_files) == 0, f"No debería haber .tmp, got: {tmp_files}"
        print(f"[OK] escritura atómica: sin archivos .tmp residuales")

    # Test 8: repr
    ent_repr = EntregadorTareas(workspace_dir="/tmp/test_repr")
    assert "EntregadorTareas" in repr(ent_repr)
    print(f"[OK] repr: {ent_repr!r}")

    print("\n[PASS] entregador_tareas.py: todos los tests pasaron")
