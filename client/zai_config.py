# contexto_zai/client/zai_config.py -- Configuracion particular de la plataforma Z.ai (v6.11 F1).
"""Configuración particular de los endpoints de chat.z.ai.

v6.11 F1: separada de config.py para cumplir la separación de capas.
Lo particular de Z.ai (URLs, cookies, endpoints) vive aquí;
lo general (límites, rutas, reglas) vive en config.py.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class APIConfig:
    """Configuración de los endpoints de chat.z.ai.

    Nota v3.2: El batch endpoint usa chat_id con autenticación, NO share_id
    como invitado. La plataforma cambió desde v2.2.
    """

    base_url: str = "https://chat.z.ai"
    timeout_seconds: float = 30.0
    cookie_name: str = "token"

    @property
    def share_info_url(self) -> str:
        return f"{self.base_url}/api/v1/chats/share/{{share_id}}"

    @property
    def messages_batch_by_chat_url(self) -> str:
        """Endpoint de batch autenticado por chat_id (v3.2)."""
        return f"{self.base_url}/api/v1/chats/{{chat_id}}/messages/batch"

    @property
    def create_share_url(self) -> str:
        return f"{self.base_url}/api/v1/chats/{{chat_id}}/share"

    @property
    def auth_check_url(self) -> str:
        return f"{self.base_url}/api/v1/auths/"


API_CONFIG = APIConfig()
