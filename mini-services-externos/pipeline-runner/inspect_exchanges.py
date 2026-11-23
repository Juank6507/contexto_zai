#!/usr/bin/env python3
"""Inspecciona los exchanges del chat EP 02 y muestra el cron completo.

Objetivo: identificar el punto exacto donde el Director empieza a hablar
del proyecto contexto_zai, para luego filtrar desde ahí hasta el final.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, "/home/z/my-project")

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("inspect")

SHARE_ID = "db717d70-95a7-4e2d-8992-fb4b6ba10df6"


def main() -> int:
    from client.chat_client import ChatClient
    from processing.exchange_builder import ExchangeBuilder
    from models import DetectionTrigger
    import datetime

    creds = json.loads(Path.home().joinpath(".czai/credentials.json").read_text())
    jwt = creds["token"]

    with ChatClient(token=jwt) as client:
        messages, raw = client.extract_all_with_raw(share_id=SHARE_ID)

    log.warning("Total mensajes extraidos: %d", len(messages))

    # Construir exchanges
    from subagents.intercambios_clasificador_subagent import (
        IntercambiosClasificadorSubagent,
        ModoClasificador,
    )
    from subagents.launcher import SubagentLauncher

    builder = ExchangeBuilder()
    exchanges = builder.build(messages)
    log.warning("Total exchanges construidos: %d", len(exchanges))

    # Listar cada exchange con su número, fecha, y un snippet del mensaje del Director
    print(f"\n{'#':>3}  {'Fecha':<17}  {'Tema':<40}  Snippet del Director")
    print("-" * 140)
    for ex in exchanges:
        fecha = datetime.datetime.fromtimestamp(ex.start_timestamp).strftime("%Y-%m-%d %H:%M")
        director_msg = ex.director_msg.content.strip()
        snippet = director_msg[:80].replace("\n", " ")
        if len(director_msg) > 80:
            snippet += "..."
        tema = (ex.topic or "(sin tema)")[:40]
        print(f"{ex.id:>3}  {fecha:<17}  {tema:<40}  {snippet}")

    # Guardar a JSON para siguiente paso
    out = []
    for ex in exchanges:
        agente_msg = ""
        if ex.agent_msgs:
            agente_msg = "\n\n---\n\n".join(m.content for m in ex.agent_msgs)
        out.append({
            "id": ex.id,
            "start_timestamp": ex.start_timestamp,
            "end_timestamp": ex.end_timestamp,
            "fecha": datetime.datetime.fromtimestamp(ex.start_timestamp).strftime("%Y-%m-%d %H:%M"),
            "tema": ex.topic,
            "director_msg": ex.director_msg.content,
            "agente_msg": agente_msg,
        })
    Path("/tmp/exchanges_ep02.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nExchanges guardados en /tmp/exchanges_ep02.json ({len(out)} intercambios)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
