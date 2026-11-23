# contexto_zai/processing/message_extractor.py -- Proceso de extracción que separa capas (v6.11 F3 + v7.0 F2).
"""Proceso de extracción de mensajes (v6.11 F3 + v7.0 F2).

Separa la capa general (procesamiento de mensajes) de la capa particular
(clientes de Z.ai). Los módulos generales (ciclos, orquestador) le piden
a este proceso lo que necesitan y no saben ni les importa cómo se obtiene.

v7.0 F2: la separación de capas es ahora vía ABCs de
``contexto_zai.platforms.interfaces`` (``PlatformAuth``,
``PlatformChat``). En vez de importar ``AuthClient`` y ``ChatClient``
directamente, el proceso recibe las implementaciones por constructor
(default Zai) y opera contra las interfaces.

Este proceso:
1. Crea el share (si es necesario) vía ``PlatformAuth.create_share``.
2. Obtiene el árbol de mensajes vía ``PlatformChat.get_message_tree``.
3. Filtra los message_ids por timestamp (solo los nuevos).
4. Pagina el batch en lotes de BATCH_SIZE.
5. Devuelve los mensajes con contenido.

Para cambiar de plataforma, solo se inyectan implementaciones distintas
de ``PlatformAuth`` y ``PlatformChat`` (o se crea un subpaquete nuevo
en ``platforms/`` con clases que implementen las ABCs).
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


import logging
from typing import Optional

# v7.0 F2: imports de las ABCs y de las implementaciones concretas Zai.
# Los módulos generales (process/, generation/) ya no importan de
# ``client/`` directamente: importan de ``processing/message_extractor``
# que a su vez opera contra las interfaces.
from contexto_zai.platforms.interfaces import PlatformAuth, PlatformChat
from contexto_zai.platforms.zai.zai_auth import ZaiAuth
from contexto_zai.platforms.zai.zai_chat import ZaiChat
from contexto_zai.models import Message, MessageRole

logger = logging.getLogger(__name__)


class MessageExtractor:
    """Proceso de extracción de mensajes que separa capas.

    La capa general le pide a este proceso lo que necesita (mensajes nuevos,
    todos los mensajes, etc.) y este proceso se encarga de hablar con las
    implementaciones de plataforma (``PlatformAuth``, ``PlatformChat``)
    para obtenerlos.

    v7.0 F2: el constructor acepta ``auth`` y ``chat`` inyectados (con
    default Zai) para soportar multi-plataforma. Los llamadores existentes
    que pasan solo ``jwt`` y ``chat_id`` siguen funcionando: se construyen
    ``ZaiAuth(jwt=jwt)`` y ``ZaiChat(jwt=jwt)`` por defecto.

    Args:
        jwt: JWT del Director. Usado solo si ``auth`` o ``chat`` no se
            inyectan (para construir los defaults Zai).
        chat_id: UUID interno del chat.
        auth: Implementación ``PlatformAuth`` opcional. Si es ``None``,
            se construye ``ZaiAuth(jwt=jwt)``.
        chat: Implementación ``PlatformChat`` opcional. Si es ``None``,
            se construye ``ZaiChat(jwt=jwt or auth.get_jwt())``.

    Usage:
        >>> extractor = MessageExtractor(jwt="eyJ...", chat_id="abc-123")
        >>> new_messages = extractor.get_new_messages(since_timestamp=1234567890.0)
        >>> all_messages = extractor.get_all_messages()
    """

    def __init__(
        self,
        jwt: str = "",
        chat_id: str = "",
        auth: Optional[PlatformAuth] = None,
        chat: Optional[PlatformChat] = None,
    ) -> None:
        self._jwt = jwt
        self._chat_id = chat_id
        self._share_id: Optional[str] = None
        # v7.0 F2: inyección por constructor con default Zai.
        self._auth = auth if auth is not None else ZaiAuth(jwt=jwt)
        # ZaiChat necesita el jwt (explícito o leído del auth inyectado).
        effective_jwt = jwt or self._auth.get_jwt()
        self._chat = chat if chat is not None else ZaiChat(jwt=effective_jwt)

    def _ensure_share(self) -> str:
        """Crea o reutiliza el share del chat. Devuelve el share_id.

        v7.0 F2: delega en ``PlatformAuth.create_share`` (implementación
        Zai: ``ZaiAuth.create_share`` que envuelve ``AuthClient.create_share``).
        """
        if self._share_id:
            return self._share_id
        self._share_id = self._auth.create_share(self._chat_id)
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
        # v7.0 F2: PlatformChat.extract_all (ZaiChat.extract_all delega
        # a ChatClient.extract_all).
        messages = self._chat.extract_all(
            share_id=share_id, chat_id=self._chat_id
        )
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

        # v7.0 F2: PlatformChat.get_message_tree (ZaiChat.get_message_tree
        # delega a ChatClient.get_message_tree con share_id=).
        tree_data = self._chat.get_message_tree(
            chat_id=self._chat_id, share_id=share_id
        )
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
        # v7.0 F2: PlatformChat.get_messages_batch (ZaiChat.get_messages_batch
        # delega a ChatClient.get_messages_batch con chat_id, message_ids, share_id=).
        batch_data = self._chat.get_messages_batch(
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

            # v7.0 F2: PlatformChat.extract_content (ZaiChat.extract_content
            # delega a ChatClient._extract_content, método estático).
            content = self._chat.extract_content(msg_raw)
            role_str = msg_raw.get("role", "user")
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
        # v7.0 F2: PlatformChat.get_message_tree (ZaiChat.get_message_tree
        # delega a ChatClient.get_message_tree con share_id=).
        return self._chat.get_message_tree(
            chat_id=self._chat_id, share_id=share_id
        )
