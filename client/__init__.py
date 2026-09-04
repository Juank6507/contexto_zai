"""Cliente HTTP para interactuar con la API de chat.z.ai (v3.2).

Exporta:
    AuthClient       — Autenticación y gestión de shares (legacy + v3.2).
    ChatClient       — Extracción de mensajes (legacy + v3.2).
    BrowserSession   — Sesión del navegador para autenticación automática (v3.2).
"""

from contexto_zai.client.auth_client import AuthClient
from contexto_zai.client.browser_session import BrowserSession
from contexto_zai.client.chat_client import ChatClient

__all__ = ["AuthClient", "ChatClient", "BrowserSession"]
