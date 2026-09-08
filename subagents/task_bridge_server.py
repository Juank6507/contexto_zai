# contexto_zai/subagents/task_bridge_server.py -- Mini HTTP server que puentea Task requests del pipeline al agente (v3.6).
"""Task Bridge Server (v3.6).

Mini HTTP server que permite al pipeline Python lanzar subagentes reales
a través del agente (que tiene acceso al Task tool de Z.ai).

Flujo:
1. El pipeline Python hace POST /task-request con {prompt, files_to_read, description}
2. El server guarda la request en una cola
3. El agente (que tiene Task tool) hace GET /pending-tasks
4. El agente ejecuta cada Task con el tool real
5. El agente hace POST /task-result con {id, result, success}
6. El pipeline Python hace GET /task-result/{id} (polling)
7. El pipeline recibe el resultado y continúa

Atómico standalone: solo usa http.server y json.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TaskBridgeServer:
    """Mini HTTP server que puentea Task requests del pipeline al agente (v3.6).

    Args:
        port: Puerto del servidor (default 8087).

    Usage:
        >>> server = TaskBridgeServer(port=8087)
        >>> server.start()
        >>> # El pipeline Python hace POST /task-request
        >>> # El agente hace GET /pending-tasks, ejecuta, POST /task-result
        >>> # El pipeline hace GET /task-result/{id}
        >>> server.stop()
    """

    def __init__(self, port: int = 8087) -> None:
        self._port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._pending: dict[str, dict] = {}  # id -> {prompt, files, desc}
        self._results: dict[str, dict] = {}  # id -> {result, success, error}
        self._lock = threading.Lock()
        logger.debug("TaskBridgeServer inicializado: port=%d", port)

    def start(self) -> None:
        """Levanta el servidor HTTP en un thread daemon."""
        if self._server is not None:
            return

        server_self = self

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, data, status=200):
                body = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/pending-tasks":
                    with server_self._lock:
                        pending = list(server_self._pending.values())
                    self._send_json({"tasks": pending})
                elif self.path.startswith("/task-result/"):
                    task_id = self.path.split("/")[-1]
                    with server_self._lock:
                        result = server_self._results.get(task_id)
                    if result:
                        self._send_json(result)
                    else:
                        self._send_json({"error": "Not ready"}, 202)  # still pending
                elif self.path == "/health":
                    self._send_json({"status": "ok"})
                else:
                    self._send_json({"error": "Not found"}, 404)

            def do_POST(self):
                if self.path == "/task-request":
                    body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                    data = json.loads(body)
                    task_id = str(uuid.uuid4())[:8]
                    with server_self._lock:
                        server_self._pending[task_id] = {
                            "id": task_id,
                            "prompt": data.get("prompt", ""),
                            "files_to_read": data.get("files_to_read", []),
                            "description": data.get("description", ""),
                        }
                    logger.info("Task request %s: %s", task_id, data.get("description", ""))
                    self._send_json({"id": task_id, "status": "pending"})

                elif self.path == "/task-result":
                    body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                    data = json.loads(body)
                    task_id = data.get("id", "")
                    with server_self._lock:
                        if task_id in server_self._pending:
                            del server_self._pending[task_id]
                        server_self._results[task_id] = {
                            "id": task_id,
                            "result": data.get("result", ""),
                            "success": data.get("success", True),
                            "error": data.get("error", ""),
                        }
                    logger.info("Task result %s: success=%s", task_id, data.get("success", True))
                    self._send_json({"status": "ok"})

                elif self.path == "/task-batch":
                    # Recibir múltiples task requests a la vez (para paralelo)
                    body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                    data = json.loads(body)
                    requests = data.get("requests", [])
                    ids = []
                    with server_self._lock:
                        for req in requests:
                            task_id = str(uuid.uuid4())[:8]
                            server_self._pending[task_id] = {
                                "id": task_id,
                                "prompt": req.get("prompt", ""),
                                "files_to_read": req.get("files_to_read", []),
                                "description": req.get("description", ""),
                            }
                            ids.append(task_id)
                    logger.info("Batch: %d task requests", len(ids))
                    self._send_json({"ids": ids})

                elif self.path == "/task-results-batch":
                    # Obtener resultados de múltiples tasks
                    body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                    data = json.loads(body)
                    ids = data.get("ids", [])
                    results = []
                    with server_self._lock:
                        for tid in ids:
                            r = server_self._results.get(tid)
                            if r:
                                results.append(r)
                    all_ready = len(results) == len(ids)
                    self._send_json({"results": results, "all_ready": all_ready})

                elif self.path == "/task-result-submit":
                    # Enviar resultado de un task (mismo que /task-result pero diferente nombre)
                    body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                    data = json.loads(body)
                    task_id = data.get("id", "")
                    with server_self._lock:
                        if task_id in server_self._pending:
                            del server_self._pending[task_id]
                        server_self._results[task_id] = {
                            "id": task_id,
                            "result": data.get("result", ""),
                            "success": data.get("success", True),
                            "error": data.get("error", ""),
                        }
                    logger.info("Task result submit %s", task_id)
                    self._send_json({"status": "ok"})
                else:
                    self._send_json({"error": "Not found"}, 404)

            def log_message(self, format, *args):
                pass  # suprimir logs HTTP

        self._server = HTTPServer(("0.0.0.0", self._port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("TaskBridgeServer iniciado en http://0.0.0.0:%d", self._port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def __repr__(self) -> str:
        return f"TaskBridgeServer(port={self._port}, running={self.is_running})"


if __name__ == "__main__":
    import io, sys
    try:
        if hasattr(sys.stdout, 'buffer') and 'utf' not in (getattr(sys.stdout, 'encoding', '') or '').lower():
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except:
        pass

    print("=== Validacion de task_bridge_server.py ===\n")
    import httpx, time

    server = TaskBridgeServer(port=18087)
    server.start()
    time.sleep(0.5)

    # Test 1: health
    r = httpx.get("http://localhost:18087/health", timeout=5)
    assert r.json()["status"] == "ok"
    print("[OK] GET /health")

    # Test 2: POST task-request
    r = httpx.post("http://localhost:18087/task-request", json={
        "prompt": "Lee el archivo", "files_to_read": ["/tmp/test.pdf"],
        "description": "Test task"
    }, timeout=5)
    data = r.json()
    task_id = data["id"]
    assert data["status"] == "pending"
    print(f"[OK] POST /task-request: id={task_id}")

    # Test 3: GET pending-tasks
    r = httpx.get("http://localhost:18087/pending-tasks", timeout=5)
    tasks = r.json()["tasks"]
    assert len(tasks) == 1
    print(f"[OK] GET /pending-tasks: {len(tasks)} pending")

    # Test 4: GET task-result (pending → 202)
    r = httpx.get(f"http://localhost:18087/task-result/{task_id}", timeout=5)
    assert r.status_code == 202
    print("[OK] GET /task-result (pending): 202")

    # Test 5: POST task-result
    r = httpx.post("http://localhost:18087/task-result", json={
        "id": task_id, "result": "Task completed", "success": True
    }, timeout=5)
    assert r.json()["status"] == "ok"
    print("[OK] POST /task-result: submitted")

    # Test 6: GET task-result (ready)
    r = httpx.get(f"http://localhost:18087/task-result/{task_id}", timeout=5)
    result = r.json()
    assert result["result"] == "Task completed"
    print(f"[OK] GET /task-result (ready): {result['result']}")

    # Test 7: batch
    r = httpx.post("http://localhost:18087/task-batch", json={
        "requests": [
            {"prompt": "q1", "files_to_read": [], "description": "d1"},
            {"prompt": "q2", "files_to_read": [], "description": "d2"},
        ]
    }, timeout=5)
    ids = r.json()["ids"]
    assert len(ids) == 2
    print(f"[OK] POST /task-batch: {len(ids)} requests")

    # Test 8: results-batch (not ready)
    r = httpx.post("http://localhost:18087/task-results-batch", json={"ids": ids}, timeout=5)
    data = r.json()
    assert not data["all_ready"]
    print("[OK] GET /task-results-batch (not ready)")

    # Submit both results
    for tid in ids:
        httpx.post("http://localhost:18087/task-result", json={
            "id": tid, "result": f"result_{tid}", "success": True
        }, timeout=5)

    r = httpx.post("http://localhost:18087/task-results-batch", json={"ids": ids}, timeout=5)
    data = r.json()
    assert data["all_ready"]
    assert len(data["results"]) == 2
    print("[OK] GET /task-results-batch (ready): 2 results")

    server.stop()
    print(f"\n[PASS] task_bridge_server.py: todos los tests pasaron")
