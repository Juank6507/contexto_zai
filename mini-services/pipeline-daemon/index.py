# contexto_zai/mini-services/pipeline-daemon/index.py -- Daemon del pipeline contexto_zai: ejecuta pipeline.run() en background, escribe progreso en _daemon_status.json.
"""Daemon del pipeline contexto_zai (v6.17 F5, criterio 4 → v6.18 F5, criterio 5).

Proceso que corre el pipeline en background. Escribe progreso en
``_daemon_status.json`` (en el workspace_dir) con el formato:

    {
      "status": "running|idle|done",
      "total_bloques": 50,
      "completados": 23,
      "pendientes": 27,
      "tarea_actual": "bloque_24",
      "timestamp": 1234567890
    }

El agente CZAI lee ``_daemon_status.json`` antes de responder al Director
e incluye el estado en la frase de control.

Endpoints HTTP (puerto 8088):

- ``POST /pipeline-run``: arranca ``pipeline.run()`` en background.
  Body JSON: ``{"chat_id": "...", "chat_label": "...", "jwt": "..."}``.
  Respuesta: ``{"accepted": true, "task_id": "..."}``.

- ``POST /ampliar-contexto`` (v6.18 F5, criterio 5): arranca
  ``ampliar_contexto()`` en background. Body JSON:
  ``{"source_type": "file|url", "source_path": "...", "jwt": "...",
     "workspace_dir": "..."}``.

  Orquesta el flujo ampliar_contexto → RecoveryCycle (o
  ProcesadorDocumento) → collect_responses → cascada → P16+P17+P18+P19.

  - Si ``contexto_recuperacion/`` no existe: invoca ``ampliar_contexto()``
    que crea los bloques desde la fuente externa (estructura cronológica
    → RecoveryCycle con BlockPacker descendente; arbitraria →
    ProcesadorDocumento). El agente ejecuta subagentes, llama
    ``collect_responses()``, y luego re-invoca ``/ampliar-contexto``.

  - Si ``contexto_recuperacion/`` ya existe: ejecuta
    ``_auditar_y_completar()`` (cascada + P16+P17+P18+P19).

- ``GET /daemon-status``: lee ``_daemon_status.json`` del workspace.

- ``POST /recovery-cycle`` (v6.17 F6, criterio 5): arranca RecoveryCycle
  en background. Si ``contexto_recuperacion/`` no existe, lo crea desde lo
  que existe en ese chat. No usa ``ampliar_contexto`` modo INCREMENTAL.

El daemon desvincula el proceso del Bash tool con doble setsid y
sobrevive entre llamadas. Si el daemon no está haciendo nada, lo dice
(status=idle). Cuando termina, lo dice (status=done).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
# Soporta Estructura A (<workspace>/contexto_zai/) y Estructura B (workspace=contexto_zai/)
_here = os.path.dirname(os.path.abspath(__file__))
_candidate = _here
_package_root = None
for _ in range(10):
    if not os.path.isfile(os.path.join(_candidate, '__init__.py')):
        break  # salimos del paquete
    _parent = os.path.dirname(_candidate)
    if not os.path.isfile(os.path.join(_parent, '__init__.py')):
        _package_root = _candidate
        break
    _candidate = _parent
if _package_root:
    _workspace = os.path.dirname(_package_root)
    if _workspace not in sys.path:
        sys.path.insert(0, _workspace)
else:
    _parent = os.path.dirname(_here)
    if _parent not in sys.path:
        sys.path.insert(0, _parent)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("pipeline-daemon")

# Workspace por defecto (mismo que pipeline.py WORKSPACE_OUTPUT_DIR).
try:
    from contexto_zai.config import WORKSPACE_OUTPUT_DIR as _WS
    DEFAULT_WORKSPACE = Path(_WS)
except Exception:
    DEFAULT_WORKSPACE = Path("/home/z/my-project/contexto_recuperacion")

# Estado compartido del daemon.
_daemon_lock = threading.Lock()
_daemon_thread: threading.Thread | None = None
_daemon_task_id: str = ""
_daemon_started_at: float = 0.0


def escribir_status(
    workspace_dir: Path | str,
    status: str,
    total_bloques: int = 0,
    completados: int = 0,
    pendientes: int = 0,
    tarea_actual: str = "",
) -> None:
    """v6.17 F5 (criterio 4): escribe ``_daemon_status.json`` en el workspace.

    Args:
        workspace_dir: Directorio del workspace (donde viven los bloques).
        status: ``running``, ``idle`` o ``done``.
        total_bloques: Número total de bloques del workspace.
        completados: Número de bloques completos (4 artefactos).
        pendientes: Número de bloques pendientes.
        tarea_actual: ``block_id`` del bloque en proceso (o vacío si idle).
    """
    ws = Path(workspace_dir)
    try:
        ws.mkdir(parents=True, exist_ok=True)
        status_path = ws / "_daemon_status.json"
        payload = {
            "status": status,
            "total_bloques": total_bloques,
            "completados": completados,
            "pendientes": pendientes,
            "tarea_actual": tarea_actual,
            "timestamp": int(time.time()),
        }
        status_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info(
            "v6.17 F5: status=%s completados=%d/%d pendientes=%d tarea=%s",
            status, completados, total_bloques, pendientes, tarea_actual or "-",
        )
    except Exception as e:
        log.warning("v6.17 F5: escribir_status falló: %s", e)


def leer_status(workspace_dir: Path | str) -> dict:
    """Lee ``_daemon_status.json`` del workspace. Devuelve dict vacío si no existe."""
    ws = Path(workspace_dir)
    status_path = ws / "_daemon_status.json"
    if not status_path.exists():
        return {"status": "idle", "total_bloques": 0, "completados": 0,
                "pendientes": 0, "tarea_actual": "", "timestamp": 0}
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "idle", "total_bloques": 0, "completados": 0,
                "pendientes": 0, "tarea_actual": "", "timestamp": 0}


def _contar_bloques(workspace_dir: Path | str) -> tuple[int, int, int]:
    """Cuenta (total, completados, pendientes) del workspace."""
    try:
        from contexto_zai.pipeline import EnriquecimientoOrquestador
        incompletos = EnriquecimientoOrquestador._descubrir_bloques_incompletos(workspace_dir)
        ws = Path(workspace_dir)
        total = len(list(ws.glob("bloque_*.md"))) if ws.exists() else 0
        pendientes = len(incompletos)
        completados = max(0, total - pendientes)
        return total, completados, pendientes
    except Exception as e:
        log.warning("v6.17 F5: _contar_bloques falló: %s", e)
        return 0, 0, 0


def _run_pipeline_in_background(
    chat_id: str,
    jwt: str,
    chat_label: str,
    workspace_dir: Path | str,
    task_id: str,
) -> None:
    """Hilo que ejecuta ``pipeline.run()`` en background y actualiza el status.

    v6.18 F3 (criterio 3): si ``contexto_recuperacion/`` no existe, P2
    (auditoría inicial + completar) NO se realiza. El daemon va directo a
    ejecutar ``pipeline.run()`` completo. Si existe, se llama
    ``_auditar_y_completar()`` (P2 = auditar + completar lo faltante).
    """
    global _daemon_thread, _daemon_task_id
    try:
        log.info("v6.17 F5: arrancando pipeline.run() (task_id=%s)", task_id)
        # Status inicial: running, sin tarea_actual todavía.
        total, compl, pend = _contar_bloques(workspace_dir)
        escribir_status(workspace_dir, "running", total, compl, pend, "")
        # Importar aquí para que el daemon arranque rápido.
        from contexto_zai.models import DetectionTrigger
        from contexto_zai.pipeline import run
        # v6.18 F3 (criterio 3): si contexto_recuperacion/ no existe, P2
        # no se realiza. El daemon NO llama _auditar_y_completar ni
        # AuditorWorkspace.auditar_completitud — va directo a procesar la
        # fuente. Si existe, se realiza P2 normalmente.
        ws = Path(workspace_dir)
        if ws.exists() and any(ws.glob("bloque_*.md")):
            log.info("v6.18 F3: contexto_recuperacion existe — P2 (auditar + completar)")
            # F7: usar la función única _auditar_y_completar que reutiliza F1.
            from contexto_zai.pipeline import EnriquecimientoOrquestador
            result_audit = EnriquecimientoOrquestador._auditar_y_completar(workspace_dir)
            log.info(
                "v6.17 F7: auditoría+completar terminó — incompletos_iniciales=%d, "
                "pending_tasks=%d, contexto_existia=%s",
                result_audit.get("incompletos_iniciales", 0),
                result_audit.get("pending_tasks", 0),
                result_audit.get("contexto_existia", False),
            )
        else:
            # Ejecutar el pipeline completo.
            result = run(
                chat_id=chat_id,
                jwt=jwt,
                trigger=DetectionTrigger.EXPLICITO,
                reason="pipeline-daemon (v6.17 F5)",
                chat_label=chat_label or "daemon",
                workspace_dir=workspace_dir,
            )
            log.info("v6.17 F5: pipeline.run() terminó success=%s", result.success)
        # Status final: done.
        total, compl, pend = _contar_bloques(workspace_dir)
        escribir_status(workspace_dir, "done", total, compl, pend, "")
    except Exception as e:
        log.error("v6.17 F5: excepción en hilo del daemon: %s", e)
        log.error("Traceback:\n%s", traceback.format_exc())
        escribir_status(workspace_dir, "done", 0, 0, 0, "")
    finally:
        with _daemon_lock:
            _daemon_thread = None
            _daemon_task_id = ""


def _run_recovery_cycle_in_background(
    chat_id: str,
    jwt: str,
    workspace_dir: Path | str,
    task_id: str,
) -> None:
    """v6.17 F6 (criterio 5): hilo que ejecuta RecoveryCycle en background.

    Si ``contexto_recuperacion/`` no existe, lo crea desde lo que existe en
    ese chat. No usa ``ampliar_contexto`` modo INCREMENTAL.

    v6.18 F3 (criterio 3): si ``contexto_recuperacion/`` no existe, P2
    (auditoría inicial) NO se realiza — el daemon va directo a crear el
    contexto con ``RecoveryCycle.run()``. Si existe, se llama
    ``_auditar_y_completar()`` (P2 = auditar + completar lo faltante).
    """
    global _daemon_thread, _daemon_task_id
    try:
        log.info("v6.17 F6: arrancando RecoveryCycle (task_id=%s)", task_id)
        total, compl, pend = _contar_bloques(workspace_dir)
        escribir_status(workspace_dir, "running", total, compl, pend, "")
        ws = Path(workspace_dir)
        # v6.18 F3 (criterio 3): si contexto_recuperacion/ no existe, P2
        # no se realiza — el daemon NO llama _auditar_y_completar ni
        # AuditorWorkspace.auditar_completitud. Va directo a crear el
        # contexto con RecoveryCycle.run().
        if not ws.exists() or not any(ws.glob("bloque_*.md")):
            # contexto_recuperacion no existe — crear desde el chat.
            log.info("v6.17 F6: contexto_recuperacion no existe — creando desde el chat")
            from contexto_zai.process.recovery_cycle import RecoveryCycle
            cycle = RecoveryCycle(
                jwt=jwt,
                chat_id=chat_id,
                workspace_dir=workspace_dir,
            )
            result = cycle.run()
            log.info("v6.17 F6: RecoveryCycle terminó success=%s", result.success)
        else:
            # Ya existe — solo auditar y completar (F7).
            log.info("v6.17 F6+F7: contexto_recuperacion existe — solo auditar + completar")
            from contexto_zai.pipeline import EnriquecimientoOrquestador
            result_audit = EnriquecimientoOrquestador._auditar_y_completar(workspace_dir)
            log.info(
                "v6.17 F6+F7: auditoría+completar terminó — incompletos_iniciales=%d, "
                "pending_tasks=%d",
                result_audit.get("incompletos_iniciales", 0),
                result_audit.get("pending_tasks", 0),
            )
        total, compl, pend = _contar_bloques(workspace_dir)
        escribir_status(workspace_dir, "done", total, compl, pend, "")
    except Exception as e:
        log.error("v6.17 F6: excepción en hilo RecoveryCycle: %s", e)
        log.error("Traceback:\n%s", traceback.format_exc())
        escribir_status(workspace_dir, "done", 0, 0, 0, "")
    finally:
        with _daemon_lock:
            _daemon_thread = None
            _daemon_task_id = ""


def _run_ampliar_contexto_in_background(
    source_type: str,
    source_path: str,
    jwt: str,
    workspace_dir: Path | str,
    task_id: str,
) -> None:
    """v6.18 F5 (criterio 5): hilo que ejecuta ``ampliar_contexto()`` en background.

    Orquesta el flujo ampliar_contexto → RecoveryCycle (o ProcesadorDocumento)
    → collect_responses → cascada → P16+P17+P18+P19.

    Si ``contexto_recuperacion/`` ya existe, el daemon solo audita y completa
    (F3 de v6.17 — _auditar_y_completar) que ejecuta P2 + cascada +
    P16+P17+P18+P19 en una sola pasada. Esto cubre el caso en que el
    agente ya ejecutó los subagentes y llamó ``collect_responses()``
    — el daemon entra por la rama "existe" y dispara cascada + P16-P19.

    Si ``contexto_recuperacion/`` no existe, el daemon invoca
    ``ampliar_contexto()``:

    - Si estructura="cronologica": pasa por RecoveryCycle (F1) que construye
      intercambios, clasifica, BlockPacker ordena descendente, genera
      bloques + archivos 00-03.
    - Si estructura="arbitrario": pasa por ProcesadorDocumento que
      divide en lotes y publica pending_tasks.

    El hilo termina tras generar los bloques y publicar las pending_tasks.
    El agente CZAI ejecuta los subagentes, llama ``collect_responses()``
    (que integra respuestas), y luego invoca nuevamente
    ``POST /ampliar-contexto`` (o ``/recovery-cycle``) — en esa segunda
    invocación el daemon ve contexto_recuperacion existe y ejecuta
    _auditar_y_completar (cascada + P16+P17+P18+P19).

    v6.18 F3 (criterio 3): si contexto_recuperacion/ no existe, P2
    (auditoría inicial) NO se realiza.
    """
    global _daemon_thread, _daemon_task_id
    try:
        log.info(
            "v6.18 F5: arrancando ampliar_contexto (task_id=%s, source_type=%s)",
            task_id, source_type,
        )
        total, compl, pend = _contar_bloques(workspace_dir)
        escribir_status(workspace_dir, "running", total, compl, pend, "")
        ws = Path(workspace_dir)
        # v6.18 F3 (criterio 3): si contexto_recuperacion/ no existe, P2
        # no se realiza — el daemon NO llama _auditar_y_completar ni
        # AuditorWorkspace.auditar_completitud. Va directo a ampliar_contexto.
        if ws.exists() and any(ws.glob("bloque_*.md")):
            # contexto_recuperacion ya existe — F3 de v6.17: solo auditar
            # + completar. Esto cubre la segunda invocación del agente
            # (tras ejecutar subagentes y collect_responses) — el daemon
            # entra aquí y dispara cascada + P16+P17+P18+P19.
            log.info(
                "v6.18 F5: contexto_recuperacion existe — auditando + completando "
                "(cascada + P16+P17+P18+P19)"
            )
            from contexto_zai.pipeline import EnriquecimientoOrquestador
            result_audit = EnriquecimientoOrquestador._auditar_y_completar(workspace_dir)
            log.info(
                "v6.18 F5: auditoría+completar terminó — incompletos_iniciales=%d, "
                "pending_tasks=%d, contexto_existia=%s",
                result_audit.get("incompletos_iniciales", 0),
                result_audit.get("pending_tasks", 0),
                result_audit.get("contexto_existia", False),
            )
        else:
            # contexto_recuperacion no existe — ampliar_contexto crea los
            # bloques desde la fuente externa.
            log.info(
                "v6.18 F5: contexto_recuperacion no existe — invocando ampliar_contexto "
                "(estructura cronológica → RecoveryCycle; arbitraria → ProcesadorDocumento)"
            )
            from contexto_zai.pipeline import ampliar_contexto
            result = ampliar_contexto(
                source_type=source_type,
                source_path=source_path,
                jwt=jwt,
                workspace_dir=workspace_dir,
            )
            if "error" in result:
                log.error("v6.18 F5: ampliar_contexto falló: %s", result["error"])
            else:
                log.info(
                    "v6.18 F5: ampliar_contexto terminó — indexed=%s, estructura=%s, "
                    "flujo=%s, %d pending_tasks (el agente debe ejecutar subagentes, "
                    "llamar collect_responses(), y luego re-invocar /ampliar-contexto "
                    "para cascada + P16+P17+P18+P19)",
                    result.get("indexed", False),
                    result.get("estructura", ""),
                    result.get("flujo", ""),
                    len(result.get("pending_tasks", [])),
                )
        total, compl, pend = _contar_bloques(workspace_dir)
        escribir_status(workspace_dir, "done", total, compl, pend, "")
    except Exception as e:
        log.error("v6.18 F5: excepción en hilo ampliar_contexto: %s", e)
        log.error("Traceback:\n%s", traceback.format_exc())
        escribir_status(workspace_dir, "done", 0, 0, 0, "")
    finally:
        with _daemon_lock:
            _daemon_thread = None
            _daemon_task_id = ""


class DaemonHandler(BaseHTTPRequestHandler):
    """HTTP handler del daemon."""

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/daemon-status":
            payload = leer_status(DEFAULT_WORKSPACE)
            self._send_json(200, payload)
            return
        if parsed.path == "/health":
            self._send_json(200, {"ok": True, "service": "pipeline-daemon"})
            return
        self._send_json(404, {"error": f"unknown path {parsed.path}"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body_str = self.rfile.read(length).decode("utf-8") if length else "{}"
            body = json.loads(body_str) if body_str else {}
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON body: {e}"})
            return

        if parsed.path == "/pipeline-run":
            self._arrancar_tarea(body, kind="pipeline-run")
            return
        if parsed.path == "/ampliar-contexto":
            self._arrancar_tarea(body, kind="ampliar-contexto")
            return
        if parsed.path == "/recovery-cycle":
            self._arrancar_tarea(body, kind="recovery-cycle")
            return
        self._send_json(404, {"error": f"unknown path {parsed.path}"})

    def _arrancar_tarea(self, body: dict, kind: str) -> None:
        global _daemon_thread, _daemon_task_id
        with _daemon_lock:
            if _daemon_thread is not None and _daemon_thread.is_alive():
                self._send_json(409, {
                    "error": "daemon ya está corriendo otra tarea",
                    "task_id": _daemon_task_id,
                })
                return
            task_id = f"{kind}_{int(time.time() * 1000)}"
            _daemon_task_id = task_id
            _daemon_started_at = time.time()
        chat_id = body.get("chat_id", "")
        jwt = body.get("jwt", "")
        chat_label = body.get("chat_label", "daemon")
        workspace_dir = body.get("workspace_dir", str(DEFAULT_WORKSPACE))
        # v6.18 F5: parámetros específicos de ampliar-contexto.
        source_type = body.get("source_type", "file")
        source_path = body.get("source_path", "")
        # Estado inicial.
        escribir_status(workspace_dir, "running", 0, 0, 0, "")
        if kind == "pipeline-run":
            t = threading.Thread(
                target=_run_pipeline_in_background,
                args=(chat_id, jwt, chat_label, workspace_dir, task_id),
                daemon=True,
            )
        elif kind == "recovery-cycle":
            t = threading.Thread(
                target=_run_recovery_cycle_in_background,
                args=(chat_id, jwt, workspace_dir, task_id),
                daemon=True,
            )
        elif kind == "ampliar-contexto":
            # v6.18 F5 (criterio 5): validación mínima de parámetros.
            if not source_path:
                self._send_json(400, {
                    "error": "ampliar-contexto requiere 'source_path' en el body.",
                })
                # Restaurar estado idle porque no arrancamos hilo.
                with _daemon_lock:
                    _daemon_task_id = ""
                escribir_status(workspace_dir, "idle", 0, 0, 0, "")
                return
            t = threading.Thread(
                target=_run_ampliar_contexto_in_background,
                args=(source_type, source_path, jwt, workspace_dir, task_id),
                daemon=True,
            )
        else:
            self._send_json(501, {"error": f"kind {kind} no implementado en daemon"})
            return
        with _daemon_lock:
            _daemon_thread = t
        t.start()
        self._send_json(202, {"accepted": True, "task_id": task_id, "kind": kind})

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        log.info("HTTP %s - %s", self.address_string(), fmt % args)


def main() -> int:
    port = int(os.environ.get("PIPELINE_DAEMON_PORT", "8088"))
    host = os.environ.get("PIPELINE_DAEMON_HOST", "127.0.0.1")
    # Status inicial: idle.
    escribir_status(DEFAULT_WORKSPACE, "idle", 0, 0, 0, "")
    server = ThreadingHTTPServer((host, port), DaemonHandler)
    log.info("v6.17 F5: pipeline-daemon escuchando en http://%s:%d", host, port)
    log.info("v6.17 F5: workspace por defecto: %s", DEFAULT_WORKSPACE)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("v6.17 F5: interrumpido por señal — cerrando")
        escribir_status(DEFAULT_WORKSPACE, "idle", 0, 0, 0, "")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
