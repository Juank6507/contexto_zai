# /home/z/my-project/mini-services/pipeline-runner/real_test_h2_e2e.py
"""Test real H2: RecoveryCycle + EstadoGenerator con launcher real.

Flujo:
1. RecoveryCycle extrae mensajes del chat real (con JWT).
2. RecoveryCycle genera los archivos de recuperación (modo offline para D4).
3. Después, generamos el 00_estado_actual.md de nuevo con EstadoGenerator(launcher=...)
   para probar D4 con subagente real.
4. El agente hace polling y ejecuta la tarea del subagente.

Requiere:
- JWT en ~/.czai/credentials.json
- TaskBridgeServer activo en puerto 8087
"""
import sys
import time
import logging
import os

sys.path.insert(0, "/home/z/my-project")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", stream=sys.stdout)
log = logging.getLogger("h2_e2e")


def main():
    log.info("=== Test REAL H2 E2E: RecoveryCycle + EstadoGenerator con launcher ===")

    from client.credential_manager import CredentialManager
    from process.recovery_cycle import RecoveryCycle
    from generation.estado_generator import EstadoGenerator
    from subagents.launcher import SubagentLauncher

    cm = CredentialManager()
    jwt = cm.get_jwt()
    if not jwt:
        log.error("No hay JWT. Abortando.")
        return 1
    chat_id = "13b43432-36d8-4ed0-8fde-2c17e2f90484"  # chat actual

    log.info("JWT: %s", cm.get_email())
    log.info("chat_id: %s", chat_id)

    # 1. RecoveryCycle normal (extrae mensajes, genera archivos)
    log.info("\n--- FASE 1: RecoveryCycle (extracción + clasificación) ---")
    rc = RecoveryCycle(
        jwt=jwt,
        chat_id=chat_id,
        enable_capa3=False,
        enable_attachments=False,
    )

    t0 = time.time()
    try:
        result = rc.run(chat_label="H2 E2E")
    except Exception as e:
        elapsed = time.time() - t0
        log.error("RecoveryCycle falló tras %.1fs: %s", elapsed, e)
        import traceback
        log.error("Traceback:\n%s", traceback.format_exc())
        return 1

    elapsed = time.time() - t0
    log.info("RecoveryCycle terminado en %.1fs", elapsed)
    log.info("success: %s", result.success)

    if not result.success:
        log.error("RecoveryCycle falló: %s", result.error)
        return 1

    # 2. Leer los intercambios extraídos del _metadata.json o del archivo
    # Para esto, vamos a leer el chat_messages.json si existe, o re-extraer
    log.info("\n--- FASE 2: Generar 00_estado_actual.md con launcher real ---")

    # Leer el _metadata.json para ver cuántos intercambios hay
    import json
    from pathlib import Path
    meta_path = Path("/home/z/my-project/contexto_recuperacion/_metadata.json")
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
        log.info("Metadata: %d intercambios, %d temas", 
                  meta.get("total_exchanges", 0), 
                  len(meta.get("tema_a_archivo", {})))

    # Leer el 00_estado_actual.md generado (modo offline, sin subagente)
    estado_path = Path("/home/z/my-project/contexto_recuperacion/00_estado_actual.md")
    if estado_path.exists():
        estado_offline = estado_path.read_text(encoding="utf-8")
        log.info("00_estado_actual.md (offline) generado: %d chars", len(estado_offline))

    # 3. Ahora generar de nuevo con launcher real (para probar D4 con subagente)
    # Para eso necesitamos los intercambios. Los re-extraemos rápido.
    log.info("\n--- FASE 3: Re-extraer intercambios para generar con launcher ---")

    from client.auth_client import AuthClient
    from client.chat_client import ChatClient
    from processing.exchange_builder import ExchangeBuilder

    ac = AuthClient(token=jwt)
    cc = ChatClient(token=jwt)

    # Crear share
    share_id = ac.create_share(chat_id)
    log.info("Share creado: %s", share_id)

    # Obtener árbol
    tree = cc.get_message_tree(share_id)
    log.info("Árbol obtenido: %d mensajes", len(tree))

    # Extraer contenido
    messages = cc.extract_all_with_raw(chat_id, tree)
    log.info("Mensajes extraídos: %d", len(messages))

    # Construir intercambios
    builder = ExchangeBuilder()
    exchanges = builder.build(messages)
    log.info("Intercambios construidos: %d", len(exchanges))

    # 4. Generar 00_estado_actual.md con launcher real
    log.info("\n--- FASE 4: EstadoGenerator con launcher real ---")
    launcher = SubagentLauncher()
    gen = EstadoGenerator(launcher=launcher)

    log.info("Generando 00_estado_actual.md con subagente real para D4...")
    t0 = time.time()
    try:
        content = gen.generate(exchanges, chat_label="H2 E2E con launcher")
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
    with open("/tmp/real_test_h2_e2e_estado.md", "w", encoding="utf-8") as f:
        f.write(content)

    log.info("\n=== Contenido generado (primeros 1000 chars) ===")
    print(content[:1000])

    # Validaciones
    print("\n=== VALIDACIONES ===")
    for section in ["D1", "D4", "A1", "A2", "A3", "A4"]:
        assert f"Sección {section}" in content, f"Falta sección {section}"
    assert "Sección D2" not in content
    assert "Sección D3" not in content
    print("[OK] 5 secciones presentes (D2/D3 eliminadas)")

    print(f"\n=== TEST REAL H2 E2E: PASS ===")
    print(f"Archivo guardado en /tmp/real_test_h2_e2e_estado.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
