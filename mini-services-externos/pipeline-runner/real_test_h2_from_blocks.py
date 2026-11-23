# /home/z/my-project/mini-services/pipeline-runner/real_test_h2_from_blocks.py
"""Test real H2: EstadoGenerator con launcher real usando intercambios de bloques existentes.

No usa la API de Z.ai (que cambió). En su lugar, lee un bloque temático ya generado
y construye intercambios sintéticos a partir de su contenido para probar el
EstadoGenerator con launcher real.

Requiere:
- Bloques temáticos en /home/z/my-project/contexto_recuperacion/bloque_*.md
- TaskBridgeServer activo en puerto 8087
"""
import sys
import time
import logging
import re
from pathlib import Path

sys.path.insert(0, "/home/z/my-project")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", stream=sys.stdout)
log = logging.getLogger("h2_blocks")


def parse_bloque_to_exchanges(bloque_path: Path) -> list:
    """Parsea un bloque temático y construye intercambios sintéticos."""
    from models import Exchange, Message, MessageRole

    content = bloque_path.read_text(encoding="utf-8")
    exchanges = []

    # Buscar bloques de intercambio en el formato:
    # ## Exchange N -- [fecha]
    # ### Director:
    # <contenido>
    # ### Agente:
    # <contenido>
    pattern = r"## Exchange (\d+) -- \[([^\]]+)\]\s*\n\s*### Director:\s*\n(.*?)\n\s*### Agente:\s*\n(.*?)(?=\n---\n|\n## Exchange|\Z)"
    matches = re.findall(pattern, content, re.DOTALL)

    for i, (ex_id, fecha, director_msg, agent_msg) in enumerate(matches, 1):
        # Limpiar el contenido (quitar JSON de tool_calls, dejar solo texto legible)
        director_clean = director_msg.strip()
        # Si el agente tiene JSON de tool_calls, tomar solo el primer texto
        agent_clean = agent_msg.strip()
        if agent_clean.startswith('{"type":'):
            # Es JSON de tool_calls, tomar el primer texto
            json_match = re.search(r'"type": "text", "content": "([^"]+)"', agent_clean)
            if json_match:
                agent_clean = json_match.group(1).replace("\\n", "\n").replace('\\"', '"')
            else:
                agent_clean = "[tool_calls]"

        ex = Exchange(
            id=int(ex_id),
            director_msg=Message(
                seq=i*2-1, role=MessageRole.USER, timestamp=i,
                content=director_clean[:2000]  # truncar para no llenar
            ),
            agent_msgs=[Message(
                seq=i*2, role=MessageRole.ASSISTANT, timestamp=i+0.5,
                content=agent_clean[:2000]
            )],
            topic="tema_del_bloque",
            start_timestamp=i,
            end_timestamp=i+1,
        )
        exchanges.append(ex)

    return exchanges


def main():
    log.info("=== Test REAL H2: EstadoGenerator con launcher (intercambios de bloque real) ===")

    # 1. Leer un bloque temático existente
    bloque_path = Path("/home/z/my-project/contexto_recuperacion/bloque_07.md")
    if not bloque_path.exists():
        log.error("No existe el bloque_07.md. Abortando.")
        return 1

    log.info("Leyendo bloque: %s", bloque_path.name)
    exchanges = parse_bloque_to_exchanges(bloque_path)
    log.info("Intercambios extraídos del bloque: %d", len(exchanges))

    if not exchanges:
        log.error("No se pudieron extraer intercambios del bloque.")
        return 1

    # Mostrar los primeros 3 intercambios
    for ex in exchanges[:3]:
        log.info("  Exchange %d (tema: %s): %s", ex.id, ex.topic, ex.director_msg.content[:80])

    # 2. Generar 00_estado_actual.md con launcher real
    log.info("\n--- Generar 00_estado_actual.md con launcher real ---")

    from generation.estado_generator import EstadoGenerator
    from subagents.launcher import SubagentLauncher

    launcher = SubagentLauncher()
    gen = EstadoGenerator(launcher=launcher)

    t0 = time.time()
    log.info("Lanzando EstadoGenerator.generate()...")
    try:
        content = gen.generate(exchanges, chat_label="H2 Test con bloque real")
    except Exception as e:
        elapsed = time.time() - t0
        log.error("EstadoGenerator falló tras %.1fs: %s", elapsed, e)
        import traceback
        log.error("Traceback:\n%s", traceback.format_exc())
        return 1

    elapsed = time.time() - t0
    log.info("EstadoGenerator terminado en %.1fs", elapsed)
    log.info("Contenido generado: %d chars", len(content))

    # Guardar resultado
    with open("/tmp/real_test_h2_blocks_estado.md", "w", encoding="utf-8") as f:
        f.write(content)

    log.info("\n=== Contenido generado (primeros 2000 chars) ===")
    print(content[:2000])

    # Validaciones
    print("\n=== VALIDACIONES ===")
    for section in ["D1", "D4", "A1", "A2", "A3", "A4"]:
        assert f"Sección {section}" in content, f"Falta sección {section}"
    assert "Sección D2" not in content
    assert "Sección D3" not in content
    print("[OK] 5 secciones presentes (D2/D3 eliminadas)")

    print(f"\n=== TEST REAL H2 (con bloque real): PASS ===")
    print(f"Archivo guardado en /tmp/real_test_h2_blocks_estado.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
