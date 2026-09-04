# Destino: /home/z/my-project/contexto_zai/process/recovery_cycle.py
"""Ciclo de recuperación completo (v3.2).

Coordina los pasos 5-9 del flujo de la spec:
5. Extracción de mensajes desde chat.z.ai.
6. Clasificación y empaquetado en bloques temáticos.
7. Generación de los 3 archivos (estado, índice, decisiones).
8. Subagente de estado actual (extrae contexto del tema activo).
9. Barrido por temas cuando sigue faltando contexto.

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
from contexto_zai.generation.recovery_generator import RecoveryGenerator
from contexto_zai.metadata.manager import MetadataManager
from contexto_zai.models import RecoveryFile
from contexto_zai.processing.block_packer import BlockPacker
from contexto_zai.processing.classifier import MessageClassifier
from contexto_zai.processing.exchange_builder import ExchangeBuilder
from contexto_zai.processing.subdivider import Subdivider
from contexto_zai.subagents.decisiones_subagent import DecisionesSubagent

logger = logging.getLogger(__name__)


@dataclass
class RecoveryCycleResult:
    """Resultado del ciclo de recuperación.

    Attributes:
        success: Si el ciclo completó sin errores.
        messages_count: Mensajes extraídos.
        exchanges_count: Intercambios construidos.
        blocks_count: Bloques generados.
        files_count: Archivos escritos.
        share_id: Share utilizado.
        error: Mensaje de error si falló.
    """

    success: bool
    messages_count: int = 0
    exchanges_count: int = 0
    blocks_count: int = 0
    files_count: int = 0
    share_id: str = ""
    error: str = ""


class RecoveryCycle:
    """Orquesta el ciclo completo de recuperación (pasos 5-9).

    Args:
        jwt: JWT del Director (para autenticación).
        chat_id: UUID interno del chat.
        workspace_dir: Directorio del workspace (donde viven los archivos).
        download_dir: Directorio de descarga (copia para el Director).
        decision_extractor: Extractor LLM de decisiones (opcional).

    Usage:
        >>> cycle = RecoveryCycle(jwt="...", chat_id="...")
        >>> result = cycle.run()
    """

    def __init__(
        self,
        jwt: str,
        chat_id: str,
        workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
        download_dir: Path | str = DOWNLOAD_OUTPUT_DIR,
        decision_extractor=None,
    ) -> None:
        self._jwt = jwt
        self._chat_id = chat_id
        self._workspace_dir = Path(workspace_dir)
        self._download_dir = Path(download_dir)
        self._decision_extractor = decision_extractor

        # Componentes atómicos (inyectados en constructor)
        self._exchange_builder = ExchangeBuilder()
        self._classifier = MessageClassifier()
        self._subdivider = Subdivider()
        self._packer = BlockPacker()
        self._recovery_gen = RecoveryGenerator(
            decisiones_generator=self._build_decisiones_generator(),
        )
        self._metadata_mgr = MetadataManager(output_dir=self._workspace_dir)

    def _build_decisiones_generator(self):
        """Construye el generador de decisiones con extractor LLM si está disponible."""
        from contexto_zai.generation.decisiones_generator import DecisionesGenerator
        if self._decision_extractor:
            # Si es DecisionesSubagent, usar su método extract como extractor
            if hasattr(self._decision_extractor, "extract"):
                extractor = self._decision_extractor.extract
            else:
                extractor = self._decision_extractor
            return DecisionesGenerator(extractor=extractor)
        return DecisionesGenerator()

    # ── API pública ────────────────────────────────────────────────

    def run(
        self,
        chat_label: str = "",
    ) -> RecoveryCycleResult:
        """Ejecuta el ciclo completo de recuperación.

        Args:
            chat_label: Etiqueta descriptiva del chat.

        Returns:
            RecoveryCycleResult con el resultado.
        """
        try:
            # PASO 5: Extracción de mensajes
            logger.info("Paso 5: Extrayendo mensajes...")
            with AuthClient(token=self._jwt) as auth:
                share_id = auth.create_share(self._chat_id)
            with ChatClient(token=self._jwt) as client:
                messages = client.extract_all(
                    share_id=share_id, chat_id=self._chat_id
                )

            if not messages:
                return RecoveryCycleResult(
                    success=False,
                    error="No se extrajeron mensajes del chat.",
                )

            logger.info(
                "Extraídos: %d mensajes (%d chars)",
                len(messages),
                sum(len(m.content) for m in messages),
            )

            # PASO 6: Clasificación y empaquetado
            logger.info("Paso 6: Clasificando y empaquetando...")
            exchanges = self._exchange_builder.build(messages)
            self._classifier.classify_exchanges(exchanges)

            # Agrupar por tema
            by_topic: dict = {}
            for ex in exchanges:
                by_topic.setdefault(ex.topic, []).append(ex)

            # Subdividir temas que superen el límite
            expanded: dict = {}
            for tema, exs in by_topic.items():
                if self._subdivider.needs_subdivision(tema, exs):
                    result = self._subdivider.subdivide(tema, exs)
                    for name, sub_exs in result.subtemas:
                        for ex in sub_exs:
                            ex.topic = name
                        expanded[name] = sub_exs
                else:
                    expanded[tema] = exs

            # Empaquetar en bloques por tamaño
            blocks = self._packer.pack(expanded)

            # Actualizar metadata con mapeo tema→archivo
            metadata = self._metadata_mgr.read()
            metadata.chat_id = self._chat_id
            metadata.share_id = share_id
            metadata.total_exchanges = len(exchanges)
            for block in blocks:
                for tema in block.temas:
                    metadata.registrar_tema(tema, block.filename)
            metadata.ultimo_timestamp = max(
                m.timestamp for m in messages
            )
            from datetime import datetime, timezone
            metadata.ultima_activacion = datetime.now(timezone.utc).isoformat()
            self._metadata_mgr.write(metadata)

            # PASO 7: Generación de los 3 archivos + bloques
            logger.info("Paso 7: Generando archivos de recuperación...")
            recovery_files = self._recovery_gen.generate_all(
                exchanges=exchanges,
                blocks=blocks,
                chat_label=chat_label or self._chat_id[:8],
                metadata=metadata,
            )

            # PASO 8: (Subagente de estado actual) ya integrado en la generación
            # El estado_actual.md se genera con el contexto del tema del último exchange.
            # El subagente de estado se lanzaría en runtime para extraer contexto más rico,
            # pero la generación base del archivo se hace aquí.

            # PASO 9: (Barrido por temas) se lanza bajo demanda del agente,
            # no en este ciclo automático.

            # Escribir archivos en workspace y en download
            self._write_files(recovery_files, self._workspace_dir)
            self._write_files(recovery_files, self._download_dir)

            logger.info(
                "Ciclo completado: %d archivos, %d bloques, %d intercambios",
                len(recovery_files),
                len(blocks),
                len(exchanges),
            )

            return RecoveryCycleResult(
                success=True,
                messages_count=len(messages),
                exchanges_count=len(exchanges),
                blocks_count=len(blocks),
                files_count=len(recovery_files),
                share_id=share_id,
            )

        except Exception as e:
            logger.exception("Error en ciclo de recuperación")
            return RecoveryCycleResult(success=False, error=str(e))

    # ── Métodos privados ───────────────────────────────────────────

    def _write_files(
        self,
        files: list[RecoveryFile],
        output_dir: Path,
    ) -> None:
        """Escribe los archivos de recuperación en el directorio."""
        output_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            file_path = output_dir / f.filename
            file_path.write_text(f.content, encoding="utf-8")
        logger.info("Escritos %d archivos en %s", len(files), output_dir)

    def __repr__(self) -> str:
        return f"RecoveryCycle(chat_id={self._chat_id[:8]}...)"
