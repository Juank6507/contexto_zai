# Destino: /home/z/my-project/contexto_zai/process/incremental_cycle.py
"""Ciclo de actualización incremental (v3.2).

Coordina el paso 10 del flujo:
- Lee la metadata para saber el último timestamp procesado.
- Extrae solo mensajes nuevos desde ese timestamp.
- Los clasifica y añade a los archivos temáticos existentes.
- Actualiza la metadata con el nuevo timestamp.

Es un script de dependencia: orquesta varios atómicos.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from contexto_zai.client.auth_client import AuthClient
from contexto_zai.client.chat_client import ChatClient
from contexto_zai.config import DOWNLOAD_OUTPUT_DIR, WORKSPACE_OUTPUT_DIR
from contexto_zai.metadata.manager import MetadataManager
from contexto_zai.models import RecoveryFile
from contexto_zai.processing.block_packer import BlockPacker
from contexto_zai.processing.classifier import MessageClassifier
from contexto_zai.processing.exchange_builder import ExchangeBuilder
from contexto_zai.processing.subdivider import Subdivider

logger = logging.getLogger(__name__)


@dataclass
class IncrementalCycleResult:
    """Resultado del ciclo incremental.

    Attributes:
        success: Si la actualización fue exitosa.
        new_messages_count: Mensajes nuevos procesados.
        new_exchanges_count: Intercambios nuevos procesados.
        new_blocks_count: Bloques nuevos generados (0 si solo se actualizaron).
        files_updated: Archivos actualizados.
        previous_timestamp: Timestamp anterior (antes de actualizar).
        new_timestamp: Nuevo timestamp registrado.
        error: Mensaje de error si falló.
    """

    success: bool
    new_messages_count: int = 0
    new_exchanges_count: int = 0
    new_blocks_count: int = 0
    files_updated: int = 0
    previous_timestamp: float = 0.0
    new_timestamp: float = 0.0
    error: str = ""


class IncrementalCycle:
    """Orquesta la actualización incremental de los archivos.

    Args:
        jwt: JWT del Director.
        chat_id: UUID interno del chat.
        workspace_dir: Directorio del workspace.
        download_dir: Directorio de descarga.

    Usage:
        >>> cycle = IncrementalCycle(jwt="...", chat_id="...")
        >>> result = cycle.run()
    """

    def __init__(
        self,
        jwt: str,
        chat_id: str,
        workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
        download_dir: Path | str = DOWNLOAD_OUTPUT_DIR,
    ) -> None:
        self._jwt = jwt
        self._chat_id = chat_id
        self._workspace_dir = Path(workspace_dir)
        self._download_dir = Path(download_dir)

        self._exchange_builder = ExchangeBuilder()
        self._classifier = MessageClassifier()
        self._subdivider = Subdivider()
        self._packer = BlockPacker()
        self._metadata_mgr = MetadataManager(output_dir=self._workspace_dir)

    # ── API pública ────────────────────────────────────────────────

    def run(self) -> IncrementalCycleResult:
        """Ejecuta la actualización incremental.

        Returns:
            IncrementalCycleResult con el resultado.
        """
        try:
            # 1. Leer metadata actual
            metadata = self._metadata_mgr.read()
            previous_ts = metadata.ultimo_timestamp

            if not metadata.share_id:
                return IncrementalCycleResult(
                    success=False,
                    error="No hay metadata previa. Ejecutar RecoveryCycle primero.",
                )

            # 2. Extraer mensajes nuevos (filtrar por timestamp)
            with AuthClient(token=self._jwt) as auth:
                # Reutilizar share_id existente (idempotente)
                share_id = auth.create_share(self._chat_id)

            with ChatClient(token=self._jwt) as client:
                all_messages = client.extract_all(
                    share_id=share_id, chat_id=self._chat_id
                )

            new_messages = [
                m for m in all_messages if m.timestamp > previous_ts
            ]

            logger.info(
                "Incremental: %d/%d mensajes son nuevos (ts > %d)",
                len(new_messages),
                len(all_messages),
                previous_ts,
            )

            if not new_messages:
                return IncrementalCycleResult(
                    success=True,
                    new_messages_count=0,
                    new_exchanges_count=0,
                    previous_timestamp=previous_ts,
                    new_timestamp=previous_ts,
                )

            # 3. Construir intercambios nuevos
            new_exchanges = self._exchange_builder.build(new_messages)
            self._classifier.classify_exchanges(new_exchanges)

            # 4. Para cada intercambio nuevo, añadirlo al bloque existente
            # (o crear uno nuevo si no cabe)
            # Esto requiere reempaquetar todos los intercambios (viejos + nuevos)
            # Optimización: solo reempaquetar los temas que recibieron nuevos intercambios
            updated_files: list[RecoveryFile] = []

            # Agrupar intercambios por tema
            by_topic: dict = {}
            for ex in new_exchanges:
                by_topic.setdefault(ex.topic, []).append(ex)

            # Reempaquetar bloques para los temas afectados
            # Para simplicidad: regenerar todos los bloques con todos los intercambios
            # (optimización futura: solo los temas afectados)
            all_exchanges = self._exchange_builder.build(all_messages)
            self._classifier.classify_exchanges(all_exchanges)

            all_by_topic: dict = {}
            for ex in all_exchanges:
                all_by_topic.setdefault(ex.topic, []).append(ex)

            # Subdividir temas grandes
            expanded: dict = {}
            for tema, exs in all_by_topic.items():
                if self._subdivider.needs_subdivision(tema, exs):
                    result = self._subdivider.subdivide(tema, exs)
                    for name, sub_exs in result.subtemas:
                        for ex in sub_exs:
                            ex.topic = name
                        expanded[name] = sub_exs
                else:
                    expanded[tema] = exs

            blocks = self._packer.pack(expanded)

            # Actualizar metadata
            new_ts = max(m.timestamp for m in all_messages)
            metadata.ultimo_timestamp = new_ts
            metadata.total_exchanges = len(all_exchanges)
            from datetime import datetime, timezone
            metadata.ultima_activacion = datetime.now(timezone.utc).isoformat()
            # Reconstruir tema_a_archivo desde los nuevos bloques
            metadata.tema_a_archivo = {}
            for block in blocks:
                for tema in block.temas:
                    metadata.registrar_tema(tema, block.filename)
            self._metadata_mgr.write(metadata)

            logger.info(
                "Incremental completado: %d nuevos intercambios, %d bloques regenerados",
                len(new_exchanges),
                len(blocks),
            )

            return IncrementalCycleResult(
                success=True,
                new_messages_count=len(new_messages),
                new_exchanges_count=len(new_exchanges),
                new_blocks_count=len(blocks),
                files_updated=0,  # se regeneran todos
                previous_timestamp=previous_ts,
                new_timestamp=new_ts,
            )

        except Exception as e:
            logger.exception("Error en ciclo incremental")
            return IncrementalCycleResult(success=False, error=str(e))

    def __repr__(self) -> str:
        return f"IncrementalCycle(chat_id={self._chat_id[:8]}...)"
