# /home/z/my-project/mini-services/pipeline-daemon/index.py
"""Mini-servicio daemon del proceso contexto_zai (puerto 8088).

v6.14 F5 (criterios 20, 21): daemon siempre corriendo que expone la API
pública del proceso contexto_zai. El agente CZAI no escribe scripts
``runner_*.py`` para invocar el proceso — usa esta API pública.

Endpoints
---------
- ``POST /ampliar-contexto`` → invoca ``ampliar_contexto(source_type, source_path, jwt, metadata)``.
  Body JSON: ``{source_type, source_path, jwt?, metadata?}``.
- ``POST /pipeline-run`` → invoca ``pipeline.run(chat_id, jwt, reason, chat_label)``.
  Body JSON: ``{chat_id, jwt, reason?, chat_label?}``.
- ``GET /pending-tasks`` → lee ``_pending_tasks.json`` del workspace y lo devuelve.
- ``GET /status`` → lee ``_processed_blocks.json`` y devuelve conteos de completed/pending.
- ``GET /health`` → devuelve ``{"status": "ok"}``.

Errores
-------
Los errores se devuelven como JSON ``{"error": "..."}`` con el status code apropiado:
- 400 Bad Request: body inválido o faltan campos obligatorios.
- 404 Not Found: endpoint desconocido.
- 405 Method Not Allowed: método no permitido para el endpoint.
- 500 Internal Server Error: excepción en la lógica del proceso.

El daemon se lanza con doble setsid (patrón ``_launch.sh``) para sobrevivir
entre llamadas del Bash tool. Ver ``mini-services/_launch.sh``.
"""
from __future__ import annotations

import json
import logging
import signal
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

# Asegurar que el paquete contexto_zai sea importable.
sys.path.insert(0, "/home/z/my-project")

from contexto_zai.config import WORKSPACE_OUTPUT_DIR


PORT = 8088
WORKSPACE_DIR = WORKSPACE_OUTPUT_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("pipeline-daemon")


