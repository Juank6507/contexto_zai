#!/usr/bin/env python3
"""Test real contra el chat del Director via link /s/.

Procesa el share_id db717d70-95a7-4e2d-8992-fb4b6ba10df6
usando el JWT del sandbox (/etc/.z-ai-config).
"""
from __future__ import annotations

import json
import logging
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, "/home/z/my-project")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("ampliar-share")

SHARE_URL = "https://chat.z.ai/s/db717d70-95a7-4e2d-8992-fb4b6ba10df6"
SHARE_ID = "db717d70-95a7-4e2d-8992-fb4b6ba10df6"
WORKSPACE_DIR = Path("/home/z/my-project/contexto_recuperacion")
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)


def load_jwt() -> str:
    """Lee JWT persistido en ~/.czai/credentials.json (JWT del Director)."""
    creds_path = Path.home() / ".czai" / "credentials.json"
    if not creds_path.exists():
        raise RuntimeError(
            "No existe ~/.czai/credentials.json. El Director debe ejecutar "
            "el .bat de Conectar CZAI para persistir su JWT."
        )
    data = json.loads(creds_path.read_text(encoding="utf-8"))
    token = data.get("token", "")
    if not token:
        raise RuntimeError("credentials.json existe pero el token está vacío.")
    return token


def main() -> int:
    log.info("=== Ampliar contexto desde link /s/ ===")
    log.info("Share URL: %s", SHARE_URL)
    log.info("Workspace: %s", WORKSPACE_DIR)

    jwt = load_jwt()
    log.info("JWT cargado (%d chars).", len(jwt))

    # Antes de invocar ampliar_contexto: obtener el arbol para
    # mostrar al Director cuantos exchanges hay y donde empieza el proyecto.
    log.info("--- Pre-exploracion: arbol de mensajes ---")
    from client.chat_client import ChatClient

    with ChatClient(token=jwt) as client:
        tree_data = client.get_message_tree(SHARE_ID)
        chat_data = tree_data.get("chat", {})
        chat_id = chat_data.get("id", "")
        messages_map = chat_data.get("history", {}).get("messages", {})
        log.info("chat_id descubierto: %s", chat_id)
        log.info("Total mensajes en arbol: %d", len(messages_map))

    # Invocar ampliar_contexto() — es el path publico del proceso
    from pipeline import ampliar_contexto

    t0 = time.time()
    try:
        result = ampliar_contexto(
            source_type="url",
            source_path=SHARE_URL,
            jwt=jwt,
            metadata={"jwt": jwt, "titulo": "Chat Director (link /s/)"},
            workspace_dir=WORKSPACE_DIR,
        )
    except Exception as e:
        log.error("EXCEPCION en ampliar_contexto(): %s", e)
        log.error("Traceback:\n%s", traceback.format_exc())
        Path("/tmp/ampliar_result.json").write_text(
            json.dumps({"success": False, "error": str(e), "traceback": traceback.format_exc()}, indent=2),
            encoding="utf-8",
        )
        return 1

    elapsed = time.time() - t0
    log.info("=== ampliar_contexto termino en %.1fs ===", elapsed)
    log.info("Resultado:\n%s", json.dumps(result, indent=2, default=str))

    # Persistir resultado
    Path("/tmp/ampliar_result.json").write_text(
        json.dumps({"success": True, "result": result, "elapsed_sec": elapsed}, indent=2, default=str),
        encoding="utf-8",
    )

    # Listar archivos generados en el workspace
    log.info("--- Workspace (%s) ---", WORKSPACE_DIR)
    for p in sorted(WORKSPACE_DIR.iterdir()):
        if p.is_file():
            log.info("  %s (%d bytes)", p.name, p.stat().st_size)
        else:
            log.info("  %s/", p.name)

    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
