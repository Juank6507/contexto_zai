# contexto_zai/client/jwt_bridge_server.py -- Mini HTTP server temporal para recibir JWT del .bat (v3.6).
"""Servidor HTTP temporal para recibir el JWT del Director (v3.6).

Expone 3 endpoints:
- GET /jwt-status → {"needs_jwt": true|false}
- POST /recibir-jwt → recibe el JWT y lo persiste
- GET /czai-jwt-bridge.bat → sirve el script descargable

El servidor se apaga automáticamente después de recibir el JWT.

Atómico standalone: importa credential_manager y httpx.
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
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
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

from contexto_zai.client.credential_manager import CredentialManager
from contexto_zai.config import JWT_BRIDGE_SERVER_HOST, JWT_BRIDGE_SERVER_PORT

logger = logging.getLogger(__name__)


class JwtBridgeServer:
    """Mini HTTP server temporal para recibir el JWT del Director (v3.6).

    Args:
        port: Puerto del servidor (default JWT_BRIDGE_SERVER_PORT).
        credential_manager: CredentialManager para persistir el JWT.
        bat_file_path: Ruta del script .bat a servir.

    Usage:
        >>> server = JwtBridgeServer()
        >>> server.start()
        >>> # El Director descarga .bat y lo ejecuta
        >>> # El .bat envía el JWT vía POST /recibir-jwt
        >>> # El servidor lo persiste y se apaga
        >>> server.wait_for_jwt(timeout=300)  # esperar hasta 5 min
    """

    def __init__(
        self,
        port: int = JWT_BRIDGE_SERVER_PORT,
        credential_manager: Optional[CredentialManager] = None,
        bat_file_path: Optional[Path | str] = None,
    ) -> None:
        self._port = port
        self._cm = credential_manager or CredentialManager()
        self._bat_path = Path(bat_file_path) if bat_file_path else None
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._jwt_received = threading.Event()
        logger.debug(
            "JwtBridgeServer inicializado: port=%d, bat=%s",
            port, self._bat_path,
        )

    # -- API pública ------------------------------------------------

    def start(self) -> None:
        """Levanta el servidor HTTP en un thread daemon."""
        if self._server is not None:
            logger.warning("Server ya está corriendo")
            return

        server_self = self

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, data: dict, status: int = 200) -> None:
                body = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                # CORS headers para que el .bat pueda hacer requests
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()
                self.wfile.write(body)

            def _send_file(self, path: Path, content_type: str = "application/octet-stream") -> None:
                if not path.exists():
                    self._send_json({"error": "File not found"}, 404)
                    return
                content = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
                self.end_headers()
                self.wfile.write(content)

            def do_OPTIONS(self):
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def do_GET(self):
                if self.path == "/jwt-status":
                    needs = server_self._cm.needs_jwt()
                    self._send_json({"needs_jwt": needs})
                elif self.path == "/czai-jwt-bridge.bat":
                    if server_self._bat_path:
                        self._send_file(server_self._bat_path, "application/octet-stream")
                    else:
                        self._send_json({"error": "No .bat file configured"}, 404)
                elif self.path == "/" or self.path == "/health":
                    self._send_json({"status": "ok", "service": "CZAI JWT Bridge"})
                else:
                    self._send_json({"error": "Not found"}, 404)

            def do_POST(self):
                if self.path == "/recibir-jwt":
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length).decode("utf-8")
                    try:
                        data = json.loads(body)
                        jwt = data.get("token", "")
                        email = data.get("email", "")
                        if not jwt:
                            self._send_json({"success": False, "error": "Token vacío"}, 400)
                            return
                        # Guardar en CredentialManager (única fuente de verdad)
                        server_self._cm.save_jwt(jwt, email)
                        logger.info("JWT guardado en CredentialManager (email=%s)", email)
                        self._send_json({"success": True, "email": email})
                        server_self._jwt_received.set()
                        logger.info("JWT recibido y persistido (email=%s)", email)
                    except json.JSONDecodeError as e:
                        self._send_json({"success": False, "error": f"JSON inválido: {e}"}, 400)
                else:
                    self._send_json({"error": "Not found"}, 404)

            def log_message(self, format, *args):
                # Suprimir logs de HTTP server (usar logger propio)
                logger.debug("HTTP: %s", format % args)

        self._server = HTTPServer((JWT_BRIDGE_SERVER_HOST, self._port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("JwtBridgeServer iniciado en http://%s:%d", JWT_BRIDGE_SERVER_HOST, self._port)

    def stop(self) -> None:
        """Detiene el servidor HTTP."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("JwtBridgeServer detenido")

    def wait_for_jwt(self, timeout: float = 300) -> bool:
        """Espera hasta que el JWT sea recibido.

        Args:
            timeout: Tiempo máximo de espera en segundos (default 5 min).

        Returns:
            True si el JWT fue recibido, False si timeout.
        """
        received = self._jwt_received.wait(timeout=timeout)
        if received:
            logger.info("JWT recibido correctamente")
        else:
            logger.warning("Timeout esperando JWT (%d segundos)", timeout)
        return received

    @property
    def is_running(self) -> bool:
        """True si el servidor está corriendo."""
        return self._server is not None

    @property
    def jwt_received(self) -> bool:
        """True si el JWT ya fue recibido."""
        return self._jwt_received.is_set()

    def get_url(self) -> str:
        """Devuelve la URL base del servidor."""
        return f"http://localhost:{self._port}"

    def __repr__(self) -> str:
        return f"JwtBridgeServer(port={self._port}, running={self.is_running})"


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

    print("=== Validacion de jwt_bridge_server.py ===\n")

    import tempfile
    import httpx
    import time

    with tempfile.TemporaryDirectory() as tmpdir:
        creds_path = Path(tmpdir) / "creds.json"
        cm = CredentialManager(credentials_path=creds_path)

        # Crear un .bat mock
        bat_path = Path(tmpdir) / "czai-jwt-bridge.bat"
        bat_path.write_text("@echo off\nREM mock bat\n", encoding="utf-8")

        # Test 1: iniciar servidor
        server = JwtBridgeServer(
            port=18086,  # puerto diferente para no conflictar
            credential_manager=cm,
            bat_file_path=bat_path,
        )
        server.start()
        assert server.is_running
        print("[OK] Servidor iniciado")

        # Test 2: GET /jwt-status (sin JWT → needs_jwt=True)
        time.sleep(0.5)  # esperar a que el servidor esté listo
        resp = httpx.get("http://localhost:18086/jwt-status", timeout=5.0)
        assert resp.status_code == 200
        data = resp.json()
        assert data["needs_jwt"] is True
        print(f"[OK] GET /jwt-status: needs_jwt={data['needs_jwt']}")

        # Test 3: GET /health
        resp = httpx.get("http://localhost:18086/health", timeout=5.0)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        print(f"[OK] GET /health: status={resp.json()['status']}")

        # Test 4: GET /czai-jwt-bridge.bat
        resp = httpx.get("http://localhost:18086/czai-jwt-bridge.bat", timeout=5.0)
        assert resp.status_code == 200
        assert b"mock bat" in resp.content
        print(f"[OK] GET /czai-jwt-bridge.bat: {len(resp.content)} bytes")

        # Test 5: POST /recibir-jwt
        resp = httpx.post(
            "http://localhost:18086/recibir-jwt",
            json={"token": "eyJhbG.test.jwt", "email": "director@test.com"},
            timeout=5.0,
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        print(f"[OK] POST /recibir-jwt: success={resp.json()['success']}")

        # Test 6: JWT persistido
        jwt = cm.get_jwt()
        assert jwt == "eyJhbG.test.jwt"
        email = cm.get_email()
        assert email == "director@test.com"
        print(f"[OK] JWT persistido: {jwt[:20]}... (email={email})")

        # Test 7: jwt_received = True
        assert server.jwt_received
        print("[OK] jwt_received: True")

        # Test 8: GET /jwt-status (con JWT → needs_jwt=False sin validación real)
        # needs_jwt llama a is_valid que hace HTTP a Z.ai → puede fallar en test
        # Por eso solo verificamos que no crashea
        resp = httpx.get("http://localhost:18086/jwt-status", timeout=5.0)
        assert resp.status_code == 200
        print(f"[OK] GET /jwt-status después de recibir: {resp.json()}")

        # Test 9: POST /recibir-jwt con token vacío → error 400
        resp = httpx.post(
            "http://localhost:18086/recibir-jwt",
            json={"token": "", "email": ""},
            timeout=5.0,
        )
        assert resp.status_code == 400
        print(f"[OK] POST /recibir-jwt con token vacío: error 400")

        # Test 10: POST /recibir-jwt con JSON inválido → error 400
        resp = httpx.post(
            "http://localhost:18086/recibir-jwt",
            content="not json",
            headers={"Content-Type": "application/json"},
            timeout=5.0,
        )
        assert resp.status_code == 400
        print(f"[OK] POST /recibir-jwt con JSON inválido: error 400")

        # Test 11: GET endpoint inexistente → 404
        resp = httpx.get("http://localhost:18086/noexiste", timeout=5.0)
        assert resp.status_code == 404
        print(f"[OK] GET /noexiste: 404")

        # Test 12: detener servidor
        server.stop()
        assert not server.is_running
        print(f"[OK] Servidor detenido: is_running={server.is_running}")

        # Test 13: get_url
        server2 = JwtBridgeServer(port=18087, credential_manager=cm)
        url = server2.get_url()
        assert "18087" in url
        print(f"[OK] get_url: {url}")

        # Test 14: wait_for_jwt con timeout (ya recibido → inmediato)
        server2.start()
        # Simular recepción
        server2._jwt_received.set()
        result = server2.wait_for_jwt(timeout=1)
        assert result is True
        print(f"[OK] wait_for_jwt (ya recibido): True")
        server2.stop()

        # Test 15: wait_for_jwt con timeout (no recibido → False)
        server3 = JwtBridgeServer(port=18088, credential_manager=cm)
        server3.start()
        result = server3.wait_for_jwt(timeout=1)
        assert result is False
        print(f"[OK] wait_for_jwt (timeout): False")
        server3.stop()

        # Test 16: repr
        r = repr(server3)
        assert "JwtBridgeServer" in r
        print(f"[OK] repr: {r}")

    print("\n[PASS] jwt_bridge_server.py: todos los tests pasaron")
