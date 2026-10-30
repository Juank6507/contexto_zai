# contexto_zai/processing/message_extractor.py -- Proceso de extracción que separa capas (v6.11 F3).
"""Proceso de extracción de mensajes (v6.11 F3).

Separa la capa general (procesamiento de mensajes) de la capa particular
(clientes de Z.ai). Los módulos generales (ciclos, orquestador) le piden
a este proceso lo que necesitan y no saben ni les importa cómo se obtiene.

Este proceso:
1. Crea el share (si es necesario) vía AuthClient.
2. Obtiene el árbol de mensajes vía ChatClient.
3. Filtra los message_ids por timestamp (solo los nuevos).
4. Pagina el batch en lotes de BATCH_SIZE.
5. Devuelve los mensajes con contenido.

Para cambiar de plataforma, solo se cambia este proceso; los módulos
generales no se tocan.
"""
from __future__ import annotations

import logging
from typing import Optional

from contexto_zai.client.auth_client import AuthClient
from contexto_zai.client.chat_client import ChatClient
from contexto_zai.models import Message

logger = logging.getLogger(__name__)


class MessageExtractor:
    """Proceso de extracción de mensajes que separa capas.

    La capa general le pide a este proceso lo que necesita (mensajes nuevos,
    todos los mensajes, etc.) y este proceso se encarga de hablar con los
    clientes de la plataforma (Z.ai) para obtenerlos.

    Args:
        jwt: JWT del Director.
        chat_id: UUID interno del chat.

    Usage:
        >>> extractor = MessageExtractor(jwt="eyJ...", chat_id="abc-123")
        >>> new_messages = extractor.get_new_messages(since_timestamp=1234567890.0)
        >>> all_messages = extractor.get_all_messages()
    """

    def __init__(self, jwt: str, chat_id: str) -> None:
        self._jwt = jwt
        self._chat_id = chat_id
        self._share_id: Optional[str] = None

    def _ensure_share(self) -> str:
        """Crea o reutiliza el share del chat. Devuelve el share_id."""
        if self._share_id:
            return self._share_id
        with AuthClient(token=self._jwt) as auth:
            self._share_id = auth.create_share(self._chat_id)
        logger.info(
            "MessageExtractor: share creado/reutilizado: %s",
            self._share_id[:12] if self._share_id else "N/A",
        )
        return self._share_id

    def get_all_messages(self) -> list[Message]:
        """Extrae TODOS los mensajes del chat con contenido.

        Usa el árbol + batch paginado. No filtra por timestamp.

        Returns:
            Lista de objetos Message ordenados cronológicamente.
        """
        share_id = self._ensure_share()
        with ChatClient(token=self._jwt) as client:
            messages = client.extract_all(share_id=share_id, chat_id=self._chat_id)
        logger.info(
            "MessageExtractor: %d mensajes totales extraídos del chat %s",
            len(messages),
            self._chat_id[:12] if self._chat_id else "N/A",
        )
        return messages

    def get_new_messages(self, since_timestamp: float) -> list[Message]:
        """Extrae solo los mensajes nuevos (posteriores al timestamp dado).

        v6.11 F3: este es el método clave que resuelve el bug del timeout.
        En vez de descargar todos los mensajes y filtrar después, este método:
        1. Obtiene el árbol (solo metadata, sin contenido).
        2. Filtra los message_ids por timestamp en memoria (rápido).
        3. Descarga el contenido SOLO de los mensajes nuevos, en lotes paginados.

        Args:
            since_timestamp: Timestamp del último mensaje ya procesado.
                Se devuelven solo los mensajes con timestamp mayor a este.

        Returns:
            Lista de objetos Message nuevos, ordenados cronológicamente.
        """
        share_id = self._ensure_share()

        with ChatClient(token=self._jwt) as client:
            # Paso 1: obtener el árbol (solo metadata)
            tree_data = client.get_message_tree(share_id=share_id)
            chat_data = tree_data.get("chat", {})
            resolved_chat_id = self._chat_id or chat_data.get("id", "")

            if not resolved_chat_id:
                logger.warning("MessageExtractor: no se pudo determinar el chat_id del árbol")
                return []

            messages_map = chat_data.get("history", {}).get("messages", {})
            if not messages_map:
                logger.warning("MessageExtractor: el chat %s no tiene mensajes en el árbol", resolved_chat_id[:12])
                return []

            # Paso 2: filtrar message_ids por timestamp (solo los nuevos)
            new_msg_ids = [
                mid for mid, mdata in messages_map.items()
                if mdata.get("timestamp", 0) > since_timestamp
            ]

            # Ordenar cronológicamente
            new_msg_ids.sort(
                key=lambda mid: messages_map[mid].get("timestamp", 0)
            )

            logger.info(
                "MessageExtractor: %d/%d mensajes son nuevos (ts > %d)",
                len(new_msg_ids),
                len(messages_map),
                int(since_timestamp),
            )

            if not new_msg_ids:
                return []

            # Paso 3: descargar contenido SOLO de los nuevos, en lotes paginados
            # (la paginación la hace get_messages_batch internamente con F2)
            batch_data = client.get_messages_batch(
                resolved_chat_id, new_msg_ids, share_id=share_id
            )
            content_map = batch_data.get("data", {})

            # Paso 4: construir objetos Message
            messages: list[Message] = []
            for seq, msg_id in enumerate(new_msg_ids, start=1):
                msg_raw = content_map.get(msg_id)
                if not msg_raw:
                    logger.debug("MessageExtractor: mensaje %s sin contenido, saltando.", msg_id)
                    continue

                content = ChatClient._extract_content(msg_raw)
                role_str = msg_raw.get("role", "user")
                from contexto_zai.models import MessageRole
                try:
                    role = MessageRole(role_str)
                except ValueError:
                    role = MessageRole.USER

                model_name = msg_raw.get("model_name") or msg_raw.get("model") or ""

                messages.append(
                    Message(
                        seq=seq,
                        role=role,
                        timestamp=msg_raw.get("timestamp", 0),
                        model=model_name,
                        content=content,
                    )
                )

        logger.info(
            "MessageExtractor: %d mensajes nuevos con contenido extraídos",
            len(messages),
        )
        return messages

    def get_message_tree(self) -> dict:
        """Devuelve el árbol de mensajes del chat (solo metadata, sin contenido).

        Útil para descubrir el chat_id desde un share_id, o para inspeccionar
        la estructura sin descargar contenido.

        Returns:
            Diccionario con la estructura del chat.
        """
        share_id = self._ensure_share()
        with ChatClient(token=self._jwt) as client:
            return client.get_message_tree(share_id=share_id)
