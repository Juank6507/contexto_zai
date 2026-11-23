"""contexto_zai/platforms/zai/zai_chat.py -- Implementacion Zai de PlatformChat (v7.0 F2).

Envuelve ``ChatClient`` (extraccion de mensajes de chat.z.ai). NO lo
reemplaza: la abstraccion vive aqui, la implementacion HTTP sigue en
``client/chat_client.py``.

Inyeccion por constructor: si un llamador no inyecta nada, se usa la
implementacion Zai por defecto (construye un ``ChatClient(token=jwt)``).
"""
from __future__ import annotations

import logging
from typing import Optional

from contexto_zai.platforms.interfaces import PlatformChat
from contexto_zai.client.chat_client import ChatClient
from contexto_zai.models import Message

logger = logging.getLogger(__name__)


class ZaiChat(PlatformChat):
    """Implementacion Zai de ``PlatformChat``.

    Envuelve ``ChatClient`` para extraer mensajes de chat.z.ai via
    share link + batch autenticado.

    Args:
        jwt: JWT del Director para autenticacion batch. Si es vacio,
            el ``ChatClient`` se crea sin token (no podra hacer batch,
            pero si get_message_tree en chats publicos).

    Usage:
        >>> chat = ZaiChat(jwt="eyJhbG...")
        >>> tree = chat.get_message_tree(chat_id="", share_id="abc-123")
        >>> messages = chat.extract_all(share_id="abc-123", chat_id="def-456")
    """

    def __init__(self, jwt: str = "") -> None:
        # ChatClient acepta token=None (modo browser v3.2) o token=str.
        # Si jwt es vacio, pasamos None para que intente la cookie del
        # navegador (igual que el MessageExtractor original).
        self._jwt = jwt or ""
        self._client = ChatClient(token=self._jwt) if self._jwt else ChatClient()

    # -- PlatformChat API --------------------------------------------

    def get_message_tree(
        self,
        chat_id: str,
        share_id: Optional[str] = None,
    ) -> dict:
        """Obtiene el arbol de mensajes de un chat compartido.

        En Zai, el endpoint historico solo necesita ``share_id`` (no
        ``chat_id``). El ``chat_id`` se ignora a nivel HTTP pero se
        acepta por compatibilidad con la interfaz abstracta.

        Args:
            chat_id: UUID interno del chat (no usado por el endpoint
                Zai, pero requerido por ``PlatformChat``).
            share_id: UUID del share link (requerido por Zai v3.2).

        Returns:
            Diccionario con la estructura del chat.
        """
        if not share_id:
            raise ValueError(
                "ZaiChat.get_message_tree requiere share_id (Zai v3.2). "
                "Llama a PlatformAuth.create_share(chat_id) primero."
            )
        return self._client.get_message_tree(share_id=share_id)

    def get_messages_batch(
        self,
        chat_id: str,
        message_ids: list,
        share_id: Optional[str] = None,
    ) -> dict:
        """Extrae el contenido completo de una lista de mensajes (batch).

        Delega en ``ChatClient.get_messages_batch``. ``share_id`` se
        acepta por compatibilidad con la interfaz abstracta pero Zai
        v3.2 lo ignora (el batch usa chat_id autenticado).

        Args:
            chat_id: UUID interno del chat (autenticacion).
            message_ids: Lista de IDs de mensajes a extraer.
            share_id: UUID del share (ignorado en Zai v3.2).

        Returns:
            Diccionario {data: {msg_id: {content, ...}}}.
        """
        return self._client.get_messages_batch(
            chat_id=chat_id,
            message_ids=message_ids,
            share_id=share_id,
        )

    def get_all_messages(
        self,
        chat_id: str,
        from_timestamp: float = 0.0,
    ) -> list:
        """Extrae TODOS los mensajes del chat con contenido.

        v7.0 F2: implementacion nueva que respeta el contrato abstracto
        ``get_all_messages(chat_id, from_timestamp)``. NO requiere que
        el llamador pase un ``share_id``: lo crea internamente via
        ``ChatClient`` (que descubre el chat del arbol si hace falta).

        Para preservar el comportamiento exacto del MessageExtractor
        original, los llamadores internos siguen usando ``extract_all``
        (que recibe share_id explicito). Este metodo existe por
        completitud de la interfaz.

        Args:
            chat_id: UUID interno del chat.
            from_timestamp: Si > 0, filtra solo mensajes posteriores.

        Returns:
            Lista de objetos Message ordenados cronologicamente.
        """
        # Si no hay chat_id, no podemos crear share.
        if not chat_id:
            logger.warning(
                "ZaiChat.get_all_messages: chat_id vacio, no se puede crear share."
            )
            return []
        # Crear share via AuthClient (inyectado por separado en
        # MessageExtractor; aqui usamos ChatClient directamente que
        # delega internamente). En v7.0 F2, el MessageExtractor pasa
        # share_id explicito por eso esta funcion rara vez se llama
        # directamente.
        from contexto_zai.client.auth_client import AuthClient
        with AuthClient(token=self._jwt) as auth:
            share_id = auth.create_share(chat_id)
        messages = self._client.extract_all(
            share_id=share_id, chat_id=chat_id
        )
        if from_timestamp > 0.0:
            messages = [
                m for m in messages
                if getattr(m, "timestamp", 0) > from_timestamp
            ]
        return messages

    def extract_all(
        self,
        share_id: str,
        chat_id: Optional[str] = None,
    ) -> list:
        """Wrapper de ``ChatClient.extract_all`` (backward-compat).

        Orquesta: get_message_tree -> ordenar IDs -> get_messages_batch
        -> parsear a objetos Message.

        Args:
            share_id: UUID del share link.
            chat_id: UUID interno del chat. Si es None, se descubre del
                arbol de mensajes.

        Returns:
            Lista de objetos Message ordenados cronologicamente.
        """
        return self._client.extract_all(share_id=share_id, chat_id=chat_id)

    def extract_content(self, msg_raw: dict) -> str:
        """Extrae el contenido textual de un mensaje crudo.

        Delega en ``ChatClient._extract_content`` (metodo estatico del
        cliente Zai). Es el mismo comportamiento que tenia el
        ``MessageExtractor`` original cuando llamaba
        ``ChatClient._extract_content(msg_raw)``.

        Args:
            msg_raw: Diccionario con el mensaje crudo del batch endpoint.

        Returns:
            String con el contenido textual del mensaje.
        """
        return ChatClient._extract_content(msg_raw)

    def __repr__(self) -> str:
        mode = "token" if self._jwt else "browser-or-none"
        return f"ZaiChat(mode={mode!r})"
