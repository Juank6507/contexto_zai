# /home/z/my-project/mini-services/pipeline-runner/real_test_h1.py
"""Test real (sin mocks) del IntercambiosClasificadorSubagent (H1).

Prueba el modo CONSULTA_BLOQUE (M8) y el modo RESTRICCIONES_TEMA (M3 D4)
con el SubagentLauncher real. El agente CZAI hace polling y ejecuta la tarea.

Requiere:
- TaskBridgeServer activo en puerto 8087.
- El agente CZAI haciendo polling concurrente.
"""
import sys
import time
import logging

sys.path.insert(0, "/home/z/my-project")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("real_test_h1")


def main():
    log.info("=== Test REAL de H1: IntercambiosClasificadorSubagent (sin mocks) ===")

    import requests
    try:
        r = requests.get("http://127.0.0.1:8087/health", timeout=3)
        if r.status_code != 200:
            log.error("TaskBridgeServer no responde. Abortando.")
            return 1
        log.info("TaskBridgeServer activo en puerto 8087.")
    except Exception as e:
        log.error("No se puede conectar a TaskBridgeServer: %s", e)
        return 1

    from contexto_zai.subagents.intercambios_clasificador_subagent import (
        IntercambiosClasificadorSubagent,
        ModoClasificador,
    )
    from contexto_zai.subagents.launcher import SubagentLauncher
    from contexto_zai.models import Exchange, Message, MessageRole

    # Intercambios de prueba
    exchanges = [
        Exchange(
            id=1,
            director_msg=Message(
                seq=1, role=MessageRole.USER, timestamp=1,
                content="¿Qué se decidió sobre el uso de OOP en el proyecto?"
            ),
            agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=2,
                                content="El Director decidió usar OOP para la clase base ClasificadorSubagent.")],
            topic="arquitectura_subagentes",
            start_timestamp=1,
            end_timestamp=2,
        ),
        Exchange(
            id=2,
            director_msg=Message(
                seq=3, role=MessageRole.USER, timestamp=3,
                content="Vamos a usar OOP. No crear clases paralelas con fallback regex."
            ),
            agent_msgs=[Message(seq=4, role=MessageRole.ASSISTANT, timestamp=4,
                                content="Entendido. Implementando...")],
            topic="arquitectura_subagentes",
            start_timestamp=3,
            end_timestamp=4,
        ),
    ]

    # Test 1: modo CONSULTA_BLOQUE (M8)
    log.info("\n--- TEST 1: modo CONSULTA_BLOQUE (M8) ---")
    launcher = SubagentLauncher()
    sub = IntercambiosClasificadorSubagent(
        launcher=launcher,
        modo=ModoClasificador.CONSULTA_BLOQUE,
        pregunta="¿Qué se decidió sobre OOP?",
    )

    t0 = time.time()
    log.info("Lanzando subagente en modo CONSULTA_BLOQUE...")
    result = sub.run(exchanges)
    elapsed = time.time() - t0

    log.info("Resultado en %.1fs:", elapsed)
    log.info("  success: %s", result.success)
    log.info("  error: %s", result.error)
    if result.success:
        log.info("  resultado (primeros 300 chars): %s", result.resultado[:300])
        with open("/tmp/real_test_h1_consulta.txt", "w", encoding="utf-8") as f:
            f.write(result.resultado)

    # Test 2: modo RESTRICCIONES_TEMA (M3 D4)
    log.info("\n--- TEST 2: modo RESTRICCIONES_TEMA (M3 D4) ---")
    sub2 = IntercambiosClasificadorSubagent(
        launcher=launcher,
        modo=ModoClasificador.RESTRICCIONES_TEMA,
    )

    t0 = time.time()
    log.info("Lanzando subagente en modo RESTRICCIONES_TEMA...")
    result2 = sub2.run(exchanges)
    elapsed2 = time.time() - t0

    log.info("Resultado en %.1fs:", elapsed2)
    log.info("  success: %s", result2.success)
    log.info("  error: %s", result2.error)
    if result2.success:
        restricciones = result2.resultado
        log.info("  restricciones detectadas: %d", len(restricciones))
        for r in restricciones:
            log.info("    - texto: %s", r.texto[:80])
            log.info("      alcance: %s", r.alcance[:80])

    # Test 3: modo NOMBRE_LEGIBLE (M7)
    log.info("\n--- TEST 3: modo NOMBRE_LEGIBLE (M7) ---")
    sub3 = IntercambiosClasificadorSubagent(
        launcher=launcher,
        modo=ModoClasificador.NOMBRE_LEGIBLE,
        max_context_tokens=2000,
    )

    t0 = time.time()
    log.info("Lanzando subagente en modo NOMBRE_LEGIBLE...")
    result3 = sub3.run(exchanges)
    elapsed3 = time.time() - t0

    log.info("Resultado en %.1fs:", elapsed3)
    log.info("  success: %s", result3.success)
    log.info("  error: %s", result3.error)
    if result3.success:
        log.info("  nombre legible: %s", result3.resultado)

    # Resumen final
    log.info("\n=== RESUMEN ===")
    log.info("Test 1 (CONSULTA_BLOQUE): %s", "PASS" if result.success else "FAIL")
    log.info("Test 2 (RESTRICCIONES_TEMA): %s", "PASS" if result2.success else "FAIL")
    log.info("Test 3 (NOMBRE_LEGIBLE): %s", "PASS" if result3.success else "FAIL")

    if result.success and result2.success and result3.success:
        log.info("\n=== TEST REAL H1: PASS ===")
        return 0
    else:
        log.error("\n=== TEST REAL H1: FAIL ===")
        return 1


if __name__ == "__main__":
    sys.exit(main())
