#!/usr/bin/env python3
"""Script de enriquecimiento Nivel 2 para F10 v6.14.

Lanza _enriquecer_con_proxy_zai para cada bloque sin RESUMEN del workspace.
Robusto: captura todas las excepciones, no muere en el primer error.
"""
import sys
sys.path.insert(0, "/home/z/my-project")
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("enrich-v614")

import time
from pathlib import Path
from models import ThematicBlock
# v7.0 modularización: ``_enriquecer_con_proxy_zai`` ahora vive en
# ``pipeline_cascada``; ``AuditorWorkspace`` vive en ``pipeline_auditoria``.
# Ambos se re-exportan desde ``pipeline.py`` para backward-compat.
from pipeline import _enriquecer_con_proxy_zai, AuditorWorkspace

WORKSPACE = "/home/z/my-project/contexto_recuperacion"

def main():
    ws = Path(WORKSPACE)
    bloques_sin_resumen = []
    for p in sorted(ws.glob("bloque_*.md")):
        content = p.read_text(encoding="utf-8", errors="ignore")
        if not content.startswith("RESUMEN:"):
            bloques_sin_resumen.append(ThematicBlock(filename=p.name))

    log.info("=== Enriqueciendo %d bloques via proxy Z.ai (Nivel 2) ===", len(bloques_sin_resumen))
    t0 = time.time()
    completados = 0
    fallidos = []
    for i, bloque in enumerate(bloques_sin_resumen, 1):
        try:
            ok = _enriquecer_con_proxy_zai(bloque, WORKSPACE)
            if ok:
                completados += 1
                log.info("[%d/%d] %s: OK", i, len(bloques_sin_resumen), bloque.filename)
            else:
                fallidos.append(bloque.filename)
                log.warning("[%d/%d] %s: FALLÓ", i, len(bloques_sin_resumen), bloque.filename)
        except Exception as e:
            fallidos.append(bloque.filename)
            log.error("[%d/%d] %s: EXCEPCION %s", i, len(bloques_sin_resumen), bloque.filename, e)

    AuditorWorkspace.sincronizar_registro(WORKSPACE)
    elapsed = time.time() - t0
    log.info("=== RESUMEN: %d completados, %d fallidos, %.1fs ===", completados, len(fallidos), elapsed)
    if fallidos:
        log.warning("Fallidos: %s", fallidos[:10])
    return 0 if not fallidos else 2

if __name__ == "__main__":
    sys.exit(main())
