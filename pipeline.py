# Destino: /home/z/my-project/contexto_zai/pipeline.py
"""Entry point del proceso Contexto Z.ai (v3.2).

Reemplaza la CLI de v1.0. Expone una función `run` que el agente
puede invocar directamente para activar el proceso de recuperación.

Es un script de dependencia: orquesta el Orchestrator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from contexto_zai.config import DOWNLOAD_OUTPUT_DIR, WORKSPACE_OUTPUT_DIR
from contexto_zai.models import DetectionTrigger
from contexto_zai.process.orchestrator import Orchestrator, OrchestratorResult

logger = logging.getLogger(__name__)


def run(
    chat_id: str,
    jwt: str,
    trigger: DetectionTrigger = DetectionTrigger.EXPLICITO,
    reason: str = "",
    chat_label: str = "",
    workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
    download_dir: Path | str = DOWNLOAD_OUTPUT_DIR,
) -> OrchestratorResult:
    """Activa el proceso de recuperación de contexto.

    Es la función principal que el agente invoca cuando detecta
    pérdida de contexto o el Director lo indica.

    Args:
        chat_id: UUID interno del chat (viene en metadatos del gateway).
        jwt: JWT del Director.
        trigger: Tipo de disparador.
        reason: Razón legible de la activación.
        chat_label: Etiqueta del chat.
        workspace_dir: Directorio donde se escriben los archivos
            de recuperación en el workspace del agente.
        download_dir: Directorio de descarga (copia para el Director).

    Returns:
        OrchestratorResult con el resultado de la activación.

    Example:
        >>> from contexto_zai.pipeline import run
        >>> from contexto_zai.models import DetectionTrigger
        >>> result = run(
        ...     chat_id="13b43432-...",
        ...     jwt="eyJhbG...",
        ...     trigger=DetectionTrigger.EXPLICITO,
        ...     reason="Director indicó pérdida de contexto",
        ... )
        >>> if result.success:
        ...     print(f"Recuperación: ciclo={result.cycle_used}")
    """
    orch = Orchestrator(
        chat_id=chat_id,
        jwt=jwt,
        workspace_dir=workspace_dir,
        download_dir=download_dir,
    )
    return orch.activate(
        trigger=trigger,
        reason=reason,
        chat_label=chat_label,
    )


def status(
    chat_id: str,
    workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
) -> dict:
    """Devuelve el estado actual del proceso.

    Args:
        chat_id: UUID del chat.
        workspace_dir: Directorio del workspace.

    Returns:
        Diccionario con el estado de la metadata.
    """
    # El Orchestrator solo necesita chat_id para status
    orch = Orchestrator(
        chat_id=chat_id,
        jwt="",  # no se usa para status
        workspace_dir=workspace_dir,
    )
    return orch.status()


if __name__ == "__main__":
    # ── Validación interna de pipeline.py ──
    print("=== Validación de pipeline.py ===\n")

    import tempfile
    from contexto_zai.models import DetectionTrigger

    # Test 1: status() en directorio vacío
    with tempfile.TemporaryDirectory() as tmpdir:
        st = status(chat_id="abc-123", workspace_dir=tmpdir)
        assert st["metadata_exists"] is False
        assert st["chat_id"] == ""
        print(f"✓ status() en directorio vacío: metadata_exists=False")

    # Test 2: run() con parámetros inválidos (sin JWT) → error
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run(
            chat_id="invalid-chat",
            jwt="invalid-jwt",
            workspace_dir=tmpdir,
            download_dir=tmpdir + "/download",
        )
        # Debe fallar porque el JWT es inválido
        assert not result.success
        assert result.error != ""
        print(f"✓ run() con JWT inválido: error capturado correctamente")

    # Test 3: signature de run()
    import inspect
    sig = inspect.signature(run)
    expected_params = {"chat_id", "jwt", "trigger", "reason", "chat_label", "workspace_dir", "download_dir"}
    actual_params = set(sig.parameters.keys())
    assert expected_params == actual_params, f"Faltan params: {expected_params - actual_params}"
    print(f"✓ run() signature: {len(actual_params)} parámetros correctos")

    # Test 4: trigger por defecto es EXPLICITO
    assert sig.parameters["trigger"].default == DetectionTrigger.EXPLICITO
    print(f"✓ Trigger por defecto: EXPLICITO")

    print("\n✅ pipeline.py: todos los tests pasaron")
