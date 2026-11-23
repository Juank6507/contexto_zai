# contexto_zai/pipeline.py -- API pública del proceso Contexto Z.ai (v7.0 modularizado).
"""API pública del proceso Contexto Z.ai (v7.0 modularizado).

v7.0 separa los subprocesos reusables en módulos dedicados dentro del
paquete ``contexto_zai/``. Este archivo queda como la API pública del
proceso:

- ``ContextoPipeline`` (v6.11 F5) — clase con métodos estáticos que
  exponen ``run``, ``ampliar_contexto``, ``query_context``,
  ``collect_responses`` y delegan a los nuevos módulos.
- Wrappers módulo-nivel (``run``, ``status``, ``ampliar_contexto``,
  ``collect_responses``, ``query_context``, ``recuperar_contexto_si_necesario``,
  ``index_document``, ``index_document_large``, ``export_context``,
  ``import_context``, ``find_context_packages``) — wrappers que delegan
  a ``ContextoPipeline``.
- Funciones utility (``_buscar_en_resumenes``, ``_extraer_id_de_link``,
  ``_construir_pending_task_para_bloque``, ``_detectar_estructura_contenido``,
  ``_parsear_intercambios_desde_contenido``) — helpers usados por
  ``ContextoPipeline.ampliar_contexto`` y ``query_context``.
- Re-exports para backward-compat: ``AuditorWorkspace``, ``ProgressMonitor``
  (de ``pipeline_auditoria``), ``CascadaAccesoLLM`` (de ``pipeline_cascada``),
  ``CicloW3``, ``PROMPT_FUSIONADO_W1W2W3`` (de ``pipeline_w3``), ``CicloD7``
  (de ``pipeline_d7``), ``SubprocesoArchivos`` (de ``pipeline_archivos``).
- Re-exports de wrappers v6.x (``_enriquecer_bloques_post_run``,
  ``_bucle_d7_completitud``, ``_consolidar_decisiones_llm``, etc.) que
  delegan a los nuevos módulos — se eliminarán en fases posteriores.

La clase ``EnriquecimientoOrquestador`` ya NO existe en este archivo: sus
métodos estáticos se distribuyeron en ``pipeline_cascada``,
``pipeline_w3``, ``pipeline_d7`` y ``pipeline_archivos``.

Reemplaza la CLI de v1.0. Expone funciones para activar la
recuperación de contexto (``run``), consultar estado (``status``),
y exportar/importar el contexto entre agentes (``export_context``,
``import_context``).

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

# v7.0 modularización: imports de los nuevos módulos.
from contexto_zai.pipeline_auditoria import (
    AuditorWorkspace,
    ProgressMonitor,
)
from contexto_zai.pipeline_cascada import (
    CascadaAccesoLLM,
    _proxy_zai_disponible as _cascada_proxy_zai_disponible,
    _arrancar_worker_y_esperar as _cascada_arrancar_worker_y_esperar,
    _persistir_pending_task_en_disco as _cascada_persistir_pending_task_en_disco,
    _post_bloque as _cascada_post_bloque,
    _actualizar_estado_daemon as _cascada_actualizar_estado_daemon,
    _escribir_artefactos_bloque as _cascada_escribir_artefactos_bloque,
    _enriquecer_con_proxy_zai as _cascada_enriquecer_con_proxy_zai,
)
from contexto_zai.pipeline_w3 import (
    CicloW3,
    PROMPT_FUSIONADO_W1W2W3,
)
from contexto_zai.pipeline_d7 import (
    CicloD7,
)
from contexto_zai.pipeline_archivos import (
    SubprocesoArchivos,
)

logger = logging.getLogger(__name__)

class ContextoPipeline:
    """v6.11 F5: API pública del pipeline (refactor OOP).

    Agrupa funciones relacionadas como métodos estáticos. Las funciones
    módulo-nivel son wrappers momentáneos que delegan a estos métodos.

    v7.0: los métodos estáticos que antes vivían en
    ``EnriquecimientoOrquestador`` (cascada, W3, D7, archivos) se mudaron
    a módulos dedicados. ``ContextoPipeline`` delega a esos módulos.
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
            result = CicloW3._enriquecer_bloques_post_run(
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
            result = CicloD7._bucle_d7_completitud(
                result=result,
                workspace_dir=workspace_dir,
            )
            # v6.4 F1: consolidar decisiones del LLM (de _responses/) en 02_decisiones_clave.md
            # v6.14: paso P18 del proceso de 19 pasos.
            SubprocesoArchivos._consolidar_decisiones_llm(workspace_dir=workspace_dir)
            # v6.15 F6 (criterio 33): paso P19 del proceso de 19 pasos.
            # Regenera ``01_indice_recuperacion.md`` DESPUÉS del enriquecimiento
            # (P14) y la consolidación de decisiones (P18), cuando los bloques
            # ya tienen RESUMEN y ``tema_a_archivo`` está poblado con los temas
            # significativos extraídos de ``_responses/<bloque>_temas.txt``.
            # En P9 (durante ``RecoveryGenerator.generate_all``), el IndiceGenerator
            # se invoca como placeholder inicial (sin temas) — P19 lo sobrescribe
            # con contenido real.
            SubprocesoArchivos._regenerar_indice_tras_enriquecimiento(workspace_dir=workspace_dir)
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
        chat_id: str = "",
        force_rebuild: bool = False,  # v6.20 F7: autorización del Director
    ) -> dict:
            """Amplía el contexto desde una fuente externa (link o archivo).

            v6.14 F5 (criterio 21): esta función es la API pública del
            proceso. El agente CZAI **no** escribe scripts ``runner_*.py``
            para invocarla — usa el daemon ``pipeline-daemon`` (puerto 8088,
            endpoint ``POST /ampliar-contexto``).

            v6.19 F1 (P1/P5 conciliados): ``chat_id`` siempre del chat actual.
            El daemon lo pasa desde los metadatos del gateway IM. Se propaga
            a ``RecoveryCycle``, ``EstadoGenerator`` y al escritor de
            ``_metadata.json``.

            v6.19 F5 (P6/P7 conciliados): hash SHA256 del documento fuente
            comparado con ``_metadata.json["source_sha256"]``. Si difieren,
            eliminar todos los ``bloque_*.md`` antes de regenerar.

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
                chat_id: v6.19 F1 — chat_id del chat actual donde corre el agente.
                    Si llega vacío, se intenta leer del metadata del gateway IM
                    vía ``metadata["chat_id"]``.

            Returns:
                Dict con:
                - "needs_agent_read": True si el archivo es chico y el agente lo lee directo.
                - "path": ruta al archivo (si needs_agent_read=True).
                - "indexed": True si el proceso lo indexó (archivo grande).
                - "bloques_nuevos": lista de nombres de bloques nuevos (si indexed=True).
                - "error": mensaje de error si algo falló.

            Example:
                >>> from contexto_zai.pipeline import ampliar_contexto
                >>> result = ampliar_contexto("file", "/path/to/doc.pdf", chat_id="abc-123")
                >>> if result.get("needs_agent_read"):
                ...     # El agente lee el archivo directo
                ...     pass
                >>> elif result.get("indexed"):
                ...     print(f"Bloques nuevos: {result['bloques_nuevos']}")
            """
            import json as _json
            import hashlib as _hashlib
            from contexto_zai.config import (
                AMPLIAR_SMALL_FILE_THRESHOLD_TOKENS,
                AMPLIAR_URL_DOWNLOAD_TIMEOUT,
                AMPLIAR_URL_MAX_SIZE_BYTES,
                ATTACHMENTS_TEMP_DIR,
                WORKSPACE_OUTPUT_DIR as _WS_DIR,
            )

            workspace = Path(workspace_dir)
            metadata = metadata or {}

            # v6.19 F1 (P1/P5 conciliados): chat_id siempre del chat actual.
            # Si llega vacío pero el metadata trae chat_id, usarlo.
            if not chat_id and isinstance(metadata, dict):
                chat_id = metadata.get("chat_id", "") or ""

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
            estructura = _detectar_estructura_contenido(content_bytes)
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
                messages = _parsear_intercambios_desde_contenido(
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

                # v6.19 F5 (P6/P7 conciliados): hash SHA256 del documento fuente
                # comparado con _metadata.json["source_sha256"]. Si difieren,
                # eliminar todos los bloque_*.md antes de regenerar (la fuente
                # cambió). Si coinciden, preservar (re-corrida del mismo
                # documento, permite al bucle D7 re-procesar lo incompleto).
                source_sha256_actual = _hashlib.sha256(content_bytes).hexdigest()
                metadata_path_pre = workspace / "_metadata.json"
                source_sha256_previo = ""
                if metadata_path_pre.exists():
                    try:
                        meta_pre = _json.loads(metadata_path_pre.read_text(encoding="utf-8"))
                        source_sha256_previo = meta_pre.get("source_sha256", "") or ""
                    except (_json.JSONDecodeError, ValueError):
                        pass

                if source_sha256_previo and source_sha256_previo != source_sha256_actual:
                    # v6.20 F7: pedir autorización al Director antes de regenerar
                    if not force_rebuild:
                        logger.info("v6.20 F7: fuente cambiada — pidiendo autorización al Director")
                        _cascada_actualizar_estado_daemon(
                            workspace_dir=workspace,
                            status="waiting_for_authorization",
                            tarea_actual="Fuente cambiada — esperando autorización",
                        )
                        return {
                            "needs_agent_read": False,
                            "indexed": False,
                            "needs_authorization": True,
                            "filename": filename,
                            "reason": f"El archivo cambió (hash previo={source_sha256_previo[:16]}... ≠ actual={source_sha256_actual[:16]}...). Autoriza con force_rebuild=true.",
                        }
                    else:
                        logger.info("v6.20 F7: force_rebuild=True — eliminando bloques")
                        for bloque_file in workspace.glob("bloque_*.md"):
                            try:
                                bloque_file.unlink()
                            except Exception as e:
                                logger.warning("v6.20 F5: no se pudo eliminar %s: %s", bloque_file, e)
                elif not source_sha256_previo:
                    logger.info(
                        "v6.19 F5: primera corrida (sin source_sha256 previo). "
                        "Generando bloques nuevos. Hash actual=%s...",
                        source_sha256_actual[:12],
                    )
                else:
                    logger.info(
                        "v6.19 F5: re-corrida del mismo documento (hash coincide=%s...). "
                        "Preservando bloques existentes.",
                        source_sha256_actual[:12],
                    )

                # Crear RecoveryCycle con origen="externo" y
                # estructura="cronologico". El packer.pack() usa default
                # origen="cronologico" → ordena descendente (criterio 2).
                # v6.19 F1 (P1/P5 conciliados): chat_id del chat actual.
                cycle = RecoveryCycle(
                    jwt=jwt or "",
                    chat_id=chat_id,
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
                # v6.19 F1 (P1/P5): chat_id del chat actual siempre poblado.
                if chat_id:
                    meta["chat_id"] = chat_id
                    # share_id se deja vacío para archivos externos (no hay share
                    # de Z.ai); el chat_id es el del chat actual donde corre el
                    # agente, no de un share público.
                    if not meta.get("share_id"):
                        meta["share_id"] = ""
                # v6.19 F5 (P6/P7): guardar hash SHA256 del documento fuente
                # para detectar cambios en re-corridas futuras.
                meta["source_sha256"] = source_sha256_actual
                metadata_path.write_text(
                    _json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
                )

                logger.info(
                    "v6.18 F1: ampliar_contexto cronológico procesado — "
                    "%d bloques, %d intercambios, %d pending_tasks. "
                    "Continuando pipeline (collect_responses → cascada → P16-P19).",
                    cycle_result.blocks_count,
                    cycle_result.exchanges_count,
                    len(cycle_result.pending_tasks or []),
                )

                # v6.18 Fix (spec §3.1): NO retornar aquí. Tras RecoveryCycle,
                # ampliar_contexto() continúa el pipeline completo:
                #   collect_responses → descubrir incompletos → cascada →
                #   P16 (auditoría final) + P17 (bucle D7) + P18 (consolidar
                #   decisiones) + P19 (regenerar índice).
                # Antes hacía ``return`` tras RecoveryCycle y se saltaba
                # todo el enriquecimiento posterior (bloques externos
                # cronológicos se quedaban sin RESUMEN ni archivos
                # _responses/).

                # (1) collect_responses: integra respuestas de pending_tasks
                # de extracción (puede no haber — RecoveryCycle ya generó
                # los bloques directamente). En ese caso collect_responses
                # no hace nada pero no falla.
                try:
                    ContextoPipeline.collect_responses(
                        workspace_dir=workspace,
                        is_chat_chronological=False,
                    )
                except Exception as e:
                    logger.warning(
                        "v6.18 Fix: collect_responses tras RecoveryCycle falló: %s", e
                    )

                # (2) Verificar bloques incompletos con F1.
                incompletos = CicloW3._descubrir_bloques_incompletos(
                    workspace
                )

                # (3) Si hay incompletos, disparar la cascada W1+W2+W3
                # (_enriquecer_bloques_con_fallback) sobre los ThematicBlock
                # descubiertos.
                cascada_pending_tasks: list = []
                if incompletos:
                    bloques_para_cascada = [inc["bloque"] for inc in incompletos]
                    try:
                        cascada_pending_tasks = (
                            CicloW3._enriquecer_bloques_con_fallback(
                                blocks=bloques_para_cascada,
                                workspace_dir=workspace,
                            )
                        )
                    except Exception as e:
                        logger.warning(
                            "v6.18 Fix: _enriquecer_bloques_con_fallback falló: %s", e
                        )

                # v6.19 F6 (autonomía del agente CZAI): si la cascada publicó
                # pending_tasks de Nivel 3 (subagentes que solo el agente CZAI
                # puede ejecutar vía Task tool), NO ejecutar P16-P19 todavía.
                # Publicar _daemon_status.json con status=waiting_for_agent y
                # _pending_tasks.json con las tareas. Retornar temprano con
                # needs_agent_action=True. El agente CZAI debe ejecutar las
                # pending_tasks automáticamente (sin pedir permiso al Director)
                # y luego llamar POST /collect-responses al daemon para que
                # ejecute collect_responses() + P16-P19.
                if cascada_pending_tasks:
                    import json as _json_f6
                    # Escribir _pending_tasks.json
                    pending_path = workspace / "_pending_tasks.json"
                    try:
                        pending_data = {"tasks": cascada_pending_tasks}
                        if hasattr(cascada_pending_tasks[0], 'model_dump'):
                            pending_data = {
                                "tasks": [
                                    t.model_dump() if hasattr(t, 'model_dump') else t
                                    for t in cascada_pending_tasks
                                ]
                            }
                        pending_path.write_text(
                            _json_f6.dumps(pending_data, indent=2, ensure_ascii=False, default=str),
                            encoding="utf-8",
                        )
                    except Exception as e:
                        logger.warning("v6.19 F6: escribir _pending_tasks.json falló: %s", e)

                    # Escribir _daemon_status.json con waiting_for_agent
                    _cascada_actualizar_estado_daemon(
                        workspace_dir=workspace,
                        status="waiting_for_agent",
                        tarea_actual="Nivel 3 — agente CZAI debe ejecutar pending_tasks",
                    )

                    logger.info(
                        "v6.19 F6: %d pending_tasks de Nivel 3 publicadas. "
                        "Daemon en waiting_for_agent. El agente CZAI debe "
                        "ejecutarlas automáticamente y llamar /collect-responses.",
                        len(cascada_pending_tasks),
                    )

                    return {
                        "needs_agent_read": False,
                        "indexed": True,
                        "filename": filename,
                        "path": str(indexed_path),
                        "needs_agent_action": True,
                        "pending_tasks_count": len(cascada_pending_tasks),
                        "instruction": (
                            "El daemon publicó pending_tasks de Nivel 3 que solo "
                            "el agente CZAI puede ejecutar (vía Task tool). "
                            "Ejecutarlas automáticamente SIN pedir permiso al "
                            "Director y luego llamar POST /collect-responses al "
                            "daemon (puerto 8088) para integrar respuestas y "
                            "continuar con P16-P19."
                        ),
                        "tokens_estimados": int(estimated_tokens),
                        "flujo": "recovery_cycle_cronologico",
                        "num_lotes": cycle_result.blocks_count,
                        "estructura": estructura,
                        "origen": origen,
                        "bloques_nuevos": cycle_result.blocks_count,
                    }

                # (4) P16 — auditoría final post-enriquecimiento (criterio 4:
                # P16 SIEMPRE se ejecuta tras procesar).
                try:
                    audit_final = AuditorWorkspace.auditar_completitud(workspace)
                    logger.info(
                        "v6.18 P16: Auditoría final (post RecoveryCycle+cascada): "
                        "%d completos, %d incompletos, metadata_valida=%s",
                        len(audit_final["completos"]),
                        len(audit_final["incompletos"]),
                        audit_final["metadata_valida"],
                    )
                except Exception as e:
                    logger.warning("v6.18 P16: auditar_completitud falló: %s", e)

                # (5) P17 — bucle D7 con feedback para los bloques que
                # quedaron incompletos. Construir un OrchestratorResult
                # dummy con las pending_tasks de RecoveryCycle + las de la
                # cascada (Nivel 3). _bucle_d7_completitud devuelve el
                # resultado con las pending_tasks actualizadas (las que
                # siguen incompletas tras MAX_ITER_D7=5).
                pending_tasks_acumuladas = list(cycle_result.pending_tasks or [])
                pending_tasks_acumuladas.extend(cascada_pending_tasks or [])
                dummy_result = OrchestratorResult(success=True)
                dummy_result.pending_tasks = pending_tasks_acumuladas
                try:
                    dummy_result = CicloD7._bucle_d7_completitud(
                        result=dummy_result,
                        workspace_dir=workspace,
                    )
                    pending_tasks_acumuladas = list(
                        getattr(dummy_result, "pending_tasks", []) or []
                    )
                except Exception as e:
                    logger.warning("v6.18 P17: _bucle_d7_completitud falló: %s", e)

                # (6) P18 — consolidar decisiones del LLM en 02_decisiones_clave.md.
                try:
                    SubprocesoArchivos._consolidar_decisiones_llm(
                        workspace_dir=workspace
                    )
                except Exception as e:
                    logger.warning(
                        "v6.18 P18: _consolidar_decisiones_llm falló: %s", e
                    )

                # (7) P19 — regenerar 01_indice_recuperacion.md tras enriquecimiento.
                try:
                    SubprocesoArchivos._regenerar_indice_tras_enriquecimiento(
                        workspace_dir=workspace
                    )
                except Exception as e:
                    logger.warning(
                        "v6.18 P19: _regenerar_indice_tras_enriquecimiento falló: %s", e
                    )

                return {
                    "needs_agent_read": False,
                    "indexed": True,
                    "filename": filename,
                    "path": str(indexed_path),
                    "pending_tasks": pending_tasks_acumuladas,
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
            # v6.20 F7: hash en rama arbitraria
            source_sha256_actual_arb = _hashlib.sha256(content_bytes).hexdigest()
            metadata_path_pre_arb = workspace / "_metadata.json"
            source_sha256_previo_arb = ""
            if metadata_path_pre_arb.exists():
                try:
                    meta_pre_arb = _json.loads(metadata_path_pre_arb.read_text(encoding="utf-8"))
                    source_sha256_previo_arb = meta_pre_arb.get("source_sha256", "") or ""
                except (_json.JSONDecodeError, ValueError):
                    pass

            if source_sha256_previo_arb and source_sha256_previo_arb != source_sha256_actual_arb and not force_rebuild:
                logger.info("v6.20 F7: fuente arbitraria cambiada — pidiendo autorización")
                _cascada_actualizar_estado_daemon(
                    workspace_dir=workspace,
                    status="waiting_for_authorization",
                    tarea_actual="Fuente arbitraria cambiada — esperando autorización",
                )
                return {
                    "needs_agent_read": False,
                    "indexed": False,
                    "needs_authorization": True,
                    "filename": filename,
                    "reason": f"El archivo cambió. Autoriza con force_rebuild=true.",
                }

            if source_sha256_previo_arb and source_sha256_previo_arb != source_sha256_actual_arb and force_rebuild:
                logger.info("v6.20 F7: force_rebuild=True — eliminando bloques arbitrarios viejos")
                for bloque_file in workspace.glob("bloque_*.md"):
                    try:
                        bloque_file.unlink()
                    except Exception as e:
                        logger.warning("v6.20 F7: no se pudo eliminar %s: %s", bloque_file, e)

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
            # v6.19 F1 (P1/P5): chat_id del chat actual siempre poblado.
            if chat_id:
                meta["chat_id"] = chat_id
                if not meta.get("share_id"):
                    meta["share_id"] = ""
            # v6.19 F5 (P6/P7): hash SHA256 del documento fuente.
            meta["source_sha256"] = _hashlib.sha256(content_bytes).hexdigest()
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
            # v7.0 modularización: delega a CicloW3.collect_responses() que
            # es la implementación real. Esta wrapper se mantiene por
            # compatibilidad con código externo que llama
            # ``ContextoPipeline.collect_responses()``.
            return CicloW3.collect_responses(
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


def ampliar_contexto(
    source_type: str,
    source_path: str,
    jwt: str = "",
    metadata: Optional[dict] = None,
    workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
    chat_id: str = "",
    force_rebuild: bool = False,
) -> dict:
    """v6.11 F5 → v6.18 F1 → v6.19 F1+F5: Wrapper que delega a ContextoPipeline.ampliar_contexto().

    v6.18 F1: si la estructura del archivo externo es ``cronologico``
    (marcadores ``## Exchange N -- [timestamp]``), el flujo pasa por
    ``RecoveryCycle`` (reusar, no duplicar lógica). Si es ``arbitrario``,
    sigue por ``ProcesadorDocumento``.

    v6.19 F1 (P1/P5 conciliados): ``chat_id`` siempre del chat actual.
    La cabecera de ``00_estado_actual.md`` y los campos ``chat_id`` y
    ``share_id`` de ``_metadata.json`` se poblan con el ``chat_id`` del
    chat actual donde corre el agente, sin importar si la fuente es un
    chat vivo de Z.ai o un archivo externo.

    v6.19 F5 (P6/P7 conciliados): hash SHA256 del documento fuente
    comparado con ``_metadata.json["source_sha256"]``. Si difieren,
    eliminar todos los ``bloque_*.md`` antes de regenerar (la fuente
    cambió). Si coinciden, preservar (re-corrida del mismo documento).
    Aplica a todas las fuentes externas.
    """
    return ContextoPipeline.ampliar_contexto(
        source_type=source_type,
        source_path=source_path,
        jwt=jwt,
        metadata=metadata,
        workspace_dir=workspace_dir,
        chat_id=chat_id,
        force_rebuild=force_rebuild,
    )


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
            result_audit = CicloW3._auditar_y_completar(ws)
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


# -- v6.2: Utility functions (v7.0 — mudadas de EnriquecimientoOrquestador) --

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


# -- v6.x backward-compat: wrappers que delegan a los nuevos módulos --
#
# Estos wrappers se mantienen para no romper código externo (tests,
# mini-services, etc.) que importaba las funciones módulo-nivel de
# pipeline.py. Apuntan a las implementaciones reales en
# pipeline_cascada, pipeline_w3, pipeline_d7 y pipeline_archivos.
# Se eliminarán en fases posteriores cuando todos los llamadores estén
# actualizados.

# -- desde pipeline_cascada --
_proxy_zai_disponible = _cascada_proxy_zai_disponible
_arrancar_worker_y_esperar = _cascada_arrancar_worker_y_esperar
_persistir_pending_task_en_disco = _cascada_persistir_pending_task_en_disco
_post_bloque = _cascada_post_bloque
_actualizar_estado_daemon = _cascada_actualizar_estado_daemon
_escribir_artefactos_bloque = _cascada_escribir_artefactos_bloque
_enriquecer_con_proxy_zai = _cascada_enriquecer_con_proxy_zai

# -- desde pipeline_w3 (métodos estáticos de CicloW3 expuestos como funciones) --
_ciclo_w3 = CicloW3._ciclo_w3
_validar_resumen_w3 = CicloW3._validar_resumen_w3
_validar_resumen_critico_subagente = CicloW3._validar_resumen_critico_subagente
_llamar_cascada_llm = CicloW3._llamar_cascada_llm
_enriquecer_bloques_con_fallback = CicloW3._enriquecer_bloques_con_fallback
_enriquecer_bloques_post_run = CicloW3._enriquecer_bloques_post_run
_descubrir_bloques_incompletos = CicloW3._descubrir_bloques_incompletos
_bloque_esta_completo = CicloW3._bloque_esta_completo
_auditar_y_completar = CicloW3._auditar_y_completar

# -- desde pipeline_d7 (métodos estáticos de CicloD7 expuestos como funciones) --
_bucle_d7_completitud = CicloD7._bucle_d7_completitud
_bucle_d7 = CicloD7._bucle_d7
_construir_pending_task_d7_corregido = CicloD7._construir_pending_task_d7_corregido
_ejecutar_pending_tasks_obligatorias = CicloD7._ejecutar_pending_tasks_obligatorias

# -- desde pipeline_archivos (métodos estáticos de SubprocesoArchivos como funciones) --
_generar_archivos_recuperacion = SubprocesoArchivos._generar_archivos_recuperacion
_collect_responses_and_finalize = SubprocesoArchivos._collect_responses_and_finalize
_consolidar_decisiones_llm = SubprocesoArchivos._consolidar_decisiones_llm
_regenerar_indice_tras_enriquecimiento = SubprocesoArchivos._regenerar_indice_tras_enriquecimiento
_normalizar_bloques_externos = SubprocesoArchivos._normalizar_bloques_externos


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
