# /home/z/my-project/mini-services/pipeline-runner/real_test_h1_nombre.py
"""Test real H1 TEST 3: modo NOMBRE_LEGIBLE (M7)."""
import sys
import time
import logging

sys.path.insert(0, "/home/z/my-project")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("real_test_h1_nombre")


def main():
    log.info("=== Test REAL H1 TEST 3: modo NOMBRE_LEGIBLE (M7) ===")

    from contexto_zai.subagents.intercambios_clasificador_subagent import (
        IntercambiosClasificadorSubagent,
        ModoClasificador,
    )
    from contexto_zai.subagents.launcher import SubagentLauncher
    from contexto_zai.models import Exchange, Message, MessageRole

    exchanges = [
        Exchange(
            id=1,
            director_msg=Message(
                seq=1, role=MessageRole.USER, timestamp=1,
                content="Vamos a implementar la autenticación JWT para acceder a la API de Z.ai"
            ),
            agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=2,
                                content="Entendido. Usaremos el JWT del Director.")],
            topic="general_general_2026sep09",  # nombre ilegible
            start_timestamp=1,
            end_timestamp=2,
        ),
        Exchange(
            id=2,
            director_msg=Message(
                seq=3, role=MessageRole.USER, timestamp=3,
                content="El JWT se obtiene con el bookmarklet y se guarda en credentials.json"
            ),
            agent_msgs=[Message(seq=4, role=MessageRole.ASSISTANT, timestamp=4,
                                content="Implementando...")],
            topic="general_general_2026sep09",
            start_timestamp=3,
            end_timestamp=4,
        ),
    ]

    launcher = SubagentLauncher()
    sub = IntercambiosClasificadorSubagent(
        launcher=launcher,
        modo=ModoClasificador.NOMBRE_LEGIBLE,
        max_context_tokens=2000,
    )

    t0 = time.time()
    log.info("Lanzando subagente en modo NOMBRE_LEGIBLE...")
    result = sub.run(exchanges)
    elapsed = time.time() - t0

    log.info("Resultado en %.1fs:", elapsed)
    log.info("  success: %s", result.success)
    log.info("  error: %s", result.error)
    if result.success:
        log.info("  nombre legible: %s", result.resultado)
        with open("/tmp/real_test_h1_nombre.txt", "w", encoding="utf-8") as f:
            f.write(result.resultado)

    if result.success and result.resultado:
        log.info("\n=== TEST REAL H1 TEST 3 (NOMBRE_LEGIBLE): PASS ===")
        return 0
    else:
        log.error("\n=== TEST REAL H1 TEST 3 (NOMBRE_LEGIBLE): FAIL ===")
        return 1


if __name__ == "__main__":
    sys.exit(main())
