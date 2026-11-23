"""Runner para el chat 6a00fcb8 (este mismo chat) — iteración 1 del Gauntlet v6.13.

Ejecuta pipeline.run() contra el chat 6a00fcb8-e86c-44dc-9df2-0df035018523
usando el workspace /home/z/my-project/contexto_zai/gauntlet_ws (limpio).

El pipeline puede encolar tareas de subagentes en TaskBridgeServer (8087);
el agente principal debe hacer polling activo de /pending-tasks y ejecutarlas.
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
log = logging.getLogger("runner-6a00fcb8")


def main() -> int:
    from contexto_zai.client.credential_manager import CredentialManager
    from contexto_zai.models import DetectionTrigger
    from contexto_zai.pipeline import run

    cm = CredentialManager()
    jwt = cm.get_jwt()
    chat_id = "6a00fcb8-e86c-44dc-9df2-0df035018523"  # este chat
    workspace_dir = "/home/z/my-project/contexto_zai/gauntlet_ws"
    download_dir = "/home/z/my-project/contexto_zai/download/gauntlet_ws"

    Path(workspace_dir).mkdir(parents=True, exist_ok=True)
    Path(download_dir).mkdir(parents=True, exist_ok=True)

    log.info("=== Iteración 1 Gauntlet v6.13 — chat 6a00fcb8 ===")
    log.info("chat_id=%s, email=%s, jwt_len=%d", chat_id, cm.get_email(), len(jwt))
    log.info("workspace_dir=%s", workspace_dir)
    log.info("TaskBridgeServer en 8087 (si el pipeline encola tareas)")

    t0 = time.time()
    try:
        result = run(
            chat_id=chat_id,
            jwt=jwt,
            trigger=DetectionTrigger.EXPLICITO,
            reason="Iteración 1 del Gauntlet v6.13: ejecutar proceso real + 7 pasos con datos reales.",
            chat_label="CZAI Director (este chat)",
            workspace_dir=workspace_dir,
            download_dir=download_dir,
        )
    except Exception as e:
        log.error("EXCEPCIÓN en pipeline.run(): %s", e)
        log.error("Traceback:\n%s", traceback.format_exc())
        Path("/tmp/pipeline_6a00fcb8_result.json").write_text(
            json.dumps({"success": False, "error": str(e),
                       "traceback": traceback.format_exc()}, indent=2),
            encoding="utf-8",
        )
        return 1

    elapsed = time.time() - t0

    log.info("=== Pipeline terminado en %.1fs ===", elapsed)
    log.info("success=%s", result.success)
    log.info("cycle_used=%s", result.cycle_used)
    log.info("error=%s", result.error)
    log.info("pending_tasks=%d", len(result.pending_tasks) if result.pending_tasks else 0)

    out = {
        "success": result.success,
        "cycle_used": str(result.cycle_used),
        "error": result.error,
        "elapsed_sec": elapsed,
        "pending_tasks_count": len(result.pending_tasks) if result.pending_tasks else 0,
    }
    for attr in ("files_generated", "metadata", "stats", "summary"):
        v = getattr(result, attr, None)
        if v is not None:
            try:
                out[attr] = v.model_dump() if hasattr(v, "model_dump") else v
            except Exception:
                out[attr] = str(v)
    Path("/tmp/pipeline_6a00fcb8_result.json").write_text(
        json.dumps(out, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Resultado guardado en /tmp/pipeline_6a00fcb8_result.json")
    return 0 if result.success else 2


if __name__ == "__main__":
    sys.exit(main())
