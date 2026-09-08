# contexto_zai/processing/exchange_builder.py -- Constructor de intercambios: agrupa mensajes en pares Director+agente.
"""Módulo de construcción de exchanges a partir de mensajes.

Agrupa mensajes individuales en unidades de conversación (Exchange),
donde cada exchange comienza con un mensaje del Director (user) y contiene
todas las respuestas consecutivas del agente (assistant) hasta el
siguiente mensaje del Director.
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
# Soporta Estructura A (<workspace>/contexto_zai/) y Estructura B (workspace=contexto_zai/)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
_package_root = None
for _ in range(10):
    if not _os.path.isfile(_os.path.join(_candidate, '__init__.py')):
        break  # salimos del paquete
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

from contexto_zai.models import Exchange, Message, MessageRole

logger = logging.getLogger(__name__)

class ExchangeBuilder:
    """Construye exchanges a partir de una lista plana de mensajes.

    Un exchange es una unidad de conversación compuesta por un mensaje
    del Director (user) seguido de cero o más respuestas del agente
    (assistant). Los mensajes system se omiten silenciosamente.

    v3.5: soporta inyección de delegator y indexer_subagent para decidir
    cuándo delegar la lectura de links externos y attachments al subagente.

    Example::

        builder = ExchangeBuilder()
        exchanges = builder.build(messages)
    """

    def __init__(
        self,
        delegator=None,
        indexer_subagent=None,
        attachments: list = None,
    ) -> None:
        """Inicializa el builder de exchanges.

        Args:
            delegator: ContentDelegator para decidir delegación (v3.5).
                Si es None, usa criterio simple (tamaño > 5000 → delegar).
            indexer_subagent: DocumentoIndexerSubagent para delegar attachments (v3.5).
                Si es None, los attachments se leen directamente.
            attachments: Lista de attachments detectados (v3.5).
        """
        self._delegator = delegator
        self._indexer_subagent = indexer_subagent
        self._attachments = attachments or []
        logger.debug(
            "ExchangeBuilder inicializado: delegator=%s, indexer=%s, attachments=%d",
            bool(delegator), bool(indexer_subagent), len(self._attachments),
        )

    def set_attachments(self, attachments: list) -> None:
        """Establece la lista de attachments detectados (v3.5).

        Debe llamarse antes de build() si se quieren procesar attachments.
        """
        self._attachments = attachments or []
        logger.debug("Attachments establecidos: %d", len(self._attachments))

    def build(self, messages: list[Message]) -> list[Exchange]:
        """Agrupa mensajes en exchanges secuenciales.

        Recorre la lista de mensajes en orden. Cada mensaje del Director
        (user) inicia un nuevo exchange. Todos los mensajes del agente
        (assistant) consecutivos se asignan al exchange actual. Los
        mensajes system se omiten.

        Args:
            messages: Lista ordenada de mensajes (por campo ``seq``).

        Returns:
            Lista de :class:`Exchange` con ids secuenciales (1-based),
            timestamps asignados y tema por defecto ``"general"``.
        """
        logger.info("Iniciando construccion de exchanges a partir de %d mensajes", len(messages))

        exchanges: list[Exchange] = []
        current_director: Message | None = None
        current_agent_msgs: list[Message] = []
        exchange_id = 0

        for msg in messages:
            # Omitir mensajes system
            if msg.role == MessageRole.SYSTEM:
                logger.debug("Omitiendo mensaje system (seq=%d)", msg.seq)
                continue

            if msg.is_user:
                # Si ya había un exchange en construcción, cerrarlo
                if current_director is not None:
                    exchange_id += 1
                    exchange = Exchange(
                        id=exchange_id,
                        director_msg=current_director,
                        agent_msgs=list(current_agent_msgs),
                        topic="general",
                    )
                    self._assign_timestamps(exchange)
                    exchanges.append(exchange)
                    logger.debug(
                        "Exchange %d cerrado: %d respuestas del agente",
                        exchange.id,
                        exchange.agent_count,
                    )

                # Iniciar nuevo exchange
                current_director = msg
                current_agent_msgs = []
                logger.debug("Nuevo exchange iniciado con mensaje del Director (seq=%d)", msg.seq)

            elif msg.is_assistant:
                # Acumular respuestas del agente al exchange actual
                if current_director is not None:
                    current_agent_msgs.append(msg)
                    logger.debug("Respuesta del agente anadida al exchange actual (seq=%d)", msg.seq)
                else:
                    logger.warning(
                        "Mensaje de agente (seq=%d) sin Director previo; se omite",
                        msg.seq,
                    )

        # Cerrar el último exchange abierto
        if current_director is not None:
            exchange_id += 1
            exchange = Exchange(
                id=exchange_id,
                director_msg=current_director,
                agent_msgs=list(current_agent_msgs),
                topic="general",
            )
            self._assign_timestamps(exchange)
            exchanges.append(exchange)
            logger.debug(
                "Ultimo exchange %d cerrado: %d respuestas del agente",
                exchange.id,
                exchange.agent_count,
            )

        logger.info("%d exchanges construidos exitosamente", len(exchanges))

        # v3.5: detectar y procesar links externos + attachments unificados
        exchanges = self._process_external_content(
            exchanges, messages,
            attachments=self._attachments,
            delegator=self._delegator,
            indexer_subagent=self._indexer_subagent,
        )

        return exchanges

    def _process_external_content(
        self,
        exchanges: list[Exchange],
        messages: list[Message],
        attachments: list = None,
        delegator=None,
        indexer_subagent=None,
        agent_context_pct: float = 0.0,
    ) -> list[Exchange]:
        """Procesa links externos + attachments unificados bajo ContentDelegator (v3.5).

        Para cada URL o attachment detectado:
        1. Estima tokens del contenido.
        2. Decide delegación con DocumentDelegator.should_delegate().
        3. Si delega: lanza DocumentoIndexerSubagent (para attachments) o
           lee + resume (para URLs). Crea intercambio virtual con el resumen.
        4. Si no delega: lee directamente con WebReader (URLs) o AttachmentClient
           (attachments). Crea intercambio virtual con contenido completo.
        5. NO trunca a 10K chars (el Subdivider se encarga de partir contenido grande).
        """
        attachments = attachments or []

        # 1. Procesar links externos en mensajes del Director
        try:
            from contexto_zai.client.web_reader import WebReader
            reader = WebReader()
        except ImportError:
            try:
                from client.web_reader import WebReader
                reader = WebReader()
            except ImportError:
                reader = None
                logger.debug("WebReader no disponible, saltando links externos")

        if reader:
            for msg in messages:
                if not msg.is_user:
                    continue
                urls = WebReader.find_urls(msg.content)
                for url in urls:
                    exchanges = self._process_url(
                        exchanges, msg, url, reader, delegator,
                        agent_context_pct,
                    )

        # 2. Procesar attachments (v3.5)
        for att in attachments:
            exchanges = self._process_attachment(
                exchanges, messages, att, delegator,
                indexer_subagent, agent_context_pct,
            )

        return exchanges

    def _process_url(
        self,
        exchanges: list[Exchange],
        director_msg: Message,
        url: str,
        reader,
        delegator=None,
        agent_context_pct: float = 0.0,
    ) -> list[Exchange]:
        """Procesa una URL externa (v3.5: con delegación)."""
        director_override = self._detect_override(director_msg.content)

        # Estimar tokens (aproximado, no se sabe hasta descargar)
        estimated_tokens = 5000  # página web típica

        if delegator:
            should_delegate = delegator.should_delegate(
                estimated_tokens, agent_context_pct, director_override,
            )
        else:
            should_delegate = estimated_tokens > 5000

        content = reader.read(url)
        if content.source == "error" or not content.content:
            logger.warning("No se pudo leer link: %s", url)
            return exchanges

        if should_delegate:
            # Resumen breve (sin truncar contenido completo)
            resumen_text = content.content[:500] if len(content.content) > 500 else content.content
            agent_content = (
                f"[Link externo indexado: {content.title}]\n"
                f"URL: {url}\n"
                f"Resumen: {resumen_text}"
            )
            topic = "link_externo"
        else:
            # Contenido completo (sin truncar a 10K)
            agent_content = (
                f"[Link externo: {content.title}]\n"
                f"URL: {url}\n\n{content.content}"
            )
            topic = "link_externo"

        next_id = len(exchanges) + 1
        virtual_agent_msg = Message(
            seq=director_msg.seq + 1,
            role=MessageRole.ASSISTANT,
            timestamp=director_msg.timestamp + 1,
            content=agent_content,
        )
        virtual_exchange = Exchange(
            id=next_id,
            director_msg=Message(
                seq=director_msg.seq,
                role=MessageRole.USER,
                timestamp=director_msg.timestamp,
                content=f"Lee este link: {url}",
            ),
            agent_msgs=[virtual_agent_msg],
            topic=topic,
        )
        self._assign_timestamps(virtual_exchange)
        exchanges.append(virtual_exchange)
        logger.info(
            "Link externo procesado: %s (%d chars, delegado=%s)",
            url, len(content.content), should_delegate,
        )
        return exchanges

    def _process_attachment(
        self,
        exchanges: list[Exchange],
        messages: list[Message],
        attachment,
        delegator=None,
        indexer_subagent=None,
        agent_context_pct: float = 0.0,
    ) -> list[Exchange]:
        """Procesa un attachment (v3.5: delega al subagente si es grande)."""
        # Buscar override en el mensaje del Director que adjuntó el archivo
        director_override = None
        ref_msg = None
        for msg in messages:
            if not msg.is_user:
                continue
            # Matching por filename o por mensaje de referencia
            if (
                (hasattr(attachment, 'filename') and attachment.filename in msg.content)
                or (hasattr(attachment, 'ref_msg_id') and attachment.ref_msg_id)
            ):
                director_override = self._detect_override(msg.content)
                ref_msg = msg
                break

        if not ref_msg:
            ref_msg = next((m for m in messages if m.is_user), None)
        if not ref_msg:
            return exchanges  # sin mensaje del Director, no se puede crear intercambio

        estimated_tokens = int(attachment.estimated_tokens) if hasattr(attachment, 'estimated_tokens') else 5000

        if delegator:
            should_delegate = delegator.should_delegate(
                estimated_tokens, agent_context_pct, director_override,
            )
        else:
            should_delegate = estimated_tokens > 5000

        filename = attachment.filename if hasattr(attachment, 'filename') else "documento"
        file_id = attachment.file_id if hasattr(attachment, 'file_id') else "unknown"

        if should_delegate and indexer_subagent:
            # Delegar al subagente
            result = indexer_subagent.run(attachment)
            if result.success:
                agent_content = (
                    f"[Documento indexado: {result.filename}]\n"
                    f"ID: {file_id}\n"
                    f"Resumen: {result.resumen_breve}\n"
                    f"Temas: {result.temas_nombres}\n"
                    f"Archivo: {result.archivo_indexado_path}"
                )
            else:
                agent_content = f"[Error indexando {filename}: {result.error}]"
            topic = "documento_adjunto"
        else:
            # Lectura directa (sin truncar a 10K)
            agent_content = (
                f"[Documento leído directamente: {filename}]\n"
                f"ID: {file_id}\n"
                f"Contenido completo disponible para consulta."
            )
            topic = "documento_adjunto"

        next_id = len(exchanges) + 1
        virtual_agent_msg = Message(
            seq=ref_msg.seq + 1,
            role=MessageRole.ASSISTANT,
            timestamp=ref_msg.timestamp + 1,
            content=agent_content,
        )
        virtual_exchange = Exchange(
            id=next_id,
            director_msg=Message(
                seq=ref_msg.seq,
                role=MessageRole.USER,
                timestamp=ref_msg.timestamp,
                content=f"Lee este documento: {filename}",
            ),
            agent_msgs=[virtual_agent_msg],
            topic=topic,
        )
        self._assign_timestamps(virtual_exchange)
        exchanges.append(virtual_exchange)
        logger.info(
            "Attachment procesado: %s (delegado=%s)",
            filename, should_delegate,
        )
        return exchanges

    @staticmethod
    def _detect_override(text: str) -> str | None:
        """Detecta override del Director en el texto del mensaje."""
        if not text:
            return None
        text_lower = text.lower()
        if "completo" in text_lower or "completa" in text_lower:
            return "lee completo"
        if "no leas" in text_lower or "solo indexa" in text_lower or "ignora" in text_lower:
            return "no leas"
        return None

    def _assign_timestamps(self, exchange: Exchange) -> None:
        """Asigna los timestamps de inicio y fin a un exchange.

        El timestamp de inicio se toma del mensaje del Director.
        El timestamp de fin se toma del último mensaje del agente si
        hay respuestas; en caso contrario, se usa el mismo timestamp
        del Director.

        Args:
            exchange: Exchange al que se le asignarán los timestamps.
            Los campos ``start_timestamp`` y ``end_timestamp`` se
            modifican in-place.
        """
        exchange.start_timestamp = exchange.director_msg.timestamp

        if exchange.agent_msgs:
            exchange.end_timestamp = exchange.agent_msgs[-1].timestamp
        else:
            exchange.end_timestamp = exchange.director_msg.timestamp

        logger.debug(
            "Exchange %d: start=%.2f, end=%.2f",
            exchange.id,
            exchange.start_timestamp,
            exchange.end_timestamp,
        )

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
    # -- Validación interna de exchange_builder.py (atómico standalone) --
    print("=== Validacion de exchange_builder.py ===\n")

    from contexto_zai.models import Message, MessageRole

    # Test 1: dos intercambios user -> assistant
    msgs = [
        Message(seq=1, role=MessageRole.USER, timestamp=1.0, content="hola"),
        Message(seq=2, role=MessageRole.ASSISTANT, timestamp=2.0, content="respuesta1"),
        Message(seq=3, role=MessageRole.USER, timestamp=3.0, content="otra"),
        Message(seq=4, role=MessageRole.ASSISTANT, timestamp=4.0, content="respuesta2"),
    ]
    eb = ExchangeBuilder()
    exchanges = eb.build(msgs)
    assert len(exchanges) == 2, f"Esperaba 2 exchanges, obtuve {len(exchanges)}"
    assert exchanges[0].director_msg.content == "hola"
    assert exchanges[1].director_msg.content == "otra"
    print(f"[OK] 2 exchanges construidos correctamente")

    # Test 2: assistant con múltiples respuestas en un exchange
    msgs2 = [
        Message(seq=1, role=MessageRole.USER, timestamp=1.0, content="pregunta"),
        Message(seq=2, role=MessageRole.ASSISTANT, timestamp=2.0, content="r1"),
        Message(seq=3, role=MessageRole.ASSISTANT, timestamp=3.0, content="r2"),
        Message(seq=4, role=MessageRole.ASSISTANT, timestamp=4.0, content="r3"),
    ]
    exchanges2 = eb.build(msgs2)
    assert len(exchanges2) == 1
    assert len(exchanges2[0].agent_msgs) == 3
    print(f"[OK] 1 exchange con 3 respuestas del agente")

    # Test 3: lista vacía
    assert eb.build([]) == []
    print(f"[OK] Lista vacia manejada correctamente")

    # Test 4: solo user (sin respuesta del agente)
    msgs3 = [Message(seq=1, role=MessageRole.USER, timestamp=1.0, content="solo")]
    exchanges3 = eb.build(msgs3)
    assert len(exchanges3) == 1
    assert exchanges3[0].agent_msgs == []
    print(f"[OK] Exchange sin respuesta del agente manejado")

    print("\n[PASS] exchange_builder.py: todos los tests pasaron")
