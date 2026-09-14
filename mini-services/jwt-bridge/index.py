# /home/z/my-project/mini-services/jwt-bridge/index.py
"""Mini-servicio lanzadera para JwtBridgeServer (puerto 8086).

Mantiene el proceso vivo bloqueando el thread principal hasta que llega el JWT
o hasta que se reciba SIGINT/SIGTERM. El servidor HTTP corre en un thread daemon
interno, así que este wrapper debe quedarse bloqueado para que el daemon no muera.
"""
from __future__ import annotations

import signal
import sys
import time

# Asegurar que el paquete contexto_zai sea importable
sys.path.insert(0, "/home/z/my-project")

from contexto_zai.client.credential_manager import CredentialManager
from contexto_zai.client.jwt_bridge_server import JwtBridgeServer


PORT = 8086


def main() -> int:
    cm = CredentialManager()
    server = JwtBridgeServer(port=PORT, credential_manager=cm)
    server.start()
    print(f"[jwt-bridge] JwtBridgeServer escuchando en puerto {PORT}", flush=True)
    print(f"[jwt-bridge] CM.needs_jwt al arranque: {cm.needs_jwt()}", flush=True)

    stop = {"flag": False}

    def _on_signal(signum, _frame):
        print(f"[jwt-bridge] señal {signum} recibida, deteniendo...", flush=True)
        stop["flag"] = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    # Bucle principal: esperar al JWT o hasta que llegue señal de parada.
    # wait_for_jwt bloquea el thread con timeout periódico para poder
    # responder a señales y loguear el progreso.
    while not stop["flag"]:
        arrived = server.wait_for_jwt(timeout=2)
        if arrived:
            print("[jwt-bridge] JWT recibido. Cerrando servidor...", flush=True)
            # Dar 1s para que el handler termine de responder al .bat
            time.sleep(1.0)
            break

    server.stop()
    print("[jwt-bridge] Servidor detenido. Saliendo.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
