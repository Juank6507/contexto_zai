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

class Orchestrator:
    """Orquesta la activación del proceso de recuperación.

    Args:
        chat_id: UUID interno del chat.
        jwt: JWT del Director.
        workspace_dir: Directorio del workspace.
        download_dir: Directorio de descarga.
        decision_extractor: Extractor LLM de decisiones (opcional).

    Usage:
        >>> orch = Orchestrator(chat_id="...", jwt="...")
        >>> result = orch.activate(
        ...     trigger=DetectionTrigger.EXPLICITO,
        ...     reason="Director indicó pérdida de contexto",
        ... )
    """

    def __init__(
        self,
        chat_id: str,
        jwt: str,
        workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
        download_dir: Path | str = DOWNLOAD_OUTPUT_DIR,
        decision_extractor=None,
    ) -> None:
        self._chat_id = chat_id
        self._jwt = jwt
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

        Args:
            trigger: Tipo de disparador (lexico, contador, auto_preguntas, explicito).
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

        # Decidir qué ciclo ejecutar
        if self._metadata_mgr.exists() and self._has_metadata():
            # Metadata ya existe -> ciclo incremental
            logger.info("Metadata existente -> ejecutando IncrementalCycle")
            cycle = IncrementalCycle(
                jwt=self._jwt,
                chat_id=self._chat_id,
                workspace_dir=self._workspace_dir,
                download_dir=self._download_dir,
            )
            result = cycle.run()
            return OrchestratorResult(
                success=result.success,
                cycle_used="incremental",
                exchanges_processed=result.new_exchanges_count,
                files_updated=result.new_blocks_count,
                error=result.error,
            )
        else:
            # Sin metadata -> ciclo completo de recuperación
            logger.info("Sin metadata previa -> ejecutando RecoveryCycle")
            cycle = RecoveryCycle(
                jwt=self._jwt,
                chat_id=self._chat_id,
                workspace_dir=self._workspace_dir,
                download_dir=self._download_dir,
                decision_extractor=self._decision_extractor,
            )
            result = cycle.run(chat_label=chat_label)
            return OrchestratorResult(
                success=result.success,
                cycle_used="recovery",
                exchanges_processed=result.exchanges_count,
                files_generated=result.files_count,
                error=result.error,
            )

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

    print("\n[PASS] orchestrator.py: tests basicos pasaron")
    print("   Tests de integracion: tests/test_orchestrator.py")
