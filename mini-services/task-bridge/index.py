# /home/z/my-project/mini-services/task-bridge/index.py
"""Mini-servicio lanzadera para TaskBridgeServer (puerto 8087).

El servidor HTTP corre en un thread daemon interno. Este wrapper mantiene el
proceso vivo hasta que se reciba SIGINT/SIGTERM, exponiendo además un
endpoint /health para verificación.
"""
from __future__ import annotations

import signal
import sys
import time

sys.path.insert(0, "/home/z/my-project")

from contexto_zai.subagents.task_bridge_server import TaskBridgeServer


PORT = 8087


def main() -> int:
    server = TaskBridgeServer(port=PORT)
    server.start()
    print(f"[task-bridge] TaskBridgeServer escuchando en puerto {PORT}", flush=True)

    stop = {"flag": False}

    def _on_signal(signum, _frame):
        print(f"[task-bridge] señal {signum} recibida, deteniendo...", flush=True)
        stop["flag"] = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    # Bucle de keep-alive
    while not stop["flag"]:
        time.sleep(1.0)

    server.stop()
    print("[task-bridge] Servidor detenido. Saliendo.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
