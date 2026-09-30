# contexto_zai/coordinador/orquestador.py -- Orquestador: coordina el flujo completo entre el agente y el proceso.
"""Orquestador (v4.2).

Coordina el flujo completo entre el proceso Python y el agente
principal. Es la herramienta del agente: existe para ayudarlo, no
para hacerlo menos eficiente.

Flujo típico:
1. El proceso (o un procesador) llama a ``preparar_tareas()`` para
   construir las tareas que necesita.
2. El ``EntregadorTareas`` las publica en ``_pending_tasks.json``.
3. (El agente las lee y lanza los subagentes con el Task tool —
   esto ocurre fuera del proceso.)
4. Los subagentes escriben sus respuestas en ``_responses/``.
5. El agente llama a ``pipeline.collect_responses()``.
6. El ``Orquestador.aplicar_respuestas()`` lee las respuestas, las
   integra a los archivos, y devuelve el resultado estructurado.

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

from contexto_zai.config import WORKSPACE_OUTPUT_DIR
from contexto_zai.coordinador.entregador_tareas import EntregadorTareas
from contexto_zai.coordinador.recogedor_respuestas import RecogedorRespuestas
from contexto_zai.models import SubagentResponse, SubagentTask

logger = logging.getLogger(__name__)


class Orquestador:
    """Coordina el flujo completo entre el agente y el proceso.

    El Orquestador es el punto central de coordinación. Sabe cuándo
    hay tareas pendientes, cuándo las respuestas llegaron, y cuándo
    integrarlas a los archivos.

    Attributes:
        workspace_dir: Directorio del workspace donde viven _pending_tasks.json
            y _responses/.

    Usage (proceso):
        >>> from contexto_zai.coordinador import Orquestador
        >>> from contexto_zai.models import SubagentTask
        >>> orch = Orquestador(workspace_dir="/path/to/ws")
        >>> tareas = [SubagentTask(task_id="estado_d4", prompt="...")]
        >>> orch.publicar_tareas(tareas)
        >>> # El agente lanza los subagentes, estos escriben en _responses/
        >>> resultado = orch.aplicar_respuestas()
        >>> print(resultado["total_applied"])

    Usage (agente, tras lanzar subagentes):
        >>> # El agente llama a pipeline.collect_responses() que invoca:
        >>> resultado = orch.aplicar_respuestas()
    """

    def __init__(self, workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR) -> None:
        self._workspace_dir = Path(workspace_dir)
        self._entregador = EntregadorTareas(workspace_dir=self._workspace_dir)
        self._recogedor = RecogedorRespuestas(workspace_dir=self._workspace_dir)
        logger.debug(
            "Orquestador inicializado: workspace=%s",
            self._workspace_dir,
        )

    @property
    def workspace_dir(self) -> Path:
        return self._workspace_dir

    @property
    def entregador(self) -> EntregadorTareas:
        return self._entregador

    @property
    def recogedor(self) -> RecogedorRespuestas:
        return self._recogedor

    # -- API pública ------------------------------------------------

    def publicar_tareas(self, tasks: list[SubagentTask]) -> None:
        """Publica tareas para que el agente las ejecute.

        Delega al ``EntregadorTareas``. Si ya hay tareas pendientes,
        las añade a las existentes.

        Args:
            tasks: Lista de SubagentTask a publicar.
        """
        self._entregador.publicar(tasks)

    def leer_tareas_pendientes(self) -> list[SubagentTask]:
        """Lee las tareas pendientes publicadas.

        Returns:
            Lista de SubagentTask pendientes.
        """
        return self._entregador.leer()

    def hay_tareas_pendientes(self) -> bool:
        """Verifica si hay tareas pendientes publicadas."""
        return self._entregador.hay_tareas_pendientes()

    def hay_respuestas_listas(self) -> bool:
        """Verifica si hay respuestas listas para aplicar."""
        return self._recogedor.hay_respuestas()

    def aplicar_respuestas(
        self,
        integrador: Optional[object] = None,
    ) -> dict:
        """Lee las respuestas de ``_responses/``, las integra a los archivos,
        y devuelve el resultado estructurado al agente.

        Este método lo invoca ``pipeline.collect_responses()`` tras que el
        agente haya lanzado los subagentes y estos hayan escrito sus respuestas.

        Args:
            integrador: Objeto opcional con método ``integrar(responses)``
                que aplica las respuestas a los archivos. Si no se pasa,
                solo se leen y devuelven las respuestas sin integrar (para
                que el llamador decida qué hacer con ellas).

        Returns:
            Dict con el resultado estructurado:
            - "responses": lista de SubagentResponse leídas.
            - "total_leidas": número de respuestas leídas.
            - "integradas": True si se llamó al integrador.
            - "total_aplicadas": número de respuestas aplicadas (si integrador).
            - "errores": lista de errores (si los hubo).
        """
        responses = self._recogedor.leer_todas()
        errors: list[str] = []
        total_aplicadas = 0
        integradas = False

        if not responses:
            logger.info("Orquestador: no hay respuestas para aplicar")
            return {
                "responses": [],
                "total_leidas": 0,
                "integradas": False,
                "total_aplicadas": 0,
                "errores": [],
            }

        # Reportar respuestas fallidas
        for r in responses:
            if not r.success:
                errors.append(f"{r.task_id}: {r.error}")
                logger.warning("Orquestador: respuesta fallida %s: %s", r.task_id, r.error)

        # Aplicar con el integrador (si se pasó)
        if integrador is not None:
            try:
                aplicadas = integrador.integrar(responses, self._workspace_dir)
                if isinstance(aplicadas, dict):
                    total_aplicadas = aplicadas.get("total_applied", len(responses))
                else:
                    total_aplicadas = len(responses) if aplicadas else 0
                integradas = True
                logger.info(
                    "Orquestador: %d respuestas integradas por el integrador",
                    total_aplicadas,
                )
            except Exception as e:
                msg = f"Error en integrador: {e}"
                errors.append(msg)
                logger.error(msg, exc_info=True)

        # Limpiar tareas y respuestas tras aplicar
        self._entregador.limpiar()
        self._recogedor.limpiar()

        return {
            "responses": responses,
            "total_leidas": len(responses),
            "integradas": integradas,
            "total_aplicadas": total_aplicadas,
            "errores": errors,
        }

    def estado(self) -> dict:
        """Devuelve el estado actual de la coordinación.

        Returns:
            Dict con:
            - "tareas_pendientes": número de tareas en _pending_tasks.json.
            - "respuestas_listas": número de respuestas en _responses/.
            - "listo_para_aplicar": True si hay respuestas y no hay tareas pendientes.
        """
        tareas = self._entregador.total_pendientes()
        respuestas = self._recogedor.total_respuestas()
        return {
            "tareas_pendientes": tareas,
            "respuestas_listas": respuestas,
            "listo_para_aplicar": respuestas > 0 and tareas == 0,
        }

    def limpiar_todo(self) -> None:
        """Borra todas las tareas y respuestas (para reiniciar)."""
        self._entregador.limpiar()
        self._recogedor.limpiar()
        logger.info("Orquestador: tareas y respuestas borradas")

    def __repr__(self) -> str:
        estado = self.estado()
        return (
            f"Orquestador(workspace_dir={self._workspace_dir!r}, "
            f"tareas={estado['tareas_pendientes']}, "
            f"respuestas={estado['respuestas_listas']})"
        )


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

    print("=== Validacion de orquestador.py ===\n")

    import tempfile

    # Test 1: publicar tareas y verificar estado
    with tempfile.TemporaryDirectory() as tmpdir:
        orch = Orquestador(workspace_dir=tmpdir)
        assert not orch.hay_tareas_pendientes()
        tareas = [
            SubagentTask(task_id="estado_d4", purpose="estado.d4", prompt="prompt D4"),
            SubagentTask(task_id="decisiones", purpose="decisiones", prompt="prompt dec"),
        ]
        orch.publicar_tareas(tareas)
        assert orch.hay_tareas_pendientes()
        assert len(orch.leer_tareas_pendientes()) == 2
        print(f"[OK] publicar_tareas: 2 tareas publicadas")

    # Test 2: aplicar_respuestas sin integrador (solo lee)
    with tempfile.TemporaryDirectory() as tmpdir:
        orch = Orquestador(workspace_dir=tmpdir)
        # El agente "escribió" respuestas
        orch.recogedor.escribir_respuesta("estado_d4", "RESTRICCION: No usar indigo")
        orch.recogedor.escribir_respuesta("decisiones", "DECISION: Usar OOP")
        resultado = orch.aplicar_respuestas()
        assert resultado["total_leidas"] == 2
        assert not resultado["integradas"]
        assert resultado["total_aplicadas"] == 0
        print(f"[OK] aplicar_respuestas sin integrador: {resultado['total_leidas']} leídas")

    # Test 3: aplicar_respuestas con integrador mock
    with tempfile.TemporaryDirectory() as tmpdir:
        orch = Orquestador(workspace_dir=tmpdir)
        orch.recogedor.escribir_respuesta("t1", "r1")

        class IntegradorMock:
            def __init__(self):
                self.llamado = False
                self.responses_recibidas = 0

            def integrar(self, responses, workspace_dir):
                self.llamado = True
                self.responses_recibidas = len(responses)
                return {"total_applied": len(responses)}

        integrador = IntegradorMock()
        resultado = orch.aplicar_respuestas(integrador=integrador)
        assert integrador.llamado
        assert integrador.responses_recibidas == 1
        assert resultado["integradas"]
        assert resultado["total_aplicadas"] == 1
        print(f"[OK] aplicar_respuestas con integrador: {resultado['total_aplicadas']} aplicadas")

    # Test 4: aplicar_respuestas en workspace vacío
    with tempfile.TemporaryDirectory() as tmpdir:
        orch = Orquestador(workspace_dir=tmpdir)
        resultado = orch.aplicar_respuestas()
        assert resultado["total_leidas"] == 0
        assert not resultado["integradas"]
        print(f"[OK] workspace vacío: 0 respuestas")

    # Test 5: errores de subagentes se reportan
    with tempfile.TemporaryDirectory() as tmpdir:
        orch = Orquestador(workspace_dir=tmpdir)
        orch.recogedor.escribir_respuesta("t1", "r1", success=True)
        orch.recogedor.escribir_respuesta("t2", "", success=False, error="timeout")
        resultado = orch.aplicar_respuestas()
        assert len(resultado["errores"]) == 1
        assert "timeout" in resultado["errores"][0]
        print(f"[OK] errores reportados: {len(resultado['errores'])} error(es)")

    # Test 6: limpiar_todo borra todo
    with tempfile.TemporaryDirectory() as tmpdir:
        orch = Orquestador(workspace_dir=tmpdir)
        orch.publicar_tareas([SubagentTask(task_id="t1", prompt="p1")])
        orch.recogedor.escribir_respuesta("t1", "r1")
        assert orch.hay_tareas_pendientes()
        assert orch.hay_respuestas_listas()
        orch.limpiar_todo()
        assert not orch.hay_tareas_pendientes()
        assert not orch.hay_respuestas_listas()
        print(f"[OK] limpiar_todo: tareas y respuestas borradas")

    # Test 7: aplicar_respuestas limpia tareas y respuestas tras aplicar
    with tempfile.TemporaryDirectory() as tmpdir:
        orch = Orquestador(workspace_dir=tmpdir)
        orch.publicar_tareas([SubagentTask(task_id="t1", prompt="p1")])
        orch.recogedor.escribir_respuesta("t1", "r1")
        assert orch.hay_tareas_pendientes()
        resultado = orch.aplicar_respuestas()
        # Tras aplicar, tareas y respuestas deben estar limpias
        assert not orch.hay_tareas_pendientes()
        assert not orch.hay_respuestas_listas()
        print(f"[OK] aplicar limpia tras aplicar: tareas y respuestas limpias")

    # Test 8: estado devuelve info correcta
    with tempfile.TemporaryDirectory() as tmpdir:
        orch = Orquestador(workspace_dir=tmpdir)
        estado = orch.estado()
        assert estado["tareas_pendientes"] == 0
        assert estado["respuestas_listas"] == 0
        assert not estado["listo_para_aplicar"]

        orch.publicar_tareas([SubagentTask(task_id="t1", prompt="p1")])
        estado = orch.estado()
        assert estado["tareas_pendientes"] == 1
        assert not estado["listo_para_aplicar"]  # hay tareas pendientes

        orch.recogedor.escribir_respuesta("t1", "r1")
        estado = orch.estado()
        assert estado["respuestas_listas"] == 1
        # listo_para_aplicar = respuestas > 0 AND tareas == 0
        # aquí hay 1 tarea pendiente, así que no está listo
        assert not estado["listo_para_aplicar"]
        print(f"[OK] estado: tareas={estado['tareas_pendientes']}, respuestas={estado['respuestas_listas']}")

    # Test 9: repr
    orch_repr = Orquestador(workspace_dir="/tmp/test_repr")
    assert "Orquestador" in repr(orch_repr)
    print(f"[OK] repr: {orch_repr!r}")

    print("\n[PASS] orquestador.py: todos los tests pasaron")
