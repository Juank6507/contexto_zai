# contexto_zai/process/incremental_cycle.py -- Ciclo incremental: orquesta paso 10 (actualizacion con mensajes nuevos desde ultimo_timestamp).
"""Ciclo de actualización incremental (v3.2).

Coordina el paso 10 del flujo:
- Lee la metadata para saber el último timestamp procesado.
- Extrae solo mensajes nuevos desde ese timestamp.
- Los clasifica y añade a los archivos temáticos existentes.
- Actualiza la metadata con el nuevo timestamp.

Es un script de dependencia: orquesta varios atómicos.
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

    # -- API pública ------------------------------------------------

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
    # -- Validación interna de incremental_cycle.py (atómico standalone) --
    # Tests básicos. Los tests de integración con API simulada están en
    # tests/test_incremental_cycle.py
    print("=== Validacion de incremental_cycle.py ===\n")

    import tempfile
    from pathlib import Path

    # Test 1: construcción del ciclo
    with tempfile.TemporaryDirectory() as tmpdir:
        cycle = IncrementalCycle(
            jwt="fake-jwt",
            chat_id="fake-chat-id",
            workspace_dir=Path(tmpdir) / "ws",
            download_dir=Path(tmpdir) / "dl",
        )
        assert cycle._jwt == "fake-jwt"
        assert cycle._chat_id == "fake-chat-id"
        assert cycle._exchange_builder is not None
        assert cycle._classifier is not None
        assert cycle._packer is not None
        assert cycle._metadata_mgr is not None
        print(f"[OK] Construccion con componentes inyectados")

    # Test 2: paths multiplataforma
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_dir = Path(tmpdir) / "ws"
        dl_dir = Path(tmpdir) / "dl"
        cycle = IncrementalCycle(
            jwt="x", chat_id="abc",
            workspace_dir=ws_dir, download_dir=dl_dir,
        )
        assert isinstance(cycle._workspace_dir, Path)
        assert isinstance(cycle._download_dir, Path)
        print(f"[OK] Paths multiplataforma (Path objects)")

    # Test 3: IncrementalCycleResult estructura
    r = IncrementalCycleResult(success=True, new_messages_count=5, new_exchanges_count=2, new_blocks_count=3, previous_timestamp=100.0, new_timestamp=200.0)
    assert r.success
    assert r.new_messages_count == 5
    assert r.new_timestamp == 200.0
    print(f"[OK] IncrementalCycleResult: estructura correcta")

    # Test 4: error si no hay metadata previa
    with tempfile.TemporaryDirectory() as tmpdir:
        cycle = IncrementalCycle(
            jwt="x", chat_id="abc",
            workspace_dir=Path(tmpdir), download_dir=Path(tmpdir) / "dl",
        )
        result = cycle.run()
        assert not result.success
        assert "metadata" in result.error.lower()
        print(f"[OK] Sin metadata previa: error reportado")

    # Test 5: repr
    cycle = IncrementalCycle(jwt="x", chat_id="abc-123-def")
    assert "abc-123" in repr(cycle)
    print(f"[OK] repr: {cycle!r}")

    print("\n[PASS] incremental_cycle.py: tests basicos pasaron")
    print("   Tests de integracion: tests/test_incremental_cycle.py")
