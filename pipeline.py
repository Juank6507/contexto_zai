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

            # 5. Si es grande, usar ProcesadorDocumento (patrón diferido v4.2)
            # El ProcesadorDocumento decide según tamaño (mediano=un subagente, grande=3 niveles)
            # y publica las tareas vía el Orquestador. No intenta descargar de la API de Z.ai.
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
                }
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
            """v4.2: Recoge las respuestas de los subagentes y las integra a los archivos.

            Esta función es el integrador de respuestas de subagentes (cualquier
            propósito: estado, intercambios, decisiones, consultas, documentos).
            Lee ``_responses/``, las aplica al workspace según el ``purpose`` de
            cada tarea, Y dispara la cascada W1+W2+W3 (P14) cuando quedan bloques
            sin RESUMEN. **NO es un bucle D7** — si tras llamarla quedan bloques
            incompletos, el bucle D7 de P17 (``_bucle_d7_completitud()``) se
            encarga de los reintentos con feedback.

            Tras ``pipeline.run()`` y el lanzamiento de subagentes por parte del agente,
            esta función lee las respuestas que los subagentes escribieron en
            ``_responses/``, las integra a los archivos de recuperación, y devuelve
            el resultado estructurado.

            El agente nunca ve el contenido crudo de las respuestas — solo llama
            a esta función y recibe el resultado estructurado.

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

            # v6.10 F2: enriquecer bloques nuevos después de que collect_responses()
            # los haya escrito al disco. El momento correcto es aquí, después de
            # aplicar las respuestas (los bloques ya están en disco).
            # Esto aplica tanto para bloques externos (de ampliar_contexto) como para
            # bloques del chat que hayan quedado sin RESUMEN.
            # v6.10 F2: SIN try/except silencioso. Si el enriquecimiento falla, el
            # error se propaga. Las pending_tasks se capturan del valor de retorno
            # directamente (v6.8.1 re-aplicado), sin re-leer del Orquestador.
            # v6.10 F3: el arnés (_enriquecer_bloques_con_fallback) detecta la caída
            # del Worker Bun en menos de 5s y devuelve las pending_tasks inmediatamente.
            bloques_sin_resumen = _descubrir_bloques_sin_resumen(workspace_dir)
            if bloques_sin_resumen:
                fallback_tasks = _enriquecer_bloques_con_fallback(
                    blocks=bloques_sin_resumen,
                    workspace_dir=workspace_dir,
                    chat_label="collect_responses",
                )
                # v6.8.1 re-aplicado: capturar el valor de retorno, no re-leer del Orquestador.
                if fallback_tasks:
                    resultado.setdefault("pending_tasks", []).extend(fallback_tasks)
                    logger.info(
                        "v6.10: %d tarea(s) de fallback añadida(s) a pending_tasks.",
                        len(fallback_tasks),
                    )
                # v6.8.4 re-aplicado: tras enriquecer, consolidar decisiones y regenerar índice.
                # v6.11 F6: si la operación NO es cronológica (ampliar_contexto), NO
                # consolidar decisiones ni regenerar índice — la fuente externa no
                # es chat-cronológica, los 4 archivos deben preservarse como están.
                if is_chat_chronological:
                    _consolidar_decisiones_llm(workspace_dir=workspace_dir)
                    _regenerar_indice_tras_enriquecimiento(workspace_dir=workspace_dir)
                else:
                    logger.info(
                        "v6.11 F6: collect_responses no cronológico — se preservan los 4 archivos "
                        "(no se consolida 02_decisiones_clave.md ni se regenera 01_indice_recuperacion.md)."
                    )

            return resultado


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
    """v6.11 F5: Wrapper que delega a ContextoPipeline.ampliar_contexto()."""
    return ContextoPipeline.ampliar_contexto(source_type=source_type, source_path=source_path, jwt=jwt, metadata=metadata, workspace_dir=workspace_dir)


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
    def _descubrir_bloques_sin_resumen(workspace_dir: Path | str) -> list:
            """v6.6 F3 (Bug 7 fix): Descubre los bloques del workspace que NO tienen RESUMEN al inicio.

            Usado por collect_responses() para saber qué bloques enriquecer.
            Lee cada bloque_*.md del workspace y verifica si la primera línea
            empieza con "RESUMEN:". Los que no lo tengan se devuelven como
            ThematicBlock (con temas y external_size_chars poblados).

            Args:
                workspace_dir: Directorio del workspace.

            Returns:
                Lista de ThematicBlock sin RESUMEN, listos para enriquecer.
            """
            from contexto_zai.models import ThematicBlock as _TB
            ws = Path(workspace_dir)
            if not ws.exists():
                return []

            bloques_sin_resumen: list = []
            for p in sorted(ws.glob("bloque_*.md")):
                try:
                    content = p.read_text(encoding="utf-8")
                    if len(content) < 100:
                        continue  # bloque vacío
                    # Verificar si ya tiene RESUMEN al inicio
                    first_line = content.split("\n", 1)[0].strip()
                    if first_line.startswith("RESUMEN:"):
                        continue  # ya tiene resumen, no necesita enriquecer
                    # Extraer temas del header
                    temas: list[str] = []
                    for line in content.split("\n"):
                        if line.startswith("# Bloque tematico:") or line.startswith("# Bloque temático:"):
                            temas_str = line.split(":", 1)[1].strip()
                            temas = [t.strip() for t in temas_str.split(",") if t.strip()]
                            break
                        elif line.startswith("# Bloque externo:"):
                            # Compatibilidad con bloques pre-v6.6
                            nombre = line.split(":", 1)[1].strip()
                            temas = [nombre.lower().replace(" ", "_")[:50]]
                            break
                    if not temas:
                        temas = ["contexto_externo"]
                    block = _TB(
                        filename=p.name,
                        temas=temas,
                        external_size_chars=len(content),
                    )
                    bloques_sin_resumen.append(block)
                except Exception as e:
                    logger.warning("v6.6 F3: no se pudo leer bloque %s: %s", p.name, e)

            logger.info("v6.6 F3: %d bloques sin RESUMEN descubiertos", len(bloques_sin_resumen))
            return bloques_sin_resumen

    @staticmethod
    def _enriquecer_bloques_con_fallback(
        blocks: list,
        workspace_dir: Path | str,
        chat_label: str = "",
    ) -> list:
            """v6.13 F4: Arnés de cascada que NUNCA se detiene.

            1. Identificar bloques sin RESUMEN.
            2. Nivel 1 (Worker Bun): si proxy disponible, arrancar una vez. Verificar.
            3. Nivel 2 (proxy Z.ai W1+W2+W3): si proxy disponible, procesar restantes uno por uno.
            4. Nivel 3 (subagentes): los que queden van a pending_tasks.
            5. Sincronizar _processed_blocks.json con estado físico.
            Nunca se detiene. Nunca pausa.
            """
            # 1. Bloques sin RESUMEN
            bloques_sin_resumen = [b for b in blocks if not b.tiene_resumen(workspace_dir=workspace_dir)]

            if not bloques_sin_resumen:
                logger.info("v6.13: Todos los bloques ya tienen RESUMEN. Nada que hacer.")
                AuditorWorkspace.sincronizar_registro(workspace_dir)
                return []

            logger.info("v6.13: %d bloque(s) sin RESUMEN. Cascada que nunca se detiene.",
                        len(bloques_sin_resumen))

            pending_tasks = []
            bloques_para_n3 = []

            # 2. Check proxy Z.ai disponible
            proxy_ok = _proxy_zai_disponible()

            if proxy_ok:
                # NIVEL 1: Worker Bun (una vez para todos los pendientes)
                logger.info("v6.13 Nivel 1: Arrancando Worker Bun para %d bloque(s)...",
                            len(bloques_sin_resumen))
                try:
                    EnriquecimientoOrquestador._arrancar_worker_y_esperar(workspace_dir=workspace_dir)
                except Exception as e:
                    logger.warning("v6.13 Nivel 1 (Worker Bun) error: %s", e)

                # Verificar cuáles completó
                bloques_restantes = [
                    b for b in bloques_sin_resumen
                    if not EnriquecimientoOrquestador._bloque_esta_completo(b, workspace_dir=workspace_dir)
                ]
                completados_n1 = len(bloques_sin_resumen) - len(bloques_restantes)
                logger.info("v6.13 Nivel 1: Worker Bun completó %d, quedan %d.",
                            completados_n1, len(bloques_restantes))

                # NIVEL 2: proxy Z.ai directo con W1+W2+W3 (uno por uno, nunca pausa)
                if bloques_restantes:
                    logger.info("v6.13 Nivel 2: Intentando %d bloque(s) con proxy Z.ai (W1+W2+W3)...",
                                len(bloques_restantes))
                    for bloque in bloques_restantes:
                        try:
                            ok = EnriquecimientoOrquestador._enriquecer_con_proxy_zai(
                                bloque, workspace_dir=workspace_dir
                            )
                        except Exception as e:
                            logger.warning("v6.13 Nivel 2 error en %s: %s", bloque.filename, e)
                            ok = False

                        if not ok:
                            bloques_para_n3.append(bloque)
                        else:
                            logger.info("v6.13 Nivel 2: %s completado.", bloque.filename)

                    if not bloques_para_n3:
                        logger.info("v6.13 Nivel 2: Proxy Z.ai completó todos los restantes.")
                    else:
                        logger.info("v6.13 Nivel 2: Quedan %d para Nivel 3.", len(bloques_para_n3))
            else:
                # Proxy no disponible: saltar Niveles 1 y 2, ir directo a Nivel 3
                bloques_para_n3 = bloques_sin_resumen
                logger.info("v6.13: Proxy Z.ai no disponible. Saltando Niveles 1 y 2. %d bloque(s) para Nivel 3.",
                            len(bloques_para_n3))

            # NIVEL 3: subagentes (último recurso)
            for bloque in bloques_para_n3:
                task = _construir_pending_task_para_bloque(bloque, chat_label=chat_label)
                if task:
                    pending_tasks.append(task)

            # Sincronizar _processed_blocks.json con estado físico
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

        # Caché por hash
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

            messages = [{"role": "user", "content": prompt}]
            result = None
            w3_ok = False
            w3_motivo = ""
            intento = 0
            retries_429 = 0
            max_retries_429 = 10  # máx reintentos por 429 (no consumen MAX_ITER)

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
                    if e.code == 429 and retries_429 < max_retries_429:
                        # v6.13: HTTP 429 rate-limited. Backoff exponencial
                        # SIN consumir MAX_ITER (es espera de cuota, no fallo de W3).
                        retries_429 += 1
                        wait_s = min(30 * (2 ** (retries_429 - 1)), 600)  # 30, 60, 120, 240, 480, 600, 600, ...
                        logger.warning("v6.13 Nivel 2: HTTP 429 para %s. Esperando %ds "
                                       "(reintento 429 %d/%d, no consume MAX_ITER).",
                                       block_id, wait_s, retries_429, max_retries_429)
                        time.sleep(wait_s)
                        # No consumir este intento: retroceder el contador
                        intento -= 1
                        continue
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

        # Validar que tenemos los 4 artefactos
        if not resumen or not nombre:
            logger.warning("v6.13 Nivel 2: %s - respuesta incompleta (resumen o nombre vacío).", block_id)
            return False

        # Escribir los 4 artefactos a la vez (no puede haber "medio enriquecimiento")
        # 1. RESUMEN al inicio del bloque
        current_content = bloque_path.read_text(encoding="utf-8")
        if current_content.startswith("RESUMEN:"):
            # Ya tiene resumen, reemplazar
            parts = current_content.split("\n\n---\n\n", 1)
            new_content = f"RESUMEN: {resumen}\n\n---\n\n" + (parts[1] if len(parts) > 1 else "")
        else:
            new_content = f"RESUMEN: {resumen}\n\n---\n\n{current_content}"
        bloque_path.write_text(new_content, encoding="utf-8")

        # 2. _nombre.txt
        (responses_dir / f"{block_id}_nombre.txt").write_text(nombre, encoding="utf-8")

        # 3. _decisiones.txt
        decisiones_text = "\n".join(decisiones) if decisiones else "SIN_DECISIONES_REALES"
        (responses_dir / f"{block_id}_decisiones.txt").write_text(decisiones_text, encoding="utf-8")

        # 4. _temas.txt
        temas_text = ", ".join(temas) if temas else "general"
        (responses_dir / f"{block_id}_temas.txt").write_text(temas_text, encoding="utf-8")

        # W3 final: confirmar completitud (ya validado arriba, pero mantener log informativo)
        if not completo:
            logger.info("v6.13 W3: %s - LLM reportó completo=False, observaciones: %s",
                        block_id, observaciones)

        logger.info("v6.13 Nivel 2: %s completado (W1+W2+W3 en 1 llamada, %d intento(s)).",
                    block_id, intento)
        return True

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
            """v6.14 F3 (criterio 18): Bucle D7 en P17 para garantizar completitud.

            Lee el saco ``_pending_tasks.json`` y, para cada bloque incompleto
            tras P14-P16, construye un prompt corregido con feedback sobre
            qué falló (W3: longitud, oraciones, etiquetas) o qué archivos
            faltan (``_nombre.txt``, ``_decisiones.txt``, ``_temas.txt``).

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
            try:
                from contexto_zai.coordinador.entregador_tareas import EntregadorTareas
                entregador = EntregadorTareas(workspace_dir=workspace_dir)
                entregador.limpiar()  # limpiar el saco viejo
                if new_pending_tasks:
                    entregador.publicar(new_pending_tasks)
            except Exception as e:
                logger.warning(
                    "v6.14 P17 D7: no se pudo publicar pending_tasks: %s", e
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


def _descubrir_bloques_sin_resumen(workspace_dir: Path | str) -> list:
    """v6.11 F5: Wrapper que delega a EnriquecimientoOrquestador._descubrir_bloques_sin_resumen()."""
    return EnriquecimientoOrquestador._descubrir_bloques_sin_resumen(workspace_dir=workspace_dir)


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
                            logger.warning("AuditorWorkspace: metadata referencia %s que no existe", a)
                            return False
                elif isinstance(archivo, str):
                    if archivo not in bloques_fisicos and not (ws / archivo).exists():
                        logger.warning("AuditorWorkspace: metadata referencia %s que no existe", archivo)
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
    import logging as _logging
    _old_level = _logging.getLogger("contexto_zai").level
    _logging.getLogger("contexto_zai").setLevel(_logging.CRITICAL)
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run(
                chat_id="invalid-chat",
                jwt="invalid-jwt",
                workspace_dir=tmpdir,
                download_dir=tmpdir + "/download",
            )
            # Debe fallar porque el JWT es inválido
            assert not result.success
            assert result.error != ""
            print(f"[OK] run() con JWT inválido: error capturado correctamente")
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

    # === Tests v4.2 (unificación): query_context encuentra bloques externos ===

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