class PipelineDaemonServer:
    """Mini HTTP server que expone la API pública del proceso contexto_zai.

    Args:
        port: Puerto del servidor (default 8088).
        workspace_dir: Directorio del workspace donde viven _pending_tasks.json
            y _processed_blocks.json.

    Usage:
        >>> server = PipelineDaemonServer(port=8088)
        >>> server.start()
        >>> # El agente CZAI hace POST /ampliar-contexto
        >>> server.stop()
    """

    def __init__(self, port: int = PORT, workspace_dir: Path | str = WORKSPACE_DIR) -> None:
        self._port = port
        self._workspace_dir = Path(workspace_dir)
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        log.debug("PipelineDaemonServer inicializado: port=%d workspace=%s", port, self._workspace_dir)

    @property
    def workspace_dir(self) -> Path:
        return self._workspace_dir

    def start(self) -> None:
        """Levanta el servidor HTTP en un thread daemon."""
        if self._server is not None:
            return

        server_self = self

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, data, status=200):
                body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json_body(self) -> dict:
                length = int(self.headers.get("Content-Length", "0") or "0")
                if length == 0:
                    return {}
                try:
                    raw = self.rfile.read(length).decode("utf-8")
                    return json.loads(raw) if raw.strip() else {}
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    raise ValueError(f"body JSON inválido: {e}")

            def do_GET(self):
                if self.path == "/health":
                    self._send_json({"status": "ok", "service": "pipeline-daemon", "port": server_self._port})
                    return
                if self.path == "/pending-tasks":
                    self._send_json(server_self._read_pending_tasks())
                    return
                if self.path == "/status":
                    self._send_json(server_self._read_status())
                    return
                # 404
                self._send_json({"error": f"endpoint desconocido: {self.path}"}, status=404)

            def do_POST(self):
                try:
                    body = self._read_json_body()
                except ValueError as e:
                    self._send_json({"error": str(e)}, status=400)
                    return

                if self.path == "/ampliar-contexto":
                    self._send_json(server_self._handle_ampliar_contexto(body))
                    return
                if self.path == "/pipeline-run":
                    self._send_json(server_self._handle_pipeline_run(body))
                    return
                # v6.19 F6 (autonomía del agente CZAI): endpoint para integrar
                # respuestas de subagentes y finalizar el pipeline (P16-P19).
                if self.path == "/collect-responses":
                    self._send_json(server_self._handle_collect_responses(body))
                    return
                # v6.20 F5: endpoint para generar archivos de recuperación
                if self.path == "/generar-archivos":
                    self._send_json(server_self._handle_generar_archivos(body))
                    return
                # 404
                self._send_json({"error": f"endpoint desconocido: {self.path}"}, status=404)

            def do_OPTIONS(self):
                # CORS preflight
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def log_message(self, format, *args):
                # http.server loguea a stderr por defecto; lo redirigimos a nuestro logger.
                log.info("%s - %s", self.address_string(), format % args)

        self._server = HTTPServer(("0.0.0.0", self._port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        log.info("PipelineDaemonServer escuchando en puerto %d (workspace=%s)", self._port, self._workspace_dir)

    def stop(self) -> None:
        """Detiene el servidor HTTP."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        log.info("PipelineDaemonServer detenido.")

    # -- Handlers de endpoints -------------------------------------

    def _handle_ampliar_contexto(self, body: dict) -> dict:
        """POST /ampliar-contexto → invoca ampliar_contexto().

        v6.19 F1: chat_id del chat actual.
        v6.20 F6: force_rebuild + workspace_dir aceptados del body.
        v6.20 F7: force_rebuild para autorizar regeneración cuando el hash cambió.
        """
        source_type = body.get("source_type")
        source_path = body.get("source_path")
        if not source_type or not source_path:
            return {"error": "faltan campos obligatorios: source_type, source_path"}
        jwt = body.get("jwt", "")
        metadata = body.get("metadata")
        # v6.19 F1 (P1/P5): chat_id del chat actual.
        chat_id = body.get("chat_id", "") or ""
        if not chat_id and isinstance(metadata, dict):
            chat_id = metadata.get("chat_id", "") or ""
        # v6.20 F6: workspace_dir + force_rebuild
        workspace_dir = body.get("workspace_dir", "")
        force_rebuild = body.get("force_rebuild", False)
        try:
            from contexto_zai.pipeline import ampliar_contexto
            kwargs = {
                "source_type": source_type,
                "source_path": source_path,
                "jwt": jwt,
                "metadata": metadata,
                "chat_id": chat_id,
                "force_rebuild": force_rebuild,
            }
            if workspace_dir:
                kwargs["workspace_dir"] = workspace_dir
            result = ampliar_contexto(**kwargs)
            if not isinstance(result, dict):
                return {"error": "resultado inesperado (no es dict)", "raw": str(result)}
            return result
        except Exception as e:
            log.exception("ampliar_contexto falló")
            return {"error": f"ampliar_contexto falló: {e}"}

    def _handle_collect_responses(self, body: dict) -> dict:
        """POST /collect-responses → v6.19 F6: integra respuestas de subagentes y finaliza.

        El agente CZAI llama este endpoint después de ejecutar las pending_tasks
        de Nivel 3 (vía Task tool). El daemon invoca
        ``_collect_responses_and_finalize()`` que:
        1. ``collect_responses()`` — integra respuestas en bloques.
        2. Re-verifica bloques incompletos.
        3. Si aún hay → publica nuevas pending_tasks, retorna ``needs_agent_action=True``.
        4. Si todos completos → P16 + P18 + P19 + status=done.
        """
        workspace_dir = body.get("workspace_dir", "")
        if not workspace_dir:
            return {"error": "faltan campos obligatorios: workspace_dir"}
        try:
            # v7.0 modularización: ``_collect_responses_and_finalize`` ahora
            # vive en ``SubprocesoArchivos`` (pipeline_archivos.py). Se
            # re-exporta como función módulo-nivel en ``pipeline.py``.
            from contexto_zai.pipeline import _collect_responses_and_finalize
            result = _collect_responses_and_finalize(
                workspace_dir=workspace_dir,
            )
            if not isinstance(result, dict):
                return {"error": "resultado inesperado (no es dict)", "raw": str(result)}
            return result
        except Exception as e:
            log.exception("collect_responses falló")
            return {"error": f"collect_responses falló: {e}"}

    def _handle_generar_archivos(self, body: dict) -> dict:
        """POST /generar-archivos → v6.20 F5: genera los 4 archivos de recuperación.

        Llama a ``_generar_archivos_recuperacion()`` que hace una sola llamada
        al LLM vía cascada con un prompt estructurado para los 4 archivos.
        """
        workspace_dir = body.get("workspace_dir", "")
        if not workspace_dir:
            return {"error": "faltan campos obligatorios: workspace_dir"}
        chat_id = body.get("chat_id", "")
        try:
            # v7.0 modularización: ``_generar_archivos_recuperacion`` ahora
            # vive en ``SubprocesoArchivos`` (pipeline_archivos.py). Se
            # re-exporta como función módulo-nivel en ``pipeline.py``.
            from contexto_zai.pipeline import _generar_archivos_recuperacion
            result = _generar_archivos_recuperacion(
                workspace_dir=workspace_dir,
                chat_id=chat_id,
            )
            if not isinstance(result, dict):
                return {"error": "resultado inesperado (no es dict)", "raw": str(result)}
            return result
        except Exception as e:
            log.exception("generar_archivos falló")
            return {"error": f"generar_archivos falló: {e}"}

    def _handle_pipeline_run(self, body: dict) -> dict:
        """POST /pipeline-run → invoca pipeline.run()."""
        chat_id = body.get("chat_id")
        jwt = body.get("jwt", "")
        if not chat_id:
            return {"error": "faltan campos obligatorios: chat_id"}
        reason = body.get("reason", "")
        chat_label = body.get("chat_label", "")
        try:
            from contexto_zai.pipeline import run
            result = run(chat_id=chat_id, jwt=jwt, reason=reason, chat_label=chat_label)
            # OrchestratorResult → dict
            return {
                "success": result.success,
                "cycle_used": result.cycle_used,
                "exchanges_processed": result.exchanges_processed,
                "files_generated": result.files_generated,
                "error": result.error,
                "pending_tasks_count": len(result.pending_tasks or []),
            }
        except Exception as e:
            log.exception("pipeline.run falló")
            return {"error": f"pipeline.run falló: {e}"}

    def _read_pending_tasks(self) -> dict:
        """Lee _pending_tasks.json del workspace."""
        path = self._workspace_dir / "_pending_tasks.json"
        if not path.exists():
            return {"tasks": [], "total": 0}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data
        except (json.JSONDecodeError, ValueError) as e:
            return {"error": f"_pending_tasks.json corrupto: {e}", "tasks": [], "total": 0}

    def _read_status(self) -> dict:
        """C9: Lee _processed_blocks.json y valida contra estado físico real.

        Si el archivo no coincide con el estado físico del workspace
        (bloques con RESUMEN + 3 archivos auxiliares), lo sincroniza
        usando AuditorWorkspace.
        """
        # C9: validar contra estado físico real
        try:
            from contexto_zai.pipeline_auditoria import AuditorWorkspace
            audit = AuditorWorkspace.auditar_completitud(self._workspace_dir)
            fisicos_completos = len(audit.get("completos", []))
            fisicos_incompletos = len(audit.get("incompletos", []))
            fisicos_total = fisicos_completos + fisicos_incompletos
        except Exception as e:
            log.warning("AuditorWorkspace falló: %s", e)
            fisicos_completos = fisicos_incompletos = fisicos_total = 0

        path = self._workspace_dir / "_processed_blocks.json"
        if not path.exists():
            return {
                "completed": fisicos_completos,
                "pending": fisicos_incompletos,
                "total": fisicos_total,
                "exists": False,
                "source": "auditoria_fisica",
            }
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            blocks = data.get("blocks", [])
            archivo_completed = sum(1 for b in blocks if b.get("status") == "completed")
            archivo_pending = sum(1 for b in blocks if b.get("status") == "pending")

            # C9: si el archivo no coincide con el estado físico, sincronizar
            if archivo_completed != fisicos_completos and fisicos_total > 0:
                log.info(
                    "C9: discrepancia detectada (archivo=%d completos, físico=%d completos). Sincronizando.",
                    archivo_completed, fisicos_completos,
                )
                try:
                    AuditorWorkspace.sincronizar_registro(self._workspace_dir)
                except Exception:
                    pass

            # C9: devolver el estado físico (fuente de verdad, no el archivo)
            return {
                "completed": fisicos_completos if fisicos_total > 0 else archivo_completed,
                "pending": fisicos_incompletos if fisicos_total > 0 else archivo_pending,
                "total": fisicos_total if fisicos_total > 0 else len(blocks),
                "exists": True,
                "source": "auditoria_fisica" if fisicos_total > 0 else "archivo",
            }
        except (json.JSONDecodeError, ValueError) as e:
            return {"error": f"_processed_blocks.json corrupto: {e}", "exists": True}


def main() -> int:
    """Entry point del daemon. Mantiene el proceso vivo hasta SIGINT/SIGTERM."""
    server = PipelineDaemonServer(port=PORT, workspace_dir=WORKSPACE_DIR)
    server.start()
    print(f"[pipeline-daemon] escuchando en puerto {PORT}", flush=True)
    print(f"[pipeline-daemon] workspace_dir={WORKSPACE_DIR}", flush=True)

    stop = {"flag": False}

    def _on_signal(signum, _frame):
        print(f"[pipeline-daemon] señal {signum} recibida, deteniendo...", flush=True)
        stop["flag"] = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    # Bucle de keep-alive
    while not stop["flag"]:
        time.sleep(1.0)

    server.stop()
    print("[pipeline-daemon] servidor detenido. Saliendo.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
