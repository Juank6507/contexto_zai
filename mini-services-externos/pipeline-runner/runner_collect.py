"""Llama pipeline.collect_responses() para integrar las 50 respuestas de subagentes.

Tras ampliar_contexto() que publicó 50 pending_tasks y el agente CZAI ejecutó
los 50 subagentes (Nivel 3 de la cascada), esta función lee las respuestas
en _responses/, las integra, y genera los archivos finales de recuperación
(00_estado_actual, 01_indice_recuperacion, 02_decisiones_clave, 03_objetivo_proyecto,
_metadata.json, _processed_blocks.json, bloques temáticos, etc.).
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
log = logging.getLogger("collect-responses")


def main() -> int:
    from config import WORKSPACE_OUTPUT_DIR
    from pipeline import collect_responses

    workspace_dir = str(WORKSPACE_OUTPUT_DIR)

    log.info("=== collect_responses() — integrar 50 respuestas de subagentes ===")
    log.info("workspace_dir=%s", workspace_dir)
    log.info("Respuestas en _responses/: %d archivos",
             len(list(Path(workspace_dir).glob("_responses/*.txt"))))

    t0 = time.time()
    try:
        # is_chat_chronological=False porque viene de ampliar_contexto (fuente externa)
        result = collect_responses(
            workspace_dir=workspace_dir,
            is_chat_chronological=False,
        )
    except Exception as e:
        log.error("EXCEPCIÓN en collect_responses(): %s", e)
        log.error("Traceback:\n%s", traceback.format_exc())
        Path("/tmp/collect_result.json").write_text(
            json.dumps({"success": False, "error": str(e),
                       "traceback": traceback.format_exc()}, indent=2),
            encoding="utf-8",
        )
        return 1

    elapsed = time.time() - t0

    log.info("=== collect_responses terminado en %.1fs ===", elapsed)
    log.info("Resultado: %s", json.dumps(result, default=str, ensure_ascii=False, indent=2)[:3000])

    out = {
        "success": not result.get("error"),
        "elapsed_sec": elapsed,
        "result": result,
    }
    Path("/tmp/collect_result.json").write_text(
        json.dumps(out, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Resultado guardado en /tmp/collect_result.json")
    return 0 if not result.get("error") else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
