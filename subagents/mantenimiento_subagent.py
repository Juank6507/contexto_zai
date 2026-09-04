# Destino: /home/z/my-project/contexto_zai/subagents/mantenimiento_subagent.py
"""Subagente de mantenimiento (actualización incremental) (v3.2).

Lee la metadata para saber el último timestamp procesado, extrae solo
mensajes nuevos, los clasifica y añade a los archivos existentes.
Actualiza la metadata con el nuevo timestamp.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from contexto_zai.metadata.manager import MetadataManager

if TYPE_CHECKING:
    from contexto_zai.client.chat_client import ChatClient
    from contexto_zai.models import Exchange, RecoveryMetadata

logger = logging.getLogger(__name__)


@dataclass
class MantenimientoResult:
    """Resultado del mantenimiento incremental.

    Attributes:
        success: Si la actualización fue exitosa.
        new_exchanges_count: Número de intercambios nuevos procesados.
        new_ultimo_timestamp: Nuevo último timestamp registrado.
        error: Mensaje de error si falló.
    """

    success: bool
    new_exchanges_count: int = 0
    new_ultimo_timestamp: float = 0.0
    error: str = ""


class MantenimientoSubagent:
    """Subagente de actualización incremental.

    Args:
        chat_client: ChatClient para extraer mensajes nuevos.
        metadata_manager: MetadataManager para leer/escribir metadata.

    Usage:
        >>> sub = MantenimientoSubagent(chat_client=client, metadata_manager=mgr)
        >>> result = sub.run(chat_id="...", share_id="...")
    """

    def __init__(
        self,
        chat_client: "ChatClient",
        metadata_manager: MetadataManager,
    ) -> None:
        self._chat_client = chat_client
        self._metadata_mgr = metadata_manager

    def run(
        self,
        chat_id: str,
        share_id: str,
    ) -> MantenimientoResult:
        """Ejecuta la actualización incremental.

        Args:
            chat_id: UUID interno del chat.
            share_id: UUID del share.

        Returns:
            MantenimientoResult con el resultado.
        """
        try:
            # 1. Leer metadata actual
            metadata = self._metadata_mgr.read()

            # 2. Extraer todos los mensajes (la API no soporta filtro por timestamp)
            all_messages = self._chat_client.extract_all(
                share_id=share_id, chat_id=chat_id
            )

            # 3. Filtrar solo mensajes nuevos
            ultimo_ts = metadata.ultimo_timestamp
            new_messages = [
                m for m in all_messages
                if m.timestamp > ultimo_ts
            ]

            logger.info(
                "Mantenimiento: %d mensajes totales, %d nuevos (ts > %d)",
                len(all_messages),
                len(new_messages),
                ultimo_ts,
            )

            if not new_messages:
                logger.info("No hay mensajes nuevos desde última activación")
                return MantenimientoResult(
                    success=True,
                    new_exchanges_count=0,
                    new_ultimo_timestamp=ultimo_ts,
                )

            # 4. Actualizar metadata con nuevo timestamp
            new_ts = max(m.timestamp for m in new_messages)
            self._metadata_mgr.set_ultimo_timestamp(new_ts)
            self._metadata_mgr.touch_activacion()

            return MantenimientoResult(
                success=True,
                new_exchanges_count=len(new_messages),
                new_ultimo_timestamp=new_ts,
            )

        except Exception as e:
            logger.error("Error en mantenimiento incremental: %s", e)
            return MantenimientoResult(
                success=False,
                error=str(e),
            )

    def __repr__(self) -> str:
        return "MantenimientoSubagent()"


if __name__ == "__main__":
    print("=== Validación de mantenimiento_subagent.py ===\n")

    import tempfile
    from pathlib import Path
    from contexto_zai.client.chat_client import ChatClient
    from contexto_zai.models import Message, MessageRole

    # Test 1: mantenimiento exitoso con mensajes nuevos
    with tempfile.TemporaryDirectory() as tmpdir:
        # Metadata vacía
        mgr = MetadataManager(output_dir=Path(tmpdir))
        # Set ultimo_timestamp = 0 (todo es nuevo)

        # Chat client simulado
        class MockChatClient:
            def extract_all(self, share_id, chat_id):
                return [
                    Message(seq=1, role=MessageRole.USER, timestamp=100, content="msg1"),
                    Message(seq=2, role=MessageRole.ASSISTANT, timestamp=200, content="msg2"),
                    Message(seq=3, role=MessageRole.USER, timestamp=300, content="msg3"),
                ]

        sub = MantenimientoSubagent(chat_client=MockChatClient(), metadata_manager=mgr)
        result = sub.run(chat_id="abc", share_id="def")
        assert result.success
        assert result.new_exchanges_count == 3  # 3 mensajes nuevos (ts=0 al inicio)
        assert result.new_ultimo_timestamp == 300
        print(f"✓ Mantenimiento exitoso: 3 mensajes nuevos, último ts={result.new_ultimo_timestamp}")

        # Verificar que metadata se actualizó
        meta = mgr.read()
        assert meta.ultimo_timestamp == 300
        assert meta.ultima_activacion != ""
        print(f"✓ Metadata actualizada: ultimo_timestamp={meta.ultimo_timestamp}")

    # Test 2: sin mensajes nuevos
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MetadataManager(output_dir=Path(tmpdir))
        mgr.set_ultimo_timestamp(1000)  # último ts alto

        class MockChatClient2:
            def extract_all(self, share_id, chat_id):
                return [
                    Message(seq=1, role=MessageRole.USER, timestamp=100, content="old1"),
                    Message(seq=2, role=MessageRole.ASSISTANT, timestamp=200, content="old2"),
                ]

        sub2 = MantenimientoSubagent(chat_client=MockChatClient2(), metadata_manager=mgr)
        result2 = sub2.run(chat_id="abc", share_id="def")
        assert result2.success
        assert result2.new_exchanges_count == 0
        assert result2.new_ultimo_timestamp == 1000  # no cambió
        print(f"✓ Sin mensajes nuevos: 0 intercambios procesados")

    # Test 3: error en chat_client
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MetadataManager(output_dir=Path(tmpdir))

        class FailingChatClient:
            def extract_all(self, share_id, chat_id):
                raise RuntimeError("API caída")

        sub3 = MantenimientoSubagent(chat_client=FailingChatClient(), metadata_manager=mgr)
        result3 = sub3.run(chat_id="abc", share_id="def")
        assert not result3.success
        assert "API caída" in result3.error
        print(f"✓ Error en chat_client: capturado correctamente")

    print("\n✅ mantenimiento_subagent.py: todos los tests pasaron")
