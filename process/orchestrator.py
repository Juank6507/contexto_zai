# contexto_zai/process/orchestrator.py -- Orquestador del proceso autónomo: decide recovery vs incremental segun metadata.
"""Orquestador del proceso autónomo (v3.2).

Punto de entrada que el agente activa cuando detecta pérdida de
contexto o el Director lo indica. Decide si ejecuta RecoveryCycle
(primera vez) o IncrementalCycle (siguientes veces) según el
estado de la metadata.

Es un script de dependencia: orquesta varios atómicos.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from contexto_zai.config import DOWNLOAD_OUTPUT_DIR, WORKSPACE_OUTPUT_DIR
from contexto_zai.metadata.manager import MetadataManager
from contexto_zai.models import DetectionEvent, DetectionTrigger
from contexto_zai.process.incremental_cycle import IncrementalCycle
from contexto_zai.process.recovery_cycle import RecoveryCycle

logger = logging.getLogger(__name__)

@dataclass
class OrchestratorResult:
    """Resultado de la activación del orquestador.

    Attributes:
        success: Si la activación completó sin errores.
        cycle_used: "recovery" o "incremental".
        exchanges_processed: Intercambios procesados.
        files_generated: Archivos generados/actualizados.
        error: Mensaje de error si falló.
    """

    success: bool
    cycle_used: str = ""
    exchanges_processed: int = 0
    files_generated: int = 0
    error: str = ""
    pending_tasks: list = None  # H9: SubagentTask diferidas para el agente principal

    def __post_init__(self):
        if self.pending_tasks is None:
            self.pending_tasks = []

class Orchestrator:
    """Orquesta la activación del proceso de recuperación.

    Args:
        chat_id: UUID interno del chat. Puede estar vacío si se pasa
            ``share_id`` externo (v4.2: link /s/ de otra sesión).
        jwt: JWT del Director.
        workspace_dir: Directorio del workspace.
        download_dir: Directorio de descarga.
        decision_extractor: Extractor LLM de decisiones (opcional).
        share_id: UUID de un share público existente (opcional, v4.2).
            Si se pasa, ``RecoveryCycle`` no crea su propio share y
            usa este ``share_id`` para leer el chat compartido.

    Usage:
        >>> # Caso 1: chat actual del agente
        >>> orch = Orchestrator(chat_id="...", jwt="...")
        >>> result = orch.activate(trigger=DetectionTrigger.EXPLICITO)
        >>> # Caso 2: chat externo vía link /s/
        >>> orch = Orchestrator(chat_id="", jwt="...", share_id="abc-123")
        >>> result = orch.activate(trigger=DetectionTrigger.EXPLICITO)
    """

    def __init__(
        self,
        chat_id: str,
        jwt: str,
        workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
        download_dir: Path | str = DOWNLOAD_OUTPUT_DIR,
        decision_extractor=None,
        share_id: Optional[str] = None,
    ) -> None:
        self._chat_id = chat_id
        self._jwt = jwt
        self._share_id = share_id  # v4.2: share externo (link /s/)
        self._workspace_dir = Path(workspace_dir)
        self._download_dir = Path(download_dir)
        self._decision_extractor = decision_extractor
        self._metadata_mgr = MetadataManager(output_dir=self._workspace_dir)

    # -- API pública ------------------------------------------------

    def activate(
        self,
        trigger: DetectionTrigger = DetectionTrigger.EXPLICITO,
        reason: str = "",
        chat_label: str = "",
    ) -> OrchestratorResult:
        """Activa el proceso de recuperación.

        v4.4: lógica de decisión de 4 casos. El proceso entiende su
        situación antes de actuar: descubre el ``chat_id`` real, lo
        compara con el de la metadata, y decide entre:

        - Caso 1 (primera vez): sin metadata → RecoveryCycle.
        - Caso 2/3 (mismo chat): metadata del mismo chat → IncrementalCycle.
        - Caso 4 (otro chat distinto): metadata de OTRO chat → RecoveryCycle.

        Args:
            trigger: Tipo de disparador.
            reason: Descripción legible del motivo.
            chat_label: Etiqueta del chat (opcional).

        Returns:
            OrchestratorResult con el resultado.
        """
        import time
        event = DetectionEvent(
            trigger=trigger,
            reason=reason,
            timestamp=time.time(),
        )
        logger.info(
            "Activacion por trigger '%s': %s",
            trigger.value, reason or "(sin razon)",
        )

        # v4.4: descubrir el chat_id real si viene por share_id (link /s/).
        # Si no hay chat_id pero sí share_id, leer el árbol del share
        # para descubrir de qué chat se trata.
        chat_id_real = self._chat_id
        if not chat_id_real and self._share_id:
            chat_id_real = self._descubrir_chat_id_del_share()
            if chat_id_real:
                self._chat_id = chat_id_real
                logger.info("chat_id descubierto del share: %s", chat_id_real)

        # v4.4: decidir qué ciclo ejecutar con 4 casos.
        if not self._metadata_mgr.exists() or not self._has_metadata():
            # Caso 1: primera vez (sin metadata) → RecoveryCycle
            logger.info("Caso 1 (primera vez): RecoveryCycle")
            return self._ejecutar_recovery(chat_label)
        else:
            # Metadata existe. ¿Es el mismo chat?
            meta = self._metadata_mgr.read()
            chat_id_metadata = meta.chat_id

            if chat_id_real and chat_id_metadata and chat_id_real == chat_id_metadata:
                # Caso 2/3: mismo chat → IncrementalCycle
                logger.info(
                    "Caso 2/3 (mismo chat %s): IncrementalCycle",
                    chat_id_real[:12],
                )
                return self._ejecutar_incremental()
            else:
                # Caso 4: otro chat distinto → RecoveryCycle
                logger.info(
                    "Caso 4 (otro chat: metadata=%s, actual=%s): RecoveryCycle",
                    (chat_id_metadata or "")[:12],
                    (chat_id_real or "")[:12],
                )
                return self._ejecutar_recovery(chat_label)

    def _ejecutar_recovery(self, chat_label: str) -> OrchestratorResult:
        """Ejecuta el ciclo de recuperación completo (RecoveryCycle)."""
        from contexto_zai.coordinador.orquestador import Orquestador
        from contexto_zai.procesadores.procesador_intercambios import ProcesadorIntercambios

        orquestador = Orquestador(workspace_dir=self._workspace_dir)
        procesador = ProcesadorIntercambios(
            workspace_dir=self._workspace_dir,
            orquestador=orquestador,
        )
        cycle = RecoveryCycle(
            jwt=self._jwt,
            chat_id=self._chat_id,
            workspace_dir=self._workspace_dir,
            download_dir=self._download_dir,
            decision_extractor=self._decision_extractor,
            subagent_launcher=procesador,
            enable_capa3=True,  # v4.4 F5: subagentes de calidad cableados por defecto
            enable_attachments=False,
            share_id=self._share_id,
        )
        result = cycle.run(chat_label=chat_label)
        return OrchestratorResult(
            success=result.success,
            cycle_used="recovery",
            exchanges_processed=result.exchanges_count,
            files_generated=result.files_count,
            error=result.error,
            pending_tasks=result.pending_tasks,
        )

    def _ejecutar_incremental(self) -> OrchestratorResult:
        """Ejecuta el ciclo incremental (IncrementalCycle)."""
        cycle = IncrementalCycle(
            jwt=self._jwt,
            chat_id=self._chat_id,
            workspace_dir=self._workspace_dir,
            download_dir=self._download_dir,
            share_id=self._share_id,  # v4.4: pasar share_id (F3 lo hará funcional)
        )
        result = cycle.run()
        return OrchestratorResult(
            success=result.success,
            cycle_used="incremental",
            exchanges_processed=result.new_exchanges_count,
            files_generated=result.new_blocks_count,
            error=result.error,
        )

    def _descubrir_chat_id_del_share(self) -> str:
        """v4.4: Descubre el ``chat_id`` real de un share público.

        Si el proceso recibe un ``share_id`` externo (link ``/s/``),
        el ``chat_id`` interno se descubre leyendo el árbol del share.
        Esto permite al Orchestrator comparar el chat que llega con el
        que ya está en la metadata.

        Returns:
            El ``chat_id`` descubierto, o string vacío si falla.
        """
        if not self._share_id or not self._jwt:
            return ""
        try:
            from contexto_zai.client.chat_client import ChatClient
            with ChatClient(token=self._jwt) as client:
                tree_data = client.get_message_tree(self._share_id)
                chat_id = tree_data.get("chat", {}).get("id", "")
                if chat_id:
                    logger.info(
                        "chat_id descubierto del share %s: %s",
                        self._share_id[:12], chat_id[:12],
                    )
                return chat_id
        except Exception as e:
            logger.warning(
                "No se pudo descubrir chat_id del share %s: %s",
                self._share_id[:12] if self._share_id else "?", e,
            )
            return ""

    def status(self) -> dict:
        """Devuelve el estado actual del proceso.

        Returns:
            Diccionario con: metadata_exists, ultimo_timestamp,
            total_exchanges, total_temas, ultima_activacion.
        """
        meta = self._metadata_mgr.read()
        return {
            "metadata_exists": self._metadata_mgr.exists(),
            "chat_id": meta.chat_id,
            "share_id": meta.share_id,
            "ultimo_timestamp": meta.ultimo_timestamp,
            "total_exchanges": meta.total_exchanges,
            "total_temas": len(meta.tema_a_archivo),
            "ultima_activacion": meta.ultima_activacion,
        }

    # -- Métodos privados -------------------------------------------

    def _has_metadata(self) -> bool:
        """Verifica si la metadata tiene datos válidos."""
        meta = self._metadata_mgr.read()
        return bool(meta.chat_id and meta.share_id)

    def __repr__(self) -> str:
        return f"Orchestrator(chat_id={self._chat_id[:8]}...)"

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
    # -- Validación interna de orchestrator.py (atómico standalone) --
    # Tests básicos. Los tests de integración completos están en
    # tests/test_orchestrator.py
    print("=== Validacion de orchestrator.py ===\n")

    import tempfile
    from pathlib import Path

    # Test 1: construcción
    with tempfile.TemporaryDirectory() as tmpdir:
        orch = Orchestrator(
            chat_id="fake-chat-id",
            jwt="fake-jwt",
            workspace_dir=Path(tmpdir) / "ws",
            download_dir=Path(tmpdir) / "dl",
        )
        assert orch._chat_id == "fake-chat-id"
        assert orch._jwt == "fake-jwt"
        assert orch._metadata_mgr is not None
        print(f"[OK] Construccion con componentes inyectados")

    # Test 2: paths multiplataforma
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        dl = Path(tmpdir) / "dl"
        orch = Orchestrator(chat_id="x", jwt="y", workspace_dir=ws, download_dir=dl)
        assert isinstance(orch._workspace_dir, Path)
        assert isinstance(orch._download_dir, Path)
        print(f"[OK] Paths multiplataforma (Path objects)")

    # Test 3: status en workspace vacío
    with tempfile.TemporaryDirectory() as tmpdir:
        orch = Orchestrator(chat_id="abc", jwt="x", workspace_dir=Path(tmpdir))
        st = orch.status()
        assert st["metadata_exists"] is False
        assert st["chat_id"] == ""
        assert st["total_temas"] == 0
        print(f"[OK] status() en workspace vacío: OK")

    # Test 4: OrchestratorResult estructura
    r = OrchestratorResult(success=True, cycle_used="recovery", exchanges_processed=10, files_generated=8)
    assert r.success
    assert r.cycle_used == "recovery"
    print(f"[OK] OrchestratorResult: estructura correcta")

    # Test 5: repr
    orch = Orchestrator(chat_id="abc-123-def", jwt="x")
    assert "abc-123" in repr(orch)
    print(f"[OK] repr: {orch!r}")

    # Test 6 (v4.3 fix Bug B): OrchestratorResult NO tiene campo files_updated
    # Bug B original: IncrementalCycle devolvía files_updated=... pero la dataclass
    # no tenía ese campo → TypeError. Fix: usar files_generated.
    import inspect as _inspect_b
    sig_fields = set(_inspect_b.signature(OrchestratorResult).parameters.keys())
    assert "files_updated" not in sig_fields, \
        "Bug B: files_updated NO debe existir en OrchestratorResult"
    assert "files_generated" in sig_fields, \
        "Bug B fix: files_generated debe existir en OrchestratorResult"
    # Verificar que se puede construir sin files_updated y con files_generated
    r_b = OrchestratorResult(
        success=True, cycle_used="incremental",
        exchanges_processed=5, files_generated=3, error="",
    )
    assert r_b.files_generated == 3
    print(f"[OK] Fix Bug B: OrchestratorResult usa files_generated (no files_updated)")

    # === Tests v4.4 (F1): lógica de decisión de 4 casos ===
    from unittest.mock import patch, MagicMock as _MagicMock

    # Test 7 (v4.4 F1): Caso 1 (primera vez) → RecoveryCycle
    # Sin metadata en el workspace → debe ir a recovery.
    with tempfile.TemporaryDirectory() as tmpdir:
        from contexto_zai.models import DetectionTrigger as _DT
        orch_v44 = Orchestrator(
            chat_id="chat-nuevo-001",
            jwt="fake-jwt",
            workspace_dir=Path(tmpdir),
        )
        mock_result = _MagicMock()
        mock_result.success = True
        mock_result.cycle_used = "recovery"
        mock_result.exchanges_count = 10
        mock_result.files_count = 5
        mock_result.error = ""
        mock_result.pending_tasks = []
        with patch.object(orch_v44, "_ejecutar_recovery", return_value=OrchestratorResult(
            success=True, cycle_used="recovery", exchanges_processed=10, files_generated=5
        )) as mock_recovery:
            with patch.object(orch_v44, "_ejecutar_incremental") as mock_incremental:
                result_v44 = orch_v44.activate(trigger=_DT.EXPLICITO)
                mock_recovery.assert_called_once()
                mock_incremental.assert_not_called()
                assert result_v44.cycle_used == "recovery"
        print(f"[OK] F1 Caso 1 (primera vez): RecoveryCycle (sin metadata)")

    # Test 8 (v4.4 F1): Caso 2/3 (mismo chat) → IncrementalCycle
    # Metadata existe con chat_id="A", llega chat_id="A" → debe ir a incremental.
    with tempfile.TemporaryDirectory() as tmpdir:
        import json as _json_t8
        # Crear _metadata.json con chat_id="chat-A"
        (Path(tmpdir) / "_metadata.json").write_text(_json_t8.dumps({
            "chat_id": "chat-A",
            "share_id": "share-A",
            "ultimo_timestamp": 1000,
            "total_exchanges": 50,
            "tema_a_archivo": {"tema1": "bloque_01.md"},
            "ultima_activacion": "2026-09-15T00:00:00Z",
        }), encoding="utf-8")
        orch_v44_t8 = Orchestrator(
            chat_id="chat-A",  # mismo chat_id que metadata
            jwt="fake-jwt",
            workspace_dir=Path(tmpdir),
        )
        with patch.object(orch_v44_t8, "_ejecutar_incremental", return_value=OrchestratorResult(
            success=True, cycle_used="incremental", exchanges_processed=5, files_generated=2
        )) as mock_incremental:
            with patch.object(orch_v44_t8, "_ejecutar_recovery") as mock_recovery:
                result_t8 = orch_v44_t8.activate(trigger=DetectionTrigger.EXPLICITO)
                mock_incremental.assert_called_once()
                mock_recovery.assert_not_called()
                assert result_t8.cycle_used == "incremental"
        print(f"[OK] F1 Caso 2/3 (mismo chat): IncrementalCycle")

    # Test 9 (v4.4 F1): Caso 4 (otro chat distinto) → RecoveryCycle
    # Metadata existe con chat_id="A", llega chat_id="B" → debe ir a recovery.
    with tempfile.TemporaryDirectory() as tmpdir:
        import json as _json_t9
        (Path(tmpdir) / "_metadata.json").write_text(_json_t9.dumps({
            "chat_id": "chat-A",
            "share_id": "share-A",
            "ultimo_timestamp": 1000,
            "total_exchanges": 50,
            "tema_a_archivo": {"tema1": "bloque_01.md"},
            "ultima_activacion": "2026-09-15T00:00:00Z",
        }), encoding="utf-8")
        orch_v44_t9 = Orchestrator(
            chat_id="chat-B",  # DISTINTO chat_id que metadata
            jwt="fake-jwt",
            workspace_dir=Path(tmpdir),
        )
        with patch.object(orch_v44_t9, "_ejecutar_recovery", return_value=OrchestratorResult(
            success=True, cycle_used="recovery", exchanges_processed=30, files_generated=8
        )) as mock_recovery:
            with patch.object(orch_v44_t9, "_ejecutar_incremental") as mock_incremental:
                result_t9 = orch_v44_t9.activate(trigger=DetectionTrigger.EXPLICITO)
                mock_recovery.assert_called_once()
                mock_incremental.assert_not_called()
                assert result_t9.cycle_used == "recovery"
        print(f"[OK] F1 Caso 4 (otro chat distinto): RecoveryCycle (no incremental)")

    # Test 10 (v4.4 F1): IncrementalCycle acepta share_id
    with tempfile.TemporaryDirectory() as tmpdir:
        cycle_v44 = IncrementalCycle(
            jwt="fake-jwt",
            chat_id="chat-test",
            workspace_dir=tmpdir,
            share_id="share-externo-001",
        )
        assert cycle_v44._share_id_externo == "share-externo-001"
        print(f"[OK] F1 IncrementalCycle acepta share_id (backward compatible)")

    print("\n[PASS] orchestrator.py: tests basicos pasaron")
    print("   Tests de integracion: tests/test_orchestrator.py")
