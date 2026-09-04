# contexto_zai/client/browser_session.py -- Sesion autenticada del navegador: protocolo de inyeccion de cookie JWT (metodologia JWT).
"""Sesión autenticada del navegador para chat.z.ai.

Maneja el protocolo de inyección de cookie de la metodología JWT
(spec v3.2 sección 11): lee/escribe la cookie `token`, detecta
sesiones de invitado, aplica el protocolo de inyección cuando hace
falta, y persiste el estado autenticado para sesiones futuras.

Atómico standalone: no importa otros módulos del proyecto excepto
los estrictamente necesarios para su lógica (config para rutas).
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
for _ in range(5):
    if _os.path.isdir(_os.path.join(_candidate, 'contexto_zai')):
        if _candidate not in _sys.path:
            _sys.path.insert(0, _candidate)
        break
    _candidate = _os.path.dirname(_candidate)
else:
    _parent = _os.path.dirname(_here)
    if _parent not in _sys.path:
        _sys.path.insert(0, _parent)

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from contexto_zai.config import API_CONFIG, BROWSER_AUTH_STATE_PATH

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class CookieInfo:
    """Información de una cookie del navegador.

    Attributes:
        name: Nombre de la cookie.
        value: Valor de la cookie.
        is_guest: True si el JWT decodificado es de invitado.
        email: Email extraído del payload JWT (o 'unknown').
    """

    name: str
    value: str
    is_guest: bool = False
    email: str = "unknown"

class BrowserSession:
    """Wrapper sobre agent-browser para autenticación en chat.z.ai.

    Encapsula el protocolo de inyección de cookie descrito en la
    metodología JWT. El navegador del sandbox abre chat.z.ai como
    invitado por defecto, así que el JWT del Director es necesario
    para autenticar.

    Usage:
        session = BrowserSession()
        if session.is_guest():
            session.authenticate(jwt_director)
        session.save_state()

    Args:
        auth_state_path: Ruta al archivo .browser_auth_state.json.
        chat_url_template: Plantilla de URL del chat.
    """

    def __init__(
        self,
        auth_state_path: Path | str = BROWSER_AUTH_STATE_PATH,
        chat_url_template: str = "https://chat.z.ai/c/{chat_id}",
    ) -> None:
        self._auth_state_path = Path(auth_state_path)
        self._chat_url_template = chat_url_template
        self._is_open = False

    # -- Operaciones del navegador ----------------------------------

    def open_chat_zai(self) -> None:
        """Abre chat.z.ai (página principal) para establecer el dominio."""
        self._run_browser_cmd(["open", API_CONFIG.base_url])
        self._is_open = True
        self._wait(2)

    def navigate_to_chat(self, chat_id: str) -> None:
        """Navega al chat indicado. Requiere haber hecho open_chat_zai antes."""
        if not self._is_open:
            self.open_chat_zai()
        url = self._chat_url_template.format(chat_id=chat_id)
        self._run_browser_cmd(["open", url])
        self._wait(2)

    def set_auth_header(self, jwt: str) -> None:
        """Establece el header Authorization para todas las requests.

        Esto previene que el servidor redirija a home cuando se navega
        a /c/{chat_id} sin cookie válida.
        """
        header_json = json.dumps({"Authorization": f"Bearer {jwt}"})
        self._run_browser_cmd(["set", "headers", header_json])

    def get_token_cookie(self) -> CookieInfo | None:
        """Lee la cookie `token` del navegador.

        Devuelve None si la cookie no existe.
        """
        result = self._run_browser_cmd(["cookies"], capture=True)
        if not result:
            return None
        for line in result.splitlines():
            line = line.strip()
            if line.startswith(f"{API_CONFIG.cookie_name}="):
                value = line.split("=", 1)[1]
                return self._parse_token_cookie(value)
        return None

    def set_token_cookie(self, jwt: str) -> None:
        """Inyecta el JWT como cookie `token` en el navegador."""
        self._run_browser_cmd(["cookies", "set", API_CONFIG.cookie_name, jwt])

    def reload_page(self, wait_seconds: int = 3) -> None:
        """Recarga la página actual y espera."""
        self._run_browser_cmd(["eval", "location.reload()"])
        self._wait(wait_seconds)

    def eval_js(self, js_code: str, wait_seconds: int = 0) -> str:
        """Ejecuta JavaScript en la página actual y devuelve el resultado."""
        result = self._run_browser_cmd(["eval", js_code], capture=True)
        if wait_seconds > 0:
            self._wait(wait_seconds)
        return result or ""

    def close(self) -> None:
        """Cierra el navegador."""
        self._run_browser_cmd(["close"])
        self._is_open = False

    # -- Estado autenticado -----------------------------------------

    def save_state(self) -> bool:
        """Guarda el estado autenticado en .browser_auth_state.json."""
        self._auth_state_path.parent.mkdir(parents=True, exist_ok=True)
        result = self._run_browser_cmd(
            ["state", "save", str(self._auth_state_path)], capture=True
        )
        saved = self._auth_state_path.exists()
        if saved:
            logger.info("Estado autenticado guardado en %s", self._auth_state_path)
        else:
            logger.error("No se pudo guardar el estado: %s", result)
        return saved

    def load_state(self) -> bool:
        """Carga el estado autenticado desde .browser_auth_state.json."""
        if not self._auth_state_path.exists():
            logger.info("No hay estado guardado en %s", self._auth_state_path)
            return False
        self._run_browser_cmd(["state", "load", str(self._auth_state_path)])
        self._is_open = True
        logger.info("Estado autenticado cargado desde %s", self._auth_state_path)
        return True

    def has_saved_state(self) -> bool:
        """Verifica si existe un estado autenticado guardado."""
        return self._auth_state_path.exists()

    # -- Protocolo de autenticación completo ------------------------

    def is_guest(self) -> bool:
        """Verifica si la sesión actual es de invitado."""
        cookie = self.get_token_cookie()
        return cookie is None or cookie.is_guest

    def authenticate(self, jwt_director: str, chat_id: str) -> bool:
        """Aplica el protocolo de inyección de cookie completo.

        Pasos (de la metodología JWT):
        1. Abrir chat.z.ai (establece dominio, cookie guest inicial).
        2. set headers Authorization (previene redirección).
        3. Navegar a /c/{chat_id} (URL se mantiene).
        4. set cookie `token` con el JWT del Director.
        5. reload (servidor valida, refresca el token).
        6. Verificar que la cookie ahora es del Director.

        Args:
            jwt_director: JWT del Director (obtenido de DevTools una vez).
            chat_id: UUID interno del chat.

        Returns:
            True si la autenticación fue exitosa.
        """
        logger.info("Aplicando protocolo de inyeccion de cookie para chat %s", chat_id)

        # Paso 1: abrir chat.z.ai
        self.open_chat_zai()

        # Paso 2: set headers Authorization
        self.set_auth_header(jwt_director)

        # Paso 3: navegar al chat
        self.navigate_to_chat(chat_id)

        # Paso 4: inyectar cookie
        self.set_token_cookie(jwt_director)

        # Paso 5: reload
        self.reload_page(wait_seconds=3)

        # Paso 6: verificar
        cookie = self.get_token_cookie()
        if cookie is None:
            logger.error("No se encontro cookie `token` tras autenticacion")
            return False
        if cookie.is_guest:
            logger.error("La cookie sigue siendo de invitado tras autenticacion")
            return False

        logger.info("Autenticacion exitosa: %s", cookie.email)
        return True

    def ensure_authenticated(self, jwt_director: str, chat_id: str) -> bool:
        """Asegura que la sesión está autenticada, cargando estado si existe.

        Flujo:
        1. Si hay estado guardado, cargarlo y verificar.
        2. Si sigue siendo invitado, aplicar protocolo de inyección.
        3. Guardar estado tras autenticación exitosa.
        """
        # Intentar cargar estado guardado primero
        if self.has_saved_state():
            self.load_state()
            self.navigate_to_chat(chat_id)
            if not self.is_guest():
                logger.info("Sesion ya autenticada (estado cargado)")
                return True
            logger.info("Estado guardado expiro o es de invitado, re-autenticando")

        # Aplicar protocolo de inyección
        success = self.authenticate(jwt_director, chat_id)
        if success:
            self.save_state()
        return success

    # -- Internos ---------------------------------------------------

    def _parse_token_cookie(self, value: str) -> CookieInfo:
        """Decodifica un JWT y devuelve CookieInfo."""
        email = "unknown"
        is_guest = False

        # Un JWT tiene 3 partes separadas por puntos
        parts = value.split(".")
        if len(parts) == 3:
            try:
                # El payload es la parte del medio, base64url
                import base64
                payload_b64 = parts[1]
                # Añadir padding si hace falta
                payload_b64 += "=" * (4 - len(payload_b64) % 4)
                payload_bytes = base64.urlsafe_b64decode(payload_b64)
                payload = json.loads(payload_bytes)
                email = payload.get("email", "unknown")
                is_guest = email.startswith("guest-") or "@guest.com" in email
            except Exception as e:
                logger.warning("No se pudo decodificar JWT: %s", e)

        return CookieInfo(
            name=API_CONFIG.cookie_name,
            value=value,
            is_guest=is_guest,
            email=email,
        )

    def _run_browser_cmd(
        self, args: list[str], capture: bool = False
    ) -> str:
        """Ejecuta un comando de agent-browser.

        Args:
            args: Argumentos del comando (ej: ["open", "https://..."]).
            capture: Si True, captura y devuelve stdout.

        Returns:
            stdout del comando, o cadena vacía si capture=False.
        """
        cmd = ["agent-browser"] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if result.returncode != 0:
                logger.warning(
                    "agent-browser %s fallo (code %d): %s",
                    args[0], result.returncode, result.stderr.strip(),
                )
            return result.stdout.strip() if capture else ""
        except subprocess.TimeoutExpired:
            logger.error("agent-browser %s timeout", args[0])
            return ""
        except FileNotFoundError:
            logger.error("agent-browser no encontrado en PATH")
            return ""

    def _wait(self, seconds: float) -> None:
        """Espera los segundos indicados."""
        time.sleep(seconds)

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
    # -- Validación interna de browser_session.py (atómico standalone) -
    print("=== Validacion de browser_session.py ===\n")

    import tempfile
    from pathlib import Path

    # Test 1: instancia con path temporal
    with tempfile.TemporaryDirectory() as tmpdir:
        session = BrowserSession(auth_state_path=Path(tmpdir) / "state.json")
        assert not session.has_saved_state()
        print("[OK] Instancia sin estado guardado")

        # Test 2: parseo de cookie guest
        # JWT real de invitado: header.payload.signature
        # Payload {"id":"abc","email":"guest-123@guest.com"}
        import base64
        payload_guest = base64.urlsafe_b64encode(
            b'{"id":"abc","email":"guest-123@guest.com"}'
        ).decode().rstrip("=")
        guest_jwt = f"eyJhbG.{payload_guest}.signature"
        cookie = session._parse_token_cookie(guest_jwt)
        assert cookie.is_guest is True
        assert cookie.email == "guest-123@guest.com"
        print(f"[OK] Cookie guest detectada: email={cookie.email}")

        # Test 3: parseo de cookie del Director
        payload_dir = base64.urlsafe_b64encode(
            b'{"id":"abc","email":"juanca6507@gmail.com"}'
        ).decode().rstrip("=")
        director_jwt = f"eyJhbG.{payload_dir}.signature"
        cookie = session._parse_token_cookie(director_jwt)
        assert cookie.is_guest is False
        assert cookie.email == "juanca6507@gmail.com"
        print(f"[OK] Cookie Director detectada: email={cookie.email}")

        # Test 4: parseo de JWT malformado
        cookie = session._parse_token_cookie("no-es-un-jwt")
        assert cookie.is_guest is False  # No se pudo decodificar
        assert cookie.email == "unknown"
        print(f"[OK] JWT malformado tratado como unknown")

    # Test 5: URL template del chat
    session = BrowserSession()
    url = session._chat_url_template.format(chat_id="abc-123")
    assert url == "https://chat.z.ai/c/abc-123"
    print(f"[OK] URL template: {url}")

    print("\n[PASS] browser_session.py: todos los tests pasaron")
    print("\nNota: para validar el protocolo completo de autenticacion")
    print("      contra chat.z.ai real, ejecutar tests/test_browser_session.py")
