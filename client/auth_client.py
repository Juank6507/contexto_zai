"""Cliente de autenticación para chat.z.ai (v3.2).

Dos modos de operación:
1. Token directo (legacy): el Director proporciona su JWT y se
   valida contra /api/v1/auths/ con cookies HTTP.
2. Sesión del navegador (v3.2): delega en BrowserSession para leer
   la cookie `token` del navegador del sandbox, que es donde el
   Director ya está autenticado. El protocolo de inyección de cookie
   se aplica automáticamente si el navegador es invitado.

Utiliza httpx para solicitudes HTTP síncronas en modo token directo.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from contexto_zai.client.browser_session import BrowserSession
from contexto_zai.config import API_CONFIG

logger = logging.getLogger(__name__)


class AuthClientError(Exception):
    """Error base del AuthClient."""


class AuthenticationError(AuthClientError):
    """El token no es válido o fue rechazado."""


class ShareCreationError(AuthClientError):
    """Error al crear el share del chat."""


class AuthClient:
    """Gestiona autenticación y creación de shares en chat.z.ai.

    Args:
        token: JWT token del Director (modo legacy). Si es None,
            se usa el modo sesión del navegador (v3.2).
        browser_session: Sesión del navegador inyectada (modo v3.2).
            Si es None y token tampoco se proporciona, se crea una
            nueva BrowserSession.
        timeout: Timeout en segundos para las solicitudes HTTP.

    Usage (modo v3.2, recomendado)::
        >>> session = BrowserSession()
        >>> auth = AuthClient(browser_session=session)
        >>> auth.authenticate(chat_id="chat-uuid", jwt_director="eyJ...")
        >>> share_id = auth.create_share("chat-uuid")

    Usage (modo legacy)::
        >>> auth = AuthClient(token="eyJhbG...")
        >>> share_id = auth.create_share("chat-uuid-here")
        >>> profile = auth.validate_token()
    """

    def __init__(
        self,
        token: Optional[str] = None,
        browser_session: Optional[BrowserSession] = None,
        timeout: float = API_CONFIG.timeout_seconds,
    ) -> None:
        self._token = token.strip() if token else ""
        self._timeout = timeout
        self._base_url = API_CONFIG.base_url
        self._browser_session = browser_session or (BrowserSession() if not token else None)
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "ContextoZAI/3.2",
                "Accept": "application/json",
            },
        )

    # ── Propiedades públicas ───────────────────────────────────

    @property
    def token(self) -> str:
        """JWT actual (modo legacy) o cadena vacía (modo v3.2)."""
        return self._token

    @property
    def browser_session(self) -> Optional[BrowserSession]:
        """Sesión del navegador (modo v3.2) o None."""
        return self._browser_session

    @property
    def is_browser_mode(self) -> bool:
        """True si opera en modo navegador (v3.2)."""
        return self._browser_session is not None and not self._token

    # ── Autenticación vía navegador (v3.2) ──────────────────────

    def authenticate(self, chat_id: str, jwt_director: str) -> bool:
        """Aplica el protocolo de inyección de cookie (modo v3.2).

        Delega en BrowserSession.ensure_authenticated.

        Args:
            chat_id: UUID interno del chat.
            jwt_director: JWT del Director.

        Returns:
            True si la autenticación fue exitosa.

        Raises:
            AuthClientError: Si no hay BrowserSession configurado.
        """
        if not self._browser_session:
            raise AuthClientError(
                "authenticate() requiere modo navegador. "
                "Crea AuthClient sin parámetro token, o con browser_session."
            )
        return self._browser_session.ensure_authenticated(jwt_director, chat_id)

    def get_browser_cookie_token(self) -> Optional[str]:
        """Lee el JWT de la cookie del navegador (modo v3.2).

        Útil para pasar el token a httpx en las llamadas API.
        """
        if not self._browser_session:
            return None
        cookie = self._browser_session.get_token_cookie()
        return cookie.value if cookie and not cookie.is_guest else None

    # ── Métodos públicos ───────────────────────────────────────

    def validate_token(self) -> dict:
        """Verifica que el token es válido consultando /api/v1/auths/.

        Returns:
            Diccionario con el perfil del usuario autenticado.

        Raises:
            AuthenticationError: Si el token fue rechazado (401/403).
        """
        url = f"{self._base_url}/api/v1/auths/"
        cookies = {API_CONFIG.cookie_name: self._token}

        logger.debug("Validando token contra %s", url)
        response = self._client.get(url, cookies=cookies)

        if response.status_code in (401, 403):
            raise AuthenticationError(
                f"Token rechazado (HTTP {response.status_code}). "
                f"Verifica que el JWT sea válido y no haya expirado."
            )

        response.raise_for_status()
        data = response.json()
        logger.info(
            "Token válido. Usuario: %s (role: %s)",
            data.get("email", "desconocido"),
            data.get("role", "desconocido"),
        )
        return data

    def create_share(self, chat_id: str) -> str:
        """Crea un share link para un chat (idempotente).

        Si el chat ya tiene un share, devuelve el existente.

        Args:
            chat_id: UUID interno del chat.

        Returns:
            El share_id (UUID) del share creado o existente.

        Raises:
            ShareCreationError: Si la creación falla.
        """
        url = API_CONFIG.create_share_url.format(chat_id=chat_id)
        cookies = {API_CONFIG.cookie_name: self._token}

        logger.debug("Creando share para chat %s", chat_id)
        response = self._client.post(
            url,
            cookies=cookies,
            headers={"Content-Type": "application/json"},
        )

        if response.status_code in (401, 403):
            raise ShareCreationError(
                f"Sin permisos para crear share (HTTP {response.status_code}). "
                f"El token puede no tener acceso a este chat."
            )

        if response.status_code == 404:
            raise ShareCreationError(
                f"Chat {chat_id} no encontrado (HTTP 404)."
            )

        response.raise_for_status()
        data = response.json()
        share_id = data.get("id")

        if not share_id:
            raise ShareCreationError(
                f"La respuesta no contiene 'id'. Respuesta: {json.dumps(data)[:200]}"
            )

        logger.info("Share creado/existente: %s", share_id)
        return share_id

    def close(self) -> None:
        """Cierra el cliente HTTP."""
        self._client.close()

    def __enter__(self) -> "AuthClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __repr__(self) -> str:
        if self.is_browser_mode:
            return "AuthClient(mode=browser)"
        token_preview = self._token[:12] + "..." if len(self._token) > 12 else self._token
        return f"AuthClient(token={token_preview!r})"


if __name__ == "__main__":
    # ── Validación interna de auth_client.py (atómico standalone) ──
    print("=== Validación de auth_client.py ===\n")

    import tempfile
    from pathlib import Path
    from contexto_zai.client.browser_session import BrowserSession

    # Test 1: modo legacy con token
    auth_legacy = AuthClient(token="eyJhbG.test.payload.signature")
    assert auth_legacy.token == "eyJhbG.test.payload.signature"
    assert not auth_legacy.is_browser_mode
    assert auth_legacy.browser_session is None
    print(f"✓ Modo legacy: {auth_legacy!r}")

    # Test 2: modo navegador v3.2
    with tempfile.TemporaryDirectory() as tmpdir:
        session = BrowserSession(auth_state_path=Path(tmpdir) / "state.json")
        auth_v3 = AuthClient(browser_session=session)
        assert auth_v3.is_browser_mode
        assert auth_v3.browser_session is session
        assert auth_v3.token == ""
        print(f"✓ Modo navegador v3.2: {auth_v3!r}")

    # Test 3: authenticate() sin browser_session lanza error
    auth_no_browser = AuthClient(token="some_token")
    try:
        auth_no_browser.authenticate(chat_id="x", jwt_director="y")
        assert False, "Debería haber lanzado AuthClientError"
    except AuthClientError as e:
        print(f"✓ authenticate() sin browser_session: error correcto")

    # Test 4: get_browser_cookie_token en modo legacy devuelve None
    assert auth_legacy.get_browser_cookie_token() is None
    print(f"✓ get_browser_cookie_token() en modo legacy: None")

    # Test 5: excepciones de autenticación
    assert issubclass(AuthenticationError, AuthClientError)
    assert issubclass(ShareCreationError, AuthClientError)
    print(f"✓ Jerarquía de excepciones: AuthClientError -> Auth/Share")

    # Cerrar clientes
    auth_legacy.close()
    auth_v3.close()
    auth_no_browser.close()

    print("\n✅ auth_client.py: todos los tests pasaron")
    print("\nNota: para validar create_share/validate_token contra la API real,")
    print("      ejecutar tests/test_auth_client.py con JWT del Director")
