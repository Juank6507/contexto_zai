"""Módulo de construcción de exchanges a partir de mensajes.

Agrupa mensajes individuales en unidades de conversación (Exchange),
donde cada exchange comienza con un mensaje del Director (user) y contiene
todas las respuestas consecutivas del agente (assistant) hasta el
siguiente mensaje del Director.
"""

from __future__ import annotations

import logging

from contexto_zai.models import Exchange, Message, MessageRole

logger = logging.getLogger(__name__)


class ExchangeBuilder:
    """Construye exchanges a partir de una lista plana de mensajes.

    Un exchange es una unidad de conversación compuesta por un mensaje
    del Director (user) seguido de cero o más respuestas del agente
    (assistant). Los mensajes system se omiten silenciosamente.

    Example::

        builder = ExchangeBuilder()
        exchanges = builder.build(messages)
    """

    def __init__(self) -> None:
        """Inicializa el builder de exchanges.

        No requiere parámetros de configuración.
        """
        logger.debug("ExchangeBuilder inicializado")

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
        logger.info("Iniciando construcción de exchanges a partir de %d mensajes", len(messages))

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
                    logger.debug("Respuesta del agente añadida al exchange actual (seq=%d)", msg.seq)
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
                "Último exchange %d cerrado: %d respuestas del agente",
                exchange.id,
                exchange.agent_count,
            )

        logger.info("%d exchanges construidos exitosamente", len(exchanges))
        return exchanges

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
    # ── Validación interna de exchange_builder.py (atómico standalone) ──
    print("=== Validación de exchange_builder.py ===\n")

    from contexto_zai.models import Message, MessageRole

    # Test 1: dos intercambios user → assistant
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
    print(f"✓ 2 exchanges construidos correctamente")

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
    print(f"✓ 1 exchange con 3 respuestas del agente")

    # Test 3: lista vacía
    assert eb.build([]) == []
    print(f"✓ Lista vacía manejada correctamente")

    # Test 4: solo user (sin respuesta del agente)
    msgs3 = [Message(seq=1, role=MessageRole.USER, timestamp=1.0, content="solo")]
    exchanges3 = eb.build(msgs3)
    assert len(exchanges3) == 1
    assert exchanges3[0].agent_msgs == []
    print(f"✓ Exchange sin respuesta del agente manejado")

    print("\n✅ exchange_builder.py: todos los tests pasaron")
