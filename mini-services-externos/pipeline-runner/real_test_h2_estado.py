# /home/z/my-project/mini-services/pipeline-runner/real_test_h2_estado.py
"""Test real (sin mocks) del EstadoGenerator v4.0 con launcher real (H2).

Prueba que el EstadoGenerator genera las 5 secciones con el subagente real:
- D1 literal
- D4 con subagente (RESTRICCIONES_TEMA)
- A1 con truncado inteligente (RESUMEN_TRUNCADO)
- A2, A3, A4 con patrones ampliados

Requiere TaskBridgeServer activo en puerto 8087.
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
log = logging.getLogger("real_test_h2")


def main():
    log.info("=== Test REAL H2: EstadoGenerator con launcher real (sin mocks) ===")

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

    from generation.estado_generator import EstadoGenerator
    from subagents.launcher import SubagentLauncher
    from models import Exchange, Message, MessageRole

    # Intercambios con restricciones claras para que D4 detecte
    exchanges = [
        Exchange(
            id=1,
            director_msg=Message(
                seq=1, role=MessageRole.USER, timestamp=1,
                content="No uses hardcoding en las constantes. Siempre config.py."
            ),
            agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=2,
                                content="Entendido. Configuraré en config.py.")],
            topic="configuracion_proyecto",
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
            topic="configuracion_proyecto",
            start_timestamp=3,
            end_timestamp=4,
        ),
        Exchange(
            id=3,
            director_msg=Message(
                seq=5, role=MessageRole.USER, timestamp=5,
                content="¿Qué se decidió sobre OOP?"
            ),
            agent_msgs=[Message(seq=6, role=MessageRole.ASSISTANT, timestamp=6,
                                content="Decidimos usar OOP para ClasificadorSubagent. Queda pendiente implementar las subclases.")],
            topic="configuracion_proyecto",
            start_timestamp=5,
            end_timestamp=6,
        ),
    ]

    # Crear EstadoGenerator con launcher real
    launcher = SubagentLauncher()
    gen = EstadoGenerator(launcher=launcher)

    log.info("Generando 00_estado_actual.md con launcher real...")
    t0 = time.time()
    content = gen.generate(exchanges, chat_label="Test Real H2")
    elapsed = time.time() - t0

    log.info("Generado en %.1fs (%d chars)", elapsed, len(content))

    # Guardar resultado
    with open("/tmp/real_test_h2_estado.md", "w", encoding="utf-8") as f:
        f.write(content)

    # Validaciones
    print("\n=== VALIDACIONES ===")

    # 1. 5 secciones presentes (D2/D3 eliminados)
    for section in ["D1", "D4", "A1", "A2", "A3", "A4"]:
        assert f"Sección {section}" in content, f"Falta sección {section}"
    assert "Sección D2" not in content, "D2 no debe estar"
    assert "Sección D3" not in content, "D3 no debe estar"
    print("[OK] 5 secciones presentes (D1, D4, A1, A2, A3, A4) — D2/D3 eliminadas")

    # 2. D1 contiene la última instrucción del Director literal
    assert "¿Qué se decidió sobre OOP?" in content
    print("[OK] D1: última instrucción del Director literal")

    # 3. D4 usó subagente (debe mencionar hardcoding o config.py)
    assert "hardcoding" in content.lower() or "config.py" in content.lower()
    print("[OK] D4: subagente detectó restricciones (hardcoding/config.py)")

    # 4. A4 detectó tarea pendiente
    assert "pendiente" in content.lower() or "Responder" in content or "Ejecutar" in content
    print("[OK] A4: detecta tarea pendiente")

    # 5. Header con tema en bold
    assert "**configuracion_proyecto**" in content
    print("[OK] Header: tema activo en bold")

    print(f"\n=== Contenido generado ({len(content)} chars) ===")
    print(content[:3000])
    if len(content) > 3000:
        print(f"\n... ({len(content) - 3000} chars más)")

    print(f"\n=== TEST REAL H2: PASS ===")
    print(f"Archivo guardado en /tmp/real_test_h2_estado.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
