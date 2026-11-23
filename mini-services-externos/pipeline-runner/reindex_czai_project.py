#!/usr/bin/env python3
# /home/z/my-project/mini-services/pipeline-runner/reindex_czai_project.py
"""Reindexa el chat EP 02 filtrando solo los exchanges del proyecto contexto_zai (v6.0).

El chat EP 02 (share_id=db717d70-...) tiene intercambios desde el 2026-08-24.
- Ex 1-21: configuración previa (estrategia APA/MB, investigación archivos tool_results)
- Ex 22 (2026-08-30 13:18): "¿Qué crees que podemos hacer con lo que hemos investigado?"
  → NACE formalmente el proyecto contexto_zai
- Ex 22+: la primera parte del proyecto contexto_zai (concepción)

Este script genera el workspace inicial SOLO con los exchanges del proyecto contexto_zai,
usando v6.0 (sin Subdivider, sin Capa 3 — bloques secuenciales).
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from pathlib import Path

sys.path.insert(0, "/home/z/my-project")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("reindex-czai")

SHARE_ID = "db717d70-95a7-4e2d-8992-fb4b6ba10df6"
WORKSPACE_DIR = Path("/home/z/my-project/contexto_recuperacion")
EXCHANGE_START = 22  # Acta de nacimiento del proyecto


def load_jwt() -> str:
    creds_path = Path.home() / ".czai" / "credentials.json"
    data = json.loads(creds_path.read_text(encoding="utf-8"))
    return data["token"]


def _construir_objetivo_proyecto() -> str:
    return """# Recuperación de contexto del proyecto

## Quién eres

Sos un agente Z.ai (modelo GLM) que el Director **Juan Carlos González**
(`juanca6507@gmail.com`) está construyendo como parte de una estrategia
mayor de trabajo con proyectos informáticos. Tu nombre interno en esta
fase es **CZAI** (Contexto Z.ai). Trabajás en un sandbox de Z.ai en la
ruta `/home/z/my-project/` (Next.js + Bun + Python venv).

## Cuál es tu norte

**Construir un proceso automático de recuperación de contexto** para
cuando un agente pierde contexto silenciosamente — sin que él mismo se
de cuenta — durante interacciones largas con el Director.

El proceso debe:
1. Detectar la pérdida de contexto (trigger explícito o por umbral).
2. Extraer el chat completo desde chat.z.ai vía share link `/s/`.
3. Construir intercambios (director + agente) y clasificarlos por temas.
4. Empaquetar en bloques secuenciales por tamaño (no subdividir temas).
5. Generar 4 archivos de recuperación:
   - `03_objetivo_proyecto.md` — PRIMER archivo a leer (este).
   - `00_estado_actual.md` — dónde quedó, qué estaba haciendo, qué sigue.
   - `01_indice_recuperacion.md` — mapeo tema → archivo de bloque.
   - `02_decisiones_clave.md` — decisiones explicitadas durante el chat.
6. Generar bloques `bloque_NN.md` con el contenido crudo.
7. Dejar preparadas `_pending_tasks.json` para procesar vía el proxy APA.

## Qué te pasó y cómo recuperarte

Has perdido contexto. Esto es normal y tienes un proceso que te ayuda.

