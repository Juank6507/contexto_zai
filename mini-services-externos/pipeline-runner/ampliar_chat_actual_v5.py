#!/usr/bin/env python3
"""Amplía contexto del workspace filtrado (contexto_recuperacion_ep02)
agregando el chat actual del Director (6a00fcb8-...) usando el pipeline v5.0.

Este es el flujo normal del pipeline (sin share_id externo):
1. RecoveryCycle pide a AuthClient.create_share(chat_id) para crear un share público
2. Extrae los mensajes del share recién creado
3. Como el workspace YA tiene metadata previa del chat 371ba778 (EP 02),
   el Orchestrator detecta "otro chat distinto" → Caso 4 → RecoveryCycle
4. RecoveryCycle regenera los archivos de recuperación, preservando 03_objetivo_proyecto.md
"""
from __future__ import annotations

import json
import logging
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, "/home/z/my-project")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("ampliar-chat-actual")

# Chat actual del gateway IM
CURRENT_CHAT_ID = "6a00fcb8-e86c-44dc-9df2-0df035018523"

# Workspace filtrado donde ya están los 81 exchanges del proyecto contexto_zai
WORKSPACE_DIR = Path("/home/z/my-project/contexto_recuperacion_ep02")


def load_jwt() -> str:
    creds_path = Path.home() / ".czai" / "credentials.json"
    data = json.loads(creds_path.read_text(encoding="utf-8"))
    return data["token"]


def main() -> int:
    log.info("=== Ampliar contexto — agregando chat actual al workspace filtrado ===")
    log.info("Chat ID actual: %s", CURRENT_CHAT_ID)
    log.info("Workspace: %s", WORKSPACE_DIR)
    log.info("Usando implementación v5.0 (RecoveryCycle normal)")

    jwt = load_jwt()
    log.info("JWT cargado (%d chars).", len(jwt))

    # Listar el workspace antes
    log.info("--- Workspace ANTES ---")
    for p in sorted(WORKSPACE_DIR.iterdir()):
        if p.is_file():
            log.info("  %s (%d bytes)", p.name, p.stat().st_size)

    # Invocar pipeline.run() — flujo normal, sin share_id externo
    # El RecoveryCycle pide create_share(chat_id) internamente.
    from contexto_zai.models import DetectionTrigger
    from contexto_zai.pipeline import run

    t0 = time.time()
    try:
        result = run(
            chat_id=CURRENT_CHAT_ID,
            jwt=jwt,
            trigger=DetectionTrigger.EXPLICITO,
            reason="Director solicita ampliar contexto del chat actual con v5.0",
            chat_label="CHAT_ACTUAL_v5",
            workspace_dir=WORKSPACE_DIR,
            download_dir=WORKSPACE_DIR,  # mismo dir (no duplicar)
            share_id=None,  # flujo normal: crear share interno
        )
    except Exception as e:
        log.error("EXCEPCION en pipeline.run(): %s", e)
        log.error("Traceback:\n%s", traceback.format_exc())
        return 1

    elapsed = time.time() - t0

    log.info("=== pipeline.run() terminó en %.1fs ===", elapsed)
    log.info("Resultado:")
    log.info("  success: %s", result.success)
    log.info("  cycle_used: %s", result.cycle_used)
    log.info("  exchanges_processed: %s", result.exchanges_processed)
    log.info("  files_generated: %s", result.files_generated)
    log.info("  error: %s", result.error or "(sin errores)")
    log.info("  pending_tasks: %d", len(result.pending_tasks))

    # Listar el workspace después
    log.info("--- Workspace DESPUÉS ---")
    for p in sorted(WORKSPACE_DIR.iterdir()):
        if p.is_file():
            log.info("  %s (%d bytes)", p.name, p.stat().st_size)

    # Verificar que 03_objetivo_proyecto.md sigue existiendo (no debe borrarse)
    objetivo = WORKSPACE_DIR / "03_objetivo_proyecto.md"
    if objetivo.exists():
        log.info("[OK] 03_objetivo_proyecto.md preservado (%d bytes)",
                 objetivo.stat().st_size)
    else:
        log.warning("[WARN] 03_objetivo_proyecto.md NO existe después del run!")

    # Guardar resultado
    summary = {
        "chat_id": CURRENT_CHAT_ID,
        "success": result.success,
        "cycle_used": result.cycle_used,
        "exchanges_processed": result.exchanges_processed,
        "files_generated": result.files_generated,
        "error": result.error,
        "pending_tasks_count": len(result.pending_tasks),
        "elapsed_sec": elapsed,
    }
    Path("/tmp/ampliar_chat_actual_result.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    log.info("=== Ampliación completada ===")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
