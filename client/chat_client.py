# contexto_zai/client/chat_client.py -- Cliente de extraccion de mensajes: arbol de mensajes y contenido via batch (chat_id autenticado).
"""Cliente de extracción de mensajes de chat.z.ai (v3.2).

Extrae el árbol de mensajes (vía share público) y el contenido
completo de cada mensaje (vía batch autenticado por chat_id).

Cambio v3.2: el batch endpoint usa chat_id con autenticación
(cookie `token`), NO share_id como invitado. La plataforma cambió
desde v2.2.
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
from pathlib import Path
from typing import Optional

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
    """Extrae mensajes completos de un chat de chat.z.ai.

    v3.2: El batch endpoint requiere autenticación (cookie `token`).
    Se puede proporcionar el token directamente (modo legacy) o vía
    una BrowserSession inyectada (modo v3.2).

    Args:
        token: JWT del Director para autenticación batch.
            Si es None, se debe proporcionar browser_session.
        browser_session: Sesión del navegador (v3.2) para leer el token
            de la cookie automáticamente. Opcional.
        timeout: Timeout en segundos para las solicitudes.

    Usage (modo v3.2)::
        >>> session = BrowserSession()
        >>> client = ChatClient(browser_session=session)
        >>> messages = client.extract_all(share_id="...", chat_id="...")

    Usage (modo legacy)::
        >>> client = ChatClient(token="eyJhbG...")
        >>> messages = client.extract_all(share_id="...", chat_id="...")
    """

    def __init__(
        self,
        token: Optional[str] = None,
        browser_session=None,
        timeout: float = API_CONFIG.timeout_seconds,
    ) -> None:
        self._token = token.strip() if token else ""
        self._browser_session = browser_session
        self._timeout = timeout
        self._base_url = API_CONFIG.base_url
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "ContextoZAI/3.2",
                "Accept": "application/json",
            },
        )

    # -- Métodos públicos ---------------------------------------

    def get_message_tree(self, share_id: str) -> dict:
        """Obtiene el árbol de mensajes de un chat compartido.

        v3.2: Aunque históricamente era público, ahora requiere
        autenticación (cookie `token`) en la mayoría de chats.

        Args:
            share_id: UUID del share link.

        Returns:
            Diccionario con la estructura del chat. Clave relevante:
                - chat.id -> chat_id interno
                - chat.history.messages -> mapa de {msg_id: metadata}

        Raises:
            MessageTreeError: Si la solicitud falla.
        """
        url = f"{self._base_url}/api/v1/chats/share/{share_id}"

        # v3.2: adjuntar cookie de autenticación si hay token
        cookies = {}
        token = self._get_effective_token()
        if token:
            cookies = {API_CONFIG.cookie_name: token}

        logger.debug("Obteniendo arbol de mensajes: %s", url)
        response = self._client.get(url, cookies=cookies or None)

        if response.status_code in (401, 403):
            raise MessageTreeError(
                f"Acceso denegado al share {share_id} (HTTP {response.status_code}). "
                f"v3.2: este endpoint requiere autenticación. Proporciona token=... "
                f"o browser_session=... al crear ChatClient."
            )

        if response.status_code == 404:
            raise MessageTreeError(
                f"Share {share_id} no encontrado (HTTP 404)."
            )

        response.raise_for_status()
        data = response.json()
        logger.info(
            "Arbol obtenido. chat_id=%s, mensajes en arbol=%d",
            data.get("chat", {}).get("id", "?"),
            len(data.get("chat", {}).get("history", {}).get("messages", {})),
        )
        return data

    def get_messages_batch(
        self,
        chat_id: str,
        message_ids: list[str],
        share_id: Optional[str] = None,
    ) -> dict:
        """Extrae el contenido completo de una lista de mensajes (v3.2).

        v3.2: Usa el endpoint autenticado por chat_id.
        El endpoint por share_id como invitado dejó de funcionar.

        Args:
            chat_id: UUID interno del chat (requerido para autenticación).
            message_ids: Lista de IDs de mensajes a extraer.
            share_id: UUID del share (obsoleto en v3.2, ignorado).

        Returns:
            Diccionario {data: {msg_id: {content, content_blocks, ...}}}.

        Raises:
            BatchExtractionError: Si la solicitud falla o no hay token.
        """
        token = self._get_effective_token()
        if not token:
            raise BatchExtractionError(
                "Se requiere token para el batch endpoint (v3.2). "
                "Proporciona token=... o browser_session=... al crear ChatClient."
            )

        url = API_CONFIG.messages_batch_by_chat_url.format(chat_id=chat_id)
        payload = {"ids": message_ids}
        cookies = {API_CONFIG.cookie_name: token}

        logger.debug(
            "Extrayendo batch de %d mensajes desde chat %s (v3.2 autenticado)",
            len(message_ids),
            chat_id,
        )
        response = self._client.post(
            url,
            json=payload,
            cookies=cookies,
            headers={"Content-Type": "application/json"},
        )

        if response.status_code in (401, 403):
            raise BatchExtractionError(
                f"Acceso denegado al batch (HTTP {response.status_code}). "
                f"El token puede ser inválido o de invitado."
            )

        if response.status_code == 404:
            raise BatchExtractionError(
                f"Chat {chat_id} no encontrado (HTTP 404). "
                f"Verifica que el chat_id sea correcto y el token tenga acceso."
            )

        response.raise_for_status()
        data = response.json()
        extracted = data.get("data", {})
        logger.info(
            "Batch extraido: %d/%d mensajes con contenido",
            len(extracted),
            len(message_ids),
        )
        return data

    def extract_all(
        self,
        share_id: str,
        chat_id: Optional[str] = None,
    ) -> list[Message]:
        """Extrae todos los mensajes de un chat compartido.

        Orquesta: get_message_tree -> ordenar IDs -> get_messages_batch -> parsear.

        v3.2: Si chat_id es None, se descubre del árbol de mensajes.
        El batch usa chat_id autenticado, no share_id.

        Args:
            share_id: UUID del share link.
            chat_id: UUID interno del chat. Si es None, se obtiene
                automáticamente del árbol.

        Returns:
            Lista de objetos Message ordenados cronológicamente.

        Raises:
            ChatClientError: Si cualquier paso falla.
        """
        # Paso 1: Obtener árbol
        tree_data = self.get_message_tree(share_id)

        chat_data = tree_data.get("chat", {})
        resolved_chat_id = chat_id or chat_data.get("id", "")
        if not resolved_chat_id:
            raise ChatClientError(
                "No se pudo determinar el chat_id. "
                "Proporciónalo explícitamente: extract_all(share_id=..., chat_id=...)"
            )

        messages_map = (
            chat_data.get("history", {}).get("messages", {})
        )

        if not messages_map:
            logger.warning("El chat %s no tiene mensajes en el arbol.", resolved_chat_id)
            return []

        # Paso 2: Ordenar IDs cronológicamente
        sorted_ids = sorted(
            messages_map.keys(),
            key=lambda mid: messages_map[mid].get("timestamp", 0),
        )

        # Paso 3: Extraer contenido en batch (v3.2: con chat_id autenticado)
        batch_data = self.get_messages_batch(resolved_chat_id, sorted_ids, share_id=share_id)
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

            # model_name puede ser None; convertir a string vacío
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
            "Extraccion completa: %d mensajes de chat %s",
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
                    model=item.get("model") or "",
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
        mode = "browser" if self._browser_session else ("token" if self._token else "none")
        return f"ChatClient(mode={mode!r}, base_url={self._base_url!r})"

    # -- Métodos privados --------------------------------------

    def _get_effective_token(self) -> Optional[str]:
        """Obtiene el token efectivo: explícito o desde la cookie del navegador."""
        if self._token:
            return self._token
        if self._browser_session:
            cookie = self._browser_session.get_token_cookie()
            if cookie and not cookie.is_guest:
                return cookie.value
        return None

    @staticmethod
    def _extract_content(msg_raw: dict) -> str:
        """Extrae el contenido textual de un mensaje crudo.

        Prioriza el campo 'content' string si no es vacío. Si es un
        dict o tiene 'content_blocks', los concatena.
        """
        content = msg_raw.get("content", "")

        # content como string no vacío: usarlo directamente
        if isinstance(content, str) and content:
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
            if parts:
                return "\n".join(parts)

        # Fallback: si content es string (aunque sea vacío)
        if isinstance(content, str):
            return content

        # Fallback: serializar el content dict
        if content:
            return json.dumps(content, ensure_ascii=False)

        return ""

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
    # -- Validación interna de chat_client.py (atómico standalone) --
    print("=== Validacion de chat_client.py ===\n")

    import tempfile
    from pathlib import Path
    from contexto_zai.client.browser_session import BrowserSession

    # Test 1: modo legacy con token
    client_legacy = ChatClient(token="eyJhbG.test.payload")
    assert client_legacy._get_effective_token() == "eyJhbG.test.payload"
    print(f"[OK] Modo legacy: {client_legacy!r}")

    # Test 2: modo navegador v3.2 (sin token en cookie -> None)
    with tempfile.TemporaryDirectory() as tmpdir:
        session = BrowserSession(auth_state_path=Path(tmpdir) / "state.json")
        client_v3 = ChatClient(browser_session=session)
        # Como no hay navegador real, _get_effective_token devuelve None
        # (BrowserSession.get_token_cookie() devuelve None si agent-browser no está corriendo)
        assert client_v3._get_effective_token() is None
        print(f"[OK] Modo navegador v3.2: {client_v3!r}")

    # Test 3: sin token ni browser_session -> None
    client_no_auth = ChatClient()
    assert client_no_auth._get_effective_token() is None
    print(f"[OK] Sin autenticacion: {client_no_auth!r}")

    # Test 4: get_messages_batch sin token lanza BatchExtractionError
    try:
        client_no_auth.get_messages_batch(chat_id="abc", message_ids=["1"])
        assert False, "Debería haber lanzado BatchExtractionError"
    except BatchExtractionError as e:
        print(f"[OK] get_messages_batch sin token: error correcto")

    # Test 5: _extract_content con string
    content = ChatClient._extract_content({"content": "hola"})
    assert content == "hola"
    print(f"[OK] _extract_content string: OK")

    # Test 6: _extract_content con content_blocks
    content = ChatClient._extract_content({
        "content_blocks": [{"text": "parte1"}, {"text": "parte2"}]
    })
    assert "parte1" in content and "parte2" in content
    print(f"[OK] _extract_content blocks: OK")

    # Test 7: _extract_content filtra reasoning
    content = ChatClient._extract_content({
        "content_blocks": [{"type": "reasoning", "content": "oculto"}, {"text": "visible"}]
    })
    assert "visible" in content
    assert "oculto" not in content
    print(f"[OK] _extract_content filtra reasoning: OK")

    # Test 8: load_from_file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump([
            {"seq": 1, "role": "user", "timestamp": 1, "content": "hola"},
            {"seq": 2, "role": "assistant", "timestamp": 2, "content": "respuesta"},
        ], f)
        f.flush()
        msgs = client_legacy.load_from_file(f.name)
    assert len(msgs) == 2
    assert msgs[0].is_user
    assert msgs[1].is_assistant
    print(f"[OK] load_from_file: {len(msgs)} mensajes cargados")

    # Cerrar
    client_legacy.close()
    client_v3.close()
    client_no_auth.close()

    print("\n[PASS] chat_client.py: todos los tests pasaron")
    print("\nNota: para validar extract_all contra la API real,")
    print("      ejecutar tests/test_chat_client.py con JWT del Director")
