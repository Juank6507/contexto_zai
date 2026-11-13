# contexto_zai/pipeline.py -- Entry point del proceso (v6.9): link /s/ y /c/ de Z.ai procesados como fuente externa (preserva bloques existentes), sin delegar a pipeline.run(), un solo camino para ampliar contexto.
"""Entry point del proceso Contexto Z.ai (v3.4).

Reemplaza la CLI de v1.0. Expone funciones para activar la
recuperación de contexto (`run`), consultar estado (`status`),
y exportar/importar el contexto entre agentes (`export_context`,
`import_context`).

Es un script de dependencia: orquesta el Orchestrator y los
módulos de exportación/importación.
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
# Soporta Estructura A (<workspace>/contexto_zai/) y Estructura B (workspace=contexto_zai/)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
_package_root = None
for _ in range(10):
    if not _os.path.isfile(_os.path.join(_candidate, '__init__.py')):
        break  # salimos del paquete
    _parent = _os.path.dirname(_candidate)
    if not _os.path.isfile(_os.path.join(_parent, '__init__.py')):
        _package_root = _candidate
        break
    _candidate = _parent
if _package_root:
    _workspace = _os.path.dirname(_package_root)
    if _workspace not in _sys.path:
        _sys.path.insert(0, _workspace)
else:
    _parent = _os.path.dirname(_here)
    if _parent not in _sys.path:
        _sys.path.insert(0, _parent)

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import time  # v6.13 C10: para sleep en backoff HTTP 429

from contexto_zai.config import DOWNLOAD_OUTPUT_DIR, WORKSPACE_OUTPUT_DIR
from contexto_zai.models import DetectionTrigger
from contexto_zai.process.orchestrator import Orchestrator, OrchestratorResult

logger = logging.getLogger(__name__)

class ContextoPipeline:
    """v6.11 F5: API pública del pipeline (refactor OOP).
    
    Agrupa funciones relacionadas como métodos estáticos. Las funciones
    módulo-nivel son wrappers momentáneos que delegan a estos métodos.
    """

    @staticmethod
    def run(
        chat_id: str,
        jwt: str = "",
        trigger: DetectionTrigger = DetectionTrigger.EXPLICITO,
        reason: str = "",
        chat_label: str = "",
        workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
        download_dir: Path | str = DOWNLOAD_OUTPUT_DIR,
        share_id: Optional[str] = None,
    ) -> OrchestratorResult:
            """Activa el proceso de recuperación de contexto.

            v6.14 F5 (criterio 21): esta función es la API pública del
            proceso. El agente CZAI **no** escribe scripts ``runner_*.py``
            para invocarla — usa el daemon ``pipeline-daemon`` (puerto 8088,
            endpoint ``POST /pipeline-run``). El daemon desvincula el proceso
            del Bash tool con doble setsid y sobrevive entre llamadas.

            Es la función principal que el agente invoca cuando detecta
            pérdida de contexto o el Director lo indica.

            v6.10 F1: si ``jwt`` llega vacío, se carga automáticamente del
            ``CredentialManager`` (donde persiste el JWT del Director puesto
            por el bookmarklet). Si después de cargarlo sigue vacío, se
            devuelve un error claro.

            Args:
                chat_id: UUID interno del chat (viene en metadatos del gateway).
                    Puede estar vacío si se pasa ``share_id`` externo (v4.2).
                jwt: JWT del Director. Si es vacío, se carga del CredentialManager.
                trigger: Tipo de disparador.
                reason: Razón legible de la activación.
                chat_label: Etiqueta del chat.
                workspace_dir: Directorio donde se escriben los archivos
                    de recuperación en el workspace del agente.
                download_dir: Directorio de descarga (copia para el Director).
                share_id: UUID de un share público existente (opcional, v4.2).
                    Si se pasa, el proceso NO crea su propio share y usa este
                    ``share_id`` para leer un chat compartido externo (link
                    ``/s/`` de otra sesión del agente).

            Returns:
                OrchestratorResult con el resultado de la activación.

            Raises:
                ValueError: Si no hay JWT disponible (ni en el parámetro ni en
                    el CredentialManager).

            Example:
                >>> from contexto_zai.pipeline import run
                >>> from contexto_zai.models import DetectionTrigger
                >>> # Caso 1: chat actual del agente (JWT se carga automáticamente)
                >>> result = run(chat_id="13b43432-...")
                >>> # Caso 2: chat externo vía link /s/ (v4.2)
                >>> result = run(chat_id="", share_id="abc-123")
            """
            # v6.10 F1 / v6.11 F4: carga automática del JWT si llega vacío.
            # v6.11 F4: pipeline.py es el punto de entrada público y puede
            # importar de client/ para cargar el JWT. Es la excepción legítima:
            # el punto de entrada conoce la plataforma, los módulos internos no.
            if not jwt:
                try:
                    from contexto_zai.client.credential_manager import CredentialManager
                    cm = CredentialManager()
                    jwt = cm.get_jwt() or ""
                    if jwt:
                        logger.info("v6.10 F1: JWT cargado del CredentialManager (email=%s)", cm.get_email())
                except Exception as e:
                    logger.warning("v6.10 F1: no se pudo cargar el JWT del CredentialManager: %s", e)

            if not jwt:
                # Sin JWT no se puede continuar. Devolver error claro en vez de
                # fallar con HTTP 401 sin explicación.
                error_result = OrchestratorResult(
                    success=False,
                    error="No hay JWT disponible. Pedí al Director que reconecte CZAI desde el sandbox (botón 'Conectar CZAI' en el Preview Panel).",
                )
                return error_result

            orch = Orchestrator(
                chat_id=chat_id,
                jwt=jwt,
                workspace_dir=workspace_dir,
                download_dir=download_dir,
                share_id=share_id,
            )
            result = orch.activate(
                trigger=trigger,
                reason=reason,
                chat_label=chat_label,
            )
            # v6.2: post-procesar bloques con fallback al agente si el proxy Z.ai falla
            # v6.14: paso P14 del proceso de 19 pasos (cascada W1+W2+W3 con bucle D7
            # en cada nivel: Worker Bun → proxy Z.ai → subagentes).
            result = _enriquecer_bloques_post_run(
                result=result,
                workspace_dir=workspace_dir,
                chat_label=chat_label,
            )
            # v6.14 F2 (criterio 17): P15 — sincronizar _processed_blocks.json
            # con el estado físico real (bloques con RESUMEN + 3 archivos
            # _responses/) DESPUÉS del enriquecimiento (P14), no antes.
            try:
                AuditorWorkspace.sincronizar_registro(workspace_dir)
            except Exception as e:
                logger.warning("v6.14 P15: sincronizar_registro falló: %s", e)
            # v6.14 F2 (criterio 17): P16 — auditoría final DESPUÉS de P14.
            # Verifica el estado real del workspace tras el enriquecimiento y
            # reporta cuántos bloques están completos/incompletos. Lo que siga
            # incompleto se vierte al saco _pending_tasks.json (lo gestiona P17).
            #
            # v6.18 F4 (criterio 4): P16 SIEMPRE se ejecuta tras procesar,
            # sin importar si el contexto existía previamente o se creó desde
            # cero. Si el proceso va por ampliar_contexto → RecoveryCycle →
            # collect_responses → cascada, P16 se ejecuta al final de la
            # cascada vía ``_auditar_y_completar()`` (que también invoca
            # ``AuditorWorkspace.auditar_completitud()``).
            try:
                audit_final = AuditorWorkspace.auditar_completitud(workspace_dir)
                logger.info(
                    "v6.14 P16: Auditoría final (post-enriquecimiento): %d completos, %d incompletos, metadata_valida=%s",
                    len(audit_final["completos"]), len(audit_final["incompletos"]), audit_final["metadata_valida"],
                )
            except Exception as e:
                logger.warning("v6.14 P16: auditar_completitud falló: %s", e)
            # v6.3 F1 → v6.14 F3 (criterio 18): paso P17 — bucle D7 con
            # MAX_ITER_D7=5 para garantizar completitud de los bloques que
            # quedaron incompletos tras P14-P16. Publica pending_tasks con
            # feedback sobre qué falló (W3: longitud/oraciones/etiquetas, o
            # archivos _nombre.txt/_decisiones.txt/_temas.txt faltantes) para
            # que el agente CZAI lance los subagentes con el Task tool.
            result = _bucle_d7_completitud(
                result=result,
                workspace_dir=workspace_dir,
            )
            # v6.4 F1: consolidar decisiones del LLM (de _responses/) en 02_decisiones_clave.md
            # v6.14: paso P18 del proceso de 19 pasos.
            _consolidar_decisiones_llm(workspace_dir=workspace_dir)
            # v6.15 F6 (criterio 33): paso P19 del proceso de 19 pasos.
            # Regenera ``01_indice_recuperacion.md`` DESPUÉS del enriquecimiento
            # (P14) y la consolidación de decisiones (P18), cuando los bloques
            # ya tienen RESUMEN y ``tema_a_archivo`` está poblado con los temas
            # significativos extraídos de ``_responses/<bloque>_temas.txt``.
            # En P9 (durante ``RecoveryGenerator.generate_all``), el IndiceGenerator
            # se invoca como placeholder inicial (sin temas) — P19 lo sobrescribe
            # con contenido real.
            _regenerar_indice_tras_enriquecimiento(workspace_dir=workspace_dir)
            return result

    @staticmethod
    def query_context(
        question: str,
        max_results: int = 3,
        workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
    ) -> dict:
            """Prepara la consulta al proceso de contexto con una pregunta concreta.

            Esta función NO lanza subagentes. Identifica los bloques candidatos,
            calcula el tamaño total, elige el modo (directo o distribuido), y
            prepara los prompts para que el agente principal los ejecute con el
            Task tool directamente.

            El agente principal llama a esta función, recibe el dict con los
            prompts, lanza el/los subagente(s) con el Task tool, y consolida
            las respuestas.

            Args:
                question: Pregunta concreta del agente.
                max_results: Máximo de bloques a consultar.
                workspace_dir: Directorio donde están los archivos de recuperación.

            Returns:
                Dict con:
                - "mode": "direct" o "distributed"
                - "question": la pregunta original
                - "prompts": lista de prompts (1 para modo directo, N para distribuido)
                - "bloques": lista de nombres de bloques candidatos
                - "total_tokens": tamaño total estimado de los bloques
                - Si no hay contexto: {"error": "No hay contexto recuperado..."}
                - Si no hay candidatos: {"error": "No hay información relevante..."}

            Example:
                >>> from contexto_zai.pipeline import query_context
                >>> result = query_context("¿Qué se decidió sobre OOP?")
                >>> if "error" not in result:
                ...     # Lanzar subagente(s) con el Task tool usando result["prompts"]
                ...     pass
            """
            import json as _json
            import re as _re
            from contexto_zai.config import (
                QUERY_DIRECT_MODE_THRESHOLD_TOKENS,
                QUERY_MAX_RESULTS,
            )

            effective_max = min(max_results, QUERY_MAX_RESULTS)
            workspace = Path(workspace_dir)

            # 1. Verificar que el contexto existe.
            # v4.2 (unificación): el contexto puede venir de pipeline.run()
            # (bloques del chat + 01_indice_recuperacion.md) O de ampliar_contexto()
            # (bloques externos registrados en _metadata.json sin índice del chat).
            # No se exige 01_indice_recuperacion.md como prerrequisito — alcanza con
            # que haya _metadata.json con entradas en tema_a_archivo.
            indice_path = workspace / "01_indice_recuperacion.md"
            metadata_path = workspace / "_metadata.json"
            indice_exists = indice_path.exists()
            metadata_exists = metadata_path.exists()

            if not indice_exists and not metadata_exists:
                return {
                    "error": "No hay contexto recuperado. Ejecuta pipeline.run() o ampliar_contexto() primero."
                }

            # 2. Leer metadata para obtener mapeo tema -> archivo (fuente única de verdad)
            # v6.0: los valores pueden ser str (legacy) o list[str] (multi-bloque).
            tema_a_archivo: dict = {}
            if metadata_exists:
                try:
                    metadata = _json.loads(metadata_path.read_text(encoding="utf-8"))
                    tema_a_archivo = metadata.get("tema_a_archivo", {})
                except (_json.JSONDecodeError, ValueError):
                    pass

            # Si no hay temas en metadata y no hay índice, no hay nada que buscar.
            if not tema_a_archivo and not indice_exists:
                return {"error": "No hay información en el contexto."}

            # 3. Buscar bloques candidatos por keyword
            question_lower = question.lower()
            question_words = _re.findall(r"[a-záéíóúñ_]+", question_lower)
            _stop_words = {"que", "de", "la", "el", "en", "y", "a", "los", "las", "del",
                           "para", "con", "por", "es", "se", "un", "una", "como", "cual",
                           "cuales", "sobre", "del", "al"}
            question_words = [w for w in question_words if len(w) > 2 and w not in _stop_words]

            # v4.2: Si no hay keywords útiles (pregunta muy corta o solo stop words),
            # no buscar por keyword y devolver error claro (evita match spurious).
            if not question_words:
                return {"error": "La pregunta no contiene palabras clave para buscar."}

            # Buscar en nombres de temas (tema_a_archivo ya incluye temas del chat y externos)
            bloques_candidatos: dict[str, list[str]] = {}
            for tema, archivos in tema_a_archivo.items():
                tema_lower = tema.lower()
                match = False
                for word in question_words:
                    if word in tema_lower:
                        match = True
                        break
                if not match:
                    continue
                # v6.0: archivos puede ser str (legacy) o list[str] (multi-bloque)
                if isinstance(archivos, str):
                    archivos_list = [archivos]
                else:
                    archivos_list = list(archivos)
                for archivo in archivos_list:
                    bloques_candidatos.setdefault(archivo, []).append(tema)

            # Buscar en contenido del índice (solo del chat — ampliar_contexto no genera índice)
            if not bloques_candidatos and indice_exists:
                indice_lower = indice_path.read_text(encoding="utf-8").lower()
                for tema, archivos in tema_a_archivo.items():
                    match = False
                    for word in question_words:
                        if word in indice_lower:
                            match = True
                            break
                    if not match:
                        continue
                    # v6.0: multi-bloque
                    if isinstance(archivos, str):
                        archivos_list = [archivos]
                    else:
                        archivos_list = list(archivos)
                    for archivo in archivos_list:
                        bloques_candidatos.setdefault(archivo, []).append(tema)

            # Buscar en contenido de los bloques
            if not bloques_candidatos:
                for tema, archivos in tema_a_archivo.items():
                    # v6.0: multi-bloque
                    if isinstance(archivos, str):
                        archivos_list = [archivos]
                    else:
                        archivos_list = list(archivos)
                    for archivo in archivos_list:
                        bloque_path = workspace / archivo
                        if not bloque_path.exists():
                            continue
                        bloque_content = bloque_path.read_text(encoding="utf-8").lower()
                        match = False
                        for word in question_words:
                            if word in bloque_content:
                                match = True
                                break
                        if match:
                            bloques_candidatos.setdefault(archivo, []).append(tema)
                            break

            if not bloques_candidatos:
                return {"error": "No hay información relevante en los archivos de recuperación."}

            # Limitar a max_results bloques
            bloques_a_consultar = list(bloques_candidatos.keys())[:effective_max]

            # 4. Calcular tamaño total de los bloques
            total_chars = 0
            bloques_info = []
            for filename in bloques_a_consultar:
                bloque_path = workspace / filename
                if bloque_path.exists():
                    content = bloque_path.read_text(encoding="utf-8")
                    chars = len(content)
                    tokens_estimados = int(chars / 3.5)
                    total_chars += chars
                    bloques_info.append({
                        "filename": filename,
                        "path": str(bloque_path),
                        "chars": chars,
                        "tokens_estimados": tokens_estimados,
                        "temas": bloques_candidatos[filename],
                    })

            total_tokens = int(total_chars / 3.5)

            logger.info(
                "query_context: '%s' -> %d bloques, %d tokens totales",
                question[:60], len(bloques_a_consultar), total_tokens,
            )

            # 5. v4.4: Atajo de resúmenes (Sistema 2).
            # Antes de preparar prompts para subagentes, mirar si algún resumen
            # de los bloques candidatos ya responde la pregunta. Si responde,
            # el agente puede leer el resumen directamente sin lanzar subagente.
            resumenes_atajo = _buscar_en_resumenes(workspace, question, bloques_info)
            if resumenes_atajo:
                logger.info(
                    "query_context: atajo de resúmenes encontrado (%d chars)",
                    len(resumenes_atajo),
                )
                return {
                    "mode": "resumen_atajo",
                    "question": question,
                    "resumen_atajo": resumenes_atajo,
                    "bloques": [b["filename"] for b in bloques_info],
                    "bloques_info": bloques_info,
                }

            # 6. Elegir modo según tamaño (solo si el atajo no respondió)
            if total_tokens < QUERY_DIRECT_MODE_THRESHOLD_TOKENS:
                modo = "direct"
            else:
                modo = "distributed"

            # 6. Preparar prompts
            prompts = []

            if modo == "direct":
                # Un solo subagente que lee todos los bloques
                rutas = "\n".join(f"- {b['path']}" for b in bloques_info)
                prompt = f"""Eres un subagente que responde a una consulta del agente principal sobre el contexto del proyecto.

        ## Pregunta

        {question}

        ## Archivos a leer

        {rutas}

        ## Instrucciones

        1. Lee los archivos indicados con la herramienta Read.
        2. Busca información relevante para responder a la pregunta.
        3. Si encuentras información, respóndela de forma completa y abarcadora.
        4. Si no encuentras nada relevante en ningún archivo, responde exactamente: "No hay información relevante en los archivos."
        5. No inventes información. Solo reporta lo que encuentras.
        6. Consolida la información de todos los archivos en una sola respuesta coherente.

        Respuesta:"""
                prompts.append(prompt)
            else:
                # Modo distribuido: un subagente por bloque
                for b in bloques_info:
                    prompt = f"""Eres un subagente que responde a una consulta del agente principal sobre un bloque temático.

        ## Pregunta

        {question}

        ## Archivo a leer

        - {b['path']}

        ## Instrucciones

        1. Lee el archivo con la herramienta Read.
        2. Busca información relevante para responder a la pregunta.
        3. Si encuentras información, respóndela de forma completa.
        4. Si no encuentras nada relevante, responde exactamente: "No hay información relevante en este bloque."

        Respuesta:"""
                    prompts.append(prompt)

            return {
                "mode": modo,
                "question": question,
                "prompts": prompts,
                "bloques": [b["filename"] for b in bloques_info],
                "total_tokens": total_tokens,
                "bloques_info": bloques_info,
            }

    @staticmethod
    def ampliar_contexto(
        source_type: str,
        source_path: str,
        jwt: str = "",
        metadata: Optional[dict] = None,
        workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
    ) -> dict:
            """Amplía el contexto desde una fuente externa (link o archivo).

            v6.14 F5 (criterio 21): esta función es la API pública del
            proceso. El agente CZAI **no** escribe scripts ``runner_*.py``
            para invocarla — usa el daemon ``pipeline-daemon`` (puerto 8088,
            endpoint ``POST /ampliar-contexto``).

            El Director puede pasarle al agente links o documentos para que se
            incorporen al contexto del proyecto. Esta función procesa la fuente
            y, si es grande, la indexa como nuevos bloques en el directorio de
            recuperación.

            Args:
                source_type: "url" o "file".
                source_path: La URL o la ruta al archivo.
                jwt: JWT del Director (si es URL de Z.ai).
                metadata: Metadata opcional (título, autor, fecha).
                workspace_dir: Directorio donde están los archivos de recuperación.

            Returns:
                Dict con:
                - "needs_agent_read": True si el archivo es chico y el agente lo lee directo.
                - "path": ruta al archivo (si needs_agent_read=True).
                - "indexed": True si el proceso lo indexó (archivo grande).
                - "bloques_nuevos": lista de nombres de bloques nuevos (si indexed=True).
                - "error": mensaje de error si algo falló.

            Example:
                >>> from contexto_zai.pipeline import ampliar_contexto
                >>> result = ampliar_contexto("file", "/path/to/doc.pdf")
                >>> if result.get("needs_agent_read"):
                ...     # El agente lee el archivo directo
                ...     pass
                >>> elif result.get("indexed"):
                ...     print(f"Bloques nuevos: {result['bloques_nuevos']}")
            """
            import json as _json
            from contexto_zai.config import (
                AMPLIAR_SMALL_FILE_THRESHOLD_TOKENS,
                AMPLIAR_URL_DOWNLOAD_TIMEOUT,
                AMPLIAR_URL_MAX_SIZE_BYTES,
                ATTACHMENTS_TEMP_DIR,
                WORKSPACE_OUTPUT_DIR as _WS_DIR,
            )

            workspace = Path(workspace_dir)
            metadata = metadata or {}

            # 1. v6.9: Si es URL de Z.ai (/s/ o /c/), descargar el contenido del chat
            # como fuente externa (igual que un archivo). No delegar a pipeline.run().
            # Esto preserva los bloques existentes porque pasa por _integrar_documento()
            # que usa _siguiente_nombre_bloque().
            if source_type == "url" and "chat.z.ai/" in source_path:
                es_link_share = "/s/" in source_path
                es_link_chat = "/c/" in source_path

                if es_link_share or es_link_chat:
                    # v6.9: extraer el ID del link
                    tipo_link = "share" if es_link_share else "chat"
                    id_extraido = _extraer_id_de_link(source_path, tipo_link)
                    if not id_extraido:
                        return {
                            "error": f"No se pudo extraer el {tipo_link}_id del link /{tipo_link[0]}/: {source_path}. "
                            f"Formato esperado: https://chat.z.ai/{'s' if es_link_share else 'c'}/<uuid>."
                        }

                    # JWT: del metadata o del parámetro jwt
                    jwt_para_run = metadata.get("jwt", "") if isinstance(metadata, dict) else ""
                    if not jwt_para_run and jwt:
                        jwt_para_run = jwt
                    if not jwt_para_run:
                        return {
                            "error": f"Se requiere JWT del Director para procesar un link /{tipo_link[0]}/ "
                            "de Z.ai. Pásalo en metadata={'jwt': '...'}."
                        }

                    logger.info(
                        "v6.9: link /%s/ de Z.ai detectado, %s_id='%s' — "
                        "procesando como fuente externa (preserva bloques existentes)",
                        tipo_link[0], tipo_link, id_extraido,
                    )

                    # v6.9/v6.11 F4: extraer el contenido del chat como texto plano
                    # v6.11 F4: usa MessageExtractor en vez de importar directamente de client/
                    try:
                        from contexto_zai.processing.message_extractor import MessageExtractor
                        extractor = MessageExtractor(jwt=jwt_para_run, chat_id=id_extraido if es_link_chat else "")
                        if es_link_share:
                            # /s/ — share_id directo
                            from contexto_zai.client.chat_client import ChatClient as _CC
                            with _CC(token=jwt_para_run) as client:
                                messages = client.extract_all(share_id=id_extraido, chat_id=None)
                        else:
                            # /c/ — crear share del chat_id
                            messages = extractor.get_all_messages() if id_extraido else []
                        # v6.11 F4: pipeline.py es el punto de entrada público;
                        # puede usar MessageExtractor o los clientes directamente
                        # porque es quien conoce la plataforma.

                        if not messages:
                            return {"error": f"No se extrajeron mensajes del link /{tipo_link[0]}/: {source_path}"}

                        logger.info(
                            "v6.9: extraídos %d mensajes del link /%s/, convirtiendo a texto...",
                            len(messages), tipo_link[0],
                        )

                        # v6.9: convertir los mensajes a texto plano (formato legible)
                        # para que el ProcesadorDocumento lo procese como fuente externa
                        text_lines = []
                        for msg in messages:
                            role_label = "Director" if msg.role.value == "user" else "Agente"
                            text_lines.append(f"--- {role_label} ---")
                            text_lines.append(msg.content)
                            text_lines.append("")

                        content_str = "\n".join(text_lines)
                        content_bytes = content_str.encode("utf-8")
                        filename = f"chat_zai_{id_extraido[:12]}.txt"

                        logger.info(
                            "v6.9: contenido del chat convertido a texto: %d bytes, ~%d tokens",
                            len(content_bytes), int(len(content_bytes) / 3.5),
                        )

                        # Guardar el origen en metadata para archivo_a_source
                        metadata["_ampliar_origin"] = {
                            "source_type": "url",
                            "source_path": source_path,
                            "share_id": id_extraido if es_link_share else "",
                            "chat_id": id_extraido if es_link_chat else "",
                        }

                    except Exception as e:
                        return {"error": f"v6.9: Error extrayendo contenido del link /{tipo_link[0]}/: {e}"}

            # 2. Obtener el contenido (para archivos y URLs externas no-Z.ai)
            # v6.9: si ya se extrajo contenido del chat Z.ai (link /s/ o /c/),
            # content_bytes y filename ya están seteados. Saltar la descarga.
            temp_path = None
            if source_type == "file":
                file_path = Path(source_path)
                if not file_path.exists():
                    return {"error": f"Archivo no encontrado: {source_path}"}
                content_bytes = file_path.read_bytes()
                filename = file_path.name
            elif source_type == "url" and 'content_bytes' not in locals():
                # v6.9: solo descargar si no se extrajo ya del chat Z.ai
                import requests
                try:
                    r = requests.get(source_path, timeout=AMPLIAR_URL_DOWNLOAD_TIMEOUT, stream=True)
                    r.raise_for_status()

                    # Verificar tamaño
                    content_length = int(r.headers.get("content-length", 0))
                    if content_length > AMPLIAR_URL_MAX_SIZE_BYTES:
                        return {"error": f"URL demasiado grande: {content_length} bytes > {AMPLIAR_URL_MAX_SIZE_BYTES}"}

                    content_bytes = r.content
                    # Nombre de archivo desde la URL
                    from urllib.parse import urlparse
                    parsed = urlparse(source_path)
                    filename = Path(parsed.path).name or "documento_descargado"
                except Exception as e:
                    return {"error": f"Error descargando URL: {e}"}
            elif source_type == "url":
                # v6.9: si es url y content_bytes ya está seteado (del bloque /s/ o /c/),
                # no hacer nada aquí. El contenido ya está disponible.
                if 'content_bytes' not in locals() or 'filename' not in locals():
                    return {"error": f"source_type url pero no se pudo obtener contenido."}
            else:
                return {"error": f"source_type no válido: {source_type}. Use 'url' o 'file'."}

            # 3. Estimar tokens
            estimated_tokens = len(content_bytes) / 3.5  # aprox 1 token = 3.5 bytes

            # v6.14 F6 (criterio 22): detectar estructura del contenido.
            # - "cronologico": el contenido tiene marcadores de intercambios
            #   cronológicos (## Exchange N -- [timestamp] o ### 📅 YYYY-MM-DD).
            #   Procesar como P4.1: extraer intercambios y construirlos en P5.
            # - "arbitrario": documento sin estructura cronológica. Saltar P5
            #   y pasar directamente a P6 (clasificar por tema a nivel de bloque).
            estructura = EnriquecimientoOrquestador._detectar_estructura_contenido(content_bytes)
            if not isinstance(metadata, dict):
                metadata = {}
            metadata["_estructura"] = estructura
            logger.info(
                "ampliar_contexto: %s '%s' -> %d bytes, ~%d tokens, estructura=%s",
                source_type, filename, len(content_bytes), int(estimated_tokens), estructura,
            )

            # v6.14 F6: si la estructura es "cronologico", el contenido se procesa
            # como P4.1 (extraer intercambios y construirlos en P5). Si es
            # "arbitrario", se salta P5 y se va directo a P6 (clasificar por
            # tema a nivel de bloque). El ProcesadorDocumento (paso 5 más abajo)
            # recibe el metadata con ``_estructura`` y puede actuar en consecuencia.
            #
            # Para ampliar_contexto, el ``origen`` siempre es "externo" (viene
            # de archivo externo, no de chat Z.ai). La detección de estructura
            # solo afecta si se hace P5 (ExchangeBuilder) o se salta a P6.
            # Para pipeline.run() (chat Z.ai), ``origen`` siempre es "cronologico".
            origen = "externo"
            metadata["_origen"] = origen

            # 4. Si es chico, el agente lo lee directo
            if estimated_tokens < AMPLIAR_SMALL_FILE_THRESHOLD_TOKENS:
                # Guardar en temp para que el agente lo encuentre
                ATTACHMENTS_TEMP_DIR.mkdir(parents=True, exist_ok=True)
                temp_path = ATTACHMENTS_TEMP_DIR / filename
                temp_path.write_bytes(content_bytes)

                return {
                    "needs_agent_read": True,
                    "path": str(temp_path),
                    "filename": filename,
                    "tokens_estimados": int(estimated_tokens),
                    "estructura": estructura,
                    "origen": origen,
                }

            # v6.18 F1 (criterio 1): si estructura="cronologico", pasar por
            # RecoveryCycle. RecoveryCycle construye intercambios (P5),
            # clasifica por tema (P6), usa BlockPacker para ordenar bloques
            # por timestamp descendente (P7, bloque_01 = más reciente), y
            # genera bloques físicos + archivos 00-03. Reusar RecoveryCycle,
            # no duplicar lógica.
            #
            # v6.18 F2 (criterio 2): BlockPacker ordena descendente
            # automáticamente cuando pack() se llama con origen="cronologico"
            # (default). Los intercambios parseados del archivo externo llevan
            # start_timestamp poblado por ExchangeBuilder a partir del
            # timestamp parseado del ``## Exchange N -- [timestamp]``.
            #
            # Si estructura="arbitrario": sigue el flujo actual
            # (ProcesadorDocumento).
            if estructura == "cronologico":
                from contexto_zai.process.recovery_cycle import RecoveryCycle

                # Parsear intercambios desde el contenido del archivo externo.
                messages = EnriquecimientoOrquestador._parsear_intercambios_desde_contenido(
                    content_bytes
                )
                if not messages:
                    return {
                        "error": (
                            "Estructura cronológica detectada pero no se pudieron "
                            "parsear intercambios del archivo (formato esperado: "
                            "'## Exchange N -- [YYYY-MM-DD HH:MM]' + '### Director:' "
                            "+ '### Agente:')."
                        ),
                    }

                logger.info(
                    "v6.18 F1: ampliar_contexto con estructura=cronologico — "
                    "pasando por RecoveryCycle (%d mensajes parseados)",
                    len(messages),
                )

                # safe_filename se usa tanto en el flujo cronológico como en
                # el arbitrario para indexar el archivo original.
                safe_filename = filename.replace(" ", "_").replace("/", "_")

                # Crear RecoveryCycle con origen="externo" y
                # estructura="cronologico". El packer.pack() usa default
                # origen="cronologico" → ordena descendente (criterio 2).
                cycle = RecoveryCycle(
                    jwt=jwt or "",
                    chat_id="",
                    workspace_dir=workspace,
                    origen="externo",
                    estructura="cronologico",
                    enable_attachments=False,  # no hay attachments en archivo externo
                )
                cycle_result = cycle.run_from_messages(
                    messages, chat_label=filename,
                )

                if not cycle_result.success:
                    return {
                        "error": (
                            f"v6.18 F1: RecoveryCycle falló: {cycle_result.error}"
                        ),
                    }

                # Guardar el archivo original en indexed para referencia
                # (no necesita temp_path: los intercambios ya están
                # materializados como bloques en el workspace).
                from contexto_zai.config import ATTACHMENTS_INDEXED_DIR
                ATTACHMENTS_INDEXED_DIR.mkdir(parents=True, exist_ok=True)
                indexed_path = ATTACHMENTS_INDEXED_DIR / safe_filename
                try:
                    if indexed_path.exists():
                        indexed_path.unlink()
                    indexed_path.write_bytes(content_bytes)
                except Exception as e:
                    logger.warning(
                        "v6.18 F1: no se pudo guardar el archivo original en indexed: %s", e
                    )

                # Actualizar _metadata.json con source (mismo esquema que
                # el flujo arbitrario, para que collect_responses y la
                # cascada puedan leer la estructura externa).
                metadata_path = workspace / "_metadata.json"
                if metadata_path.exists():
                    try:
                        meta = _json.loads(metadata_path.read_text(encoding="utf-8"))
                    except (_json.JSONDecodeError, ValueError):
                        meta = {}
                else:
                    meta = {}

                if "archivo_a_source" not in meta:
                    meta["archivo_a_source"] = {}
                ampliar_origin = (
                    metadata.pop("_ampliar_origin", None)
                    if isinstance(metadata, dict) else None
                )
                if ampliar_origin:
                    meta["archivo_a_source"][safe_filename] = ampliar_origin
                else:
                    meta["archivo_a_source"][safe_filename] = {
                        "source_type": source_type,
                        "source_path": source_path,
                        "filename": filename,
                        "metadata": metadata,
                        "estructura": estructura,
                    }
                meta["_estructura_externa"] = estructura
                metadata_path.write_text(
                    _json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
                )

                logger.info(
                    "v6.18 F1: ampliar_contexto cronológico procesado — "
                    "%d bloques, %d intercambios, %d pending_tasks",
                    cycle_result.blocks_count,
                    cycle_result.exchanges_count,
                    len(cycle_result.pending_tasks or []),
                )

                return {
                    "needs_agent_read": False,
                    "indexed": True,
                    "filename": filename,
                    "path": str(indexed_path),
                    "pending_tasks": cycle_result.pending_tasks or [],
                    "tokens_estimados": int(estimated_tokens),
                    "flujo": "recovery_cycle_cronologico",
                    "num_lotes": cycle_result.blocks_count,
                    "estructura": estructura,
                    "origen": origen,
                    "bloques_nuevos": cycle_result.blocks_count,
                }

            # 5. Si es grande (estructura="arbitrario"), usar ProcesadorDocumento
            # (patrón diferido v4.2). El ProcesadorDocumento decide según tamaño
            # (mediano=un subagente, grande=3 niveles) y publica las tareas vía
            # el Orquestador. No intenta descargar de la API de Z.ai.
            from contexto_zai.coordinador import Orquestador
            from contexto_zai.procesadores import ProcesadorDocumento

            # Guardar en temp primero
            ATTACHMENTS_TEMP_DIR.mkdir(parents=True, exist_ok=True)
            safe_filename = filename.replace(" ", "_").replace("/", "_")
            temp_path = ATTACHMENTS_TEMP_DIR / f"ampliar_{safe_filename}"
            temp_path.write_bytes(content_bytes)

            # F4 v4.2: crear Orquestador + ProcesadorDocumento y procesar
            orquestador = Orquestador(workspace_dir=workspace)
            procesador = ProcesadorDocumento(
                workspace_dir=workspace,
                orquestador=orquestador,
            )

            # Procesar el documento (publica tareas automáticamente)
            proc_result = procesador.procesar(
                source_type="file",
                source_path=str(temp_path),
                jwt=jwt,
                metadata=metadata,
            )

            # Mover el archivo de temp a indexed
            from contexto_zai.config import ATTACHMENTS_INDEXED_DIR
            ATTACHMENTS_INDEXED_DIR.mkdir(parents=True, exist_ok=True)
            indexed_path = ATTACHMENTS_INDEXED_DIR / safe_filename
            if temp_path.exists():
                # v4.2 fix Windows: Path.rename() en Windows lanza FileExistsError si
                # el destino ya existe; en Linux lo sobrescribe. Para comportamiento
                # cross-platform consistente, eliminamos el destino si existe antes
                # de renombrar (igual que documento_indexer_subagent.py líneas 247-249).
                if indexed_path.exists():
                    indexed_path.unlink()
                temp_path.rename(indexed_path)

            # Actualizar _metadata.json con source
            metadata_path = workspace / "_metadata.json"
            if metadata_path.exists():
                try:
                    meta = _json.loads(metadata_path.read_text(encoding="utf-8"))
                except (_json.JSONDecodeError, ValueError):
                    meta = {}
            else:
                meta = {}

            # Agregar mapeo archivo -> source
            if "archivo_a_source" not in meta:
                meta["archivo_a_source"] = {}
            # v6.9: si el origen es un link /s/ o /c/ de Z.ai, registrar el origen correcto
            ampliar_origin = metadata.pop("_ampliar_origin", None) if isinstance(metadata, dict) else None
            if ampliar_origin:
                meta["archivo_a_source"][safe_filename] = ampliar_origin
            else:
                meta["archivo_a_source"][safe_filename] = {
                    "source_type": source_type,
                    "source_path": source_path,
                    "filename": filename,
                    "metadata": metadata,
                    # v6.17 F10 (criterio 10): propagar estructura desde P4.2
                    # hasta que el bloque externo sea integrado. Los bloques
                    # externos con estructura cronológica generan los 4 archivos
                    # de recuperación (00_estado_actual.md, 01_indice, 02_decisiones,
                    # bloques). Si estructura="arbitrario", se omiten los 2 primeros.
                    "estructura": estructura,
                }
            # v6.17 F10 (criterio 10): propagar estructura al top-level de
            # metadata.json para que collect_responses() pueda leerla sin
            # tener que recorrer archivo_a_source.
            meta["_estructura_externa"] = estructura
            metadata_path.write_text(_json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

            logger.info(
                "ampliar_contexto: documento '%s' procesado (%d tokens), %d tareas publicadas",
                filename,
                int(estimated_tokens),
                len(proc_result.get("pending_tasks", [])),
            )

            return {
                "needs_agent_read": False,
                "indexed": True,
                "filename": filename,
                "path": str(indexed_path),
                "pending_tasks": proc_result.get("pending_tasks", []),
                "tokens_estimados": int(estimated_tokens),
                "flujo": proc_result.get("flujo", "mediano"),
                "num_lotes": proc_result.get("num_lotes", 1),
                "estructura": estructura,
                "origen": origen,
            }

    @staticmethod
    def collect_responses(
        workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
        is_chat_chronological: bool = True,
    ) -> dict:
            """v4.2 → v6.17 F4 (criterio 3): Recoge respuestas y las integra al workspace.

            v6.17 F4 (criterio 3): ``collect_responses()`` SOLO integra
            respuestas. Lee ``_responses/``, las aplica al workspace
            según el ``purpose`` de cada tarea, y devuelve resultado.

            NO verifica bloques incompletos. NO dispara la cascada W1+W2+W3
            (P14). Esa verificación y disparo la hace el proceso
            (daemon/pipeline) tras llamar ``collect_responses()`` —
            típicamente ``ContextoPipeline.run()`` invoca
            ``_enriquecer_bloques_post_run()`` (que dispara la cascada) y
            luego ``_bucle_d7_completitud()`` (P17, bucle D7 separado de la
            cascada según F3).

            La consolidación de decisiones y la regeneración del índice
            (``_consolidar_decisiones_llm`` y
            ``_regenerar_indice_tras_enriquecimiento``) no son parte de la
            cascada — son pasos de post-integración. Se mantienen aquí para
            preservar el comportamiento del chat cronológico.

            El agente nunca ve el contenido crudo de las respuestas — solo
            llama a esta función y recibe el resultado estructurado.

            Args:
                workspace_dir: Directorio del workspace donde viven _pending_tasks.json
                    y _responses/.
                is_chat_chronological: v6.11 F6 — ``True`` (default) si la operación
                    viene de ``pipeline.run()`` (chat cronológico). ``False`` si viene
                    de ``ampliar_contexto()`` (fuente externa, no cronológica). Si es
                    ``False``: se saltan los handlers que regeneran
                    ``00_estado_actual.md`` y se omite ``_consolidar_decisiones_llm()``.

            Returns:
                Dict con el resultado estructurado:
                - "responses": lista de SubagentResponse leídas.
                - "total_leidas": número de respuestas leídas.
                - "integradas": True si se aplicaron.
                - "total_aplicadas": número de respuestas aplicadas.
                - "errores": lista de errores (si los hubo).

            Example:
                >>> from contexto_zai.pipeline import run, collect_responses
                >>> result = run(chat_id="...", jwt="...")
                >>> if result.pending_tasks:
                ...     # El agente lanza los subagentes con el Task tool
                ...     # Los subagentes escriben en _responses/
                ...     applied = collect_responses()
                ...     print(f"Aplicadas: {applied['total_aplicadas']}")
            """
            # v6.17 F4: delega a EnriquecimientoOrquestador.collect_responses()
            # que es la implementación real. Esta wrapper se mantiene por
            # compatibilidad con código externo que llama
            # ``ContextoPipeline.collect_responses()``.
            return EnriquecimientoOrquestador.collect_responses(
                workspace_dir=workspace_dir,
                is_chat_chronological=is_chat_chronological,
            )


def run(
    chat_id: str,
    jwt: str = "",
    trigger: DetectionTrigger = DetectionTrigger.EXPLICITO,
    reason: str = "",
    chat_label: str = "",
    workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
    download_dir: Path | str = DOWNLOAD_OUTPUT_DIR,
    share_id: Optional[str] = None,
) -> OrchestratorResult:
    """v6.11 F5: Wrapper que delega a ContextoPipeline.run()."""
    return ContextoPipeline.run(chat_id=chat_id, jwt=jwt, trigger=trigger, reason=reason, chat_label=chat_label, workspace_dir=workspace_dir, download_dir=download_dir, share_id=share_id)

def status(
    chat_id: str,
    workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
) -> dict:
    """Devuelve el estado actual del proceso.

    Args:
        chat_id: UUID del chat.
        workspace_dir: Directorio del workspace.

    Returns:
        Diccionario con el estado de la metadata.
    """
    # El Orchestrator solo necesita chat_id para status
    orch = Orchestrator(
        chat_id=chat_id,
        jwt="",  # no se usa para status
        workspace_dir=workspace_dir,
    )
    return orch.status()


# -- v3.4: Exportación / Importación de contexto entre agentes --------


def export_context(
    chat_id: str = "",
    workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
    output_dir: Path | str = DOWNLOAD_OUTPUT_DIR.parent,
) -> Optional[Path]:
    """Empaqueta el contexto del proyecto en un .zip para transferirlo a otro agente.

    Args:
        chat_id: ID del chat para nombrar el archivo (opcional).
        workspace_dir: Directorio donde están los archivos del contexto.
        output_dir: Directorio donde guardar el .zip (default: download/).

    Returns:
        Ruta del .zip creado, o None si no había archivos.

    Example:
        >>> from contexto_zai.pipeline import export_context
        >>> path = export_context(chat_id="abc-123")
        >>> if path:
        ...     print(f"Contexto exportado: {path}")
    """
    from contexto_zai.context.exporter import ContextExporter

    exporter = ContextExporter(workspace_dir=workspace_dir)
    return exporter.export(chat_id=chat_id, output_dir=output_dir)


def import_context(
    zip_path: Path | str,
    workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
) -> Optional[str]:
    """Descomprime un paquete de contexto exportado y lo carga en el workspace.

    Args:
        zip_path: Ruta del archivo .zip exportado por `export_context`.
        workspace_dir: Directorio donde cargar los archivos (default: workspace/).

    Returns:
        Contenido de las instrucciones de recuperación, o None si falló.

    Example:
        >>> from contexto_zai.pipeline import import_context
        >>> instrucciones = import_context("/path/to/contexto.zip")
        >>> if instrucciones:
        ...     print("Contexto cargado. Instrucciones:")
        ...     print(instrucciones)
    """
    from contexto_zai.context.importer import ContextImporter

    importer = ContextImporter(workspace_dir=workspace_dir)
    return importer.import_from(zip_path)


def find_context_packages(
    search_dir: Path | str = DOWNLOAD_OUTPUT_DIR.parent,
) -> list[Path]:
    """Busca paquetes de contexto exportados en un directorio.

    Args:
        search_dir: Directorio donde buscar (default: download/).

    Returns:
        Lista de rutas de archivos .zip ordenados por fecha (más reciente primero).
    """
    from contexto_zai.context.importer import ContextImporter

    importer = ContextImporter(workspace_dir=WORKSPACE_OUTPUT_DIR)
    return importer.find_packages(search_dir)


# -- v3.5: Indexación de documentos adjuntos -----------------------


def index_document(
    file_id: str,
    jwt: str,
    filename: str = "",
    content_type: str = "application/octet-stream",
    size: int = 0,
    force_direct: bool = False,
) -> Optional[object]:
    """Indexa un documento adjunto en tiempo real (v3.5).

    Descarga el documento desde la API de Z.ai y delega la lectura a un
    subagente efímero que lee el contenido completo, lo clasifica por
    temas, genera un resumen breve, y guarda el archivo para futuras
    consultas. El agente principal recibe solo el resumen (no el
    contenido completo), preservando su contexto.

    Args:
        file_id: UUID del archivo en Z.ai (del campo `files[].file.id`).
        jwt: JWT del Director para autenticación.
        filename: Nombre del archivo (opcional, se usa para logging).
        content_type: Tipo MIME (opcional, se detecta por magic number si es vacío).
        size: Tamaño en bytes (opcional).
        force_direct: Si True, fuerza lectura directa sin subagente
            (override "lee completo" del Director).

    Returns:
        DocumentoIndexResult con el resumen, temas detectados y ruta
        del archivo indexado, o None si falló.

    Example:
        >>> from contexto_zai.pipeline import index_document
        >>> result = index_document(file_id="abc-123", jwt="eyJ...", filename="doc.pdf")
        >>> if result and result.success:
        ...     print(f"Indexado: {result.filename}")
        ...     print(f"Resumen: {result.resumen_breve}")
        ...     print(f"Temas: {result.temas_nombres}")
    """
    from contexto_zai.client.attachment_client import AttachmentClient
    from contexto_zai.models import Attachment
    from contexto_zai.processing.content_delegator import DocumentDelegator
    from contexto_zai.subagents.documento_indexer_subagent import (
        DocumentoIndexerSubagent,
    )
    from contexto_zai.subagents.launcher import SubagentLauncher

    # Construir objeto Attachment
    attachment = Attachment(
        file_id=file_id,
        filename=filename or f"doc_{file_id[:8]}",
        content_type=content_type,
        size=size,
        url=f"/api/v1/files/{file_id}/content",
    )

    # Si force_direct, simular el override del Director "lee completo"
    if force_direct:
        delegator = DocumentDelegator()
        # El método should_delegate con override "lee completo" devuelve False (no delegar)
        # Pero como queremos forzar la lectura, no llamamos al subagente
        # En su lugar, descargamos y guardamos directamente
        try:
            client = AttachmentClient(token=jwt)
            content_bytes = client.download(file_id)
            # Guardar en indexed/ directamente
            from contexto_zai.config import ATTACHMENTS_INDEXED_DIR
            indexed_path = ATTACHMENTS_INDEXED_DIR / f"{file_id}_{attachment.filename}"
            indexed_path.parent.mkdir(parents=True, exist_ok=True)
            indexed_path.write_bytes(content_bytes)
            client.close()
            # Devolver resultado sin delegar al subagente
            from contexto_zai.subagents.documento_indexer_subagent import DocumentoIndexResult
            return DocumentoIndexResult(
                attachment_id=file_id,
                filename=attachment.filename,
                resumen_breve="[Lectura directa forzada por Director - contenido completo disponible]",
                temas_detectados=[],
                archivo_indexado_path=indexed_path,
                success=True,
            )
        except Exception as e:
            logger.error("Error en lectura directa forzada: %s", e)
            return None

    # Flujo normal: descargar + delegar al subagente
    try:
        client = AttachmentClient(token=jwt)
        launcher = SubagentLauncher()
        indexer = DocumentoIndexerSubagent(
            launcher=launcher,
            attachment_client=client,
        )
        result = indexer.run(attachment)
        client.close()
        return result
    except Exception as e:
        logger.error("Error indexando documento %s: %s", file_id, e)
        return None


def index_document_large(
    file_id: str,
    jwt: str,
    filename: str = "",
    content_type: str = "application/pdf",
    size: int = 0,
) -> Optional[object]:
    """Indexa un documento grande (>50K tokens) usando 3 niveles de subagentes (v3.6).

    Usa el flujo de 3 niveles (N1 Divisor → N2×N Clasificadores paralelos → N3 Conciliador)
    para procesar documentos que superan los 50K tokens.

    Args:
        file_id: UUID del archivo en Z.ai.
        jwt: JWT del Director.
        filename: Nombre del archivo (opcional).
        content_type: Tipo MIME (opcional).
        size: Tamaño en bytes (opcional).

    Returns:
        DocumentoIndexResult con el resumen, temas y ruta, o None si falló.
    """
    from contexto_zai.client.attachment_client import AttachmentClient
    from contexto_zai.config import PARTITION_THRESHOLD_TOKENS
    from contexto_zai.models import Attachment
    from contexto_zai.subagents.documento_indexer_subagent import (
        DocumentoIndexerSubagent,
    )
    from contexto_zai.subagents.launcher import SubagentLauncher

    # Construir Attachment
    attachment = Attachment(
        file_id=file_id,
        filename=filename or f"doc_{file_id[:8]}",
        content_type=content_type,
        size=size,
        url=f"/api/v1/files/{file_id}/content",
    )

    # Si el documento no es grande, usar index_document normal
    if attachment.estimated_tokens <= PARTITION_THRESHOLD_TOKENS:
        logger.info(
            "Documento %s (%d tokens <= %d) → usando index_document normal",
            attachment.filename, int(attachment.estimated_tokens), PARTITION_THRESHOLD_TOKENS,
        )
        return index_document(file_id, jwt, filename, content_type, size)

    # Documento grande → flujo de 3 niveles
    try:
        client = AttachmentClient(token=jwt)
        launcher = SubagentLauncher()
        indexer = DocumentoIndexerSubagent(
            launcher=launcher,
            attachment_client=client,
        )
        result = indexer.run_3_levels(attachment)
        client.close()
        return result
    except Exception as e:
        logger.error("Error indexando documento grande %s: %s", file_id, e)
        return None


# -- v4.0: Consulta bajo demanda (M8 revisada) --------------------------------


def query_context(
    question: str,
    max_results: int = 3,
    workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
) -> dict:
    """v6.11 F5: Wrapper que delega a ContextoPipeline.query_context()."""
    return ContextoPipeline.query_context(question=question, max_results=max_results, workspace_dir=workspace_dir)


# -- v4.2: Coordinación proceso-agente ----------------------------------


def collect_responses(
    workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
    is_chat_chronological: bool = True,
) -> dict:
    """v6.11 F5: Wrapper que delega a ContextoPipeline.collect_responses()."""
    return ContextoPipeline.collect_responses(workspace_dir=workspace_dir, is_chat_chronological=is_chat_chronological)


# -- v4.0: Ampliación de contexto desde fuentes externas (M9) ----------------


def _buscar_en_resumenes(
    workspace: Path,
    question: str,
    bloques_info: list[dict],
) -> Optional[str]:
    """v6.11 F5: Wrapper que delega a EnriquecimientoOrquestador._buscar_en_resumenes()."""
    return EnriquecimientoOrquestador._buscar_en_resumenes(workspace=workspace, question=question, bloques_info=bloques_info)


def _extraer_id_de_link(url: str, tipo: str = "share") -> Optional[str]:
    """v6.11 F5: Wrapper que delega a EnriquecimientoOrquestador._extraer_id_de_link()."""
    return EnriquecimientoOrquestador._extraer_id_de_link(url=url, tipo=tipo)


def ampliar_contexto(
    source_type: str,
    source_path: str,
    jwt: str = "",
    metadata: Optional[dict] = None,
    workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
) -> dict:
    """v6.11 F5 → v6.18 F1: Wrapper que delega a ContextoPipeline.ampliar_contexto().

    v6.18 F1: si la estructura del archivo externo es ``cronologico``
    (marcadores ``## Exchange N -- [timestamp]``), el flujo pasa por
    ``RecoveryCycle`` (reusar, no duplicar lógica). Si es ``arbitrario``,
    sigue por ``ProcesadorDocumento``.
    """
    return ContextoPipeline.ampliar_contexto(source_type=source_type, source_path=source_path, jwt=jwt, metadata=metadata, workspace_dir=workspace_dir)


def recuperar_contexto_si_necesario(
    chat_id: str,
    jwt: str = "",
    workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
    invocar_daemon: bool = True,
) -> dict:
    """v6.17 F6 (criterio 5): detonante de falta de contexto que usa RecoveryCycle.

    Cuando el agente CZAI no puede emitir la frase de control (porque no
    tiene contexto suficiente), invoca al daemon para que ejecute
    ``RecoveryCycle``. Si ``contexto_recuperacion/`` no existe, lo crea
    desde lo que existe en ese chat. No usa ``ampliar_contexto`` modo
    INCREMENTAL.

    Args:
        chat_id: UUID interno del chat (para extraer mensajes).
        jwt: JWT del Director. Si vacío, se carga del CredentialManager.
        workspace_dir: Directorio del workspace (donde se creará
            ``contexto_recuperacion/`` si no existe).
        invocar_daemon: ``True`` (default) — invoca al daemon vía HTTP
            (``POST /recovery-cycle`` en puerto 8088). ``False`` — ejecuta
            ``RecoveryCycle`` directamente en el mismo proceso (útil para
            pruebas o entornos sin daemon).

    Returns:
        Dict con:
        - ``accepted``: True si el daemon aceptó la tarea.
        - ``task_id``: ID de la tarea asignada por el daemon (si invocar_daemon=True).
        - ``contexto_creado``: True si se creó ``contexto_recuperacion/`` desde cero.
        - ``contexto_existia``: True si ya existía (F7: solo auditar + completar).
        - ``error``: mensaje si algo falló.
    """
    ws = Path(workspace_dir)
    contexto_existia = ws.exists() and any(ws.glob("bloque_*.md"))

    # JWT: cargar del CredentialManager si llega vacío.
    if not jwt:
        try:
            from contexto_zai.client.credential_manager import CredentialManager
            cm = CredentialManager()
            jwt = cm.get_jwt() or ""
        except Exception as e:
            logger.warning("v6.17 F6: no se pudo cargar JWT: %s", e)
            jwt = ""

    if not jwt:
        return {"accepted": False, "error": "Se requiere JWT del Director."}

    # Si invocar_daemon=True, enviar POST al daemon (puerto 8088).
    if invocar_daemon:
        try:
            import json as _json
            import urllib.request as _ur
            payload = _json.dumps({
                "chat_id": chat_id,
                "jwt": jwt,
                "workspace_dir": str(ws),
            }).encode("utf-8")
            req = _ur.Request(
                "http://127.0.0.1:8088/recovery-cycle",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with _ur.urlopen(req, timeout=10) as resp:
                body = _json.loads(resp.read().decode("utf-8"))
            return {
                "accepted": bool(body.get("accepted")),
                "task_id": body.get("task_id", ""),
                "contexto_creado": not contexto_existia,
                "contexto_existia": contexto_existia,
            }
        except Exception as e:
            logger.warning(
                "v6.17 F6: invocar daemon falló (%s) — ejecutando RecoveryCycle en proceso",
                e,
            )
            # Caer al flujo directo si el daemon no está disponible.

    # Flujo directo (sin daemon): ejecutar RecoveryCycle en el mismo proceso.
    try:
        if not contexto_existia:
            # contexto_recuperacion no existe — crear desde el chat.
            logger.info(
                "v6.17 F6: contexto_recuperacion no existe — creando desde el chat %s",
                chat_id[:12] if chat_id else "(sin chat_id)",
            )
            from contexto_zai.process.recovery_cycle import RecoveryCycle
            cycle = RecoveryCycle(
                jwt=jwt,
                chat_id=chat_id,
                workspace_dir=ws,
            )
            result = cycle.run()
            return {
                "accepted": True,
                "task_id": f"recovery_cycle_direct_{int(time.time())}",
                "contexto_creado": True,
                "contexto_existia": False,
                "success": bool(getattr(result, "success", False)),
            }
        else:
            # contexto_recuperacion ya existe — F7: solo auditar + completar.
            logger.info(
                "v6.17 F6+F7: contexto_recuperacion existe — solo auditar + completar"
            )
            result_audit = EnriquecimientoOrquestador._auditar_y_completar(ws)
            return {
                "accepted": True,
                "task_id": f"audit_complete_direct_{int(time.time())}",
                "contexto_creado": False,
                "contexto_existia": True,
                "incompletos_iniciales": result_audit.get("incompletos_iniciales", 0),
                "pending_tasks": result_audit.get("pending_tasks", 0),
            }
    except Exception as e:
        logger.error("v6.17 F6: excepción ejecutando RecoveryCycle: %s", e)
        return {"accepted": False, "error": str(e)}


# -- v6.2: Fallback al agente con subagentes cuando el proxy Z.ai falla --------
#
# QUÉ SOLUCIONA: en v6.1, si el proxy Z.ai agota su cuota diaria, el Worker Bun
# marca los bloques como `failed` y el proceso no completa.
# CÓMO LO HACE: el pipeline.run() consulta el proxy Z.ai antes de arrancar el
# Worker Bun. Si el proxy no responde (429, error, timeout), o si el worker no
# completa todos los bloques, los bloques sin RESUMEN: van a pending_tasks para
# que el agente principal los procese lanzando subagentes (como en v5.0).
# El agente solo gasta ventana cuando el proxy no está disponible.


class EnriquecimientoOrquestador:
    """v6.11 F5: Orquestador de enriquecimiento (refactor OOP).
    
    Agrupa funciones relacionadas como métodos estáticos. Las funciones
    módulo-nivel son wrappers momentáneos que delegan a estos métodos.
    """

    # v6.15 F5 (criterio 32): flag de clase para señalar a la cascada que
    # ``_enriquecer_con_proxy_zai()`` falló por HTTP 429 (rate limit). La
    # gestión del 429 la hace ``CascadaAccesoLLM._nivel2_proxy_zai()`` con
    # polling de progreso (5s × 3 = 15s), NO la función de enriquecimiento
    # (que hace un solo intento por llamada y devuelve False inmediatamente
    # al recibir 429, seteando este flag).
    _ultimo_error_proxy_429: bool = False

    @staticmethod
    def _proxy_zai_disponible() -> bool:
            """v6.2: Hace un ping mínimo al proxy Z.ai. Devuelve True si responde 200.

            Usa ``PROXY_ZAI_URL`` y ``PROXY_ZAI_TIMEOUT`` de config.py.
            Si la importación de ``requests`` falla, usa ``urllib`` (built-in).
            """
            try:
                from contexto_zai.config import PROXY_ZAI_TIMEOUT, PROXY_ZAI_URL
            except ImportError:
                return False
            payload = '{"model":"glm-4-flash","messages":[{"role":"user","content":"ping"}],"max_tokens":3}'
            try:
                import urllib.request as _ur
                import urllib.error as _ue
                req = _ur.Request(
                    PROXY_ZAI_URL,
                    data=payload.encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with _ur.urlopen(req, timeout=PROXY_ZAI_TIMEOUT) as resp:
                    return resp.status == 200
            except _ue.HTTPError as e:
                # 429 u otros códigos HTTP → proxy caído para nuestros fines
                logger.info("v6.2 _proxy_zai_disponible(): HTTP %d", e.code)
                return False
            except Exception as e:
                logger.info("v6.2 _proxy_zai_disponible(): error %s", e)
                return False


    @staticmethod
    def _arrancar_worker_y_esperar(
        workspace_dir: Path | str,
        timeout: Optional[int] = None,
    ) -> bool:
            """v6.12: Arranca el Worker Bun y monitorea progreso con ProgressMonitor.

            v6.12 F2: Reemplaza el timeout fijo por monitoreo de progreso.
            El Worker Bun arranca en background (no bloqueante) y
            ProgressMonitor comprueba cada intervalo si hay progreso
            (mas bloques completos). Si no progresa en 2 intervalos
            seguidos, se declara que cayo y se devuelve False.

            v6.8.2 F2: verifica si el puerto 8090 ya está en uso antes
            de intentar arrancar otro Worker Bun.

            Args:
                workspace_dir: Directorio del workspace.
                timeout: Ignorado en v6.12 (se usa ProgressMonitor).

            Returns:
                True si el Worker Bun completo todos los bloques.
                False si no progresa o falla.
            """
            import subprocess
            import socket as _socket
            try:
                from contexto_zai.config import WORKER_BUN_DIR
            except ImportError:
                logger.warning("v6.12: no se pudo importar WORKER_BUN_DIR, fallback desactivado")
                return False
            if not Path(WORKER_BUN_DIR).exists():
                logger.warning("v6.12: WORKER_BUN_DIR no existe: %s", WORKER_BUN_DIR)
                return False

            # v6.8.2 F2: verificar si el puerto 8090 ya está en uso
            WORKER_BUN_PORT = 8090
            puerto_en_uso = False
            try:
                sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                sock.settimeout(1)
                result_sock = sock.connect_ex(("localhost", WORKER_BUN_PORT))
                sock.close()
                puerto_en_uso = (result_sock == 0)
            except Exception:
                puerto_en_uso = False

            if puerto_en_uso:
                logger.info("v6.12: puerto %d en uso — Worker Bun ya corriendo, monitoreando progreso",
                           WORKER_BUN_PORT)
                # v6.12 F2: usar ProgressMonitor en vez de sleep fijo
                return ProgressMonitor.esperar_y_verificar(workspace_dir)

            # v6.12 F2: arrancar Worker Bun en background (no bloqueante)
            env = {**_os.environ, "CZAI_WORKSPACE_DIR": str(workspace_dir)}
            try:
                proc = subprocess.Popen(
                    ["bun", "run", "cli.ts", "run"],
                    cwd=WORKER_BUN_DIR,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                logger.info("v6.12: Worker Bun arrancado en background (PID %d). Monitoreando progreso...", proc.pid)

                # v6.12 F2: ProgressMonitor decide si hay progreso
                todo_completo = ProgressMonitor.esperar_y_verificar(workspace_dir)

                # Si el proceso sigue corriendo, dejarlo (puede seguir procesando)
                if proc.poll() is None:
                    logger.info("v6.12: Worker Bun sigue corriendo en background.")

                return todo_completo

            except FileNotFoundError:
                logger.warning("v6.12: 'bun' no está en PATH. Fallback desactivado.")
                return False
            except Exception as e:
                logger.warning("v6.12: Error arrancando Worker Bun: %s", e)
                return False

    @staticmethod
    def _construir_pending_task_para_bloque(
        bloque,
        chat_label: str = "",
    ) -> "SubagentTask":
            """v6.2: Construye una SubagentTask para que un subagente procese un bloque.

            El prompt pide al subagente:
            1. Leer el bloque completo.
            2. Generar un resumen (tema central, decisiones, temas, actividad).
            3. Escribir el resumen al inicio del bloque físico con prefijo 'RESUMEN: '.
            4. Extraer nombre legible, decisiones, temas.
            5. Escribir los 3 archivos en _responses/ del workspace.

            Args:
                bloque: ThematicBlock con filename.
                chat_label: Etiqueta del chat (opcional).

            Returns:
                SubagentTask lista para que el agente principal la ejecute con Task tool.
            """
            from contexto_zai.models import SubagentTask
            from contexto_zai.config import PROMPT_RESUMEN_RIGIDO
            filename = bloque.filename
            # v6.4 F4: usar el mismo prompt riguroso del Worker Bun (600-900 chars, 4 oraciones)
            prompt = PROMPT_RESUMEN_RIGIDO.format(bloque_content=f"(Lee el archivo {filename} en el workspace)")

            # Añadir instrucciones de escritura de archivos
            prompt += f"""

        INSTRUCCIONES DE ESCRITURA (después de generar el resumen):
        1. Escribe el resumen al inicio del archivo {filename} con el prefijo 'RESUMEN: ' (separado del contenido existente por \\n\\n---\\n\\n).
        2. Extrae: nombre legible en snake_case (máximo 5 palabras), decisiones con formato 'DECISION: ... | ALCANCE: ...', temas principales en snake_case (máximo 5).
        3. Escribe los 3 archivos en _responses/:
           - {filename.replace('.md','')}_nombre.txt
           - {filename.replace('.md','')}_decisiones.txt
           - {filename.replace('.md','')}_temas.txt
        """
            return SubagentTask(
                task_id=f"enriquecer_{filename.replace('.md','')}",
                purpose=f"v6.2.fallback.enriquecer_bloque.{filename}",
                prompt=prompt,
                context={"filename": filename, "chat_label": chat_label},
            )

    @staticmethod
    def _descubrir_bloques_incompletos(workspace_dir: Path | str) -> list:
            """v6.17 F1 (criterio 7): función única que detecta bloques incompletos.

            Verifica los 4 artefactos de cada ``bloque_*.md``:

            1. RESUMEN al inicio del ``bloque_*.md``.
            2. ``_responses/{block_id}_nombre.txt``.
            3. ``_responses/{block_id}_decisiones.txt``.
            4. ``_responses/{block_id}_temas.txt``.

            Lee cada ``bloque_*.md`` del workspace y devuelve lista de los
            bloques incompletos (los que faltan al menos 1 artefacto). Para
            cada uno, indica qué artefactos faltan.

            Args:
                workspace_dir: Directorio del workspace.

            Returns:
                Lista de dicts, uno por bloque incompleto:
                - ``block_id``: str (ej. ``bloque_05``).
                - ``filename``: str (ej. ``bloque_05.md``).
                - ``faltantes``: list[str] (subset de
                  ``["RESUMEN", "nombre.txt", "decisiones.txt", "temas.txt"]``).
                - ``bloque``: ThematicBlock (con ``temas`` y
                  ``external_size_chars`` poblados para compatibilidad con
                  la cascada de acceso LLM).
            """
            from contexto_zai.models import ThematicBlock as _TB
            ws = Path(workspace_dir)
            if not ws.exists():
                return []

            responses_dir = ws / "_responses"
            incompletos: list = []

            for p in sorted(ws.glob("bloque_*.md")):
                try:
                    content = p.read_text(encoding="utf-8", errors="ignore")
                except Exception as e:
                    logger.warning(
                        "v6.17 F1: no se pudo leer bloque %s: %s", p.name, e
                    )
                    continue
                if len(content) < 100:
                    # Bloque vacío o casi vacío: lo saltamos (no se puede
                    # enriquecer un bloque sin contenido).
                    continue

                block_id = p.stem
                filename = p.name

                # Verificar los 4 artefactos.
                faltantes: list[str] = []
                if not content.startswith("RESUMEN:"):
                    faltantes.append("RESUMEN")
                if not (responses_dir / f"{block_id}_nombre.txt").exists():
                    faltantes.append("nombre.txt")
                if not (responses_dir / f"{block_id}_decisiones.txt").exists():
                    faltantes.append("decisiones.txt")
                if not (responses_dir / f"{block_id}_temas.txt").exists():
                    faltantes.append("temas.txt")

                if not faltantes:
                    continue  # bloque completo, no se devuelve

                # Extraer temas del header (para compatibilidad con la cascada).
                temas: list[str] = []
                for line in content.split("\n"):
                    if line.startswith("# Bloque tematico:") or line.startswith("# Bloque temático:"):
                        temas_str = line.split(":", 1)[1].strip()
                        temas = [t.strip() for t in temas_str.split(",") if t.strip()]
                        break
                    elif line.startswith("# Bloque externo"):
                        nombre = line.split(":", 1)[1].strip() if ":" in line else ""
                        temas = [nombre.lower().replace(" ", "_")[:50]] if nombre else []
                        break
                if not temas:
                    temas = ["contexto_externo"]

                block = _TB(
                    filename=filename,
                    temas=temas,
                    external_size_chars=len(content),
                )
                incompletos.append({
                    "block_id": block_id,
                    "filename": filename,
                    "faltantes": faltantes,
                    "bloque": block,
                })

            logger.info(
                "v6.17 F1: %d bloque(s) incompleto(s) descubiertos (4 artefactos).",
                len(incompletos),
            )
            return incompletos

    @staticmethod
    def collect_responses(
        workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
        is_chat_chronological: bool = True,
    ) -> dict:
            """v4.2 → v6.17 F4 (criterio 3): Recoge respuestas y las integra al workspace.

            v6.17 F4 (criterio 3): ``collect_responses()`` SOLO integra
            respuestas. Lee ``_responses/``, las aplica al workspace según
            el ``purpose`` de cada tarea, y devuelve resultado.

            NO verifica bloques incompletos. NO dispara la cascada W1+W2+W3
            (P14). Esa verificación y disparo la hace el proceso
            (daemon/pipeline) tras llamar ``collect_responses()`` —
            típicamente ``ContextoPipeline.run()`` invoca el enriquecimiento
            (que dispara la cascada) y luego el bucle D7
            (P17, separado de la cascada según F3).

            v6.17 F10 (criterio 10): si la operación NO es cronológica
            (``is_chat_chronological=False``, viene de ampliar_contexto),
            lee ``_estructura_externa`` del ``_metadata.json`` para decidir
            si el bloque externo tiene estructura cronológica. Los bloques
            externos con estructura cronológica SÍ generan los 4 archivos
            de recuperación (consolidan decisiones y regeneran índice).

            La consolidación de decisiones y la regeneración del índice
            (``_consolidar_decisiones_llm`` y
            ``_regenerar_indice_tras_enriquecimiento``) no son parte de la
            cascada — son pasos de post-integración que se mantienen aquí
            para preservar el comportamiento del chat cronológico.

            El agente nunca ve el contenido crudo de las respuestas — solo
            llama a esta función y recibe el resultado estructurado.

            Args:
                workspace_dir: Directorio del workspace donde viven
                    _pending_tasks.json y _responses/.
                is_chat_chronological: ``True`` (default) si la operación
                    viene de ``pipeline.run()`` (chat cronológico).
                    ``False`` si viene de ``ampliar_contexto()`` (fuente
                    externa, no cronológica).

            Returns:
                Dict con el resultado estructurado devuelto por
                ``Orquestador.aplicar_respuestas()``.
            """
            from contexto_zai.coordinador import Orquestador, IntegradorRespuestas

            orch = Orquestador(workspace_dir=workspace_dir)
            integrador = IntegradorRespuestas(workspace_dir=workspace_dir)

            # v6.11 F6: reenviar is_chat_chronological para que el integrador
            # salte los handlers que regeneran 00_estado_actual.md cuando la
            # operación no es cronológica (viene de ampliar_contexto).
            resultado = orch.aplicar_respuestas(
                integrador=integrador,
                is_chat_chronological=is_chat_chronological,
            )

            # v6.17 F4 (criterio 3): collect_responses() SOLO integra.
            # NO verifica bloques incompletos. NO dispara la cascada de
            # acceso LLM (P14). Esa lógica la asume el proceso
            # (daemon/pipeline) tras llamar collect_responses().
            # La consolidación de decisiones y regeneración del índice se
            # mantienen aquí (no son parte de la cascada).
            #
            # v6.17 F10 (criterio 10): si la operación no es cronológica
            # (ampliar_contexto), leer _estructura_externa del metadata.json.
            # Los bloques externos con estructura cronológica SÍ generan los
            # 4 archivos de recuperación — consolidan decisiones y
            # regeneran índice igual que el chat cronológico.
            should_consolidate = is_chat_chronological
            if not should_consolidate:
                # Verificar si hay un bloque externo con estructura cronológica.
                import json as _json_f10
                metadata_path = Path(workspace_dir) / "_metadata.json"
                if metadata_path.exists():
                    try:
                        meta = _json_f10.loads(metadata_path.read_text(encoding="utf-8"))
                        estructura_externa = meta.get("_estructura_externa", "")
                        if estructura_externa == "cronologico":
                            should_consolidate = True
                            logger.info(
                                "v6.17 F10: ampliar_contexto con estructura=cronologico — "
                                "consolidando decisiones y regenerando índice (4 archivos)."
                            )
                    except Exception as e:
                        logger.warning(
                            "v6.17 F10: leer _estructura_externa del metadata falló: %s", e
                        )

            if should_consolidate:
                _consolidar_decisiones_llm(workspace_dir=workspace_dir)
                _regenerar_indice_tras_enriquecimiento(workspace_dir=workspace_dir)
            else:
                logger.info(
                    "v6.17 F4: collect_responses no cronológico — solo integración. "
                    "Consolidación de decisiones y regeneración del índice omitidas. "
                    "La verificación de bloques incompletos y el disparo de la cascada "
                    "los hace el proceso (daemon/pipeline) tras esta llamada."
                )

            return resultado

    @staticmethod
    def _persistir_pending_task_en_disco(
        workspace_dir: Path | str, task,
    ) -> None:
        """v6.17 F11 (criterio 11): función única para persistir pending_tasks.

        Usada por:
        - ``EnriquecimientoOrquestador._post_bloque`` — llamado cuando un
          bloque cae a Nivel 3 desde la cascada.
        - ``CascadaAccesoLLM._nivel3_subagentes`` — llamado para cada
          pending_task publicada por Nivel 3.
        - ``EnriquecimientoOrquestador._bucle_d7_completitud`` (F12) —
          llamado para cada pending_task corregida que publica el bucle D7.

        Las pending_tasks pueden caer desde cualquier nivel de la cascada
        (N1, N2 o N3). Esta función es idempotente en cuanto al archivo:
        lee, añade, escribe (append, no sobrescribir).

        Args:
            workspace_dir: Directorio del workspace.
            task: SubagentTask (pydantic BaseModel) o dict a persistir.
        """
        import json as _json
        ws = Path(workspace_dir)
        path = ws / "_pending_tasks.json"
        data: dict = {"tasks": []}
        if path.exists():
            try:
                data = _json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or "tasks" not in data:
                    data = {"tasks": []}
                if not isinstance(data.get("tasks"), list):
                    data["tasks"] = []
            except Exception as e:
                logger.warning(
                    "v6.17 F11: _pending_tasks.json corrupto, se reinicia: %s", e
                )
                data = {"tasks": []}
        # Serializar la task — pydantic BaseModel usa model_dump(), otros
        # objetos se caen a default=str para no romper el JSON.
        try:
            if hasattr(task, "model_dump"):
                task_data = task.model_dump(mode="json")
            elif isinstance(task, dict):
                task_data = task
            else:
                task_data = _json.loads(_json.dumps(task, default=str))
        except Exception as e:
            logger.warning(
                "v6.17 F11: no se pudo serializar pending_task (%s): %s",
                type(task).__name__, e,
            )
            return
        # Idempotencia: si la task ya está en el saco (mismo task_id), no
        # añadir de nuevo. Esto permite que _post_bloque y el D7 llamen a
        # esta función sin duplicar entradas.
        new_task_id = task_data.get("task_id", "") if isinstance(task_data, dict) else ""
        if new_task_id:
            existing_ids = {
                t.get("task_id", "")
                for t in data["tasks"]
                if isinstance(t, dict)
            }
            if new_task_id in existing_ids:
                logger.info(
                    "v6.17 F11: pending_task %s ya persistida — idempotencia (no duplicar).",
                    new_task_id,
                )
                return
        data["tasks"].append(task_data)
        data["total"] = len(data["tasks"])
        try:
            path.write_text(
                _json.dumps(data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(
                "v6.17 F11: no se pudo escribir _pending_tasks.json: %s", e
            )

    @staticmethod
    def _post_bloque(
        workspace_dir: Path | str,
        bloque,
        resultado: bool,
        cascada: "CascadaAccesoLLM",
    ) -> None:
        """v6.16 F8 (propuesta del Director): encapsula tareas post-bloque.

        Ejecuta la secuencia de pasos que siempre son los mismos tras
        procesar un bloque:

        1. Escribir checkpoint (``_cascada_checkpoint.json``) — refresca el
           estado físico real.
        2. Si el bloque cayó a Nivel 3 (``resultado == False``) → persistir
           pending_task en ``_pending_tasks.json`` (idempotente por block_id)
           vía ``_persistir_pending_task_en_disco`` (F11).
        3. Actualizar ``_processed_blocks.json`` (marcar completed o pending)
           vía ``AuditorWorkspace.sincronizar_registro``.
        4. Actualizar ``_pending_blocks.json`` (quitar el bloque de pendientes
           si se completó).

        Es **stateless** (criterio del Actuador: función, no clase): toma el
        estado actual y lo persiste. No preserva nada entre llamadas. Vive
        como método estático de ``EnriquecimientoOrquestador`` por
        encapsulación, pero su contrato es funcional.

        Args:
            workspace_dir: Directorio del workspace.
            bloque: ThematicBlock que se acaba de procesar.
            resultado: True si el bloque quedó completo; False si cayó a
                Nivel 3 (pending_task publicada en ``cascada._pending_tasks``).
            cascada: Instancia de ``CascadaAccesoLLM`` con los métodos
                ``_escribir_checkpoint`` y ``_pending_tasks``.
        """
        import json as _json
        ws = Path(workspace_dir)
        filename = getattr(bloque, "filename", str(bloque))
        block_id = filename.replace(".md", "")

        # 1. Escribir checkpoint.
        if cascada is not None and hasattr(cascada, "_escribir_checkpoint"):
            try:
                cascada._escribir_checkpoint()
            except Exception as e:
                logger.warning("v6.16 F8: _escribir_checkpoint falló: %s", e)

        # 2. Si el bloque cayó a Nivel 3 → persistir pending_task (idempotente).
        #    v6.17 F11: usar la función única _persistir_pending_task_en_disco.
        if not resultado and cascada is not None:
            pending_path = ws / "_pending_tasks.json"
            ya_persistida = False
            try:
                if pending_path.exists():
                    data = _json.loads(pending_path.read_text(encoding="utf-8"))
                    tasks = data.get("tasks", []) if isinstance(data, dict) else []
                    # Idempotencia: buscar por task_id == "enriquecer_{block_id}"
                    # o por context.filename == filename.
                    for t in tasks:
                        if not isinstance(t, dict):
                            continue
                        if t.get("task_id") == f"enriquecer_{block_id}":
                            ya_persistida = True
                            break
                        ctx = t.get("context") or {}
                        if isinstance(ctx, dict) and ctx.get("filename") == filename:
                            ya_persistida = True
                            break
            except Exception as e:
                logger.warning(
                    "v6.16 F8: leer _pending_tasks.json para idempotencia falló: %s", e
                )
            if not ya_persistida:
                # Buscar la task en cascada._pending_tasks para este bloque.
                pending_tasks = getattr(cascada, "_pending_tasks", []) or []
                for task in pending_tasks:
                    task_id = getattr(task, "task_id", "")
                    ctx = getattr(task, "context", {}) or {}
                    if task_id == f"enriquecer_{block_id}" or ctx.get("filename") == filename:
                        try:
                            EnriquecimientoOrquestador._persistir_pending_task_en_disco(
                                workspace_dir=workspace_dir, task=task
                            )
                        except Exception as e:
                            logger.warning(
                                "v6.16 F8: _persistir_pending_task_en_disco falló: %s", e
                            )
                        break

        # 3. Actualizar _processed_blocks.json (marcar completed o pending).
        #    ``sincronizar_registro`` ya hace esto en bloque (recorre todos los
        #    bloque_*.md), pero lo invocamos aquí para que el estado refleje
        #    este bloque específico justo después de procesarse.
        try:
            AuditorWorkspace.sincronizar_registro(workspace_dir)
        except Exception as e:
            logger.warning("v6.16 F8: sincronizar_registro falló: %s", e)

        # 4. Actualizar _pending_blocks.json (quitar el bloque de pendientes
        #    si se completó). Si no se completó, la entrada ya existe (la
        #    creó RecoveryCycle o _integrar_documento) y se deja.
        if resultado:
            pending_blocks_path = ws / "_pending_blocks.json"
            try:
                if pending_blocks_path.exists():
                    data = _json.loads(pending_blocks_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and isinstance(data.get("blocks"), list):
                        antes = len(data["blocks"])
                        data["blocks"] = [
                            b for b in data["blocks"]
                            if not (isinstance(b, dict) and b.get("block_id") == block_id)
                        ]
                        if len(data["blocks"]) < antes:
                            pending_blocks_path.write_text(
                                _json.dumps(data, indent=2, ensure_ascii=False),
                                encoding="utf-8",
                            )
                            logger.info(
                                "v6.16 F8: %s quitado de _pending_blocks.json "
                                "(completado).", filename,
                            )
            except Exception as e:
                logger.warning(
                    "v6.16 F8: actualizar _pending_blocks.json falló: %s", e
                )

        # 5. v6.17 F5 (criterio 4): actualizar _daemon_status.json.
        #    El daemon lee el estado del workspace y escribe progreso para
        #    que el agente CZAI lo incluya en la frase de control.
        try:
            EnriquecimientoOrquestador._actualizar_estado_daemon(
                workspace_dir=workspace_dir,
                tarea_actual=block_id,
            )
        except Exception as e:
            logger.warning("v6.17 F5: actualizar_estado_daemon falló: %s", e)

    @staticmethod
    def _actualizar_estado_daemon(
        workspace_dir: Path | str,
        status: str = "running",
        tarea_actual: str = "",
    ) -> None:
        """v6.17 F5 (criterio 4): escribe ``_daemon_status.json`` en el workspace.

        Cuenta bloques completos/pendientes con
        ``_descubrir_bloques_incompletos()`` (F1) y escribe el estado del
        daemon en ``_daemon_status.json``:

        .. code-block:: json

            {
              "status": "running|idle|done",
              "total_bloques": 50,
              "completados": 23,
              "pendientes": 27,
              "tarea_actual": "bloque_24",
              "timestamp": 1234567890
            }

        El agente CZAI lee ``_daemon_status.json`` antes de responder al
        Director e incluye el estado en la frase de control. Si el daemon
        no está haciendo nada (status=idle), lo dice. Cuando termina
        (status=done), lo dice.

        Args:
            workspace_dir: Directorio del workspace.
            status: ``running``, ``idle`` o ``done``.
            tarea_actual: ``block_id`` del bloque en proceso (o vacío si idle).
        """
        import json as _json_d
        import time as _time_d
        ws = Path(workspace_dir)
        if not ws.exists():
            return
        try:
            total = len(list(ws.glob("bloque_*.md")))
            incompletos = EnriquecimientoOrquestador._descubrir_bloques_incompletos(workspace_dir)
            pendientes = len(incompletos)
            completados = max(0, total - pendientes)
        except Exception as e:
            logger.warning("v6.17 F5: contar bloques falló: %s", e)
            total = completados = pendientes = 0
        status_path = ws / "_daemon_status.json"
        payload = {
            "status": status,
            "total_bloques": total,
            "completados": completados,
            "pendientes": pendientes,
            "tarea_actual": tarea_actual,
            "timestamp": int(_time_d.time()),
        }
        try:
            status_path.write_text(
                _json_d.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("v6.17 F5: escribir _daemon_status.json falló: %s", e)

    @staticmethod
    def _enriquecer_bloques_con_fallback(
        blocks: list,
        workspace_dir: Path | str,
        chat_label: str = "",
    ) -> list:
            """v6.15 F7 (criterios 29-32): Arnés thin que delega a ``CascadaAccesoLLM``.

            Reemplaza la lógica procedural de v6.13 F4 (que procesaba todos los
            bloques en bloque: Nivel 1 para todos → Nivel 2 para los restantes
            → Nivel 3 para los que quedaran) por una invocación de
            ``CascadaAccesoLLM.procesar_tarea()`` por cada bloque individual.

            Una instancia de ``CascadaAccesoLLM`` se crea una vez y se reutiliza
            por bloque (criterio 30). Las ``pending_tasks`` que publique la
            cascada (en Nivel 3) se devuelven al llamador para que las propague
            al ``OrchestratorResult.pending_tasks`` (procesadas por el agente CZAI
            vía Task tool y reintegradas vía ``collect_responses()``).

            Sigue siendo un arnés que NUNCA se detiene: si un bloque no se
            completa en la cascada, su pending_task se publica y el control
            vuelve al llamador (P14 sigue con el siguiente bloque; P17 itera
            después). Al final, sincroniza ``_processed_blocks.json`` con el
            estado físico real.

            Args:
                blocks: Lista de ThematicBlock (típicamente todos los del workspace).
                workspace_dir: Directorio del workspace.
                chat_label: Etiqueta del chat (no se usa directamente — la
                    cascada publica pending_tasks con ``chat_label='cascada_n3'``).

            Returns:
                Lista de SubagentTask pendientes (publicadas por Nivel 3 de la
                cascada para los bloques que Ni N1 ni N2 pudieron completar).
            """
            # 1. Bloques sin RESUMEN (filtro rápido para no invocar la cascada
            # sobre bloques ya completos; la cascada también filtra por idempotencia).
            bloques_sin_resumen = [
                b for b in blocks
                if not b.tiene_resumen(workspace_dir=workspace_dir)
            ]

            # v6.16 F2 (criterio 36): leer ``_cascada_checkpoint.json`` si existe
            # y saltar los bloques ya completos (reanudación tras caída).
            checkpoint_path = Path(workspace_dir, "_cascada_checkpoint.json")
            if checkpoint_path.exists() and bloques_sin_resumen:
                try:
                    import json as _json_chk
                    checkpoint = _json_chk.loads(
                        checkpoint_path.read_text(encoding="utf-8")
                    )
                    completados = set(checkpoint.get("completados", []))
                    antes = len(bloques_sin_resumen)
                    bloques_sin_resumen = [
                        b for b in bloques_sin_resumen
                        if b.filename not in completados
                    ]
                    saltados = antes - len(bloques_sin_resumen)
                    if saltados:
                        logger.info(
                            "v6.16 F2: checkpoint leído — %d bloque(s) saltado(s) "
                            "por ya completo(s) (criterio 36).",
                            saltados,
                        )
                except Exception as e:
                    logger.warning(
                        "v6.16 F2: leer checkpoint falló (se ignora): %s", e
                    )

            if not bloques_sin_resumen:
                logger.info(
                    "v6.15 F7: Todos los bloques ya tienen RESUMEN. Nada que hacer."
                )
                AuditorWorkspace.sincronizar_registro(workspace_dir)
                return []

            logger.info(
                "v6.15 F7: %d bloque(s) sin RESUMEN. CascadaAccesoLLM por bloque.",
                len(bloques_sin_resumen),
            )

            # 2. v6.15 F7: una instancia de CascadaAccesoLLM, reutilizada por bloque.
            cascada = CascadaAccesoLLM(workspace_dir=workspace_dir)
            for bloque in bloques_sin_resumen:
                completado = cascada.procesar_tarea(bloque)
                if not completado:
                    # La propia cascada ya publicó la pending_task en Nivel 3
                    # (no hace falta re-publicarla aquí). Continuar con el
                    # siguiente bloque: el arnés nunca se detiene.
                    logger.info(
                        "v6.15 F7: bloque %s no completado — pending_task publicada "
                        "en cascada.get_pending_tasks(). Continuando con el siguiente.",
                        getattr(bloque, "filename", str(bloque)),
                    )

            # 3. Recoger las pending_tasks acumuladas durante todo P14.
            pending_tasks = cascada.get_pending_tasks()

            # 4. Sincronizar _processed_blocks.json con el estado físico real.
            AuditorWorkspace.sincronizar_registro(workspace_dir)

            return pending_tasks

    @staticmethod
    def _bloque_esta_completo(
        bloque,
        workspace_dir: Path | str,
    ) -> bool:
        """v6.12 F5: Verifica si un bloque esta realmente completo.

        Un bloque esta completo cuando tiene:
        1. RESUMEN: al inicio del archivo bloque_NN.md
        2. _responses/bloque_NN_nombre.txt
        3. _responses/bloque_NN_decisiones.txt
        4. _responses/bloque_NN_temas.txt

        Args:
            bloque: ThematicBlock con filename.
            workspace_dir: Directorio del workspace.

        Returns:
            True si el bloque esta completo, False si falta algo.
        """
        ws = Path(workspace_dir)
        filename = bloque.filename
        block_id = filename.replace(".md", "")

        # 1. Verificar RESUMEN al inicio
        bloque_path = ws / filename
        if not bloque_path.exists():
            return False
        content = bloque_path.read_text(encoding="utf-8", errors="ignore")
        if not content.startswith("RESUMEN:"):
            return False

        # 2. Verificar los 3 archivos de _responses/
        responses_dir = ws / "_responses"
        if not responses_dir.exists():
            return False
        if not (responses_dir / f"{block_id}_nombre.txt").exists():
            return False
        if not (responses_dir / f"{block_id}_decisiones.txt").exists():
            return False
        if not (responses_dir / f"{block_id}_temas.txt").exists():
            return False

        return True

    @staticmethod
    def _validar_resumen_w3(
        resumen: str,
        bloque_content_len: int,
    ) -> tuple[bool, str]:
        """v6.13 C7+C8+C10: W3 validación ajena al ejecutor.

        Valida que el RESUMEN cumpla el formato rígido:
        1. Longitud 600-900 chars (RESUMEN_MIN_CHARS..RESUMEN_MAX_CHARS).
        2. Exactamente 4 oraciones (cuenta '.', '!', '?').
        3. Sin etiquetas prohibidas (Tema central:, Decisiones:, etc.).

        Devuelve (ok, motivo). Si ``ok=False``, ``motivo`` describe qué falló
        y se usará como feedback para el reintento (hasta MAX_ITER_W3).

        Regla de borde: si el bloque tiene < 2000 chars de contenido, se acepta
        el resumen con observaciones (no se exige rango estricto).
        """
        from contexto_zai.config import (
            RESUMEN_MIN_CHARS, RESUMEN_MAX_CHARS,
            RESUMEN_ORACIONES_ESPERADAS, RESUMEN_ETIQUETAS_PROHIBIDAS,
        )

        if not resumen or not resumen.strip():
            return False, "resumen vacío"

        r = resumen.strip()

        # Excepción: bloque pequeño → aceptar con observaciones
        if bloque_content_len <= 2000:
            return True, "bloque con contenido limitado, aceptado con observaciones"

        # 1. Validar etiquetas prohibidas
        for etiqueta in RESUMEN_ETIQUETAS_PROHIBIDAS:
            if etiqueta in r:
                return False, f"contiene etiqueta prohibida: '{etiqueta}'"

        # 2. Validar longitud
        if len(r) < RESUMEN_MIN_CHARS:
            return False, f"longitud {len(r)} < {RESUMEN_MIN_CHARS} (muy corto)"
        if len(r) > RESUMEN_MAX_CHARS:
            return False, f"longitud {len(r)} > {RESUMEN_MAX_CHARS} (muy largo)"

        # 3. Validar número de oraciones
        # Cuenta '.', '!' y '?' como terminadores de oración,
        # PERO ignora puntos dentro de números (ej: "v6.13", "2.8%").
        # Heurística: split por ". " (punto + espacio) y contar segmentos no vacíos.
        # Para '!' y '?' sí se cuentan directamente (no aparecen en números).
        import re as _re
        # Contar '. ' (punto seguido de espacio o fin de string)
        puntos_oracion = len(_re.findall(r'\.\s+', r)) + (1 if r.endswith('.') else 0)
        # Sumar '!' y '?' (rara vez aparecen en números/códigos)
        signos_adic = r.count('!') + r.count('?')
        oraciones = puntos_oracion + signos_adic
        if oraciones != RESUMEN_ORACIONES_ESPERADAS:
            return False, f"{oraciones} oraciones (esperadas {RESUMEN_ORACIONES_ESPERADAS})"

        return True, "cumple formato rígido"

    @staticmethod
    def _enriquecer_con_proxy_zai(
        bloque,
        workspace_dir: Path | str,
    ) -> bool:
        """v6.13 F5: Nivel 2 del arnés - enriquecer un bloque con W1+W2+W3 fusionados en 1 llamada.

        Lee el bloque, llama al proxy Z.ai con el prompt fusionado W1+W2+W3,
        y escribe los 4 artefactos (RESUMEN + 3 archivos) a partir de una sola
        respuesta JSON.

        v6.13 C10: Si el RESUMEN no cumple el formato rígido (600-900, 4 oraciones,
        sin etiquetas), reintenta hasta MAX_ITER_W3=5 con feedback al LLM.

        Args:
            bloque: ThematicBlock con filename.
            workspace_dir: Directorio del workspace.

        Returns:
            True si el bloque se completo, False si fallo.
        """
        import json as _json
        import urllib.request as _ur
        import urllib.error as _ue
        import hashlib as _hashlib

        ws = Path(workspace_dir)
        filename = bloque.filename
        block_id = filename.replace(".md", "")
        bloque_path = ws / filename
        responses_dir = ws / "_responses"
        cache_dir = responses_dir / "cache"

        if not bloque_path.exists():
            logger.warning("v6.13 Nivel 2: bloque %s no existe.", filename)
            return False

        responses_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        bloque_content = bloque_path.read_text(encoding="utf-8")
        if len(bloque_content) < 100:
            logger.warning("v6.13 Nivel 2: bloque %s demasiado corto.", filename)
            return False

        max_chars = 50000
        if len(bloque_content) > max_chars:
            bloque_content = bloque_content[:max_chars] + "\n...(contenido truncado)..."

        try:
            from contexto_zai.config import PROXY_ZAI_URL, PROXY_ZAI_TIMEOUT
        except ImportError:
            logger.warning("v6.13 Nivel 2: no se pudo importar config del proxy.")
            return False

        # v6.13 F5: Prompt fusionado W1+W2+W3
        prompt = PROMPT_FUSIONADO_W1W2W3.format(bloque_content=bloque_content)

        # v6.16 F7 (criterio 40): el hash de caché incluye la versión del
        # pipeline. Si la versión cambia, el hash cambia y la caché se
        # invalida, forzando re-generación de RESUMEN+artefactos con el
        # prompt vigente.
        try:
            from contexto_zai.config import PIPELINE_VERSION
            prompt_hash = _hashlib.sha256(
                (prompt + PIPELINE_VERSION).encode("utf-8")
            ).hexdigest()
        except ImportError:
            # Fallback: sin PIPELINE_VERSION, hash solo del prompt.
            prompt_hash = _hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        cache_file = cache_dir / f"{prompt_hash}.json"

        if cache_file.exists():
            logger.info("v6.13 Nivel 2: caché hit para %s (hash %s...)", block_id, prompt_hash[:8])
            try:
                result = _json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                result = None
        else:
            # v6.13 C10: Loop MAX_ITER_W3 con validación W3 ajena al ejecutor.
            # Si el LLM no cumple el formato rígido (600-900, 4 oraciones, sin
            # etiquetas), reintenta con feedback. Tras MAX_ITER_W3: si el bloque
            # tiene >2000 chars -> pending_task (return False); si no, aceptar.
            from contexto_zai.config import MAX_ITER_W3 as _MAX_ITER

            # v6.15 F5 (criterio 32): resetear el flag de clase antes de empezar.
            # La gestión del 429 la hace ``CascadaAccesoLLM._nivel2_proxy_zai()``
            # con polling de progreso (5s × 3 = 15s), NO esta función. Aquí
            # solo se setea el flag al recibir 429 y se devuelve False.
            EnriquecimientoOrquestador._ultimo_error_proxy_429 = False

            messages = [{"role": "user", "content": prompt}]
            result = None
            w3_ok = False
            w3_motivo = ""
            intento = 0

            while intento < _MAX_ITER:
                intento += 1

                payload = _json.dumps({
                    "model": "glm-4-plus",
                    "messages": messages,
                    "max_tokens": 3000,
                    "temperature": 0.3 if intento == 1 else 0.5,
                }).encode("utf-8")

                req = _ur.Request(PROXY_ZAI_URL, data=payload, method="POST")
                req.add_header("Content-Type", "application/json")

                try:
                    with _ur.urlopen(req, timeout=PROXY_ZAI_TIMEOUT * 6) as resp:
                        raw = resp.read().decode("utf-8")
                except _ue.HTTPError as e:
                    if e.code == 429:
                        # v6.15 F5 (criterio 32): se eliminó el backoff exponencial.
                        # Setear el flag de clase y devolver False inmediatamente.
                        # La gestión del 429 (polling de progreso, reintento, o
                        # caída a Nivel 3) la hace CascadaAccesoLLM._nivel2_proxy_zai().
                        EnriquecimientoOrquestador._ultimo_error_proxy_429 = True
                        logger.warning(
                            "v6.15 F5: HTTP 429 para %s (intento %d/%d). "
                            "Flag _ultimo_error_proxy_429=True, return False "
                            "(gestión delegada a CascadaAccesoLLM._nivel2_proxy_zai).",
                            block_id, intento, _MAX_ITER,
                        )
                        return False
                    else:
                        logger.warning("v6.13 Nivel 2: HTTP %d para %s (intento %d/%d).",
                                       e.code, block_id, intento, _MAX_ITER)
                        return False
                except Exception as e:
                    logger.warning("v6.13 Nivel 2: error %s para %s (intento %d/%d).",
                                   e, block_id, intento, _MAX_ITER)
                    return False

                # Parsear respuesta del proxy
                try:
                    proxy_resp = _json.loads(raw)
                    content_text = proxy_resp.get("choices", [{}])[0].get("message", {}).get("content", "")
                except Exception:
                    logger.warning("v6.13 Nivel 2: respuesta no parseable para %s.", block_id)
                    return False

                # Parsear JSON del contenido (el LLM debe devolver JSON)
                try:
                    content_text = content_text.strip()
                    if content_text.startswith("```json"):
                        content_text = content_text[7:]
                    if content_text.startswith("```"):
                        content_text = content_text[3:]
                    if content_text.endswith("```"):
                        content_text = content_text[:-3]
                    content_text = content_text.strip()

                    result = _json.loads(content_text)
                except Exception:
                    logger.warning("v6.13 Nivel 2: JSON no parseable para %s (intento %d). Raw: %s...",
                                   block_id, intento, content_text[:200])
                    # Añadir feedback para el siguiente intento
                    messages.append({"role": "assistant", "content": content_text})
                    messages.append({"role": "user", "content":
                        "Tu respuesta no es JSON válido. Responde SOLO con el JSON, "
                        "sin texto adicional ni markdown."})
                    continue

                # Guardar en caché del último intento
                cache_file.write_text(_json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

                # Extraer resumen y validar con W3
                resumen_candidate = result.get("resumen", "").strip()
                w3_ok, w3_motivo = EnriquecimientoOrquestador._validar_resumen_w3(
                    resumen_candidate, len(bloque_content)
                )

                if w3_ok:
                    logger.info("v6.13 Nivel 2 W3: %s OK en intento %d (%s).",
                                block_id, intento, w3_motivo)
                    break
                else:
                    logger.warning("v6.13 Nivel 2 W3: %s fallo intento %d/%d: %s",
                                   block_id, intento, _MAX_ITER, w3_motivo)
                    if intento < _MAX_ITER:
                        # Feedback al LLM para el siguiente intento
                        messages.append({"role": "assistant", "content": content_text})
                        messages.append({"role": "user", "content":
                            f"El resumen que generaste NO cumple el formato rígido: {w3_motivo}. "
                            "Genera de nuevo el JSON con un resumen que cumpla: "
                            "600-900 caracteres, exactamente 4 oraciones (separadas por punto y seguido), "
                            "SIN etiquetas como 'Tema central:', 'Decisiones:', etc., "
                            "SIN listas con guiones, SIN negritas, texto natural en un solo párrafo."})

            if result is None:
                logger.warning("v6.13 Nivel 2: %s - sin respuesta JSON válida tras %d intentos.",
                               block_id, _MAX_ITER)
                return False

            # Si W3 sigue sin cumplir tras MAX_ITER:
            # - bloque > 2000 chars -> mejorable -> return False (pending_task)
            # - bloque <= 2000 chars -> aceptar con observaciones
            if not w3_ok:
                if len(bloque_content) > 2000:
                    logger.warning("v6.13 W3: %s - bloque mejorable tras %d intentos. motivo: %s. -> pending_task",
                                   block_id, _MAX_ITER, w3_motivo)
                    return False
                else:
                    logger.info("v6.13 W3: %s - bloque con contenido limitado, aceptado con observaciones tras %d intentos.",
                                block_id, _MAX_ITER)

        # Extraer campos del JSON
        resumen = result.get("resumen", "").strip()
        nombre = result.get("nombre", "").strip()
        decisiones = result.get("decisiones", [])
        temas = result.get("temas", [])
        verificacion = result.get("verificacion", {})
        completo = verificacion.get("completo", True)
        observaciones = verificacion.get("observaciones", "")

        # v6.17 F9 (criterio 9): enriquecimiento ATÓMICO.
        # Generar los 4 contenidos primero. Si los 4 son válidos (no vacíos),
        # escribirlos todos. Si alguno falla, NO escribir ninguno — el bloque
        # queda en su estado anterior.
        # Implementación: escribir a archivos temporales primero, luego
        # renombrar todos a sus paths finales. Si cualquier write falla,
        # eliminar los temporales y devolver False (sin tocar los reales).
        decisiones_text = "\n".join(decisiones) if decisiones else "SIN_DECISIONES_REALES"
        temas_text = ", ".join(temas) if temas else "general"

        # Validar los 4 contenidos antes de escribir nada.
        artefactos_validos = bool(resumen) and bool(nombre) and bool(decisiones_text) and bool(temas_text)
        if not artefactos_validos:
            logger.warning(
                "v6.17 F9: %s - contenido inválido (alguno vacío). No se escribe "
                "nada — el bloque queda en su estado anterior.",
                block_id,
            )
            return False

        # Generar el contenido del .md con RESUMEN al inicio.
        current_content = bloque_path.read_text(encoding="utf-8")
        if current_content.startswith("RESUMEN:"):
            parts = current_content.split("\n\n---\n\n", 1)
            new_content = f"RESUMEN: {resumen}\n\n---\n\n" + (parts[1] if len(parts) > 1 else "")
        else:
            new_content = f"RESUMEN: {resumen}\n\n---\n\n{current_content}"

        # Escribir a archivos temporales primero (átomico por archivo).
        # Si cualquier write falla, eliminar los temporales y devolver False.
        import os as _os_mod
        tmp_paths: list = []
        try:
            # Temporal 1: bloque_NN.md.tmp
            bloque_tmp = bloque_path.with_suffix(bloque_path.suffix + ".tmp")
            bloque_tmp.write_text(new_content, encoding="utf-8")
            tmp_paths.append(bloque_tmp)
            # Temporal 2: bloque_NN_nombre.txt.tmp
            nombre_tmp = responses_dir / f"{block_id}_nombre.txt.tmp"
            nombre_tmp.write_text(nombre, encoding="utf-8")
            tmp_paths.append(nombre_tmp)
            # Temporal 3: bloque_NN_decisiones.txt.tmp
            decisiones_tmp = responses_dir / f"{block_id}_decisiones.txt.tmp"
            decisiones_tmp.write_text(decisiones_text, encoding="utf-8")
            tmp_paths.append(decisiones_tmp)
            # Temporal 4: bloque_NN_temas.txt.tmp
            temas_tmp = responses_dir / f"{block_id}_temas.txt.tmp"
            temas_tmp.write_text(temas_text, encoding="utf-8")
            tmp_paths.append(temas_tmp)
        except Exception as e:
            logger.warning(
                "v6.17 F9: %s - fallo escribiendo temporales (%s). Limpiando — "
                "el bloque queda en su estado anterior.",
                block_id, e,
            )
            for tp in tmp_paths:
                try:
                    if tp.exists():
                        tp.unlink()
                except Exception:
                    pass
            return False

        # Renombrar todos los temporales a sus paths finales (átomico).
        # En Linux, rename sobrescribe. En Windows, hay que eliminar el
        # destino primero.
        try:
            # 1. RESUMEN al inicio del bloque.
            if bloque_path.exists():
                bloque_path.unlink()
            bloque_tmp.rename(bloque_path)
            # 2. _nombre.txt
            nombre_final = responses_dir / f"{block_id}_nombre.txt"
            if nombre_final.exists():
                nombre_final.unlink()
            nombre_tmp.rename(nombre_final)
            # 3. _decisiones.txt
            decisiones_final = responses_dir / f"{block_id}_decisiones.txt"
            if decisiones_final.exists():
                decisiones_final.unlink()
            decisiones_tmp.rename(decisiones_final)
            # 4. _temas.txt
            temas_final = responses_dir / f"{block_id}_temas.txt"
            if temas_final.exists():
                temas_final.unlink()
            temas_tmp.rename(temas_final)
        except Exception as e:
            logger.warning(
                "v6.17 F9: %s - fallo renombrando temporales (%s). Los temporales "
                "pueden haber quedado en disco — el bloque puede estar en estado "
                "inconsistente. Reintentar con bucle D7 lo resolverá.",
                block_id, e,
            )
            # Limpiar temporales que puedan haber quedado.
            for tp in tmp_paths:
                try:
                    if tp.exists():
                        tp.unlink()
                except Exception:
                    pass
            return False

        # W3 final: confirmar completitud (ya validado arriba, pero mantener log informativo)
        if not completo:
            logger.info("v6.13 W3: %s - LLM reportó completo=False, observaciones: %s",
                        block_id, observaciones)

        logger.info("v6.13 Nivel 2 + v6.17 F9: %s completado atómicamente (W1+W2+W3 en 1 llamada, %d intento(s)).",
                    block_id, intento)
        return True

    @staticmethod
    def _auditar_y_completar(
        workspace_dir: Path | str,
    ) -> dict:
            """v6.17 F7 (criterio 6) → v6.18 F3 (criterio 3): si contexto_recuperacion existe, solo auditar + completar.

            v6.18 F3 (criterio 3): si ``contexto_recuperacion/`` no existe,
            esta función NO se llama. P2 (auditoría inicial) carece de
            sentido sobre un workspace vacío. El proceso va directo a
            procesar la fuente (``ampliar_contexto()`` o ``RecoveryCycle``).

            Si ``contexto_recuperacion/`` existe (con bloques físicos), el
            daemon/process NO re-extrae ni re-construye. Audita qué está
            completo, qué está incompleto, y completa lo faltante:

            1. Audita con ``_descubrir_bloques_incompletos()`` (F1).
            2. Completa solo los incompletos (sin re-extraer, sin
               re-construir, sin borrar caché, sin quitar RESUMENES).
            3. Auditoría final + P17 + P18 + P19.

            Si ``contexto_recuperacion/`` no existe, el llamador debe
            ejecutar ``RecoveryCycle`` completo o ``ampliar_contexto()``
            (que internamente invoca RecoveryCycle si estructura=cronologico).

            Args:
                workspace_dir: Directorio del workspace (donde viven los
                    ``bloque_*.md`` y ``_responses/``).

            Returns:
                Dict con:
                - ``audited``: True si se ejecutó la auditoría.
                - ``incompletos_iniciales``: Número de bloques incompletos al inicio.
                - ``pending_tasks``: Número de pending_tasks tras completar.
                - ``contexto_existia``: True si el workspace tenía bloques.
            """
            ws = Path(workspace_dir)
            contexto_existia = ws.exists() and any(ws.glob("bloque_*.md"))
            if not contexto_existia:
                logger.info(
                    "v6.17 F7: contexto_recuperacion no existe — no se audita "
                    "(el llamador debe ejecutar RecoveryCycle completo)."
                )
                return {
                    "audited": False,
                    "incompletos_iniciales": 0,
                    "pending_tasks": 0,
                    "contexto_existia": False,
                }

            # 1. Auditar bloques incompletos con F1.
            incompletos = EnriquecimientoOrquestador._descubrir_bloques_incompletos(ws)
            logger.info(
                "v6.17 F7: contexto_recuperacion existe — %d bloque(s) incompleto(s) "
                "de %d total. Completando solo los incompletos (sin re-extraer, "
                "sin re-construir, sin borrar caché, sin quitar RESUMENES).",
                len(incompletos), len(list(ws.glob("bloque_*.md"))),
            )

            # 2. Procesar solo los incompletos con la cascada.
            cascada = CascadaAccesoLLM(workspace_dir=ws)
            for inc in incompletos:
                cascada.procesar_tarea(inc["bloque"])
            pending_tasks_count = len(cascada.get_pending_tasks())

            # 3. Auditoría final + P17 + P18 + P19.
            # P16 — auditoría final post-enriquecimiento.
            try:
                audit_final = AuditorWorkspace.auditar_completitud(ws)
                logger.info(
                    "v6.17 F7: Auditoría final: %d completos, %d incompletos, "
                    "metadata_valida=%s",
                    len(audit_final["completos"]), len(audit_final["incompletos"]),
                    audit_final["metadata_valida"],
                )
            except Exception as e:
                logger.warning("v6.17 F7: auditar_completitud falló: %s", e)

            # P17 — bucle D7 encapsulado (F12) para reintentar con feedback.
            try:
                from contexto_zai.models import OrchestratorResult
                dummy_result = OrchestratorResult(success=True)
                dummy_result.pending_tasks = cascada.get_pending_tasks()
                EnriquecimientoOrquestador._bucle_d7_completitud(
                    result=dummy_result,
                    workspace_dir=ws,
                )
            except Exception as e:
                logger.warning("v6.17 F7: bucle D7 (P17) falló: %s", e)

            # P18 — consolidar decisiones del LLM en 02_decisiones_clave.md.
            try:
                EnriquecimientoOrquestador._consolidar_decisiones_llm(workspace_dir=ws)
            except Exception as e:
                logger.warning("v6.17 F7: _consolidar_decisiones_llm (P18) falló: %s", e)

            # P19 — regenerar 01_indice_recuperacion.md tras enriquecimiento.
            try:
                EnriquecimientoOrquestador._regenerar_indice_tras_enriquecimiento(workspace_dir=ws)
            except Exception as e:
                logger.warning("v6.17 F7: _regenerar_indice (P19) falló: %s", e)

            return {
                "audited": True,
                "incompletos_iniciales": len(incompletos),
                "pending_tasks": pending_tasks_count,
                "contexto_existia": True,
            }

    @staticmethod
    def _enriquecer_bloques_post_run(
        result: "OrchestratorResult",
        workspace_dir: Path | str,
        chat_label: str = "",
        is_chat_chronological: bool = True,
    ) -> "OrchestratorResult":
            """v6.2: Post-procesa un OrchestratorResult para añadir fallback de bloques.

            Llamada por ``pipeline.run()`` después de ``orch.activate()``. Examina los
            bloques físicos del workspace, identifica los que no tienen RESUMEN:, y
            orquesta el enriquecimiento (proxy Z.ai → worker, si no → fallback al agente).

            Las pending_tasks que devuelve el Orchestrator original se conservan; las
            nuevas (fallback de bloques) se añaden a la lista.

            v6.10 F2: SIN try/except silencioso. Si el enriquecimiento falla, el error
            se propaga y se registra claramente. Las pending_tasks se capturan del
            valor de retorno directamente (v6.8.1 re-aplicado).

            v6.11 F6: ``is_chat_chronological`` se acepta por simetría con
            ``collect_responses()``. Hoy en día ``_enriquecer_bloques_post_run`` solo
            se invoca desde ``pipeline.run()`` (chat-cronológico), pero el parámetro
            permite llamarlo en el futuro desde ``ampliar_contexto()`` para enriquecer
            bloques externos sin disparar la consolidación de los 4 archivos.

            Args:
                result: OrchestratorResult devuelto por orch.activate().
                workspace_dir: Directorio del workspace.
                chat_label: Etiqueta del chat (opcional).
                is_chat_chronological: v6.11 F6 — ``True`` (default) si la operación
                    viene de ``pipeline.run()`` (chat cronológico). ``False`` si viene
                    de ``ampliar_contexto()`` (fuente externa, no cronológica).

            Returns:
                El mismo OrchestratorResult con pending_tasks actualizadas.
            """
            # v6.10 F2: sin try/except silencioso. Si el workspace no existe o no hay
            # bloques, simplemente devolvemos result sin cambios (no es error).
            workspace_path = Path(workspace_dir)
            if not workspace_path.exists():
                return result
            from contexto_zai.models import ThematicBlock
            blocks = []
            for p in sorted(workspace_path.glob("bloque_*.md")):
                block = ThematicBlock(filename=p.name)
                blocks.append(block)
            if not blocks:
                return result

            # Orquestar enriquecimiento (v6.10 F3: el arnés detecta caída del Worker
            # Bun en menos de 5s y devuelve las pending_tasks inmediatamente).
            fallback_tasks = _enriquecer_bloques_con_fallback(
                blocks=blocks,
                workspace_dir=workspace_dir,
                chat_label=chat_label,
            )

            # Añadir a pending_tasks existentes (v6.8.1 re-aplicado: capturar del retorno).
            if fallback_tasks:
                if result.pending_tasks is None:
                    result.pending_tasks = []
                result.pending_tasks.extend(fallback_tasks)
                logger.info("v6.10: %d tarea(s) de fallback añadidas a pending_tasks.",
                            len(fallback_tasks))

            return result

    @staticmethod
    def _bucle_d7_completitud(
        result: "OrchestratorResult",
        workspace_dir: Path | str,
    ) -> "OrchestratorResult":
            """v6.14 F3 → v6.17 F3 (criterio 2): Bucle D7 SEPARADO de la cascada.

            El bucle D7 opera sobre ``pending_tasks``, NO sobre niveles de la
            cascada. Cuando la cascada (los 3 niveles: Worker Bun → proxy Z.ai
            → subagentes/Nivel 3) no completa un bloque, el bloque va a
            ``pending_task`` (publicada por ``CascadaAccesoLLM`` en
            ``_pending_tasks.json``).

            El bucle D7 lee las ``pending_tasks`` y reintenta con feedback
            hasta ``MAX_ITER_D7=5``. Si el D7 no completa tras 5 intentos,
            la tarea se MANTIENE en ``pending_task`` (no se elimina, no se
            descarta — queda para auditoría P17 y para que el agente CZAI la
            procese manualmente si decide intervenir).

            v6.17 F3 (criterio 2): el bucle D7 NO baja niveles. No
            interactúa con la cascada. La cascada decide el nivel (1/2/3),
            el D7 decide el reintento. Son mecanismos distintos.

            El proceso no puede invocar el Task tool directamente — solo
            publica las pending_tasks corregidas en ``_pending_tasks.json``
            para que el agente CZAI las ejecute. El agente CZAI, tras
            ejecutar los subagentes y llamar ``collect_responses()``, puede
            volver a invocar el pipeline; P17 detecta si quedan incompletos
            y vuelve a iterar. Las iteraciones se cuentan en
            ``_d7_iter_count.json``.

            Si ``MAX_ITER_D7`` (5) se agota → genera informe de escalado al
            Director con las 4 preguntas por iteración (qué falló → qué se
            diagnosticó → cómo se corrigió → qué se implementó) en
            ``/home/z/my-project/download/informe_escalado_d7_<timestamp>.md``.
            Las tareas SIGUEN en ``pending_tasks`` tras el informe (F3:
            no se eliminan, no se descartan).

            Args:
                result: OrchestratorResult devuelto por P14 (con pending_tasks).
                workspace_dir: Directorio del workspace.

            Returns:
                El mismo OrchestratorResult con pending_tasks actualizadas:
                - Si no hay incompletos: pending_tasks = [] (verde).
                - Si hay incompletos: pending_tasks = lista de SubagentTask
                  con prompts corregidos para que el agente CZAI las ejecute.
            """
            import json as _json
            import time as _time
            from contexto_zai.config import MAX_ITER_D7 as _MAX_ITER_D7
            from contexto_zai.models import ThematicBlock as _TB

            ws_path = Path(workspace_dir)
            if not ws_path.exists():
                return result

            # 1. Detectar bloques incompletos físicamente (post P14-P16).
            audit = AuditorWorkspace.auditar_bloques(workspace_dir)
            incompletos = audit.get("incompletos", [])

            # 2. Leer contador de iteraciones previas (archivo _d7_iter_count.json).
            iter_path = ws_path / "_d7_iter_count.json"
            iter_count = 0
            iter_history: list = []
            if iter_path.exists():
                try:
                    iter_data = _json.loads(iter_path.read_text(encoding="utf-8"))
                    iter_count = int(iter_data.get("count", 0))
                    iter_history = iter_data.get("history", [])
                except Exception:
                    iter_count = 0
                    iter_history = []

            if not incompletos:
                # Verde: no hay nada que iterar. Resetear el contador.
                if iter_path.exists():
                    try:
                        iter_path.unlink()
                    except Exception:
                        pass
                logger.info(
                    "v6.14 P17 D7: 0 bloques incompletos. Saco vacío (verde)."
                )
                result.pending_tasks = []
                try:
                    AuditorWorkspace.sincronizar_registro(workspace_dir)
                except Exception as e:
                    logger.warning("v6.14 P17 D7: sincronizar_registro falló: %s", e)
                return result

            # 3. Incrementar contador (esta invocación es la iteración N+1).
            iter_count += 1
            logger.info(
                "v6.14 P17 D7: iteración %d/%d. %d bloque(s) incompleto(s).",
                iter_count, _MAX_ITER_D7, len(incompletos),
            )

            # 4. Para cada bloque incompleto, construir prompt corregido.
            new_pending_tasks: list = []
            iter_entry = {
                "iter": iter_count,
                "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
                "bloques_incompletos": [
                    b.get("block_id", "") if isinstance(b, dict) else str(b)
                    for b in incompletos
                ],
                "diagnosticos": [],
            }

            for b in incompletos:
                if isinstance(b, dict):
                    block_id = b.get("block_id", "")
                    faltantes = b.get("faltantes", [])
                else:
                    block_id = str(b)
                    faltantes = []
                filename = f"{block_id}.md"
                bloque_path = ws_path / filename

                if not bloque_path.exists():
                    logger.warning("v6.14 P17 D7: bloque %s no existe (saltando).", filename)
                    continue

                bloque_content = bloque_path.read_text(encoding="utf-8", errors="ignore")
                diagnostico = {
                    "block_id": block_id,
                    "fallo": "",
                    "diagnostico": "",
                    "correccion": "",
                    "implementacion": "",
                }

                # Caso A: bloque tiene RESUMEN. Validar W3.
                if bloque_content.startswith("RESUMEN:"):
                    parts = bloque_content.split("\n\n---\n\n", 1)
                    if parts[0].startswith("RESUMEN:"):
                        resumen_actual = parts[0][len("RESUMEN:"):].strip()
                    else:
                        resumen_actual = parts[0].strip()
                    w3_ok, w3_motivo = EnriquecimientoOrquestador._validar_resumen_w3(
                        resumen_actual, len(bloque_content)
                    )
                    if not w3_ok:
                        # RESUMEN existe pero falla W3 → feedback al subagente.
                        diagnostico["fallo"] = f"RESUMEN no cumple W3: {w3_motivo}"
                        diagnostico["diagnostico"] = f"Validación W3 falló: {w3_motivo}"
                        diagnostico["correccion"] = (
                            "Generar nuevo RESUMEN que cumpla 600-900 chars, "
                            "4 oraciones, sin etiquetas prohibidas."
                        )
                        diagnostico["implementacion"] = (
                            "Prompt con feedback explícito publicado en _pending_tasks.json"
                        )
                        task = EnriquecimientoOrquestador._construir_pending_task_d7_corregido(
                            filename=filename,
                            feedback=(
                                f"El RESUMEN actual NO cumple el formato rígido W3: {w3_motivo}. "
                                "Genera de nuevo el resumen cumpliendo: 600-900 caracteres, "
                                "exactamente 4 oraciones (separadas por punto y seguido), "
                                "SIN etiquetas como 'Tema central:', 'Decisiones:', etc., "
                                "SIN listas con guiones, SIN negritas, texto natural "
                                "en un solo párrafo."
                            ),
                        )
                        if task:
                            new_pending_tasks.append(task)
                        iter_entry["diagnosticos"].append(diagnostico)
                        continue
                    else:
                        # RESUMEN OK pero faltan archivos auxiliares.
                        diagnostico["fallo"] = (
                            f"Faltan archivos en _responses/: {faltantes}"
                        )
                        diagnostico["diagnostico"] = (
                            "Bloque tiene RESUMEN válido pero faltan uno o más "
                            "de los 3 archivos auxiliares (_nombre.txt, "
                            "_decisiones.txt, _temas.txt)."
                        )
                        diagnostico["correccion"] = (
                            "Generar los archivos faltantes sin tocar el RESUMEN existente."
                        )
                        diagnostico["implementacion"] = (
                            "Prompt específico para archivos faltantes publicado en _pending_tasks.json"
                        )
                        faltantes_str = (
                            ", ".join(faltantes) if faltantes
                            else "nombre.txt, decisiones.txt, temas.txt"
                        )
                        task = EnriquecimientoOrquestador._construir_pending_task_d7_corregido(
                            filename=filename,
                            feedback=(
                                f"El bloque ya tiene RESUMEN válido, pero faltan estos "
                                f"archivos en _responses/: {faltantes_str}. Genera SOLO "
                                f"los archivos faltantes usando el contenido del bloque. "
                                f"NO modifiques el RESUMEN existente."
                            ),
                        )
                        if task:
                            new_pending_tasks.append(task)
                        iter_entry["diagnosticos"].append(diagnostico)
                        continue

                # Caso B: bloque NO tiene RESUMEN → usar prompt estándar.
                diagnostico["fallo"] = "Bloque sin RESUMEN (no enriquecido)"
                diagnostico["diagnostico"] = (
                    "El bloque no ha sido enriquecido todavía (no tiene RESUMEN al inicio)."
                )
                diagnostico["correccion"] = (
                    "Generar RESUMEN + 3 archivos auxiliares desde cero."
                )
                diagnostico["implementacion"] = (
                    "Prompt estándar de enriquecimiento publicado en _pending_tasks.json"
                )
                block_obj = _TB(filename=filename)
                task = _construir_pending_task_para_bloque(block_obj, chat_label="v6.14_d7")
                if task:
                    new_pending_tasks.append(task)
                iter_entry["diagnosticos"].append(diagnostico)

            iter_history.append(iter_entry)

            # 5. Si MAX_ITER_D7 agotado → generar informe de escalado al Director.
            if iter_count >= _MAX_ITER_D7:
                try:
                    ts = _time.strftime("%Y%m%d_%H%M%S", _time.gmtime())
                    informe_path = Path("/home/z/my-project/download") / f"informe_escalado_d7_{ts}.md"
                    informe_path.parent.mkdir(parents=True, exist_ok=True)
                    lines = [
                        "# Informe de Escalado al Director — Bucle D7 agotado",
                        "",
                        f"**Timestamp:** {_time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime())}",
                        f"**Workspace:** `{workspace_dir}`",
                        f"**Iteraciones D7 ejecutadas:** {iter_count} (máximo {_MAX_ITER_D7})",
                        f"**Bloques aún incompletos:** {len(incompletos)}",
                        "",
                        "## Las 4 preguntas por iteración",
                        "",
                    ]
                    for h in iter_history:
                        lines.append(
                            f"### Iteración {h.get('iter', '?')} — {h.get('timestamp', '')}"
                        )
                        lines.append("")
                        bloques_inc = h.get("bloques_incompletos", [])
                        lines.append(
                            f"- **Bloques incompletos detectados:** "
                            f"{', '.join(bloques_inc) if bloques_inc else '(ninguno)'}"
                        )
                        lines.append("")
                        for d in h.get("diagnosticos", []):
                            lines.append(f"#### Bloque `{d.get('block_id', '?')}`")
                            lines.append("")
                            lines.append(f"1. **Qué falló:** {d.get('fallo', '?')}")
                            lines.append(f"2. **Qué se diagnosticó:** {d.get('diagnostico', '?')}")
                            lines.append(f"3. **Cómo se corrigió:** {d.get('correccion', '?')}")
                            lines.append(f"4. **Qué se implementó:** {d.get('implementacion', '?')}")
                            lines.append("")
                    informe_path.write_text("\n".join(lines), encoding="utf-8")
                    logger.warning(
                        "v6.14 P17 D7: MAX_ITER_D7=%d agotado. Informe de escalado "
                        "generado en %s",
                        _MAX_ITER_D7, informe_path,
                    )
                except Exception as e:
                    logger.error(
                        "v6.14 P17 D7: no se pudo generar informe de escalado: %s", e
                    )

            # 6. Persistir contador de iteraciones + historial.
            try:
                iter_path.write_text(
                    _json.dumps(
                        {"count": iter_count, "history": iter_history},
                        indent=2, ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except Exception as e:
                logger.warning(
                    "v6.14 P17 D7: no se pudo persistir _d7_iter_count.json: %s", e
                )

            # 7. Publicar pending_tasks corregidas en _pending_tasks.json
            #    (reemplaza el saco viejo por el corregido).
            # v6.17 F11 (criterio 11): usar _persistir_pending_task_en_disco
            # (la misma función que usa _post_bloque y _nivel3_subagentes)
            # para que la persistencia sea consistente. Las pending_tasks
            # pueden caer desde cualquier nivel de la cascada (N1, N2 o N3).
            try:
                ws_path_d7 = Path(workspace_dir)
                pending_path_d7 = ws_path_d7 / "_pending_tasks.json"
                # Limpiar el saco viejo (reemplazar, no append).
                if pending_path_d7.exists():
                    pending_path_d7.unlink()
                # Persistir cada nueva pending_task con la función única.
                for task in new_pending_tasks:
                    EnriquecimientoOrquestador._persistir_pending_task_en_disco(
                        workspace_dir=workspace_dir, task=task
                    )
            except Exception as e:
                logger.warning(
                    "v6.17 F11: no se pudo persistir pending_tasks del D7: %s", e
                )

            # 8. Actualizar result.pending_tasks.
            result.pending_tasks = new_pending_tasks

            # 9. Sincronizar _processed_blocks.json.
            try:
                AuditorWorkspace.sincronizar_registro(workspace_dir)
            except Exception as e:
                logger.warning(
                    "v6.14 P17 D7: sincronizar_registro falló: %s", e
                )

            return result

    @staticmethod
    def _construir_pending_task_d7_corregido(
        filename: str,
        feedback: str,
    ) -> "SubagentTask":
            """v6.14 F3: Construye una SubagentTask con feedback explícito para el bucle D7.

            A diferencia de ``_construir_pending_task_para_bloque``, este prompt
            incluye feedback explícito sobre qué falló en la iteración anterior
            y qué debe corregir el subagente en esta iteración.

            Args:
                filename: Nombre del archivo de bloque (``bloque_NN.md``).
                feedback: Texto explicando qué falló y qué corregir.

            Returns:
                SubagentTask con prompt corregido lista para que el agente
                CZAI la ejecute con el Task tool.
            """
            from contexto_zai.models import SubagentTask
            block_id = filename.replace(".md", "")
            prompt = f"""Eres un subagente Actuador del proceso contexto_zai. Estás en el bucle D7 (P17)
de garantía de completitud: revisar la falla respecto al spec, corregirla,
re-entregarla al Actuador y re-valorar contra el baremo W3.

## Bloque a procesar

- Lee el archivo `{filename}` en el workspace.

## Feedback de la iteración anterior

{feedback}

## Tu tarea

1. Lee el bloque completo.
2. Si el bloque NO tiene RESUMEN al inicio: genera un RESUMEN de 600-900
   caracteres, exactamente 4 oraciones (separadas por punto y seguido),
   SIN etiquetas como 'Tema central:', 'Decisiones:', etc., SIN listas
   con guiones, SIN negritas, texto natural en un solo párrafo.
3. Si el bloque YA tiene RESUMEN válido: NO lo modifiques. Solo genera
   los archivos que falten en ``_responses/``.
4. Extrae: nombre legible en snake_case (máximo 5 palabras), decisiones
   con formato 'DECISION: ... | ALCANCE: ...', temas principales en
   snake_case (máximo 5).
5. Escribe los 4 artefactos:
   - RESUMEN al inicio del archivo `{filename}` con el prefijo 'RESUMEN: '
     (separado del contenido existente por \\n\\n---\\n\\n).
   - _responses/{block_id}_nombre.txt
   - _responses/{block_id}_decisiones.txt
   - _responses/{block_id}_temas.txt

Respuesta:"""
            return SubagentTask(
                task_id=f"d7_{block_id}",
                purpose=f"v6.14.d7.completitud.{filename}",
                prompt=prompt,
                context={"filename": filename, "feedback": feedback[:500]},
            )

    @staticmethod
    def _ejecutar_pending_tasks_obligatorias(
        result: "OrchestratorResult",
        workspace_dir: Path | str,
    ) -> "OrchestratorResult":
            """v6.3 F1 → v6.14 F3 (criterio 19): DEPRECATED wrapper.

            Antes: intentaba resolver pending_tasks llamando
            ``collect_responses()`` como "arregla todo" (uso incorrecto del
            integrador). Ahora: delega en ``_bucle_d7_completitud()`` que
            implementa el bucle D7 real de P17 con feedback y MAX_ITER_D7=5.

            Se mantiene como wrapper de compatibilidad para código externo
            que aún lo invoque. No hace nada por su cuenta.
            """
            return EnriquecimientoOrquestador._bucle_d7_completitud(
                result=result, workspace_dir=workspace_dir,
            )

    @staticmethod
    def _bucle_d7(
        pending_tasks: list,
        workspace_dir: Path | str,
    ) -> list:
            """v6.17 F12 (criterio 12): bucle D7 encapsulado.

            Encapsula el bucle D7 (reintento con feedback) en una función
            que recibe ``pending_tasks`` y devuelve las que siguen
            incompletas tras ``MAX_ITER_D7=5`` intentos.

            Procedimiento (criterio 12):
            1. Recibe ``pending_tasks``.
            2. Para cada una: revisar qué falló (auditando el bloque físico
               con ``_descubrir_bloques_incompletos()`` de F1), construir
               prompt corregido (con feedback explícito), reintentar y
               verificar (4 artefactos).
            3. Si cumple → fuera del saco (no se devuelve).
            4. Si no cumple → próxima iteración (sigue en el saco).
            5. Si ``MAX_ITER_D7=5`` intentos agotados → se mantiene en
               ``pending_task`` (se devuelve al llamador).

            v6.17 F3 (criterio 2): el bucle D7 NO baja niveles. No
            interactúa con la cascada. Recibe pending_tasks (que ya cayeron
            desde la cascada en cualquier nivel) y reintenta con feedback.

            v6.17 F11 (criterio 11): las pending_tasks se persisten en
            ``_pending_tasks.json`` vía ``_persistir_pending_task_en_disco``
            (la misma función que usa ``_post_bloque``).

            Args:
                pending_tasks: Lista de SubagentTask pendientes.
                workspace_dir: Directorio del workspace.

            Returns:
                Lista de SubagentTask que siguen incompletas tras
                ``MAX_ITER_D7=5`` intentos. Si todas se completaron,
                devuelve lista vacía.
            """
            if not pending_tasks:
                return []

            from contexto_zai.config import MAX_ITER_D7 as _MAX_ITER_D7
            from contexto_zai.models import OrchestratorResult

            ws_path = Path(workspace_dir)
            if not ws_path.exists():
                return list(pending_tasks)

            # Construir un OrchestratorResult dummy con las pending_tasks
            # y delegar al bucle D7 existente (_bucle_d7_completitud). El
            # bucle interno hace la auditoría, construcción de prompts
            # corregidos, y persistencia.
            dummy_result = OrchestratorResult(success=True)
            dummy_result.pending_tasks = list(pending_tasks)
            try:
                resultado = EnriquecimientoOrquestador._bucle_d7_completitud(
                    result=dummy_result,
                    workspace_dir=workspace_dir,
                )
                # _bucle_d7_completitud devuelve el OrchestratorResult con
                # pending_tasks actualizadas (las que siguen incompletas).
                return list(getattr(resultado, "pending_tasks", []) or [])
            except Exception as e:
                logger.warning(
                    "v6.17 F12: _bucle_d7 falló (%s) — devolviendo pending_tasks originales.",
                    e,
                )
                return list(pending_tasks)


    @staticmethod
    def _consolidar_decisiones_llm(workspace_dir: Path | str) -> int:
            """v6.4 F1: Consolida las decisiones del LLM en 02_decisiones_clave.md.

            QUÉ SOLUCIONA: el DecisionExtractor regex se eliminó (v6.4). Las decisiones
            reales las extrae el LLM (Worker Bun o subagentes fallback) y las escribe en
            _responses/bloque_NN_decisiones.txt con formato "DECISION: ... | ALCANCE: ...".
            Esta función lee todos esos archivos y los consolida en 02_decisiones_clave.md.

            Args:
                workspace_dir: Directorio del workspace.

            Returns:
                Número de decisiones consolidadas.
            """
            from pathlib import Path as _Path
            ws = _Path(workspace_dir)
            responses_dir = ws / "_responses"
            if not responses_dir.exists():
                return 0

            # Leer todas las decisiones de _responses/bloque_*_decisiones.txt
            all_decisions: list[str] = []
            for p in sorted(responses_dir.glob("bloque_*_decisiones.txt")):
                try:
                    content = p.read_text(encoding="utf-8").strip()
                    if not content:
                        continue
                    for line in content.split("\n"):
                        line = line.strip()
                        if line and (line.startswith("DECISION:") or line.startswith("DECISION :")):
                            all_decisions.append(line)
                except Exception as e:
                    logger.warning("v6.4 F1: no se pudo leer %s: %s", p.name, e)

            if not all_decisions:
                logger.info("v6.4 F1: no hay decisiones del LLM para consolidar.")
                return 0

            # Generar el contenido de 02_decisiones_clave.md
            lines: list[str] = [
                "# Decisiones Clave",
                "",
                f"**Total de decisiones:** {len(all_decisions)}",
                f"**Fuente:** Extracción LLM (Worker Bun + subagentes fallback)",
                "",
                "---",
                "",
            ]

            for i, dec in enumerate(all_decisions, start=1):
                # Parsear "DECISION: ... | ALCANCE: ..."
                decision_text = dec
                alcance_text = "A determinar"
                if "|" in dec:
                    parts = dec.split("|", 1)
                    decision_text = parts[0].strip()
                    alcance_part = parts[1].strip()
                    if alcance_part.startswith("ALCANCE:"):
                        alcance_text = alcance_part[len("ALCANCE:"):].strip()
                    else:
                        alcance_text = alcance_part

                # Limpiar prefijo "DECISION:" si existe
                if decision_text.startswith("DECISION:"):
                    decision_text = decision_text[len("DECISION:"):].strip()
                elif decision_text.startswith("DECISION :"):
                    decision_text = decision_text[len("DECISION :"):].strip()

                lines.append(f"## D{i:02d} -- {decision_text[:80]}")
                lines.append(f"- **Decisión:** {decision_text}")
                lines.append(f"- **Alcance:** {alcance_text}")
                lines.append("")

            content = "\n".join(lines)

            # Escribir el archivo
            decisiones_path = ws / "02_decisiones_clave.md"
            decisiones_path.write_text(content, encoding="utf-8")
            logger.info("v6.4 F1: %d decisiones del LLM consolidadas en 02_decisiones_clave.md", len(all_decisions))
            return len(all_decisions)

    @staticmethod
    def _regenerar_indice_tras_enriquecimiento(
        workspace_dir: Path | str,
    ) -> int:
            """v6.8.4 re-aplicado (v6.10 F4): Vuelca los temas significativos del
            ``_responses/<bloque>_temas.txt`` al ``tema_a_archivo`` del metadata,
            elimina los temas provisionales ``documento_externo_NN`` y regenera
            ``01_indice_recuperacion.md``.

            Es idempotente: si los ``_responses/<bloque>_temas.txt`` no existen
            todavía, no hace nada y devuelve 0.
            """
            ws = Path(workspace_dir)
            responses_dir = ws / "_responses"
            metadata_path = ws / "_metadata.json"

            if not responses_dir.exists() or not metadata_path.exists():
                return 0

            import json as _json
            try:
                metadata = _json.loads(metadata_path.read_text(encoding="utf-8"))
            except (ValueError, _json.JSONDecodeError):
                metadata = {}

            tema_a_archivo = metadata.setdefault("tema_a_archivo", {})

            # 1. Eliminar temas provisionales "documento_externo_NN" residuales.
            provisionales_eliminados = 0
            for clave in list(tema_a_archivo.keys()):
                if clave.startswith("documento_externo_"):
                    del tema_a_archivo[clave]
                    provisionales_eliminados += 1
            if provisionales_eliminados:
                logger.info(
                    "v6.10 F4: %d tema(s) provisionales eliminados de tema_a_archivo.",
                    provisionales_eliminados,
                )

            # 2. Volver a leer los _responses/<bloque>_temas.txt y registrar los temas.
            bloques_con_temas = 0
            for p in sorted(responses_dir.glob("bloque_*_temas.txt")):
                block_id = p.stem
                if block_id.endswith("_temas"):
                    block_id = block_id[: -len("_temas")]
                bloque_filename = f"{block_id}.md"

                try:
                    content = p.read_text(encoding="utf-8").strip()
                except Exception as e:
                    logger.warning("v6.10 F4: no se pudo leer %s: %s", p.name, e)
                    continue

                if not content:
                    continue

                temas_significativos = [
                    t.strip() for t in content.split("\n") if t.strip()
                ]
                if not temas_significativos:
                    continue

                for tema in temas_significativos:
                    existente = tema_a_archivo.get(tema)
                    if isinstance(existente, list):
                        if bloque_filename in existente:
                            continue
                        existente.append(bloque_filename)
                        tema_a_archivo[tema] = existente
                    elif isinstance(existente, str):
                        if existente == bloque_filename:
                            tema_a_archivo[tema] = [bloque_filename]
                        else:
                            tema_a_archivo[tema] = [existente, bloque_filename]
                    else:
                        tema_a_archivo[tema] = [bloque_filename]

                bloques_con_temas += 1

            # 3. Persistir el metadata actualizado.
            metadata_path.write_text(
                _json.dumps(metadata, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            # 4. Regenerar 01_indice_recuperacion.md.
            if bloques_con_temas > 0 or provisionales_eliminados > 0:
                try:
                    from contexto_zai.coordinador.integrador_respuestas import IntegradorRespuestas
                    IntegradorRespuestas._regenerar_indice_recuperacion(ws, metadata)
                    logger.info(
                        "v6.10 F4: índice regenerado (%d bloque(s) con temas, %d provisional(es) eliminado(s)).",
                        bloques_con_temas, provisionales_eliminados,
                    )
                except Exception as e:
                    logger.warning("v6.10 F4: no se pudo regenerar el índice: %s", e)

            return bloques_con_temas

    @staticmethod
    def _normalizar_bloques_externos(workspace_dir: Path | str) -> int:
            """v6.8.4 re-aplicado (v6.10 F4): Normaliza los bloques externos del
            workspace tras el enriquecimiento. Punto de consistencia defensivo que
            re-intenta el vuelco de temas por si algún ``_temas.txt`` llegó tarde.
            """
            ws = Path(workspace_dir)
            metadata_path = ws / "_metadata.json"
            if not metadata_path.exists():
                return 0

            import json as _json
            try:
                metadata = _json.loads(metadata_path.read_text(encoding="utf-8"))
            except (ValueError, _json.JSONDecodeError):
                return 0

            archivo_a_source = metadata.get("archivo_a_source", {})
            tema_a_archivo = metadata.setdefault("tema_a_archivo", {})

            bloques_externos = []
            for bloque_filename, source_info in archivo_a_source.items():
                if not isinstance(source_info, dict):
                    continue
                if source_info.get("source_type") in ("file", "url"):
                    bloques_externos.append(bloque_filename)

            if not bloques_externos:
                return 0

            responses_dir = ws / "_responses"
            normalizados = 0
            for bloque_filename in bloques_externos:
                block_id = bloque_filename.replace(".md", "")
                temas_path = responses_dir / f"{block_id}_temas.txt"
                if not temas_path.exists():
                    continue

                try:
                    content = temas_path.read_text(encoding="utf-8").strip()
                except Exception:
                    continue
                temas = [t.strip() for t in content.split("\n") if t.strip()]
                if not temas:
                    continue

                ya_cubierto = False
                for tema in temas:
                    existente = tema_a_archivo.get(tema)
                    if isinstance(existente, list) and bloque_filename in existente:
                        ya_cubierto = True
                        break
                    if isinstance(existente, str) and existente == bloque_filename:
                        ya_cubierto = True
                        break
                if ya_cubierto:
                    continue

                normalizados += 1

            if normalizados > 0:
                _regenerar_indice_tras_enriquecimiento(workspace_dir)
                logger.info("v6.10 F4: %d bloque(s) externo(s) normalizado(s).", normalizados)

            return normalizados

    @staticmethod
    def _buscar_en_resumenes(
        workspace: Path,
        question: str,
        bloques_info: list[dict],
    ) -> Optional[str]:
            """v4.4: Busca en ``04_resumenes_bloques.md`` como atajo para query_context.

            Lee el archivo de resúmenes (si existe) y busca las palabras de la
            pregunta en los resúmenes de los bloques candidatos. Si un resumen
            contiene las palabras clave, lo devuelve como respuesta directa.

            Args:
                workspace: Directorio del workspace.
                question: Pregunta del agente.
                bloques_info: Lista de bloques candidatos (con ``filename``).

            Returns:
                Texto del resumen si encuentra coincidencia, o ``None`` si no.
            """
            resumenes_path = workspace / "04_resumenes_bloques.md"
            if not resumenes_path.exists():
                return None

            try:
                content_original = resumenes_path.read_text(encoding="utf-8")
                content_lower = content_original.lower()
            except Exception:
                return None

            # Palabras clave de la pregunta (mismas que usa query_context)
            question_lower = question.lower()
            import re as _re
            question_words = _re.findall(r"[a-záéíóúñ_]+", question_lower)
            _stop = {"que", "de", "la", "el", "en", "y", "a", "los", "las", "del",
                     "para", "con", "por", "es", "se", "un", "una", "como", "cual",
                     "cuales", "sobre", "al"}
            question_words = [w for w in question_words if len(w) > 2 and w not in _stop]
            if not question_words:
                return None

            # Bloques candidatos (por filename)
            candidatos_filenames = {b["filename"] for b in bloques_info}

            # Buscar secciones de resumen por bloque en el archivo original (no lowercase)
            import re as _re2
            pattern = _re2.compile(r"##\s*(\S+\.md)\s*\n\n(.*?)(?=\n##\s|\Z)", _re2.DOTALL)

            resultados: list[str] = []
            for match in pattern.finditer(content_original):
                filename = match.group(1).strip()
                resumen = match.group(2).strip()
                if filename not in candidatos_filenames:
                    continue
                # ¿El resumen contiene las palabras clave? (buscar en lowercase)
                resumen_lower = resumen.lower()
                matches = sum(1 for w in question_words if w in resumen_lower)
                if matches >= 1:
                    resultados.append(f"**{filename}:**\n{resumen}")

            if resultados:
                return "\n\n".join(resultados)
            return None

    @staticmethod
    def _extraer_id_de_link(url: str, tipo: str = "share") -> Optional[str]:
            """v4.2: Extrae el ``id`` de un link ``/s/`` o ``/c/`` de Z.ai.

            Args:
                url: URL del link de Z.ai.
                tipo: "share" para ``/s/<share_id>`` (link público de un chat
                    compartido) o "chat" para ``/c/<chat_id>`` (link de un
                    chat completo).

            Returns:
                El ``share_id`` o ``chat_id`` extraído (string), o ``None`` si
                no se pudo extraer.

            Example:
                >>> _extraer_id_de_link("https://chat.z.ai/s/abc-123-def", "share")
                'abc-123-def'
                >>> _extraer_id_de_link("https://chat.z.ai/c/xyz-789", "chat")
                'xyz-789'
                >>> _extraer_id_de_link("https://chat.z.ai/s/abc-123?ref=x", "share")
                'abc-123'
                >>> _extraer_id_de_link("https://example.com/otra", "share") is None
                True
            """
            import re as _re
            if not url or not isinstance(url, str):
                return None
            # tipo="share" → /s/<id>, tipo="chat" → /c/<id>
            prefijo = "s" if tipo == "share" else "c"
            # Patrón: /<prefijo>/<id> donde id puede contener letras, números, guiones.
            # Query strings y fragmentos se descartan.
            match = _re.search(rf"/{prefijo}/([A-Za-z0-9\-]+)", url)
            if not match:
                return None
            id_extraido = match.group(1)
            # Quitar sufijos de query string o fragmento (defensivo)
            id_extraido = id_extraido.split("?")[0].split("#")[0]
            return id_extraido if id_extraido else None

    @staticmethod
    def _detectar_estructura_contenido(content_bytes: bytes) -> str:
            """v6.14 F6 (criterio 22): Detecta si el contenido es cronológico o arbitrario.

            Examina los primeros 10000 bytes del contenido y busca marcadores
            cronológicos típicos de los exports de chat de Z.ai:

            - ``## Exchange \\d+ -- [`` (formato de intercambio cronológico).
            - ``### 📅 \\d{4}-\\d{2}-\\d{2}`` (cabecera con fecha).

            Args:
                content_bytes: Bytes del contenido a examinar.

            Returns:
                ``"cronologico"`` si encuentra algún marcador cronológico.
                ``"arbitrario"`` si no (documento sin estructura cronológica).

            Example:
                >>> _detectar_estructura_contenido(b"## Exchange 1 -- [2024-01-01]")
                'cronologico'
                >>> _detectar_estructura_contenido(b"### 📅 2024-01-01\\n...")
                'cronologico'
                >>> _detectar_estructura_contenido(b"Documento arbitrario sin marcadores.")
                'arbitrario'
            """
            import re as _re
            if not content_bytes:
                return "arbitrario"
            try:
                sample = content_bytes[:10000].decode("utf-8", errors="ignore")
            except Exception:
                return "arbitrario"
            # Patrón cronológico 1: ## Exchange N -- [
            patron_exchange = _re.compile(r"##\s+Exchange\s+\d+\s+--\s+\[", _re.IGNORECASE)
            # Patrón cronológico 2: ### 📅 YYYY-MM-DD
            patron_fecha = _re.compile(r"###\s+📅\s+\d{4}-\d{2}-\d{2}")
            if patron_exchange.search(sample) or patron_fecha.search(sample):
                return "cronologico"
            return "arbitrario"

    @staticmethod
    def _parsear_intercambios_desde_contenido(content_bytes: bytes) -> list:
            """v6.18 F1 (criterio 1): Parsea el contenido de un archivo externo en Messages.

            Acepta el formato de export de chat Z.ai::

                ## Exchange N -- [YYYY-MM-DD HH:MM]

                ### Director:
                <contenido del director>

                ### Agente:
                <contenido del agente>

                ---

            Devuelve una lista plana de ``Message`` con ``seq``, ``role``,
            ``timestamp`` (Unix UTC) y ``content`` poblados. ``timestamp``
            se parsea del ``[YYYY-MM-DD HH:MM]`` y se usa para que
            ``BlockPacker`` pueda ordenar los intercambios por timestamp
            descendente (criterio 2).

            Args:
                content_bytes: Bytes del contenido a parsear.

            Returns:
                Lista de ``Message`` (vacía si no hay intercambios válidos).
            """
            import re as _re
            from datetime import datetime as _dt, timezone as _tz

            if not content_bytes:
                return []
            try:
                text = content_bytes.decode("utf-8", errors="ignore")
            except Exception:
                return []

            # Patrón para detectar el inicio de cada intercambio.
            patron_exchange = _re.compile(
                r"^##\s+Exchange\s+(\d+)\s+--\s+\[([^\]]+)\]",
                _re.MULTILINE | _re.IGNORECASE,
            )

            matches = list(patron_exchange.finditer(text))
            if not matches:
                return []

            # Pre-importar para evitar repetir en cada iteración.
            from contexto_zai.models import Message, MessageRole

            messages: list = []
            seq = 0
            for i, m in enumerate(matches):
                start = m.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                block = text[start:end]

                # Parsear el timestamp del encabezado.
                ts_str = m.group(2).strip()
                timestamp = 0.0
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                    try:
                        dt = _dt.strptime(ts_str, fmt).replace(tzinfo=_tz.utc)
                        timestamp = dt.timestamp()
                        break
                    except ValueError:
                        continue
                # Fallback: usar el índice como timestamp creciente (garantiza
                # orden temporal ascendente incluso si el parseo falla).
                if timestamp == 0.0:
                    timestamp = float(i + 1)

                # Separar Director y Agente dentro del bloque.
                director_match = _re.search(
                    r"^###\s+Director:\s*\n(.*?)(?=^###\s+Agente:|\Z)",
                    block, _re.MULTILINE | _re.DOTALL,
                )
                agente_match = _re.search(
                    r"^###\s+Agente:\s*\n(.*?)(?=^###\s+Director:|\Z)",
                    block, _re.MULTILINE | _re.DOTALL,
                )

                director_content = director_match.group(1).strip() if director_match else ""
                agente_content = agente_match.group(1).strip() if agente_match else ""

                # Quitar separador "---" al final si existe.
                director_content = _re.sub(r"\n---\s*$", "", director_content).strip()
                agente_content = _re.sub(r"\n---\s*$", "", agente_content).strip()

                # Agregar mensaje del Director.
                if director_content:
                    seq += 1
                    messages.append(Message(
                        seq=seq,
                        role=MessageRole.USER,
                        timestamp=timestamp,
                        content=director_content,
                    ))

                # Agregar mensaje del Agente (timestamp +1s para mantener orden).
                if agente_content:
                    seq += 1
                    messages.append(Message(
                        seq=seq,
                        role=MessageRole.ASSISTANT,
                        timestamp=timestamp + 1.0,
                        content=agente_content,
                    ))

            return messages


class ProgressMonitor:
    """v6.12 F1: Monitorea el progreso del Worker Bun contando bloques completos.

    Un bloque esta completo cuando tiene RESUMEN al inicio Y los 3 archivos
    en _responses/ (nombre, decisiones, temas). ProgressMonitor cuenta
    bloques completos en intervalos y decide si hay progreso.

    Separada del arnés (OOP): la comprobacion de progreso es una cosa,
    el uso de los componentes del arnés (Worker Bun, proxy Z.ai, subagentes)
    es otra.
    """

    @staticmethod
    def contar_bloques_completos(workspace_dir: Path | str) -> int:
        """Cuenta cuantos bloques estan realmente completos.

        Un bloque esta completo cuando tiene:
        1. RESUMEN: al inicio del archivo bloque_NN.md
        2. _responses/bloque_NN_nombre.txt
        3. _responses/bloque_NN_decisiones.txt
        4. _responses/bloque_NN_temas.txt

        Args:
            workspace_dir: Directorio del workspace.

        Returns:
            Numero de bloques completos.
        """
        ws = Path(workspace_dir)
        if not ws.exists():
            return 0

        responses_dir = ws / "_responses"
        completos = 0

        for p in sorted(ws.glob("bloque_*.md")):
            block_id = p.stem  # "bloque_01"
            content = p.read_text(encoding="utf-8", errors="ignore")
            if not content.startswith("RESUMEN:"):
                continue
            # Verificar los 3 archivos de _responses/
            if not responses_dir.exists():
                continue
            if not (responses_dir / f"{block_id}_nombre.txt").exists():
                continue
            if not (responses_dir / f"{block_id}_decisiones.txt").exists():
                continue
            if not (responses_dir / f"{block_id}_temas.txt").exists():
                continue
            completos += 1

        return completos

    @staticmethod
    def contar_bloques_totales(workspace_dir: Path | str) -> int:
        """Cuenta el total de bloques en el workspace."""
        ws = Path(workspace_dir)
        if not ws.exists():
            return 0
        return len(list(ws.glob("bloque_*.md")))

    @staticmethod
    def esperar_y_verificar(
        workspace_dir: Path | str,
        intervalo_inicial: int = 20,
        max_intervalos: int = 10,
        crecimiento: float = 2.0,
    ) -> bool:
        """Espera al Worker Bun monitoreando progreso en intervalos progresivos.

        Comienza tras 20s iniciales. Despues comprueba cada intervalo
        (que crece progresivamente). Si hay progreso (mas bloques completos
        que antes), sigue esperando. Si no hay progreso en 2 intervalos
        seguidos, declara que el Worker Bun cayo.

        Args:
            workspace_dir: Directorio del workspace.
            intervalo_inicial: Segundos del primer intervalo (default 20).
            max_intervalos: Maximo numero de comprobaciones (default 10).
            crecimiento: Factor de crecimiento del intervalo (default 1.5).

        Returns:
            True si el Worker Bun completo todos los bloques.
            False si no progreso en 2 intervalos seguidos o se agotaron los intervalos.
        """
        import time as _time

        total_bloques = ProgressMonitor.contar_bloques_totales(workspace_dir)

        # Espera inicial
        logger.info(
            "v6.12 ProgressMonitor: esperando %ds iniciales (%d bloques totales)...",
            intervalo_inicial, total_bloques,
        )
        _time.sleep(intervalo_inicial)

        completos_anterior = ProgressMonitor.contar_bloques_completos(workspace_dir)
        sin_progreso_consecutivos = 0
        intervalo_actual = intervalo_inicial

        for i in range(max_intervalos):
            _time.sleep(intervalo_actual)
            completos_ahora = ProgressMonitor.contar_bloques_completos(workspace_dir)

            logger.info(
                "v6.12 ProgressMonitor: intervalo %d/%d - %d/%d bloques completos (intervalo=%ds)",
                i + 1, max_intervalos, completos_ahora, total_bloques, intervalo_actual,
            )

            if completos_ahora >= total_bloques:
                logger.info("v6.12 ProgressMonitor: todos los bloques completos.")
                return True

            if completos_ahora > completos_anterior:
                sin_progreso_consecutivos = 0
                logger.info(
                    "v6.12 ProgressMonitor: progreso detectado (%d -> %d).",
                    completos_anterior, completos_ahora,
                )
            else:
                sin_progreso_consecutivos += 1
                logger.warning(
                    "v6.12 ProgressMonitor: sin progreso (%d/%d consecutivos).",
                    sin_progreso_consecutivos, 2,
                )
                if sin_progreso_consecutivos >= 2:
                    logger.warning(
                        "v6.12 ProgressMonitor: Worker Bun sin progreso en 2 intervalos. Cayo."
                    )
                    return False

            completos_anterior = completos_ahora
            intervalo_actual = int(intervalo_actual * crecimiento)

        logger.warning("v6.12 ProgressMonitor: maximo de intervalos alcanzado.")
        return completos_ahora >= total_bloques


def _proxy_zai_disponible() -> bool:
    """v6.11 F5: Wrapper que delega a EnriquecimientoOrquestador._proxy_zai_disponible()."""
    return EnriquecimientoOrquestador._proxy_zai_disponible()


def _arrancar_worker_y_esperar(
    workspace_dir: Path | str,
    timeout: Optional[int] = None,
) -> bool:
    """v6.11 F5: Wrapper que delega a EnriquecimientoOrquestador._arrancar_worker_y_esperar()."""
    return EnriquecimientoOrquestador._arrancar_worker_y_esperar(workspace_dir=workspace_dir, timeout=timeout)


def _construir_pending_task_para_bloque(
    bloque,
    chat_label: str = "",
) -> "SubagentTask":
    """v6.11 F5: Wrapper que delega a EnriquecimientoOrquestador._construir_pending_task_para_bloque()."""
    return EnriquecimientoOrquestador._construir_pending_task_para_bloque(bloque=bloque, chat_label=chat_label)


def _descubrir_bloques_incompletos(workspace_dir: Path | str) -> list:
    """v6.17 F1: Wrapper que delega a
    ``EnriquecimientoOrquestador._descubrir_bloques_incompletos()``.

    Devuelve lista de dicts con ``block_id``, ``filename``, ``faltantes``
    y ``bloque`` (ThematicBlock). Verifica los 4 artefactos (RESUMEN +
    3 archivos _responses/).
    """
    return EnriquecimientoOrquestador._descubrir_bloques_incompletos(workspace_dir=workspace_dir)


def _enriquecer_bloques_con_fallback(
    blocks: list,
    workspace_dir: Path | str,
    chat_label: str = "",
) -> list:
    """v6.11 F5: Wrapper que delega a EnriquecimientoOrquestador._enriquecer_bloques_con_fallback()."""
    return EnriquecimientoOrquestador._enriquecer_bloques_con_fallback(blocks=blocks, workspace_dir=workspace_dir, chat_label=chat_label)


def _enriquecer_bloques_post_run(
    result: "OrchestratorResult",
    workspace_dir: Path | str,
    chat_label: str = "",
    is_chat_chronological: bool = True,
) -> "OrchestratorResult":
    """v6.11 F5: Wrapper que delega a EnriquecimientoOrquestador._enriquecer_bloques_post_run()."""
    return EnriquecimientoOrquestador._enriquecer_bloques_post_run(result=result, workspace_dir=workspace_dir, chat_label=chat_label, is_chat_chronological=is_chat_chronological)


def _bucle_d7_completitud(
    result: "OrchestratorResult",
    workspace_dir: Path | str,
) -> "OrchestratorResult":
    """v6.14 F3: Wrapper que delega a EnriquecimientoOrquestador._bucle_d7_completitud()."""
    return EnriquecimientoOrquestador._bucle_d7_completitud(result=result, workspace_dir=workspace_dir)


def _ejecutar_pending_tasks_obligatorias(
    result: "OrchestratorResult",
    workspace_dir: Path | str,
) -> "OrchestratorResult":
    """v6.11 F5 → v6.14 F3: Wrapper DEPRECATED que delega al bucle D7 (P17).

    Se mantiene por compatibilidad con código externo. Equivale a
    ``_bucle_d7_completitud()``.
    """
    return EnriquecimientoOrquestador._bucle_d7_completitud(result=result, workspace_dir=workspace_dir)


def _consolidar_decisiones_llm(workspace_dir: Path | str) -> int:
    """v6.11 F5: Wrapper que delega a EnriquecimientoOrquestador._consolidar_decisiones_llm()."""
    return EnriquecimientoOrquestador._consolidar_decisiones_llm(workspace_dir=workspace_dir)


def _regenerar_indice_tras_enriquecimiento(
    workspace_dir: Path | str,
) -> int:
    """v6.11 F5: Wrapper que delega a EnriquecimientoOrquestador._regenerar_indice_tras_enriquecimiento()."""
    return EnriquecimientoOrquestador._regenerar_indice_tras_enriquecimiento(workspace_dir=workspace_dir)


def _normalizar_bloques_externos(workspace_dir: Path | str) -> int:
    """v6.11 F5: Wrapper que delega a EnriquecimientoOrquestador._normalizar_bloques_externos()."""
    return EnriquecimientoOrquestador._normalizar_bloques_externos(workspace_dir=workspace_dir)


def _detectar_estructura_contenido(content_bytes: bytes) -> str:
    """v6.14 F6: Wrapper que delega a EnriquecimientoOrquestador._detectar_estructura_contenido()."""
    return EnriquecimientoOrquestador._detectar_estructura_contenido(content_bytes=content_bytes)



# ============================================================
# v6.15 F3+F4+F5 (criterios 29-32): CascadaAccesoLLM
# ============================================================

class CascadaAccesoLLM:
    """v6.15 F3-F5: Cascada de acceso al LLM por tarea individual.

    La cascada baja niveles 1→2→3. En cada transición de nivel hay un bucle
    D7 corto que hace polling de progreso (``_esperar_y_verificar_progreso``):
    intervalo fijo de ``CASCADA_INTERVALO_PROGRESO=5s``, umbral de
    ``CASCADA_UMBRAL_SIN_PROGRESO=3`` intervalos consecutivos sin progreso
    = 15s sin progreso = caída del nivel. Se eliminó el backoff exponencial
    de v6.13 C10 (criterio 32).

    Las ``pending_tasks`` se acumulan en ``self._pending_tasks`` durante
    todo P14 y se resuelven en P17 (``_bucle_d7_completitud``). El nivel 3
    (subagentes del agente CZAI) no las ejecuta directamente: las publica
    para que el agente CZAI las procese con Task tool, llame
    ``collect_responses()``, y el proceso re-verifique (criterio 31).

    Una instancia se crea una vez y se reutiliza por tarea (criterio 30).

    Flujo (criterios 29, 30, 31, 32) — v6.17 D3+D5: cascada secuencial,
    sin reintentos dentro de la cascada:

    1. Nivel 1 (Worker Bun) → si todas completas, return True.
    2. Nivel 2 (proxy Z.ai directo, 1 intento por tarea) → si todas
       completas, return True.
    3. Si Nivel 2 cayó (429 u otra causa) → cae directo a Nivel 3. NO se
       reintenta Nivel 1 dentro de la cascada (conciliado: "Si Nivel 1 cae
       por 429, no tiene sentido probar Nivel 2 (mismo proxy). Caer a
       Nivel 3.").
    4. Nivel 3 (subagentes del agente CZAI): publica pending_tasks en
       ``self._pending_tasks`` y devuelve False si hay pendientes.
       Los reintentos los hace el bucle D7 (F12) sobre pending_tasks, no
       la cascada. El D7 no baja niveles.

    Filtra tareas ya completas (idempotencia con
    ``EnriquecimientoOrquestador._bloque_esta_completo``) al inicio y tras
    cada nivel.
    """

    def __init__(self, workspace_dir: Path | str) -> None:
        """Inicializa la cascada con el workspace_dir.

        Args:
            workspace_dir: Directorio del workspace donde viven los bloques
                bloque_*.md y el directorio _responses/.
        """
        self._workspace_dir = workspace_dir
        # v6.15 F3 (criterio 31): las pending_tasks se acumulan aquí durante
        # todo P14 y se resuelven en P17. Se rellenan solo en Nivel 3.
        self._pending_tasks: list = []

    def procesar_tarea(self, tarea_o_lote) -> bool:
        """Ejecuta la cascada para una tarea individual o un lote.

        v6.17 F8 (criterio 8) — conciliado P19: NO se hacen pings al proxy.
        La llamada de enriquecimiento ES la verificación: si Nivel 2 recibe
        429 o error al llamar ``_enriquecer_con_proxy_zai()``, la tarea cae
        a Nivel 3. Si Nivel 1 cae por causa que NO es 429 → Nivel 2 SÍ se
        prueba.

        Filtra tareas ya completas (idempotencia con
        ``_bloque_esta_completo``) al inicio y tras cada nivel.

        Args:
            tarea_o_lote: ThematicBlock individual o lista de ThematicBlock.

        Returns:
            True si todas las tareas quedaron completas tras la cascada.
            False si alguna tarea quedó pendiente (publicada en
            ``self._pending_tasks`` para que el agente CZAI la procese vía
            Nivel 3 y P17).
        """
        # Normalizar a lista.
        if isinstance(tarea_o_lote, list):
            tareas_originales = list(tarea_o_lote)
        else:
            tareas_originales = [tarea_o_lote]

        # Idempotencia: filtrar tareas ya completas.
        tareas = [
            t for t in tareas_originales
            if not EnriquecimientoOrquestador._bloque_esta_completo(
                t, workspace_dir=self._workspace_dir
            )
        ]
        if not tareas:
            logger.info(
                "CascadaAccesoLLM: todas las tareas ya completas (idempotencia)."
            )
            # v6.16 F2: aun sin trabajo que hacer, refrescar el checkpoint para
            # que _cascada_checkpoint.json refleje el estado fisico actual.
            self._escribir_checkpoint()
            # v6.16 F8: post-bloque para todas las tareas (ya completas).
            for bloque in tareas_originales:
                EnriquecimientoOrquestador._post_bloque(
                    self._workspace_dir, bloque, True, self
                )
            return True

        # Nivel 1: Worker Bun.
        if self._nivel1_worker_bun(tareas):
            logger.info(
                "CascadaAccesoLLM: Nivel 1 (Worker Bun) completó %d tarea(s).",
                len(tareas),
            )
            # v6.16 F2 (criterio 35): checkpoint tras procesar el bloque.
            self._escribir_checkpoint()
            # v6.16 F8: post-bloque para todas las tareas (N1 completó).
            for bloque in tareas_originales:
                EnriquecimientoOrquestador._post_bloque(
                    self._workspace_dir, bloque, True, self
                )
            return True

        # Filtrar completas tras Nivel 1.
        tareas_restantes = [
            t for t in tareas
            if not EnriquecimientoOrquestador._bloque_esta_completo(
                t, workspace_dir=self._workspace_dir
            )
        ]
        if not tareas_restantes:
            # v6.16 F2 (criterio 35): checkpoint.
            self._escribir_checkpoint()
            # v6.16 F8: post-bloque para todas las tareas (completas tras N1).
            for bloque in tareas_originales:
                EnriquecimientoOrquestador._post_bloque(
                    self._workspace_dir, bloque, True, self
                )
            return True

        # Nivel 2: proxy Z.ai directo. Se prueba SIEMPRE que N1 cayó
        # (sea por 429 o por otra causa). Si N2 recibe 429 o error, la
        # verificación la hace la propia llamada de enriquecimiento
        # (conciliado P19: no hay ping previo).
        nivel2_ok = self._nivel2_proxy_zai(tareas_restantes)
        if nivel2_ok:
            logger.info(
                "CascadaAccesoLLM: Nivel 2 (proxy Z.ai) completó %d tarea(s).",
                len(tareas_restantes),
            )
            # v6.16 F2 (criterio 35): checkpoint.
            self._escribir_checkpoint()
            # v6.16 F8: post-bloque para todas las tareas (N2 completó).
            for bloque in tareas_originales:
                EnriquecimientoOrquestador._post_bloque(
                    self._workspace_dir, bloque, True, self
                )
            return True

        # Nivel 3: subagentes del agente CZAI.
        # v6.17 D3: si Nivel 2 cayó (por 429 o por otra causa), cae directo a
        # Nivel 3 — no se reintenta Nivel 1 (conciliado: 'Si Nivel 1 cae por
        # 429, no tiene sentido probar Nivel 2 (mismo proxy). Caer a Nivel 3').
        # La cascada queda secuencial: N1 → N2 → N3 sin reintentos dentro de
        # la cascada. Los reintentos los hace el D7 sobre pending_tasks.
        ok = self._nivel3_subagentes(tareas_restantes)
        # v6.16 F2 (criterio 35): checkpoint tras procesar el bloque (haya
        # ido o no a Nivel 3 — el estado fisico pudo cambiar).
        self._escribir_checkpoint()
        # v6.16 F8: post-bloque para todas las tareas originales.
        # ``resultado`` por bloque = si está completo físicamente tras la cascada.
        for bloque in tareas_originales:
            bloque_ok = EnriquecimientoOrquestador._bloque_esta_completo(
                bloque, workspace_dir=self._workspace_dir
            )
            EnriquecimientoOrquestador._post_bloque(
                self._workspace_dir, bloque, bloque_ok, self
            )
        return ok

    def _escribir_checkpoint(self) -> None:
        """v6.16 F2 (criterios 35, 36): escribe ``_cascada_checkpoint.json``.

        Persiste el estado de la cascada a disco tras procesar cada bloque.
        Contiene la lista de bloques completos, pendientes y un timestamp.
        Al relanzar la cascada (``_enriquecer_bloques_con_fallback``), se lee
        el checkpoint y se saltan los bloques ya completos (criterio 36).

        Es stateless respecto a ``self._todos_los_bloques``: descubre los
        bloques físicos del workspace con ``AuditorWorkspace`` en cada
        invocación — no necesita que se le pase el lote por parámetro.
        """
        import json as _json
        import time as _time
        ws = Path(self._workspace_dir)
        try:
            audit = AuditorWorkspace.auditar_bloques(self._workspace_dir)
            completos = list(audit.get("completos", []))
            completos_set = set(completos)
            # Pendientes: todos los bloque_*.md físicos menos los completos.
            pendientes = []
            try:
                for p in sorted(ws.glob("bloque_*.md")):
                    if p.stem not in completos_set:
                        pendientes.append(p.name)
            except Exception as e:
                logger.warning(
                    "CascadaAccesoLLM._escribir_checkpoint: glob falló: %s", e
                )
            checkpoint = {
                "completados": completos,
                "pendientes": pendientes,
                "timestamp": _time.time(),
            }
            checkpoint_path = ws / "_cascada_checkpoint.json"
            checkpoint_path.write_text(
                _json.dumps(checkpoint, indent=2), encoding="utf-8"
            )
            logger.info(
                "v6.16 F2: checkpoint escrito (%d completos, %d pendientes)",
                len(completos), len(pendientes),
            )
        except Exception as e:
            logger.warning(
                "v6.16 F2: _escribir_checkpoint falló: %s", e
            )

    def _nivel1_worker_bun(self, tareas: list) -> bool:
        """v6.16 F5 (criterio 39): arranca Worker Bun y monitorea con ``_esperar_y_verificar_progreso()``.

        Reemplaza la llamada a ``EnriquecimientoOrquestador._arrancar_worker_y_esperar()``
        (que usa ``ProgressMonitor.esperar_y_verificar()`` con 20s+40s=60s) por:

        1. Arrancar el Worker Bun (subprocess, igual que antes).
        2. Usar ``self._esperar_y_verificar_progreso()`` (5s×3=15s) para monitorear.
        3. Si hay progreso → seguir esperando.
        4. Si 3 intervalos sin progreso → return False (caída).

        Args:
            tareas: Lista de ThematicBlock pendientes.

        Returns:
            True si todas las tareas quedaron completas. False si el nivel
            cayó (sin progreso en 15s) o si hay tareas aún incompletas.
        """
        if not tareas:
            return True
        # v6.16 F5 (criterio 39): arrancar el Worker Bun directamente aquí con
        # subprocess (igual que ``_arrancar_worker_y_esperar``), sin llamar a
        # ``ProgressMonitor.esperar_y_verificar()`` (que tarda 60s). El
        # monitoreo de progreso lo hace el bucle de abajo con
        # ``_esperar_y_verificar_progreso()`` (5s × 3 = 15s por ronda).
        import subprocess as _subprocess
        import socket as _socket
        import os as _os_mod
        try:
            from contexto_zai.config import WORKER_BUN_DIR
        except ImportError:
            logger.warning(
                "v6.16 F5: no se pudo importar WORKER_BUN_DIR, fallback desactivado"
            )
            return False
        if not Path(WORKER_BUN_DIR).exists():
            logger.warning("v6.16 F5: WORKER_BUN_DIR no existe: %s", WORKER_BUN_DIR)
            return False

        # v6.8.2 F2: verificar si el puerto 8090 ya está en uso.
        WORKER_BUN_PORT = 8090
        puerto_en_uso = False
        try:
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            sock.settimeout(1)
            result_sock = sock.connect_ex(("localhost", WORKER_BUN_PORT))
            sock.close()
            puerto_en_uso = (result_sock == 0)
        except Exception:
            puerto_en_uso = False

        proc = None
        if not puerto_en_uso:
            env = {**_os_mod.environ, "CZAI_WORKSPACE_DIR": str(self._workspace_dir)}
            try:
                proc = _subprocess.Popen(
                    ["bun", "run", "cli.ts", "run"],
                    cwd=WORKER_BUN_DIR,
                    env=env,
                    stdout=_subprocess.PIPE,
                    stderr=_subprocess.PIPE,
                    text=True,
                )
                logger.info(
                    "v6.16 F5: Worker Bun arrancado en background (PID %d). "
                    "Monitoreando con _esperar_y_verificar_progreso (5s×3=15s).",
                    proc.pid,
                )
            except FileNotFoundError:
                logger.warning("v6.16 F5: 'bun' no está en PATH. Fallback desactivado.")
                return False
            except Exception as e:
                logger.warning("v6.16 F5: Error arrancando Worker Bun: %s", e)
                return False
        else:
            logger.info(
                "v6.16 F5: puerto %d en uso — Worker Bun ya corriendo, "
                "monitoreando progreso con _esperar_y_verificar_progreso.",
                WORKER_BUN_PORT,
            )

        # Bucle de monitoreo: mientras haya progreso, seguir esperando.
        # Si una ronda completa (3 intervalos = 15s) no detecta progreso →
        # caída del nivel, return False.
        MAX_RONDAS = 12  # 12 rondas × 15s = 180s como techo de seguridad.
        for ronda in range(MAX_RONDAS):
            progreso = self._esperar_y_verificar_progreso()
            # ¿Todas las tareas completas tras la ronda?
            completas = [
                t for t in tareas
                if EnriquecimientoOrquestador._bloque_esta_completo(
                    t, workspace_dir=self._workspace_dir
                )
            ]
            if len(completas) == len(tareas):
                logger.info(
                    "v6.16 F5: Nivel 1 completó %d tarea(s) en ronda %d.",
                    len(tareas), ronda + 1,
                )
                return True
            if not progreso:
                # 3 intervalos sin progreso → caída del nivel.
                logger.info(
                    "v6.16 F5: Nivel 1 caído tras ronda %d (sin progreso 15s).",
                    ronda + 1,
                )
                return False
            # Hay progreso pero faltan tareas → otra ronda.
            logger.info(
                "v6.16 F5: progreso detectado en ronda %d, continuando.",
                ronda + 1,
            )
        # Techo de seguridad: tras MAX_RONDAS sin completar todo, cae.
        logger.warning(
            "v6.16 F5: Nivel 1 agotó %d rondas sin completar todas las tareas.",
            MAX_RONDAS,
        )
        return False

    def _nivel2_proxy_zai(self, tareas: list) -> bool:
        """v6.16 F6 (criterio 40): procesa un lote de bloques en paralelo con ``ThreadPoolExecutor``.

        Reemplaza el bucle secuencial (1 bloque a la vez) por una ejecución
        paralela de hasta 5 llamadas HTTP simultáneas al proxy Z.ai. Cada
        thread ejecuta ``_procesar_bloque_nivel2(bloque)`` que hace 1
        intento de ``_enriquecer_con_proxy_zai()``. Si recibe 429, espera
        progreso (15s) y reintenta 1 vez. Si no hay progreso → return False
        (caída a Nivel 3 vía ``procesar_tarea``).

        Los bloques que fallan (por cualquier motivo) NO se completan aquí;
        ``procesar_tarea`` decide si reintenta Nivel 1 (429) o cae a Nivel 3.

        Args:
            tareas: Lista de ThematicBlock pendientes.

        Returns:
            True si todas las tareas quedaron completas. False si alguna
            tarea falló (429 sostenido, W3 fallida tras MAX_ITER_W3, etc.).
        """
        if not tareas:
            return True
        # Reset del flag 429 antes de empezar (lo gestiona esta función,
        # no _enriquecer_con_proxy_zai que solo lo setea).
        EnriquecimientoOrquestador._ultimo_error_proxy_429 = False

        # v6.16 F6 (criterio 40): paralelismo con ThreadPoolExecutor(5).
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Idempotencia: filtrar tareas ya completas (no lanzar threads
        # innecesarios sobre bloques que otra ronda ya completó).
        pendientes = [
            t for t in tareas
            if not EnriquecimientoOrquestador._bloque_esta_completo(
                t, workspace_dir=self._workspace_dir
            )
        ]
        if not pendientes:
            return True

        max_workers = min(5, len(pendientes))
        resultados: dict = {}  # bloque -> (ok, was_429)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._procesar_bloque_nivel2, b): b
                for b in pendientes
            }
            for future in as_completed(futures):
                bloque = futures[future]
                try:
                    ok, was_429 = future.result()
                except Exception as e:
                    logger.warning(
                        "CascadaAccesoLLM._nivel2_proxy_zai: excepción %s para %s",
                        e, getattr(bloque, "filename", str(bloque)),
                    )
                    ok, was_429 = False, False
                resultados[bloque.filename] = (ok, was_429)
                # Si el bloque se completó, refrescar checkpoint (criterio 35).
                if ok:
                    self._escribir_checkpoint()
                # Si el flag de 429 quedó activo en algún thread, propagarlo
                # al flag de clase para que ``procesar_tarea`` active el
                # retry-Nivel-1 (criterio 32). Es conservador: si ALGÚN
                # bloque vio 429, el lote cae por 429.
                if was_429:
                    EnriquecimientoOrquestador._ultimo_error_proxy_429 = True

        # Verificar que todas las tareas quedaron completas.
        completas = [
            t for t in tareas
            if EnriquecimientoOrquestador._bloque_esta_completo(
                t, workspace_dir=self._workspace_dir
            )
        ]
        return len(completas) == len(tareas)

    def _procesar_bloque_nivel2(self, bloque) -> tuple:
        """v6.16 F6 (criterio 40): procesa 1 bloque en Nivel 2 (worker del ThreadPool).

        Llama ``_enriquecer_con_proxy_zai()`` (1 intento). Si 429 → espera
        progreso (``_esperar_y_verificar_progreso()``). Si hay progreso →
        reintenta. Si no → return (False, True) (429 sin progreso, caída).

        Args:
            bloque: ThematicBlock a enriquecer.

        Returns:
            Tupla ``(ok, was_429)``:
            - ``ok=True`` si el bloque quedó completo.
            - ``ok=False, was_429=True`` si cayó por 429 sostenido.
            - ``ok=False, was_429=False`` si cayó por otra razón (W3, JSON,
              HTTP != 429, etc.) — caída directa a Nivel 3.

        Nota sobre thread-safety: ``_ultimo_error_proxy_429`` es un atributo
        de clase compartido entre threads. Cada worker lo resetea antes de
        su llamada y captura su valor inmediatamente después. La race window
        es estrecha y el comportamiento conservador (propagar 429 al lote
        si ALGÚN thread lo vio) previene pérdida de señales 429.
        """
        # Idempotencia: si otra ronda ya completó este bloque, ok.
        if EnriquecimientoOrquestador._bloque_esta_completo(
            bloque, workspace_dir=self._workspace_dir
        ):
            return (True, False)
        # Reset del flag 429 antes de mi llamada (mi sección crítica).
        EnriquecimientoOrquestador._ultimo_error_proxy_429 = False
        try:
            ok = EnriquecimientoOrquestador._enriquecer_con_proxy_zai(
                bloque, workspace_dir=self._workspace_dir
            )
        except Exception as e:
            logger.warning(
                "CascadaAccesoLLM._procesar_bloque_nivel2: excepción %s para %s",
                e, getattr(bloque, "filename", str(bloque)),
            )
            return (False, False)
        # Capturar el flag inmediatamente (mi sección crítica).
        was_429 = bool(EnriquecimientoOrquestador._ultimo_error_proxy_429)

        if ok:
            return (True, False)
        if not was_429:
            # Falló por otra razón (W3, JSON parse, HTTP != 429, etc.) → Nivel 3.
            logger.info(
                "CascadaAccesoLLM._procesar_bloque_nivel2: %s falló por razón "
                "distinta a 429, caída a Nivel 3.",
                getattr(bloque, "filename", str(bloque)),
            )
            return (False, False)
        # 429: polling de progreso (15s).
        progreso = self._esperar_y_verificar_progreso()
        if not progreso:
            logger.info(
                "CascadaAccesoLLM._procesar_bloque_nivel2: sin progreso tras 429 "
                "para %s, return (False, True) (caída a Nivel 3).",
                getattr(bloque, "filename", str(bloque)),
            )
            return (False, True)
        logger.info(
            "CascadaAccesoLLM._procesar_bloque_nivel2: progreso detectado tras "
            "429, reintentando %s.",
            getattr(bloque, "filename", str(bloque)),
        )
        # Reset del flag antes de reintentar.
        EnriquecimientoOrquestador._ultimo_error_proxy_429 = False
        try:
            ok = EnriquecimientoOrquestador._enriquecer_con_proxy_zai(
                bloque, workspace_dir=self._workspace_dir
            )
        except Exception as e:
            logger.warning(
                "CascadaAccesoLLM._procesar_bloque_nivel2 (retry): %s", e
            )
            return (False, True)
        was_429_retry = bool(EnriquecimientoOrquestador._ultimo_error_proxy_429)
        return (bool(ok), was_429_retry)

    def _nivel3_subagentes(self, tareas: list) -> bool:
        """Nivel 3: subagentes del agente CZAI — v6.17 F2 + D1.

        El proceso Python NO puede invocar el Task tool directamente. Pero
        puede publicar pending_tasks y devolver el control al agente CZAI
        para que las ejecute. Ese es el "mecanismo que el proceso tenga
        para invocar subagentes" (plan F2).

        Para cada bloque en Nivel 3:

        1. Construir el prompt con ``PROMPT_FUSIONADO_W1W2W3`` (el mismo
           prompt fusionado W1+W2+W3 que usa Nivel 2 al llamar al proxy).
        2. Publicar la pending_task en ``_pending_tasks.json`` (con el
           prompt construido) vía ``_persistir_pending_task_en_disco``.
        3. Devolver False (indicando que el agente CZAI debe procesar las
           pending_tasks).

        Nivel 3 no llama al proxy: si lo hiciera, sería Nivel 2. Nivel 3
        publica pending_tasks para que el agente CZAI las resuelva con
        Task tool.

        Args:
            tareas: Lista de ThematicBlock pendientes que Ni Nivel 1 ni
                Nivel 2 pudieron completar.

        Returns:
            True si no hay tareas que procesar. False si hay pending_tasks
            publicadas en ``self._pending_tasks`` para que el agente CZAI
            las procese con Task tool (y el bucle D7 las reintente con
            feedback hasta ``MAX_ITER_D7=5``).
        """
        if not tareas:
            return True

        from contexto_zai.models import SubagentTask

        ws = Path(self._workspace_dir)

        # v6.17 F2 + D1: Nivel 3 publica pending_tasks con el prompt
        # construido con PROMPT_FUSIONADO_W1W2W3. El agente CZAI las procesa
        # con Task tool (mecanismo que el proceso tiene para invocar
        # subagentes). Nivel 3 no llama al proxy directamente.
        for tarea in tareas:
            filename = getattr(tarea, "filename", "")
            block_id = filename.replace(".md", "")
            bloque_path = ws / filename

            # 1. Construir el prompt con PROMPT_FUSIONADO_W1W2W3.
            #    Leer el bloque del disco para incluir su contenido en el prompt.
            bloque_content = ""
            try:
                if bloque_path.exists():
                    bloque_content = bloque_path.read_text(
                        encoding="utf-8", errors="ignore"
                    )
                    max_chars = 50000
                    if len(bloque_content) > max_chars:
                        bloque_content = (
                            bloque_content[:max_chars]
                            + "\n...(contenido truncado)..."
                        )
            except Exception as e:
                logger.warning(
                    "v6.17 F2: Nivel 3 no pudo leer bloque %s: %s", filename, e,
                )

            prompt = PROMPT_FUSIONADO_W1W2W3.format(bloque_content=bloque_content)

            # 2. Publicar la pending_task en _pending_tasks.json (con el
            #    prompt construido).
            task = SubagentTask(
                task_id=f"enriquecer_{block_id}",
                purpose=f"v6.17.nivel3.{filename}",
                prompt=prompt,
                context={"filename": filename, "chat_label": "cascada_n3"},
            )
            self._pending_tasks.append(task)
            # v6.17 F11: persistencia vía _persistir_pending_task_en_disco
            # (la misma función que usa _post_bloque y el bucle D7).
            EnriquecimientoOrquestador._persistir_pending_task_en_disco(
                workspace_dir=self._workspace_dir, task=task
            )
            logger.info(
                "v6.17 F2: Nivel 3 publicó pending_task para %s con "
                "PROMPT_FUSIONADO_W1W2W3 (para que el agente CZAI la "
                "procese con Task tool).",
                filename,
            )

        # 3. Devolver False (el agente CZAI debe procesar las pending_tasks).
        return False

    def _esperar_y_verificar_progreso(self) -> bool:
        """Polling fijo de ``CASCADA_INTERVALO_PROGRESO``s × ``CASCADA_UMBRAL_SIN_PROGRESO``.

        Usa ``AuditorWorkspace.auditar_completitud()`` para contar completados.
        Si en 3 intervalos consecutivos (5s cada uno = 15s total) no hay
        nuevo bloque completo → devuelve False (nivel caído). Si hay
        progreso en algún intervalo → devuelve True inmediatamente.

        Returns:
            True si se detectó progreso (al menos un bloque nuevo completo).
            False si tras 15s no hay progreso (caída del nivel).
        """
        from contexto_zai.config import (
            CASCADA_INTERVALO_PROGRESO as _INTERVALO,
            CASCADA_UMBRAL_SIN_PROGRESO as _UMBRAL,
        )
        try:
            audit = AuditorWorkspace.auditar_completitud(self._workspace_dir)
        except Exception as e:
            logger.warning(
                "CascadaAccesoLLM._esperar_y_verificar_progreso: audit inicial falló: %s",
                e,
            )
            return False
        prev_completos = set(audit.get("completos", []))
        for i in range(_UMBRAL):
            time.sleep(_INTERVALO)
            try:
                audit = AuditorWorkspace.auditar_completitud(self._workspace_dir)
            except Exception as e:
                logger.warning(
                    "CascadaAccesoLLM._esperar_y_verificar_progreso: audit falló: %s",
                    e,
                )
                return False
            curr_completos = set(audit.get("completos", []))
            nuevos = curr_completos - prev_completos
            if nuevos:
                logger.info(
                    "CascadaAccesoLLM: progreso detectado (+%d completos): %s",
                    len(nuevos), sorted(nuevos),
                )
                return True
            prev_completos = curr_completos
        logger.info(
            "CascadaAccesoLLM: sin progreso tras %d×%ds = %ds. Caída del nivel.",
            _UMBRAL, _INTERVALO, _UMBRAL * _INTERVALO,
        )
        return False

    def get_pending_tasks(self) -> list:
        """Devuelve las ``pending_tasks`` acumuladas durante P14.

        Se rellenan en Nivel 3 (subagentes). El llamador (típicamente
        ``_enriquecer_bloques_con_fallback`` o ``_enriquecer_bloques_post_run``)
        las propaga al ``OrchestratorResult.pending_tasks`` para que el
        agente CZAI las ejecute con Task tool.

        Returns:
            Lista de SubagentTask pendientes (vacía si todas las tareas
            se completaron en Nivel 1 o Nivel 2).
        """
        return self._pending_tasks



# ============================================================
# v6.13 F3: AuditorWorkspace — clase reutilizable de auditoría
# ============================================================

import time as _time
import json as _json_module

class AuditorWorkspace:
    """v6.13 F3: Clase reutilizable para auditar el workspace.
    
    Se ejecuta en 2 momentos:
    1. Al inicio (antes de decidir recovery vs incremental).
    2. Al final (después de procesar, para validar completitud).
    """
    
    @staticmethod
    def auditar_bloques(workspace_dir: Path | str) -> dict:
        """Recorre bloque_*.md y verifica RESUMEN + 3 archivos _responses/.
        
        Returns:
            dict con 'completos' (lista) e 'incompletos' (lista).
        """
        ws = Path(workspace_dir)
        if not ws.exists():
            return {"completos": [], "incompletos": []}
        
        responses_dir = ws / "_responses"
        completos = []
        incompletos = []
        
        for p in sorted(ws.glob("bloque_*.md")):
            block_id = p.stem
            content = p.read_text(encoding="utf-8", errors="ignore")
            
            tiene_resumen = content.startswith("RESUMEN:")
            tiene_nombre = (responses_dir / f"{block_id}_nombre.txt").exists()
            tiene_decisiones = (responses_dir / f"{block_id}_decisiones.txt").exists()
            tiene_temas = (responses_dir / f"{block_id}_temas.txt").exists()
            
            if tiene_resumen and tiene_nombre and tiene_decisiones and tiene_temas:
                completos.append(block_id)
            else:
                faltantes = []
                if not tiene_resumen: faltantes.append("RESUMEN")
                if not tiene_nombre: faltantes.append("nombre.txt")
                if not tiene_decisiones: faltantes.append("decisiones.txt")
                if not tiene_temas: faltantes.append("temas.txt")
                incompletos.append({"block_id": block_id, "faltantes": faltantes})
        
        logger.info("AuditorWorkspace: %d completos, %d incompletos", len(completos), len(incompletos))
        return {"completos": completos, "incompletos": incompletos}
    
    @staticmethod
    def auditar_metadata(workspace_dir: Path | str) -> bool:
        """Verifica que _metadata.json coincide con los bloques físicos.
        
        Returns:
            True si la metadata es válida, False si no.
        """
        ws = Path(workspace_dir)
        meta_path = ws / "_metadata.json"
        if not meta_path.exists():
            return False
        
        try:
            import json as _json
            metadata = _json.loads(meta_path.read_text(encoding="utf-8"))
            tema_a_archivo = metadata.get("tema_a_archivo", {})
            ultimo_timestamp = metadata.get("ultimo_timestamp")
            
            if not tema_a_archivo:
                return False
            if ultimo_timestamp is None:
                return False
            
            # Verificar que los archivos referenciados existen
            bloques_fisicos = set(p.name for p in ws.glob("bloque_*.md"))
            for tema, archivo in tema_a_archivo.items():
                if isinstance(archivo, list):
                    for a in archivo:
                        if a not in bloques_fisicos and not (ws / a).exists():
                            logger.info("AuditorWorkspace: metadata referencia %s que no existe", a)
                            return False
                elif isinstance(archivo, str):
                    if archivo not in bloques_fisicos and not (ws / archivo).exists():
                        logger.info("AuditorWorkspace: metadata referencia %s que no existe", archivo)
                        return False
            
            return True
        except Exception as e:
            logger.warning("AuditorWorkspace: error leyendo metadata: %s", e)
            return False
    
    @staticmethod
    def auditar_completitud(workspace_dir: Path | str) -> dict:
        """Auditoría integral: bloques + enriquecimiento + metadata.
        
        Returns:
            dict con:
            - 'completos': lista de block_id completos.
            - 'incompletos': lista de {block_id, faltantes}.
            - 'metadata_valida': bool.
        """
        bloques = AuditorWorkspace.auditar_bloques(workspace_dir)
        metadata_valida = AuditorWorkspace.auditar_metadata(workspace_dir)
        
        return {
            "completos": bloques["completos"],
            "incompletos": bloques["incompletos"],
            "metadata_valida": metadata_valida,
        }
    
    @staticmethod
    def sincronizar_registro(workspace_dir: Path | str) -> None:
        """Sincroniza _processed_blocks.json con el estado físico.
        
        Antes de devolver el OrchestratorResult, recorre todos los bloques
        y actualiza el registro con el estado físico real.
        """
        ws = Path(workspace_dir)
        registro_path = ws / "_processed_blocks.json"
        
        audit = AuditorWorkspace.auditar_bloques(workspace_dir)
        completos_set = set(audit["completos"])
        
        registro = {"blocks": []}
        for p in sorted(ws.glob("bloque_*.md")):
            block_id = p.stem
            if block_id in completos_set:
                registro["blocks"].append({
                    "block_id": block_id,
                    "status": "completed",
                    "processed_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
                    "error": None,
                })
            else:
                registro["blocks"].append({
                    "block_id": block_id,
                    "status": "pending",
                    "processed_at": None,
                    "error": "incomplete",
                })
        
        registro_path.write_text(_json_module.dumps(registro, indent=2), encoding="utf-8")
        logger.info("AuditorWorkspace: _processed_blocks.json sincronizado (%d completed, %d pending)",
                    len(completos_set), len(registro["blocks"]) - len(completos_set))


# ============================================================
# v6.13 F5: Prompt fusionado W1+W2+W3 en 1 sola llamada
# ============================================================

PROMPT_FUSIONADO_W1W2W3 = """Lee el siguiente bloque de intercambios entre un Director y un agente.

Genera una respuesta JSON con las siguientes claves:

1. "resumen": Un párrafo de 600-900 caracteres, exactamente 4 oraciones, separadas por punto y seguido. Sin secciones, sin listas, sin negritas, sin etiquetas. Estructura: (1) tema central, (2) decisiones principales, (3) temas específicos, (4) tipo de actividad.

2. "nombre": Un identificador en snake_case que resuma de qué trata el bloque (ej: "worker_bun_proxy_zai").

3. "decisiones": Una lista (array) de strings, cada uno con el formato "DECISION: descripción | ALCANCE: contexto". Si no hay decisiones reales, devuelve una lista vacía [].

4. "temas": Una lista (array) de strings con los temas abordados (2-5 keywords).

5. "verificacion": Un objeto con:
   - "completo": true si el bloque tiene contenido suficiente y el resumen cumple el rango de 600-900 chars. false si no.
   - "observaciones": texto explicando por qué está completo o no. Si el bloque tiene poco contenido (<2000 chars), indicar "bloque con contenido limitado, resumen proporcional". Si el resumen no cumple el rango pero el bloque tiene >2000 chars, indicar "resumen mejorable".

PROHIBICIONES:
- No uses etiquetas como "Tema central:", "Decisiones:", etc. en el resumen.
- No hagas listas con guiones ni numeración en el resumen.
- No incluyas código ni rutas de archivos en el resumen.
- El resumen debe ser texto natural en un solo párrafo.

Responde SOLO con el JSON, sin texto adicional.

Bloque:
{bloque_content}
"""



if __name__ == "__main__":
    # Compatibilidad Windows: reconfigurar stdout/stderr a UTF-8
    import io as _io, sys as _sys
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
        if hasattr(_sys.stderr, 'buffer') and 'utf' not in (getattr(_sys.stderr, 'encoding', '') or '').lower():
            _sys.stderr = _io.TextIOWrapper(_sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass
    # -- Validación interna de pipeline.py --
    print("=== Validacion de pipeline.py ===\n")

    import tempfile
    from contexto_zai.models import DetectionTrigger

    # Test 1: status() en directorio vacío
    with tempfile.TemporaryDirectory() as tmpdir:
        st = status(chat_id="abc-123", workspace_dir=tmpdir)
        assert st["metadata_exists"] is False
        assert st["chat_id"] == ""
        print(f"[OK] status() en directorio vacío: metadata_exists=False")

    # Test 2: run() con parámetros inválidos (sin JWT) -> error
    # v6.16 F1 fix: NO invocar run() con JWT inválido — la llamada HTTP a Z.ai
    # puede colgarse en Windows (sin signal.alarm). En su lugar, verificar
    # que run() existe, es callable, y tiene la firma correcta. El test de
    # JWT inválido se hace en el sandbox Linux (con timeout de red).
    import logging as _logging
    _old_level = _logging.getLogger("contexto_zai").level
    _logging.getLogger("contexto_zai").setLevel(_logging.CRITICAL)
    try:
        assert callable(run), "run() debe ser callable"
        import inspect as _inspect
        _sig = _inspect.signature(run)
        _expected = {"chat_id", "jwt", "trigger", "reason", "chat_label", "workspace_dir", "download_dir", "share_id"}
        _actual = set(_sig.parameters.keys())
        assert _expected == _actual, f"run() params incorrectos: {_expected - _actual}"
        print(f"[OK] run() con JWT inválido: firma verificada (no se invoca para evitar cuelgue en Windows)")
    finally:
        _logging.getLogger("contexto_zai").setLevel(_old_level)

    # Test 3: signature de run()
    import inspect
    sig = inspect.signature(run)
    expected_params = {"chat_id", "jwt", "trigger", "reason", "chat_label", "workspace_dir", "download_dir", "share_id"}
    actual_params = set(sig.parameters.keys())
    assert expected_params == actual_params, f"Faltan params: {expected_params - actual_params}"
    print(f"[OK] run() signature: {len(actual_params)} parámetros correctos")

    # Test 4: trigger por defecto es EXPLICITO
    assert sig.parameters["trigger"].default == DetectionTrigger.EXPLICITO
    print(f"[OK] Trigger por defecto: EXPLICITO")

    # Test 5 (v3.4): export_context disponible
    assert callable(export_context), "export_context debe ser callable"
    sig_export = inspect.signature(export_context)
    assert {"chat_id", "workspace_dir", "output_dir"} <= set(sig_export.parameters.keys())
    print(f"[OK] export_context(): disponible con {len(sig_export.parameters)} params")

    # Test 6 (v3.4): import_context disponible
    assert callable(import_context), "import_context debe ser callable"
    sig_import = inspect.signature(import_context)
    assert {"zip_path", "workspace_dir"} <= set(sig_import.parameters.keys())
    print(f"[OK] import_context(): disponible con {len(sig_import.parameters)} params")

    # Test 7 (v3.4): find_context_packages disponible
    assert callable(find_context_packages), "find_context_packages debe ser callable"
    print(f"[OK] find_context_packages(): disponible")

    # Test 8 (v3.4): export -> import ciclo completo
    import json as _json
    from contexto_zai.models import RecoveryMetadata
    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear contexto simulado
        ctx_dir = Path(tmpdir) / "contexto_recuperacion"
        ctx_dir.mkdir()
        (ctx_dir / "00_estado_actual.md").write_text("# Estado\n\nTest.", encoding="utf-8")
        (ctx_dir / "01_indice_recuperacion.md").write_text("# Indice\n", encoding="utf-8")
        meta = RecoveryMetadata(chat_id="test-789", share_id="share-789", total_exchanges=5)
        (ctx_dir / "_metadata.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")

        # Exportar
        zip_path = export_context(
            chat_id="test-789",
            workspace_dir=ctx_dir,
            output_dir=Path(tmpdir),
        )
        assert zip_path is not None and zip_path.exists()

        # Importar en otro workspace
        target = Path(tmpdir) / "target"
        instrucciones = import_context(zip_path=zip_path, workspace_dir=target)
        assert instrucciones is not None
        assert isinstance(instrucciones, str)
        assert (target / "00_estado_actual.md").exists()
        print(f"[OK] Ciclo export->import: {zip_path.name} cargado en {target}")

    # Test 9 (v3.5): index_document disponible
    assert callable(index_document), "index_document debe ser callable"
    sig_index = inspect.signature(index_document)
    assert {"file_id", "jwt", "filename", "content_type", "size", "force_direct"} <= set(sig_index.parameters.keys())
    print(f"[OK] index_document(): disponible con {len(sig_index.parameters)} params")

    # Test 10-12 (v3.5/v3.6): index_document y index_document_large con file_id inválido
    _logging.getLogger("contexto_zai").setLevel(_logging.CRITICAL)
    try:
        result_invalid = index_document(
            file_id="invalid-uuid",
            jwt="fake-jwt",
            filename="test.pdf",
        )
        assert result_invalid is None or (
            hasattr(result_invalid, "success") and not result_invalid.success
        ), "index_document debe manejar errores gracefully"
        print(f"[OK] index_document() con file_id inválido: maneja error correctamente")

        assert callable(index_document_large), "index_document_large debe ser callable"
        sig_large = inspect.signature(index_document_large)
        assert {"file_id", "jwt", "filename", "content_type", "size"} <= set(sig_large.parameters.keys())
        print(f"[OK] index_document_large(): disponible con {len(sig_large.parameters)} params")

        result_large_invalid = index_document_large(
            file_id="invalid-uuid",
            jwt="fake-jwt",
            filename="large.pdf",
            size=1652025,
        )
        assert result_large_invalid is None or (
            hasattr(result_large_invalid, "success") and not result_large_invalid.success
        ), "index_document_large debe manejar errores gracefully"
        print(f"[OK] index_document_large() con file_id inválido: maneja error")
    finally:
        _logging.getLogger("contexto_zai").setLevel(_old_level)

    # === Tests v4.0 (M8 revisada): query_context ===

    # Test 13 (v4.0): query_context sin contexto recuperado
    with tempfile.TemporaryDirectory() as tmpdir:
        result = query_context("¿Qué se decidió?", workspace_dir=tmpdir)
        assert "error" in result
        assert "No hay contexto recuperado" in result["error"]
        print(f"[OK] query_context sin contexto: mensaje apropiado")

    # Test 14 (v4.0): query_context con contexto simulado (modo directo)
    import json as _json_test
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "contexto"
        ws.mkdir()

        # Crear metadata con mapeo tema -> archivo
        metadata = {
            "chat_id": "test-123",
            "tema_a_archivo": {
                "autenticacion_jwt": "bloque_01.md",
                "configuracion_proyecto": "bloque_02.md",
                "general": "bloque_03.md",
            },
        }
        (ws / "_metadata.json").write_text(_json_test.dumps(metadata), encoding="utf-8")

        # Crear índice
        (ws / "01_indice_recuperacion.md").write_text(
            "# Indice\n\nautenticacion_jwt bloque_01.md\nconfiguracion_proyecto bloque_02.md\n",
            encoding="utf-8",
        )

        # Crear bloques con contenido pequeño (modo directo)
        (ws / "bloque_01.md").write_text(
            "--- Exchange 1 ---\nDirector: Vamos a usar OOP para los subagentes\nAgente: Entendido.\n",
            encoding="utf-8",
        )
        (ws / "bloque_02.md").write_text(
            "--- Exchange 1 ---\nDirector: No uses hardcoding\nAgente: De acuerdo.\n",
            encoding="utf-8",
        )
        (ws / "bloque_03.md").write_text(
            "--- Exchange 1 ---\nDirector: Hola\nAgente: Hola.\n",
            encoding="utf-8",
        )

        # Test: consultar sobre autenticacion
        result = query_context(
            "¿Qué se decidió sobre autenticacion jwt?",
            workspace_dir=ws,
        )
        assert "error" not in result, f"Error inesperado: {result}"
        assert result["mode"] == "direct", f"Esperaba modo direct, obtuvo {result['mode']}"
        assert len(result["prompts"]) == 1, f"Esperaba 1 prompt, obtuvo {len(result['prompts'])}"
        assert "autenticacion" in result["prompts"][0].lower() or "jwt" in result["prompts"][0].lower()
        assert "bloque_01.md" in result["prompts"][0]
        print(f"[OK] query_context modo directo: 1 prompt con rutas de bloques")

        # Test: consultar sobre configuracion
        result2 = query_context(
            "¿Qué restricciones hay sobre configuracion proyecto?",
            workspace_dir=ws,
        )
        assert "error" not in result2
        assert result2["mode"] == "direct"
        assert len(result2["prompts"]) == 1
        assert "bloque_02.md" in result2["prompts"][0]
        print(f"[OK] query_context modo directo: encuentra bloque correcto")

    # Test 15 (v4.0): query_context disponible como callable
    assert callable(query_context), "query_context debe ser callable"
    print(f"[OK] query_context(): disponible")

    # Test 16 (v4.0): query_context sin bloques candidatos
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "contexto"
        ws.mkdir()
        (ws / "_metadata.json").write_text(
            _json_test.dumps({"tema_a_archivo": {"tema_sin_relacion": "bloque_01.md"}}), encoding="utf-8"
        )
        (ws / "01_indice_recuperacion.md").write_text("# Indice\ntema_sin_relacion bloque_01.md", encoding="utf-8")
        (ws / "bloque_01.md").write_text("contenido", encoding="utf-8")

        result = query_context("¿algo sobre xyzqwerty?", workspace_dir=ws)
        assert "error" in result
        assert "No hay información relevante" in result["error"]
        print(f"[OK] query_context sin candidatos: mensaje apropiado")

    # Test 17 (v4.0): query_context modo distribuido con bloques grandes
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "contexto"
        ws.mkdir()
        # Crear bloques grandes (>100K tokens juntos = >350K chars)
        contenido_grande = "x" * 400000  # ~114K tokens por bloque
        (ws / "_metadata.json").write_text(
            _json_test.dumps({"tema_a_archivo": {"test_oop": "bloque_01.md", "test_otro": "bloque_02.md"}}),
            encoding="utf-8",
        )
        (ws / "01_indice_recuperacion.md").write_text(
            "# Indice\ntest_oop bloque_01.md\ntest_otro bloque_02.md", encoding="utf-8"
        )
        (ws / "bloque_01.md").write_text(contenido_grande, encoding="utf-8")
        (ws / "bloque_02.md").write_text(contenido_grande, encoding="utf-8")

        result = query_context("¿Qué se decidió sobre test oop?", workspace_dir=ws)
        assert "error" not in result
        assert result["mode"] == "distributed", f"Esperaba distributed, obtuvo {result['mode']}"
        assert len(result["prompts"]) == 2, f"Esperaba 2 prompts (1 por bloque), obtuvo {len(result['prompts'])}"
        assert result["total_tokens"] > 100000
        print(f"[OK] query_context modo distribuido: 2 prompts (bloques grandes), {result['total_tokens']} tokens")

    # === Tests v4.0 (M9): ampliar_contexto ===

    # Test 18 (v4.0): ampliar_contexto disponible como callable
    assert callable(ampliar_contexto), "ampliar_contexto debe ser callable"
    print(f"[OK] ampliar_contexto(): disponible")

    # Test 19 (v4.0): ampliar_contexto con archivo chico (needs_agent_read=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear archivo chico
        small_file = Path(tmpdir) / "documento_chico.txt"
        small_file.write_text("Contenido pequeño del documento.", encoding="utf-8")

        result = ampliar_contexto("file", str(small_file), workspace_dir=tmpdir)
        assert result.get("needs_agent_read") is True, f"Esperaba needs_agent_read=True, obtuvo: {result}"
        assert "path" in result
        assert result.get("tokens_estimados", 0) < 5000
        print(f"[OK] ampliar_contexto archivo chico: needs_agent_read=True ({result.get('tokens_estimados', 0)} tokens)")

    # Test 20 (v4.0): ampliar_contexto con archivo inexistente
    result = ampliar_contexto("file", "/ruta/que/no/existe.txt")
    assert "error" in result
    assert "no encontrado" in result["error"].lower()
    print(f"[OK] ampliar_contexto archivo inexistente: error reportado")

    # Test 21 (v4.2 Bug A fix): ampliar_contexto con link /s/ de Z.ai
    # v4.2: ya NO se rechaza — se distingue /s/ (share público) de /c/ (chat completo).
    # Sin JWT, debe pedirlo explícitamente.
    result_sin_jwt = ampliar_contexto("url", "https://chat.z.ai/s/abc-123")
    assert "error" in result_sin_jwt
    assert "JWT" in result_sin_jwt["error"]
    print(f"[OK] ampliar_contexto URL /s/ sin JWT: pide JWT en metadata")

    # Test 21b (v4.2 Bug A fix): ampliar_contexto con link /c/ sin JWT
    result_c_sin_jwt = ampliar_contexto("url", "https://chat.z.ai/c/xyz-789")
    assert "error" in result_c_sin_jwt
    assert "JWT" in result_c_sin_jwt["error"]
    print(f"[OK] ampliar_contexto URL /c/ sin JWT: pide JWT en metadata")

    # Test 21c (v4.2 Bug A fix): link /s/ mal formado (sin share_id)
    result_mal = ampliar_contexto("url", "https://chat.z.ai/s/")
    assert "error" in result_mal
    assert "share_id" in result_mal["error"]
    print(f"[OK] ampliar_contexto URL /s/ sin share_id: error claro")

    # Test 21d (v4.2 Bug A fix): _extraer_id_de_link parsea /s/ y /c/ correctamente
    assert _extraer_id_de_link("https://chat.z.ai/s/abc-123-def", "share") == "abc-123-def"
    assert _extraer_id_de_link("https://chat.z.ai/c/xyz-789", "chat") == "xyz-789"
    assert _extraer_id_de_link("https://chat.z.ai/s/abc-123?ref=x", "share") == "abc-123"
    assert _extraer_id_de_link("https://chat.z.ai/s/abc-123#frag", "share") == "abc-123"
    assert _extraer_id_de_link("https://example.com/otra", "share") is None
    assert _extraer_id_de_link("", "share") is None
    assert _extraer_id_de_link("https://chat.z.ai/s/abc", "chat") is None  # tipo incorrecto
    assert _extraer_id_de_link("https://chat.z.ai/c/abc", "share") is None  # tipo incorrecto
    print(f"[OK] _extraer_id_de_link: parsea /s/, /c/, query, fragmento, vacío, inválido")

    # Test 21e (v4.2 Bug A fix): ampliar_contexto con link /c/ mal formado
    result_c_mal = ampliar_contexto("url", "https://chat.z.ai/c/")
    assert "error" in result_c_mal
    assert "chat_id" in result_c_mal["error"]
    print(f"[OK] ampliar_contexto URL /c/ sin chat_id: error claro")

    # Test 22 (v4.0): ampliar_contexto con source_type inválido
    result = ampliar_contexto("invalid", "/path/to/file")
    assert "error" in result
    assert "no válido" in result["error"].lower()
    print(f"[OK] ampliar_contexto source_type inválido: error reportado")

    # Test 23 (v4.0): ampliar_contexto con archivo grande publica tareas vía ProcesadorDocumento
    # F4 v4.2: ya no requiere JWT (usa ProcesadorDocumento que publica tareas, no indexa síncrono)
    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear archivo grande (>5K tokens = >17.5K chars)
        large_file = Path(tmpdir) / "documento_grande.txt"
        large_file.write_text("x" * 20000, encoding="utf-8")

        result = ampliar_contexto("file", str(large_file), jwt="", workspace_dir=tmpdir)
        # F4 v4.2: devuelve indexed=True con pending_tasks (no error por falta de JWT)
        assert result.get("indexed") is True or "pending_tasks" in result, f"Esperaba indexed o pending_tasks, obtuvo: {result}"
        assert len(result.get("pending_tasks", [])) >= 1, f"Esperaba al menos 1 tarea, obtuvo: {result}"
        print(f"[OK] ampliar_contexto archivo grande: {len(result.get('pending_tasks', []))} tarea(s) publicada(s)")

    # Test 23b (v4.2 fix Windows): ampliar_contexto archivo grande DOS VECES (sobrescritura indexed/)
    # Bug Windows: Path.rename() lanza FileExistsError si el destino ya existe.
    # v4.2: el código elimina el destino antes de renombrar — comportamiento cross-platform.
    with tempfile.TemporaryDirectory() as tmpdir:
        from contexto_zai.config import ATTACHMENTS_INDEXED_DIR
        # Limpiar el indexed_dir por si quedó de tests anteriores
        indexed_anterior = ATTACHMENTS_INDEXED_DIR / "documento_grande.txt"
        if indexed_anterior.exists():
            indexed_anterior.unlink()

        large_file = Path(tmpdir) / "documento_grande.txt"
        large_file.write_text("x" * 20000, encoding="utf-8")

        # Primera llamada: crea el archivo en indexed/
        ampliar_contexto("file", str(large_file), jwt="", workspace_dir=tmpdir)
        assert indexed_anterior.exists(), "El archivo indexed debería existir tras la 1ra llamada"

        # Segunda llamada: debe sobrescribir, NO fallar con FileExistsError (bug Windows)
        result_2 = ampliar_contexto("file", str(large_file), jwt="", workspace_dir=tmpdir)
        assert result_2.get("indexed") is True or "pending_tasks" in result_2, \
            f"La 2da llamada debe funcionar como la 1ra: {result_2}"
        assert indexed_anterior.exists(), "El archivo indexed debe seguir existiendo tras la 2da llamada"
        print(f"[OK] ampliar_contexto archivo grande 2da vez: sobrescribe indexed/ sin FileExistsError")

        # Limpieza
        if indexed_anterior.exists():
            indexed_anterior.unlink()

    # Test 24 (v4.2): query_context en workspace SOLO con bloque externo (sin 01_indice)
    # Simula: ampliar_contexto() corrió, subagente indexador respondió con temas reales,
    # IntegradorRespuestas._integrar_documento() los registró en _metadata.json.
    # query_context() debe encontrar el bloque por el tema real (no por el nombre genérico).
    with tempfile.TemporaryDirectory() as tmpdir:
        import json as _json_t24
        ws = Path(tmpdir)
        # Bloque externo físico (lo crea _integrar_documento)
        bloque_externo = ws / "bloque_externo_documento_seguridad_lote_0.md"
        bloque_externo.write_text(
            "# Bloque externo: documento_seguridad (lote 0)\n\n"
            "RESUMEN: Documento sobre el sistema de seguridad JWT.\n\n"
            "TEMA: autenticacion_jwt\nDESCRIPCION: Autenticación con JWT\nSECCIONES: header, payload, signature\n",
            encoding="utf-8",
        )
        # _metadata.json con tema REAL registrado (no nombre genérico)
        (ws / "_metadata.json").write_text(_json_t24.dumps({
            "tema_a_archivo": {"autenticacion_jwt": bloque_externo.name}
        }), encoding="utf-8")
        # NO hay 01_indice_recuperacion.md (ampliar_contexto no lo genera)

        result = query_context("¿qué dice sobre jwt?", workspace_dir=str(ws))
        assert "error" not in result, f"Esperaba encontrar bloque, obtuvo error: {result}"
        assert result["mode"] == "direct", f"Esperaba modo direct, obtuvo: {result.get('mode')}"
        assert len(result["prompts"]) == 1
        assert "autenticacion_jwt" in result["bloques_info"][0]["temas"]
        assert bloque_externo.name in result["bloques"]
        print(f"[OK] query_context solo bloque externo: encuentra tema 'autenticacion_jwt' (sin 01_indice)")

    # Test 25 (v4.2): query_context en workspace MIXTO (índice del chat + bloque externo)
    # Simula: pipeline.run() corrió + ampliar_contexto() también corrió.
    # query_context() debe encontrar bloques de ambos orígenes indistintamente.
    with tempfile.TemporaryDirectory() as tmpdir:
        import json as _json_t25
        ws = Path(tmpdir)
        # Bloque del chat
        (ws / "bloque_01.md").write_text("# Bloque del chat\n\nConfiguración de pytest.\n", encoding="utf-8")
        # Bloque externo
        (ws / "bloque_externo_doc_api_lote_0.md").write_text(
            "# Bloque externo: doc_api (lote 0)\n\n"
            "TEMA: api_rest\nDESCRIPCION: Diseño de la API REST\nSECCIONES: endpoints, auth\n",
            encoding="utf-8",
        )
        # Índice del chat (pipeline.run sí lo genera)
        (ws / "01_indice_recuperacion.md").write_text("# Índice\n\n## configuracion\n", encoding="utf-8")
        # Metadata con ambos temas
        (ws / "_metadata.json").write_text(_json_t25.dumps({
            "tema_a_archivo": {
                "configuracion": "bloque_01.md",            # del chat
                "api_rest": "bloque_externo_doc_api_lote_0.md",  # de ampliar_contexto
            }
        }), encoding="utf-8")

        # Pregunta sobre el tema del bloque externo
        result_externo = query_context("¿qué dice la api?", workspace_dir=str(ws))
        assert "error" not in result_externo, f"Esperaba encontrar bloque externo: {result_externo}"
        assert "bloque_externo_doc_api_lote_0.md" in result_externo["bloques"]
        assert "api_rest" in result_externo["bloques_info"][0]["temas"]

        # Pregunta sobre el tema del chat
        result_chat = query_context("¿qué dice la configuracion?", workspace_dir=str(ws))
        assert "error" not in result_chat, f"Esperaba encontrar bloque del chat: {result_chat}"
        assert "bloque_01.md" in result_chat["bloques"]
        assert "configuracion" in result_chat["bloques_info"][0]["temas"]
        print(f"[OK] query_context workspace mixto: encuentra bloque externo (api_rest) y del chat (configuracion)")

    print("\n[PASS] pipeline.py: todos los tests pasaron")