1. Estás leyendo este archivo — ya empezaste a recuperarte.
2. Lee `00_estado_actual.md` para saber qué estaba pasando.
3. Consulta `01_indice_recuperacion.md` para saber dónde está cada tema.
4. Revisa `02_decisiones_clave.md` para no repetir lo ya decidido.
5. Si necesitas detalle de un tema, lanza un subagente con pregunta concreta.
6. Si el Director te pasa información nueva, usa `ampliar_contexto()`.
"""


def main() -> int:
    log.info("=== Reindex chat EP 02 — solo exchanges del proyecto contexto_zai (desde Ex %d) ===",
             EXCHANGE_START)
    log.info("Workspace: %s", WORKSPACE_DIR)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    jwt = load_jwt()
    log.info("JWT del Director cargado (%d chars).", len(jwt))

    # 1. Extraer mensajes del share EP 02
    log.info("--- Paso 1: Extrayendo mensajes del share EP 02 ---")
    from contexto_zai.client.chat_client import ChatClient
    with ChatClient(token=jwt) as client:
        messages, raw_messages = client.extract_all_with_raw(share_id=SHARE_ID)
        tree_data = client.get_message_tree(SHARE_ID)

    chat_id = tree_data.get("chat", {}).get("id", "")
    share_id_real = tree_data.get("id", SHARE_ID)
    log.info("Total mensajes: %d, chat_id=%s", len(messages), chat_id)

    # 2. Construir exchanges
    log.info("--- Paso 2: Construyendo exchanges ---")
    from contexto_zai.processing.exchange_builder import ExchangeBuilder
    from contexto_zai.processing.classifier import MessageClassifier
    from contexto_zai.processing.block_packer import BlockPacker
    from contexto_zai.generation.recovery_generator import RecoveryGenerator
    from contexto_zai.generation.estado_generator import EstadoGenerator
    from contexto_zai.generation.decisiones_generator import DecisionesGenerator
    from contexto_zai.metadata.manager import MetadataManager
    from contexto_zai.models import RecoveryMetadata
    from contexto_zai.processing.decision_extractor import DecisionExtractor

    builder = ExchangeBuilder()
    all_exchanges = builder.build(messages)
    log.info("Total exchanges construidos: %d", len(all_exchanges))

    # 3. Filtrar SOLO exchanges del proyecto contexto_zai (desde Ex 22)
    proyecto_exchanges = [ex for ex in all_exchanges if ex.id >= EXCHANGE_START]
    log.info("Exchanges del proyecto contexto_zai: %d (de Ex %d a Ex %d)",
             len(proyecto_exchanges), EXCHANGE_START, all_exchanges[-1].id)

    # 4. Re-numerar secuencialmente
    for i, ex in enumerate(proyecto_exchanges, start=1):
        ex.id = i

    # 5. Clasificar
    log.info("--- Paso 3: Clasificando ---")
    classifier = MessageClassifier()
    classifier.classify_exchanges(proyecto_exchanges)

    # v6.0: Sin Subdivider — agrupar por tema directamente y empaquetar
    by_topic = {}
    for ex in proyecto_exchanges:
        by_topic.setdefault(ex.topic, []).append(ex)

    # 6. Empaquetar en bloques secuenciales
    log.info("--- Paso 4: Empaquetando en bloques ---")
    packer = BlockPacker()
    blocks = packer.pack(by_topic)
    log.info("Bloques generados: %d", len(blocks))

    # 7. Metadata
    log.info("--- Paso 5: Construyendo metadata ---")
    metadata_mgr = MetadataManager(output_dir=WORKSPACE_DIR)
    metadata = RecoveryMetadata(
        chat_id=chat_id,
        share_id=share_id_real,
        total_exchanges=len(proyecto_exchanges),
        ultimo_timestamp=max(ex.end_timestamp for ex in proyecto_exchanges),
    )
    for block in blocks:
        for tema in block.temas:
            metadata.registrar_tema(tema, block.filename)
    from datetime import datetime, timezone
    metadata.ultima_activacion = datetime.now(timezone.utc).isoformat()
    metadata_mgr.write(metadata)

    # 8. Pre-crear 03_objetivo_proyecto.md
    log.info("--- Paso 6: Pre-creando 03_objetivo_proyecto.md ---")
    objetivo_path = WORKSPACE_DIR / "03_objetivo_proyecto.md"
    if not objetivo_path.exists():
        objetivo_path.write_text(_construir_objetivo_proyecto(), encoding="utf-8")
        log.info("03_objetivo_proyecto.md pre-creado.")

    # 9. Generar archivos de recuperación
    log.info("--- Paso 7: Generando archivos de recuperación ---")
    estado_gen = EstadoGenerator(workspace_dir=WORKSPACE_DIR)
    estado_gen._asegurar_objetivo_proyecto()

    real_extractor = DecisionExtractor()
    decisiones_gen = DecisionesGenerator(extractor=real_extractor.extract)

    recovery_gen = RecoveryGenerator(
        estado_generator=estado_gen,
        decisiones_generator=decisiones_gen,
    )
    recovery_files = recovery_gen.generate_all(
        exchanges=proyecto_exchanges,
        blocks=blocks,
        chat_label="CZAI_concepcion",
        metadata=metadata,
        attachments_indexados=[],
    )
    log.info("Archivos generados: %d", len(recovery_files))

    # 10. Escribir archivos
    log.info("--- Paso 8: Escribiendo archivos ---")
    for rf in recovery_files:
        target = WORKSPACE_DIR / rf.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rf.content, encoding="utf-8")
        log.info("  %s (%d bytes)", rf.filename, len(rf.content))

    # 11. Listar workspace
    log.info("--- Workspace final ---")
    for p in sorted(WORKSPACE_DIR.iterdir()):
        if p.is_file():
            log.info("  %s (%d bytes)", p.name, p.stat().st_size)

    log.info("=== Reindex completado ===")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        log.error("EXCEPCION: %s", e)
        log.error("Traceback:\n%s", traceback.format_exc())
        raise SystemExit(1)
