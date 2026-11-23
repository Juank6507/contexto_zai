# /home/z/my-project/mini-services/pipeline-runner/real_test_h4.py
"""Test real H4: query_context con contexto recuperado real."""
import sys, time, logging
sys.path.insert(0, "/home/z/my-project")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", stream=sys.stdout)
log = logging.getLogger("test_h4")

from contexto_zai.pipeline import query_context

log.info("=== Test REAL H4: query_context con contexto recuperado ===")
log.info("Pregunta: ¿Qué se decidió sobre OOP en los subagentes?")

t0 = time.time()
try:
    answer = query_context("¿Qué se decidió sobre OOP en los subagentes?")
    elapsed = time.time() - t0
    log.info("query_context terminó en %.1fs", elapsed)
    log.info("Respuesta (%d chars):", len(answer))
    print()
    print(answer)
    print()

    with open("/tmp/real_test_h4_answer.txt", "w", encoding="utf-8") as f:
        f.write(answer)

    log.info("Respuesta guardada en /tmp/real_test_h4_answer.txt")
    log.info("=== TEST REAL H4: PASS ===")
except Exception as e:
    elapsed = time.time() - t0
    log.error("query_context falló tras %.1fs: %s", elapsed, e)
    import traceback
    log.error("Traceback:\n%s", traceback.format_exc())
    log.error("=== TEST REAL H4: FAIL ===")
