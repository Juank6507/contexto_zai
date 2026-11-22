"""Runner para crear contexto desde exchanges_czai_consolidados.md vía ampliar_contexto.

Llama ampliar_contexto("file", exchanges_czai_consolidados.md) sobre el workspace
gauntlet_ws vacío. El proceso:
  1. Detecta archivo grande (>AMPLIAR_SMALL_FILE_THRESHOLD_TOKENS)
  2. Lo indexa vía ProcesadorDocumento
  3. Genera bloques temáticos
  4. Dispara la cascada de enriquecimiento (Worker Bun → proxy Z.ai → subagentes)
  5. Publica pending_tasks en _pending_tasks.json para que el agente CZAI las ejecute

El agente CZAI solo interviene cuando el proceso publica pending_tasks (Nivel 3
de la cascada). Hasta entonces, no se toca nada.
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
log = logging.getLogger("runner-ampliar")


def main() -> int:
    from contexto_zai.client.credential_manager import CredentialManager
    from contexto_zai.config import WORKSPACE_OUTPUT_DIR
    from contexto_zai.pipeline import ampliar_contexto

    cm = CredentialManager()
    jwt = cm.get_jwt()
    source_path = "/home/z/my-project/download/exchanges_czai_consolidados.md"
    # NO pasamos workspace_dir: el proceso usa su default del config
    # (WORKSPACE_OUTPUT_DIR = WORKSPACE_ROOT / "contexto_recuperacion").
    workspace_dir = str(WORKSPACE_OUTPUT_DIR)

    Path(workspace_dir).mkdir(parents=True, exist_ok=True)

    log.info("=== ampliar_contexto desde exchanges_czai_consolidados.md ===")
    log.info("source_path=%s", source_path)
    log.info("workspace_dir (default del config)=%s", workspace_dir)
    log.info("email=%s, jwt_len=%d", cm.get_email(), len(jwt))

    # Tamaño del archivo
    sp = Path(source_path)
    log.info("Archivo: %d bytes (~%d tokens)", sp.stat().st_size, int(sp.stat().st_size / 3.5))

    t0 = time.time()
    try:
        # Sin workspace_dir: el proceso usa WORKSPACE_OUTPUT_DIR del config.
        # Solo se interviene cuando el proceso publique pending_tasks (Nivel 3).
        result = ampliar_contexto(
            source_type="file",
            source_path=source_path,
            jwt=jwt,
            metadata={
                "title": "Exchanges consolidados CZAI (24/08/2026 - 03/11/2026)",
                "author": "Director",
                "date": "2026-11-03",
                "_ampliar_origin": {
                    "source_type": "file",
                    "source_path": source_path,
                },
            },
        )
    except Exception as e:
        log.error("EXCEPCIÓN en ampliar_contexto(): %s", e)
        log.error("Traceback:\n%s", traceback.format_exc())
        Path("/tmp/ampliar_result.json").write_text(
            json.dumps({"success": False, "error": str(e),
                       "traceback": traceback.format_exc()}, indent=2),
            encoding="utf-8",
        )
        return 1

    elapsed = time.time() - t0

    log.info("=== ampliar_contexto terminado en %.1fs ===", elapsed)
    log.info("Resultado: %s", json.dumps(result, default=str, ensure_ascii=False, indent=2)[:2000])

    out = {
        "success": not result.get("error"),
        "elapsed_sec": elapsed,
        "result": result,
    }
    Path("/tmp/ampliar_result.json").write_text(
        json.dumps(out, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Resultado guardado en /tmp/ampliar_result.json")
    return 0 if not result.get("error") else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
