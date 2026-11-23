# /home/z/my-project/mini-services/pipeline-runner/real_test_h3.py
"""Test real (sin mocks) del DecisionesGenerator v4.0.

Este test usa el SubagentLauncher con el invocador real (default_invoker)
que postea tareas al TaskBridgeServer en puerto 8087. El agente CZAI
hace polling de /pending-tasks y ejecuta las tareas con el Task tool.

Requiere:
- TaskBridgeServer activo en puerto 8087.
- El agente CZAI haciendo polling concurrente.
"""
import sys
import json
import time
import logging

sys.path.insert(0, "/home/z/my-project")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("real_test_h3")

from contexto_zai.generation.decisiones_generator import DecisionesGenerator
from contexto_zai.subagents.launcher import SubagentLauncher
from contexto_zai.models import Exchange, Message, MessageRole


def main():
    log.info("=== Test REAL del DecisionesGenerator v4.0 (sin mocks) ===")

    # Verificar que TaskBridgeServer está activo
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

    # Crear intercambios con una decisión real clara
    exchanges = [
        Exchange(
            id=1,
            director_msg=Message(
                seq=1, role=MessageRole.USER, timestamp=1,
                content="Vamos a usar OOP para todos los subagentes. La clase base se llama ClasificadorSubagent y tiene dos subclases."
            ),
            agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=2,
                                content="Entendido. Implementaré la clase base abstracta.")],
            topic="arquitectura_subagentes",
            start_timestamp=1,
            end_timestamp=2,
        ),
        Exchange(
            id=2,
            director_msg=Message(
                seq=3, role=MessageRole.USER, timestamp=3,
                content="Correcto"
            ),
            agent_msgs=[Message(seq=4, role=MessageRole.ASSISTANT, timestamp=4,
                                content="Implementando...")],
            topic="arquitectura_subagentes",
            start_timestamp=3,
            end_timestamp=4,
        ),
        Exchange(
            id=3,
            director_msg=Message(
                seq=5, role=MessageRole.USER, timestamp=5,
                content="No crear clases paralelas con fallback regex. Siempre subagentes."
            ),
            agent_msgs=[Message(seq=6, role=MessageRole.ASSISTANT, timestamp=6,
                                content="De acuerdo.")],
            topic="arquitectura_subagentes",
            start_timestamp=5,
            end_timestamp=6,
        ),
    ]

    # Crear SubagentLauncher con invocador REAL (sin mock)
    launcher = SubagentLauncher()
    gen = DecisionesGenerator(launcher=launcher)

    log.info("Lanzando DecisionesGenerator.generate() con launcher real...")
    log.info("Esto posteará una tarea al TaskBridgeServer y esperará la respuesta.")
    log.info("El agente CZAI debe hacer polling de /pending-tasks y ejecutar la tarea.")

    t0 = time.time()
    try:
        content, summary = gen.generate(exchanges)
        elapsed = time.time() - t0

        log.info("=== Resultado en %.1fs ===", elapsed)
        log.info("Contenido generado (%d chars):", len(content))

        # Guardar resultado
        with open("/tmp/real_test_h3_result.md", "w", encoding="utf-8") as f:
            f.write(content)
        with open("/tmp/real_test_h3_summary.txt", "w", encoding="utf-8") as f:
            f.write(summary)

        # Validaciones
        print("\n=== VALIDACIONES ===")

        # 1. El archivo tiene la estructura correcta
        assert "# Decisiones Clave" in content, "Falta header"
        print("[OK] Header 'Decisiones Clave' presente")

        # 2. Hay al menos 1 decisión (la de OOP)
        assert "OOP" in content or "oop" in content.lower(), "No se mencionó OOP"
        print("[OK] Decisión sobre OOP detectada")

        # 3. El formato incluye Alcance (v4.0)
        assert "**Alcance:**" in content, "Falta campo Alcance"
        print("[OK] Formato v4.0: campo 'Alcance' presente")

        # 4. "Correcto" NO debe ser una decisión (es aprobación genérica)
        # Buscar si "Correcto" aparece como título de decisión
        decision_headers = [line for line in content.split("\n") if line.startswith("## D")]
        for header in decision_headers:
            assert "Correcto" not in header, f"'Correcto' no debe ser decisión: {header}"
        print(f"[OK] {len(decision_headers)} decisiones detectadas, 'Correcto' descartado")

        # 5. El resumen no está vacío
        assert len(summary) > 0, "Resumen vacío"
        print(f"[OK] Resumen generado ({len(summary)} chars)")

        print(f"\n=== RESULTADO: {len(decision_headers)} decisiones reales detectadas en {elapsed:.1fs} ===")
        print(f"\nContenido completo en /tmp/real_test_h3_result.md")
        print(f"Resumen en /tmp/real_test_h3_summary.txt")

        # Mostrar las decisiones detectadas
        print("\n=== DECISIONES DETECTADAS ===")
        for header in decision_headers:
            print(f"  {header}")

        return 0

    except Exception as e:
        elapsed = time.time() - t0
        log.error("EXCEPCION tras %.1fs: %s", elapsed, e)
        import traceback
        log.error("Traceback:\n%s", traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
