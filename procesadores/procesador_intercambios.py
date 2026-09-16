# contexto_zai/procesadores/procesador_intercambios.py -- ProcesadorIntercambios: procesa intercambios del chat (D4, A1, decisiones, nombres, clasificación).
"""ProcesadorIntercambios (v4.2).

Procesa intercambios del chat para las mejoras semánticas:
- D4 (restricciones del Director).
- A1 truncado (resumen del contenido truncado).
- Decisiones reales (con alcance).
- Nombres legibles (para subtemas).
- Clasificación de temas (no regex).

Construye el prompt con ``IntercambiosClasificadorSubagent.build_prompt()``
(sin llamar ``sub.run()``), lo publica como ``SubagentTask`` vía el
``Orquestador``, y devuelve el resultado estructurado al proceso.

Reutiliza:
- ``ClasificadorSubagent`` (H1) como clase base.
- Los modos del ``IntercambiosClasificadorSubagent``.

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
    CLASIFICADOR_MAX_CONTEXT_TOKENS,
    DECISIONES_LOTE_SIZE,
    ESTADO_TRUNCADO_RESUMEN_TOKENS,
    SUBDIVIDER_NAMER_MAX_CONTEXT_TOKENS,
    WORKSPACE_OUTPUT_DIR,
)
from contexto_zai.models import SubagentTask

logger = logging.getLogger(__name__)

# Modos soportados (deben coincidir con ModoClasificador)
MODOS_VALIDOS = {
    "RESTRICCIONES_TEMA",    # D4: interpretar restricciones del Director
    "RESUMEN_TRUNCADO",      # A1: resumir contenido truncado
    "DECISIONES",            # Decisiones reales con alcance
    "NOMBRE_LEGIBLE",        # Subdivider: nombres legibles
    "CLASIFICACION_TEMAS",   # Clasificar intercambios por tema real
    "CONSULTA_BLOQUE",       # Consultar bloques (lo usa ProcesadorConsulta)
    "SINTESIS_CONTEXTO",     # v4.3: sintetizar panorama del proyecto (G0.B)
}


class ProcesadorIntercambios:
    """Procesa intercambios del chat para mejoras semánticas.

    Attributes:
        workspace_dir: Directorio del workspace.
        orquestador: Orquestador para coordinar subagentes.

    Usage (proceso):
        >>> from contexto_zai.procesadores import ProcesadorIntercambios
        >>> proc = ProcesadorIntercambios(workspace_dir="/path/to/ws", orquestador=orch)
        >>> result = proc.procesar(modo="RESTRICCIONES_TEMA", intercambios=exchanges)
        >>> if result.get("pending_tasks"):
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
        logger.debug("ProcesadorIntercambios inicializado: %s", self._workspace_dir)

    @property
    def workspace_dir(self) -> Path:
        return self._workspace_dir

    # -- API pública ------------------------------------------------

    def procesar(
        self,
        modo: str,
        intercambios: list,
        context: Optional[dict] = None,
        task_id_suffix: str = "",
    ) -> dict:
        """Procesa intercambios en un modo específico.

        Construye el prompt con ``IntercambiosClasificadorSubagent.build_prompt()``
        (sin llamar ``sub.run()``), lo publica como ``SubagentTask`` vía el
        ``Orquestador``, y devuelve info sobre la tarea publicada.

        Args:
            modo: Uno de MODOS_VALIDOS (RESTRICCIONES_TEMA, RESUMEN_TRUNCADO, etc.).
            intercambios: Lista de intercambios a procesar.
            context: Contexto adicional (ej: tema_actual, lote_idx).
            task_id_suffix: Sufijo para el task_id (ej: lote_0, lote_1).

        Returns:
            Dict con:
            - "pending_tasks": lista de SubagentTask publicadas.
            - "modo": el modo usado.
            - "total_intercambios": número de intercambios procesados.
            - "error": mensaje de error si falló.
        """
        if modo not in MODOS_VALIDOS:
            return {"error": f"Modo no válido: {modo}. Válidos: {MODOS_VALIDOS}"}

        if not intercambios:
            return {
                "pending_tasks": [],
                "modo": modo,
                "total_intercambios": 0,
            }

        context = context or {}

        # Construir el task_id
        task_id = f"intercambios_{modo.lower()}"
        if task_id_suffix:
            task_id = f"{task_id}_{task_id_suffix}"

        # F4 v4.2: construir el prompt real con IntercambiosClasificadorSubagent.build_prompt()
        prompt = self._build_real_prompt(modo, intercambios, context)
        if prompt is None:
            return {
                "pending_tasks": [],
                "modo": modo,
                "total_intercambios": len(intercambios),
                "error": "No se pudo construir el prompt",
            }

        task = SubagentTask(
            task_id=task_id,
            purpose=f"intercambios.{modo.lower()}",
            prompt=prompt,
            context={
                "modo": modo,
                "total_intercambios": len(intercambios),
                **context,
            },
        )

        # Publicar la tarea vía el Orquestador
        if self._orquestador is not None:
            self._orquestador.publicar_tareas([task])

        return {
            "pending_tasks": [task],
            "modo": modo,
            "total_intercambios": len(intercambios),
        }

    def procesar_por_lotes(
        self,
        modo: str,
        intercambios: list,
        lote_size: int = DECISIONES_LOTE_SIZE,
        context: Optional[dict] = None,
    ) -> dict:
        """Procesa intercambios en lotes (para decisiones y clasificación).

        Args:
            modo: Modo de procesamiento (DECISIONES o CLASIFICACION_TEMAS).
            intercambios: Lista de intercambios.
            lote_size: Tamaño del lote (default: DECISIONES_LOTE_SIZE).
            context: Contexto adicional.

        Returns:
            Dict con pending_tasks (una por lote).
        """
        if modo not in {"DECISIONES", "CLASIFICACION_TEMAS"}:
            return {"error": f"procesar_por_lotes solo soporta DECISIONES y CLASIFICACION_TEMAS, got: {modo}"}

        tasks: list[SubagentTask] = []
        lote_idx = 0
        for i in range(0, len(intercambios), lote_size):
            lote = intercambios[i:i + lote_size]
            if not lote:
                continue
            result = self.procesar(
                modo=modo,
                intercambios=lote,
                context=context,
                task_id_suffix=f"lote_{lote_idx}",
            )
            if "pending_tasks" in result:
                tasks.extend(result["pending_tasks"])
            lote_idx += 1

        return {
            "pending_tasks": tasks,
            "modo": modo,
            "total_intercambios": len(intercambios),
            "total_lotes": lote_idx,
        }

    # -- Métodos privados -------------------------------------------

    def _build_real_prompt(self, modo: str, intercambios: list, context: dict) -> Optional[str]:
        """F4 v4.2: Construye el prompt real usando IntercambiosClasificadorSubagent.

        Reutiliza el código existente (ClasificadorSubagent + IntercambiosClasificadorSubagent)
        para construir el prompt según el modo. No ejecuta sub.run() — solo construye el prompt.
        """
        try:
            from contexto_zai.subagents.intercambios_clasificador_subagent import (
                IntercambiosClasificadorSubagent,
                ModoClasificador,
            )
            from contexto_zai.subagents.launcher import SubagentLauncher

            # Mapear string del modo a ModoClasificador enum
            modo_map = {
                "RESTRICCIONES_TEMA": ModoClasificador.RESTRICCIONES_TEMA,
                "RESUMEN_TRUNCADO": ModoClasificador.RESUMEN_TRUNCADO,
                "DECISIONES": ModoClasificador.DECISIONES,
                "NOMBRE_LEGIBLE": ModoClasificador.NOMBRE_LEGIBLE,
                "CLASIFICACION_TEMAS": ModoClasificador.CLASIFICACION_TEMAS,
                "SINTESIS_CONTEXTO": ModoClasificador.SINTESIS_CONTEXTO,
                "CONSULTA_BLOQUE": ModoClasificador.CONSULTA_BLOQUE,
            }
            modo_enum = modo_map.get(modo)
            if modo_enum is None:
                logger.warning("Modo no mapeable: %s", modo)
                return None

            # Crear un launcher dummy (no se usa para build_prompt, solo para el constructor)
            dummy_launcher = SubagentLauncher(task_invoker=lambda p: "")

            # Configurar max_context_tokens según el modo
            max_context = CLASIFICADOR_MAX_CONTEXT_TOKENS
            if modo == "RESUMEN_TRUNCADO":
                max_context = ESTADO_TRUNCADO_RESUMEN_TOKENS
            elif modo == "NOMBRE_LEGIBLE":
                max_context = SUBDIVIDER_NAMER_MAX_CONTEXT_TOKENS

            # Para CLASIFICACION_TEMAS, el tema_padre se pasa vía 'pregunta'
            # (convención reutilizada del modo CONSULTA_BLOQUE) para que
            # _prompt_clasificacion_temas pueda incluirlo en el prompt.
            # v4.3: para SINTESIS_CONTEXTO, el contexto adicional (objetivo +
            # índice + decisiones) se pasa vía 'pregunta' también.
            if modo == "CLASIFICACION_TEMAS":
                pregunta = context.get("tema_padre")
            elif modo == "SINTESIS_CONTEXTO":
                # El contexto adicional se pasa vía context["contexto_adicional"]
                pregunta = context.get("contexto_adicional")
            else:
                pregunta = None

            sub = IntercambiosClasificadorSubagent(
                launcher=dummy_launcher,
                modo=modo_enum,
                max_context_tokens=max_context,
                pregunta=pregunta,
            )

            # Para RESUMEN_TRUNCADO, los intercambios pueden ser un exchange sintético
            # con el contenido truncado en el mensaje del Director.
            prompt, _files, _recortado = sub.build_prompt(intercambios)
            return prompt

        except Exception as e:
            logger.warning("Error construyendo prompt real para modo %s: %s", modo, e)
            return None

    def __repr__(self) -> str:
        return f"ProcesadorIntercambios(workspace_dir={self._workspace_dir!r})"


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

    print("=== Validacion de procesador_intercambios.py ===\n")

    import tempfile
    from contexto_zai.models import Message, MessageRole, Exchange

    # Crear intercambios de prueba
    def make_exchanges(n=3):
        return [
            Exchange(
                id=i,
                director_msg=Message(seq=i*2-1, role=MessageRole.USER, timestamp=float(i),
                                     content=f"Director msg {i}"),
                agent_msgs=[Message(seq=i*2, role=MessageRole.ASSISTANT, timestamp=float(i)+0.5,
                                    content=f"Agent reply {i}")],
                topic="general",
                start_timestamp=float(i),
                end_timestamp=float(i)+1,
            )
            for i in range(1, n+1)
        ]

    # Test 1: procesar en modo RESTRICCIONES_TEMA
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorIntercambios(workspace_dir=tmpdir)
        result = proc.procesar(modo="RESTRICCIONES_TEMA", intercambios=make_exchanges())
        assert result["modo"] == "RESTRICCIONES_TEMA"
        assert result["total_intercambios"] == 3
        assert len(result["pending_tasks"]) == 1
        assert result["pending_tasks"][0].purpose == "intercambios.restricciones_tema"
        print(f"[OK] RESTRICCIONES_TEMA: {len(result['pending_tasks'])} tarea")

    # Test 2: procesar en modo DECISIONES
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorIntercambios(workspace_dir=tmpdir)
        result = proc.procesar(modo="DECISIONES", intercambios=make_exchanges())
        assert result["modo"] == "DECISIONES"
        assert len(result["pending_tasks"]) == 1
        print(f"[OK] DECISIONES: {len(result['pending_tasks'])} tarea")

    # Test 3: modo inválido devuelve error
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorIntercambios(workspace_dir=tmpdir)
        result = proc.procesar(modo="MODO_INVALIDO", intercambios=make_exchanges())
        assert "error" in result
        print(f"[OK] modo inválido: error reportado")

    # Test 4: lista vacía devuelve vacío
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorIntercambios(workspace_dir=tmpdir)
        result = proc.procesar(modo="RESTRICCIONES_TEMA", intercambios=[])
        assert result["total_intercambios"] == 0
        assert len(result["pending_tasks"]) == 0
        print(f"[OK] lista vacía: 0 tareas")

    # Test 5: procesar_por_lotes
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorIntercambios(workspace_dir=tmpdir)
        exchanges = make_exchanges(6)
        result = proc.procesar_por_lotes(modo="DECISIONES", intercambios=exchanges, lote_size=2)
        assert result["total_intercambios"] == 6
        assert result["total_lotes"] == 3
        assert len(result["pending_tasks"]) == 3
        print(f"[OK] por lotes: 6 intercambios → {result['total_lotes']} lotes, {len(result['pending_tasks'])} tareas")

    # Test 6: con orquestador, publica tareas
    with tempfile.TemporaryDirectory() as tmpdir:
        from contexto_zai.coordinador import Orquestador
        orch = Orquestador(workspace_dir=tmpdir)
        proc = ProcesadorIntercambios(workspace_dir=tmpdir, orquestador=orch)
        proc.procesar(modo="NOMBRE_LEGIBLE", intercambios=make_exchanges())
        assert orch.hay_tareas_pendientes()
        tareas = orch.leer_tareas_pendientes()
        assert len(tareas) == 1
        assert tareas[0].purpose == "intercambios.nombre_legible"
        print(f"[OK] con orquestador: publica {len(tareas)} tarea(s)")

    # Test 7: procesar_por_lotes con modo no soportado devuelve error
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorIntercambios(workspace_dir=tmpdir)
        result = proc.procesar_por_lotes(modo="RESTRICCIONES_TEMA", intercambios=make_exchanges())
        assert "error" in result
        print(f"[OK] por lotes con modo no soportado: error")

    # Test 8: task_id_suffix se aplica
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorIntercambios(workspace_dir=tmpdir)
        result = proc.procesar(
            modo="DECISIONES",
            intercambios=make_exchanges(),
            task_id_suffix="lote_5",
        )
        assert "lote_5" in result["pending_tasks"][0].task_id
        print(f"[OK] task_id_suffix: {result['pending_tasks'][0].task_id}")

    # Test 9: repr
    proc_repr = ProcesadorIntercambios(workspace_dir="/tmp/test_repr")
    assert "ProcesadorIntercambios" in repr(proc_repr)
    print(f"[OK] repr: {proc_repr!r}")

    # Test 10 (F4 v4.2): CLASIFICACION_TEMAS construye prompt correcto (no alias de RESTRICCIONES)
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorIntercambios(workspace_dir=tmpdir)
        result = proc.procesar(
            modo="CLASIFICACION_TEMAS",
            intercambios=make_exchanges(4),
            context={"tema_padre": "validaciones"},
            task_id_suffix="capa3_validaciones",
        )
        assert result["modo"] == "CLASIFICACION_TEMAS"
        assert result["total_intercambios"] == 4
        assert len(result["pending_tasks"]) == 1
        task = result["pending_tasks"][0]
        assert task.purpose == "intercambios.clasificacion_temas"
        assert "capa3_validaciones" in task.task_id
        # El prompt debe ser el de CLASIFICACION_TEMAS, no el de RESTRICCIONES_TEMA
        assert "SUBTEMA:" in task.prompt
        assert "EXCHANGES:" in task.prompt
        assert "validaciones" in task.prompt
        assert "RESTRICCION:" not in task.prompt, "El prompt NO debe ser el de RESTRICCIONES_TEMA"
        print(f"[OK] CLASIFICACION_TEMAS: prompt correcto (no alias), task_id={task.task_id}")

    print("\n[PASS] procesador_intercambios.py: todos los tests pasaron")
