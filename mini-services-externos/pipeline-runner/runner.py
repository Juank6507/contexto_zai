# /home/z/my-project/mini-services/pipeline-runner/runner.py
"""Lanzadera del pipeline contexto_zai.

Ejecuta pipeline.run() contra el chat CZAI 01 y guarda el resultado.
El pipeline puede encolar tareas de subagentes en TaskBridgeServer (8087);
el agente principal debe hacer polling activo y ejecutarlas con el Task tool.
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
log = logging.getLogger("pipeline-runner")


def main() -> int:
    from contexto_zai.client.credential_manager import CredentialManager
    from contexto_zai.models import DetectionTrigger
    from contexto_zai.pipeline import run

    cm = CredentialManager()
    jwt = cm.get_jwt()
    chat_id = "13b43432-36d8-4ed0-8fde-2c17e2f90484"  # CZAI 01

    log.info("=== Iniciando pipeline.run() ===")
    log.info("chat_id=%s, email=%s, jwt_len=%d", chat_id, cm.get_email(), len(jwt))
    log.info("TaskBridgeServer deberia estar en 8087 (si el pipeline encola tareas)")

    t0 = time.time()
    try:
        result = run(
            chat_id=chat_id,
            jwt=jwt,
            trigger=DetectionTrigger.EXPLICITO,
            reason="Director solicita aplicar contexto desde share link /s/1d1196b7-...",
            chat_label="CZAI 01",
        )
    except Exception as e:
        log.error("EXCEPCION en pipeline.run(): %s", e)
        log.error("Traceback:\n%s", traceback.format_exc())
        Path("/tmp/pipeline_result.json").write_text(
            json.dumps({"success": False, "error": str(e), "traceback": traceback.format_exc()}, indent=2),
            encoding="utf-8",
        )
        return 1

    elapsed = time.time() - t0

    log.info("=== Pipeline terminado en %.1fs ===", elapsed)
    log.info("success=%s", result.success)
    log.info("cycle_used=%s", result.cycle_used)
    log.info("error=%s", result.error)

    out = {
        "success": result.success,
        "cycle_used": str(result.cycle_used),
        "error": result.error,
        "elapsed_sec": elapsed,
    }
    for attr in ("files_generated", "metadata", "stats", "summary"):
        v = getattr(result, attr, None)
        if v is not None:
            try:
                out[attr] = v.model_dump() if hasattr(v, "model_dump") else v
            except Exception:
                out[attr] = str(v)
    Path("/tmp/pipeline_result.json").write_text(
        json.dumps(out, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Resultado guardado en /tmp/pipeline_result.json")
    return 0 if result.success else 2


if __name__ == "__main__":
    sys.exit(main())
