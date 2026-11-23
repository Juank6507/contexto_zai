# /home/z/my-project/mini-services/pipeline-runner/real_test_h1_restricciones.py
"""Test real H1 TEST 2: modo RESTRICCIONES_TEMA (M3 D4)."""
import sys
import time
import logging

sys.path.insert(0, "/home/z/my-project")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("real_test_h1_restricciones")


def main():
    log.info("=== Test REAL H1 TEST 2: modo RESTRICCIONES_TEMA (M3 D4) ===")

    from subagents.intercambios_clasificador_subagent import (
        IntercambiosClasificadorSubagent,
        ModoClasificador,
    )
    from subagents.launcher import SubagentLauncher
    from models import Exchange, Message, MessageRole

    exchanges = [
        Exchange(
            id=1,
            director_msg=Message(
                seq=1, role=MessageRole.USER, timestamp=1,
                content="No uses hardcoding en las constantes. Siempre configura en config.py."
            ),
            agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=2,
                                content="Entendido.")],
            topic="configuracion",
            start_timestamp=1,
            end_timestamp=2,
        ),
        Exchange(
            id=2,
            director_msg=Message(
                seq=3, role=MessageRole.USER, timestamp=3,
                content="Prohibido crear clases paralelas con fallback regex."
            ),
            agent_msgs=[Message(seq=4, role=MessageRole.ASSISTANT, timestamp=4,
                                content="De acuerdo.")],
            topic="configuracion",
            start_timestamp=3,
            end_timestamp=4,
        ),
    ]

    launcher = SubagentLauncher()
    sub = IntercambiosClasificadorSubagent(
        launcher=launcher,
        modo=ModoClasificador.RESTRICCIONES_TEMA,
    )

    t0 = time.time()
    log.info("Lanzando subagente en modo RESTRICCIONES_TEMA...")
    result = sub.run(exchanges)
    elapsed = time.time() - t0

    log.info("Resultado en %.1fs:", elapsed)
    log.info("  success: %s", result.success)
    log.info("  error: %s", result.error)
    if result.success:
        restricciones = result.resultado
        log.info("  restricciones detectadas: %d", len(restricciones))
        for r in restricciones:
            log.info("    - texto: %s", r.texto[:100])
            log.info("      alcance: %s", r.alcance[:100])

        # Guardar resultado
        import json
        with open("/tmp/real_test_h1_restricciones.json", "w", encoding="utf-8") as f:
            json.dump({
                "success": True,
                "restricciones": [
                    {"texto": r.texto, "alcance": r.alcance}
                    for r in restricciones
                ],
                "elapsed": elapsed,
            }, f, ensure_ascii=False, indent=2)
    else:
        log.error("Test falló: %s", result.error)
        return 1

    if result.success and len(result.resultado) >= 1:
        log.info("\n=== TEST REAL H1 TEST 2 (RESTRICCIONES_TEMA): PASS ===")
        return 0
    else:
        log.error("\n=== TEST REAL H1 TEST 2 (RESTRICCIONES_TEMA): FAIL ===")
        return 1


if __name__ == "__main__":
    sys.exit(main())
