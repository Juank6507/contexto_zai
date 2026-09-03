"""Cliente de autenticación para chat.z.ai.

Gestiona la inyección del JWT y la creación de shares.
Utiliza httpx para solicitudes HTTP síncronas.
"""

from __future__ import annotations

import json
import logging

import httpx

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
        token: JWT token del usuario autenticado.
        timeout: Timeout en segundos para las solicitudes.

    Usage:
        >>> auth = AuthClient(token="eyJhbG...")
        >>> share_id = auth.create_share("chat-uuid-here")
        >>> profile = auth.validate_token()
    """

    def __init__(self, token: str, timeout: float = API_CONFIG.timeout_seconds) -> None:
        self._token = token.strip()
        self._timeout = timeout
        self._base_url = API_CONFIG.base_url
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "ContextoZAI/1.0",
                "Accept": "application/json",
            },
        )

    # ── Propiedades públicas ───────────────────────────────────

    @property
    def token(self) -> str:
        return self._token

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
        token_preview = self._token[:12] + "..." if len(self._token) > 12 else self._token
        return f"AuthClient(token={token_preview!r})"
