"""Continuación del enriquecimiento — Nivel 2 directo con MAX_ITER_W3.

Procesa los bloques sin RESUMEN del workspace gauntlet_ws usando
EnriquecimientoOrquestador._enriquecer_con_proxy_zai (que ahora tiene
el loop MAX_ITER_W3=5 con validación W3 ajena al ejecutor).

Lotes de 5 en paralelo (criterio C9 de la spec v6.13).
"""
from __future__ import annotations

import logging
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, "/home/z/my-project")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("enrich-nivel2")

WORKSPACE_DIR = "/home/z/my-project/contexto_zai/gauntlet_ws"
MAX_WORKERS = 5  # C9: lotes de 5 en paralelo


def main() -> int:
    from contexto_zai.models import ThematicBlock
    # v7.0 modularización: ``_enriquecer_con_proxy_zai`` ahora vive en
    # ``pipeline_cascada``; ``AuditorWorkspace`` vive en ``pipeline_auditoria``.
    # Ambos se re-exportan desde ``pipeline.py`` para backward-compat.
    from contexto_zai.pipeline import _enriquecer_con_proxy_zai, AuditorWorkspace

    ws = Path(WORKSPACE_DIR)

    # 1. Identificar bloques incompletos (sin RESUMEN al inicio)
    bloques_incompletos = []
    for p in sorted(ws.glob("bloque_*.md")):
        content = p.read_text(encoding="utf-8", errors="ignore")
        if not content.startswith("RESUMEN:"):
            bloques_incompletos.append(ThematicBlock(filename=p.name))

    log.info("=== Continuación Nivel 2 con MAX_ITER_W3 + backoff 429 ===")
    log.info("Workspace: %s", WORKSPACE_DIR)
    log.info("Bloques incompletos: %d", len(bloques_incompletos))
    log.info("Procesamiento SECUENCIAL (proxy Z.ai rate-limited, no paralelo)")

    if not bloques_incompletos:
        log.info("No hay bloques incompletos. Listo.")
        return 0

    # 2. Procesar SECUENCIAL (proxy está rate-limited, paralelo empeora 429)
    t0 = time.time()
    completados = 0
    fallados = []

    for i, bloque in enumerate(bloques_incompletos, start=1):
        try:
            ok = _enriquecer_con_proxy_zai(
                bloque, WORKSPACE_DIR
            )
            if ok:
                completados += 1
                log.info("[%d/%d] %s: ✅ completado", i, len(bloques_incompletos), bloque.filename)
            else:
                fallados.append(bloque.filename)
                log.warning("[%d/%d] %s: ❌ falló (irá a pending_task)",
                            i, len(bloques_incompletos), bloque.filename)
        except Exception as e:
            fallados.append(bloque.filename)
            log.error("[%d/%d] %s: EXCEPCIÓN %s",
                      i, len(bloques_incompletos), bloque.filename, e)

    elapsed = time.time() - t0

    # 3. Sincronizar registro
    AuditorWorkspace.sincronizar_registro(WORKSPACE_DIR)

    log.info("=== Resumen Nivel 2 ===")
    log.info("Total procesados: %d", len(bloques_incompletos))
    log.info("Completados: %d", completados)
    log.info("Fallidos (pending_tasks): %d", len(fallados))
    log.info("Tiempo: %.1fs (%.1fs/bloque)", elapsed, elapsed / max(1, len(bloques_incompletos)))

    if fallados:
        log.warning("Bloques fallidos:")
        for f in fallados:
            log.warning("  - %s", f)

    return 0 if not fallados else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
