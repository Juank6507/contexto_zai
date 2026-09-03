"""Cliente de extracción de mensajes de chat.z.ai.

Extrae el árbol de mensajes y su contenido completo vía API pública de shares.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TextIO

import httpx

from contexto_zai.config import API_CONFIG
from contexto_zai.models import Message, MessageRole

logger = logging.getLogger(__name__)


class ChatClientError(Exception):
    """Error base del ChatClient."""


class MessageTreeError(ChatClientError):
    """Error al obtener el árbol de mensajes."""


class BatchExtractionError(ChatClientError):
    """Error al extraer el contenido de mensajes en batch."""


class ChatClient:
    """Extrae mensajes completos de un chat compartido en chat.z.ai.

    Args:
        timeout: Timeout en segundos para las solicitudes.

    Usage:
        >>> client = ChatClient()
        >>> messages = client.extract_all("share-uuid-here")
        >>> print(f"Extraídos: {len(messages)} mensajes")
    """

    def __init__(self, timeout: float = API_CONFIG.timeout_seconds) -> None:
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

    # ── Métodos públicos ───────────────────────────────────────

    def get_message_tree(self, share_id: str) -> dict:
        """Obtiene el árbol de mensajes de un chat compartido.

        Args:
            share_id: UUID del share link.

        Returns:
            Diccionario con la estructura del chat. Clave relevante:
                - chat.id → chat_id interno
                - chat.history.messages → mapa de {msg_id: metadata}

        Raises:
            MessageTreeError: Si la solicitud falla.
        """
        url = f"{self._base_url}/api/v1/chats/share/{share_id}"

        logger.debug("Obteniendo árbol de mensajes: %s", url)
        response = self._client.get(url)

        if response.status_code in (401, 403):
            raise MessageTreeError(
                f"Acceso denegado al share {share_id} (HTTP {response.status_code}). "
                f"Verifica que el share sea público o que el token sea válido."
            )

        if response.status_code == 404:
            raise MessageTreeError(
                f"Share {share_id} no encontrado (HTTP 404)."
            )

        response.raise_for_status()
        data = response.json()
        logger.info(
            "Árbol obtenido. chat_id=%s, mensajes en árbol=%d",
            data.get("chat", {}).get("id", "?"),
            len(data.get("chat", {}).get("history", {}).get("messages", {})),
        )
        return data

    def get_messages_batch(self, share_id: str, message_ids: list[str]) -> dict:
        """Extrae el contenido completo de una lista de mensajes.

        Args:
            share_id: UUID del share link.
            message_ids: Lista de IDs de mensajes a extraer.

        Returns:
            Diccionario {msg_id: {content, content_blocks, role, ...}}.

        Raises:
            BatchExtractionError: Si la solicitud falla.
        """
        url = f"{self._base_url}/api/v1/chats/share/{share_id}/messages/batch"
        payload = {"ids": message_ids}

        logger.debug(
            "Extrayendo batch de %d mensajes desde share %s",
            len(message_ids),
            share_id,
        )
        response = self._client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )

        if response.status_code in (401, 403):
            raise BatchExtractionError(
                f"Acceso denegado al batch (HTTP {response.status_code})."
            )

        response.raise_for_status()
        data = response.json()
        extracted = data.get("data", {})
        logger.info("Batch extraído: %d/%d mensajes con contenido", len(extracted), len(message_ids))
        return data

    def extract_all(self, share_id: str) -> list[Message]:
        """Extrae todos los mensajes de un chat compartido.

        Orquesta: get_message_tree → ordenar IDs → get_messages_batch → parsear.

        Args:
            share_id: UUID del share link.

        Returns:
            Lista de objetos Message ordenados cronológicamente.

        Raises:
            ChatClientError: Si cualquier paso falla.
        """
        # Paso 1: Obtener árbol
        tree_data = self.get_message_tree(share_id)

        chat_data = tree_data.get("chat", {})
        chat_id = chat_data.get("id", "desconocido")
        messages_map = (
            chat_data.get("history", {}).get("messages", {})
        )

        if not messages_map:
            logger.warning("El chat %s no tiene mensajes en el árbol.", chat_id)
            return []

        # Paso 2: Ordenar IDs cronológicamente
        sorted_ids = sorted(
            messages_map.keys(),
            key=lambda mid: messages_map[mid].get("timestamp", 0),
        )

        # Paso 3: Extraer contenido en batch
        batch_data = self.get_messages_batch(share_id, sorted_ids)
        content_map = batch_data.get("data", {})

        # Paso 4: Construir objetos Message
        messages: list[Message] = []
        for seq, msg_id in enumerate(sorted_ids, start=1):
            msg_raw = content_map.get(msg_id)
            if not msg_raw:
                logger.debug("Mensaje %s sin contenido, saltando.", msg_id)
                continue

            content = self._extract_content(msg_raw)
            role_str = msg_raw.get("role", "user")
            try:
                role = MessageRole(role_str)
            except ValueError:
                role = MessageRole.USER

            messages.append(
                Message(
                    seq=seq,
                    role=role,
                    timestamp=msg_raw.get("timestamp", 0),
                    model=msg_raw.get("model_name", ""),
                    content=content,
                )
            )

        logger.info(
            "Extracción completa: %d mensajes de chat %s",
            len(messages),
            chat_id,
        )
        return messages

    def load_from_file(self, file_path: str | Path) -> list[Message]:
        """Carga mensajes desde un archivo JSON previamente exportado.

        Args:
            file_path: Ruta al archivo JSON con los mensajes.

        Returns:
            Lista de objetos Message.
        """
        path = Path(file_path)
        if not path.exists():
            raise ChatClientError(f"Archivo no encontrado: {path}")

        with open(path, "r", encoding="utf-8") as f:
            raw_messages = json.load(f)

        messages: list[Message] = []
        for item in raw_messages:
            role_str = item.get("role", "user")
            try:
                role = MessageRole(role_str)
            except ValueError:
                role = MessageRole.USER

            messages.append(
                Message(
                    seq=item.get("seq", len(messages) + 1),
                    role=role,
                    timestamp=item.get("timestamp", 0),
                    model=item.get("model", ""),
                    content=item.get("content", ""),
                )
            )

        logger.info("Cargados %d mensajes desde %s", len(messages), path)
        return messages

    def close(self) -> None:
        """Cierra el cliente HTTP."""
        self._client.close()

    def __enter__(self) -> "ChatClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"ChatClient(base_url={self._base_url!r})"

    # ── Métodos privados ──────────────────────────────────────

    @staticmethod
    def _extract_content(msg_raw: dict) -> str:
        """Extrae el contenido textual de un mensaje crudo.

        Prioriza el campo 'content' string. Si es un dict o tiene
        'content_blocks', los concatena.
        """
        content = msg_raw.get("content", "")

        if isinstance(content, str):
            return content

        # content_blocks puede contener texto y otros tipos
        blocks = msg_raw.get("content_blocks", [])
        if blocks:
            parts: list[str] = []
            for block in blocks:
                if isinstance(block, dict):
                    text = block.get("text", "")
                    if text:
                        parts.append(text)
                    # Si no tiene 'text', serializar el bloque completo
                    elif block.get("type") != "reasoning":
                        parts.append(json.dumps(block, ensure_ascii=False))
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(parts)

        # Fallback: serializar el content dict
        if content:
            return json.dumps(content, ensure_ascii=False)

        return ""
