# contexto_zai/pipeline.py -- Entry point del proceso (v6.8.2): _arrancar_worker_y_esperar detecta puerto 8090 en uso, _normalizar_bloques_externos restaurada, enriquecimiento sin try/except silencioso, errores visibles.
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

from contexto_zai.config import DOWNLOAD_OUTPUT_DIR, WORKSPACE_OUTPUT_DIR
from contexto_zai.models import DetectionTrigger
from contexto_zai.process.orchestrator import Orchestrator, OrchestratorResult

logger = logging.getLogger(__name__)

def run(
    chat_id: str,
    jwt: str,
    trigger: DetectionTrigger = DetectionTrigger.EXPLICITO,
    reason: str = "",
    chat_label: str = "",
    workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
    download_dir: Path | str = DOWNLOAD_OUTPUT_DIR,
    share_id: Optional[str] = None,
) -> OrchestratorResult:
    """Activa el proceso de recuperación de contexto.

    Es la función principal que el agente invoca cuando detecta
    pérdida de contexto o el Director lo indica.

    Args:
        chat_id: UUID interno del chat (viene en metadatos del gateway).
            Puede estar vacío si se pasa ``share_id`` externo (v4.2).
        jwt: JWT del Director.
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

    Example:
        >>> from contexto_zai.pipeline import run
        >>> from contexto_zai.models import DetectionTrigger
        >>> # Caso 1: chat actual del agente
        >>> result = run(chat_id="13b43432-...", jwt="eyJhbG...")
        >>> # Caso 2: chat externo vía link /s/ (v4.2)
        >>> result = run(chat_id="", jwt="eyJhbG...", share_id="abc-123")
    """
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
    # v6.2: post-procesar bloques con fallback al agente si el proxy APA falla
    result = _enriquecer_bloques_post_run(
        result=result,
        workspace_dir=workspace_dir,
        chat_label=chat_label,
    )
    # v6.3 F1: ejecutar pending_tasks obligatorias antes de devolver el resultado.
    # Garantiza que el proceso NO termine con tareas pendientes sin intentar
    # resolverlas vía collect_responses().
    result = _ejecutar_pending_tasks_obligatorias(
        result=result,
        workspace_dir=workspace_dir,
    )
    # v6.4 F1: consolidar decisiones del LLM (de _responses/) en 02_decisiones_clave.md
    _consolidar_decisiones_llm(workspace_dir=workspace_dir)
    return result

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


# -- v4.2: Coordinación proceso-agente ----------------------------------


def collect_responses(
    workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
) -> dict:
    """v4.2: Recoge las respuestas de los subagentes y las integra a los archivos.

    Tras ``pipeline.run()`` y el lanzamiento de subagentes por parte del agente,
    esta función lee las respuestas que los subagentes escribieron en
    ``_responses/``, las integra a los archivos de recuperación, y devuelve
    el resultado estructurado.

    El agente nunca ve el contenido crudo de las respuestas — solo llama
    a esta función y recibe el resultado estructurado.

    Args:
        workspace_dir: Directorio del workspace donde viven _pending_tasks.json
            y _responses/.

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

    resultado = orch.aplicar_respuestas(integrador=integrador)

    # v6.6 F3 fix (Bug 7): enriquecer bloques nuevos después de que
    # collect_responses() los haya escrito al disco. Antes, el enriquecimiento
    # se invocaba desde ampliar_contexto() PERO antes de que los subagentes
    # corrieran — los bloques físicos no existían todavía. El momento correcto
    # es aquí, después de aplicar las respuestas (los bloques ya están en disco).
    # Esto aplica tanto para bloques externos (de ampliar_contexto) como para
    # bloques del chat que hayan quedado sin RESUMEN.
    # Si el Worker Bun falla o hace timeout, el fallback genera pending_tasks
    # para que el agente las ejecute con subagentes (diseño v6.2).
    try:
        bloques_sin_resumen = _descubrir_bloques_sin_resumen(workspace_dir)
        if bloques_sin_resumen:
            _enriquecer_bloques_con_fallback(
                blocks=bloques_sin_resumen,
                workspace_dir=workspace_dir,
                chat_label="collect_responses",
            )
            # Si el enriquecimiento generó pending_tasks (fallback a subagentes),
            # añadirlas al resultado para que el agente las ejecute.
            from contexto_zai.coordinador import Orquestador as _Orq
            orch2 = _Orq(workspace_dir=workspace_dir)
            nuevas_tasks = orch2.leer_tareas_pendientes()
            if nuevas_tasks:
                resultado.setdefault("pending_tasks", []).extend(nuevas_tasks)
    except Exception as e:
        logger.warning("v6.6 F3 Bug 7 fix: error en enriquecimiento tras collect_responses: %s", e)

    return resultado


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
) -> dict:
    """Amplía el contexto desde una fuente externa (link o archivo).

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

    # 1. v4.2: Si es URL de Z.ai, distinguir /s/ (share público) de /c/ (chat completo).
    # Ambos se procesan como recuperación completa (con los 3 archivos de
    # recuperación), porque pueden ser una sesión anterior del agente cuya
    # reanudación requiere estado actual + índice + decisiones.
    if source_type == "url" and "chat.z.ai/" in source_path:
        # v4.2 Bug A fix: distinguir /s/ (share) de /c/ (chat completo).
        # /s/<share_id> → flujo share público: pipeline.run(chat_id="", share_id=...)
        # /c/<chat_id>  → flujo chat_id normal: pipeline.run(chat_id=..., share_id=None)
        es_link_share = "/s/" in source_path
        es_link_chat = "/c/" in source_path

        if es_link_share:
            share_id_extraido = _extraer_id_de_link(source_path, "share")
            if not share_id_extraido:
                return {
                    "error": f"No se pudo extraer el share_id del link /s/: {source_path}. "
                    f"Formato esperado: https://chat.z.ai/s/<uuid>."
                }
            logger.info(
                "ampliar_contexto: link /s/ de Z.ai detectado, share_id='%s' — "
                "procesando como recuperación (vía pipeline.run)",
                share_id_extraido,
            )
            # JWT: del metadata o del parámetro jwt
            jwt_para_run = metadata.get("jwt", "") if isinstance(metadata, dict) else ""
            if not jwt_para_run and jwt:
                jwt_para_run = jwt
            if not jwt_para_run:
                return {
                    "error": "Se requiere JWT del Director para procesar un link /s/ "
                    "de Z.ai. Pásalo en metadata={'jwt': '...'}."
                }
            resultado = run(
                chat_id="",  # se descubre del árbol del share
                jwt=jwt_para_run,
                workspace_dir=workspace_dir,
                download_dir=workspace,  # mismo dir
                share_id=share_id_extraido,
            )
            return {
                "procesado_como_recuperacion": True,
                "tipo_link": "share_publico",
                "share_id": share_id_extraido,
                "success": resultado.success,
                "cycle_used": resultado.cycle_used,
                "exchanges_processed": resultado.exchanges_processed,
                "files_generated": resultado.files_generated,
                "error": resultado.error,
                "pending_tasks": resultado.pending_tasks,
            }

        elif es_link_chat:
            chat_id_extraido = _extraer_id_de_link(source_path, "chat")
            if not chat_id_extraido:
                return {
                    "error": f"No se pudo extraer el chat_id del link /c/: {source_path}. "
                    f"Formato esperado: https://chat.z.ai/c/<uuid>."
                }
            logger.info(
                "ampliar_contexto: link /c/ de Z.ai detectado, chat_id='%s' — "
                "procesando como recuperación (vía pipeline.run)",
                chat_id_extraido,
            )
            # JWT: del metadata o del parámetro jwt
            jwt_para_run = metadata.get("jwt", "") if isinstance(metadata, dict) else ""
            if not jwt_para_run and jwt:
                jwt_para_run = jwt
            if not jwt_para_run:
                return {
                    "error": "Se requiere JWT del Director para procesar un link /c/ "
                    "de Z.ai. Pásalo en metadata={'jwt': '...'}."
                }
            # /c/ usa el flujo normal de create_share(chat_id)
            resultado = run(
                chat_id=chat_id_extraido,
                jwt=jwt_para_run,
                workspace_dir=workspace_dir,
                download_dir=workspace,
                share_id=None,  # se crea con create_share(chat_id)
            )
            return {
                "procesado_como_recuperacion": True,
                "tipo_link": "chat_completo",
                "chat_id": chat_id_extraido,
                "success": resultado.success,
                "cycle_used": resultado.cycle_used,
                "exchanges_processed": resultado.exchanges_processed,
                "files_generated": resultado.files_generated,
                "error": resultado.error,
                "pending_tasks": resultado.pending_tasks,
            }

    # 2. Obtener el contenido
    temp_path = None
    if source_type == "file":
        file_path = Path(source_path)
        if not file_path.exists():
            return {"error": f"Archivo no encontrado: {source_path}"}
        content_bytes = file_path.read_bytes()
        filename = file_path.name
    elif source_type == "url":
        # Descargar con requests
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
    else:
        return {"error": f"source_type no válido: {source_type}. Use 'url' o 'file'."}

    # 3. Estimar tokens
    estimated_tokens = len(content_bytes) / 3.5  # aprox 1 token = 3.5 bytes

    logger.info(
        "ampliar_contexto: %s '%s' -> %d bytes, ~%d tokens",
        source_type, filename, len(content_bytes), int(estimated_tokens),
    )

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
    }


# -- v6.2: Fallback al agente con subagentes cuando el proxy APA falla --------
#
# QUÉ SOLUCIONA: en v6.1, si el proxy APA agota su cuota diaria, el Worker Bun
# marca los bloques como `failed` y el proceso no completa.
# CÓMO LO HACE: el pipeline.run() consulta el proxy APA antes de arrancar el
# Worker Bun. Si el proxy no responde (429, error, timeout), o si el worker no
# completa todos los bloques, los bloques sin RESUMEN: van a pending_tasks para
# que el agente principal los procese lanzando subagentes (como en v5.0).
# El agente solo gasta ventana cuando el proxy no está disponible.


def _proxy_apa_disponible() -> bool:
    """v6.2: Hace un ping mínimo al proxy APA. Devuelve True si responde 200.

    Usa ``PROXY_APA_URL`` y ``PROXY_APA_TIMEOUT`` de config.py.
    Si la importación de ``requests`` falla, usa ``urllib`` (built-in).
    """
    try:
        from contexto_zai.config import PROXY_APA_TIMEOUT, PROXY_APA_URL
    except ImportError:
        return False
    payload = '{"model":"glm-4-flash","messages":[{"role":"user","content":"ping"}],"max_tokens":3}'
    try:
        import urllib.request as _ur
        import urllib.error as _ue
        req = _ur.Request(
            PROXY_APA_URL,
            data=payload.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _ur.urlopen(req, timeout=PROXY_APA_TIMEOUT) as resp:
            return resp.status == 200
    except _ue.HTTPError as e:
        # 429 u otros códigos HTTP → proxy caído para nuestros fines
        logger.info("v6.2 _proxy_apa_disponible(): HTTP %d", e.code)
        return False
    except Exception as e:
        logger.info("v6.2 _proxy_apa_disponible(): error %s", e)
        return False


def _arrancar_worker_y_esperar(
    workspace_dir: Path | str,
    timeout: Optional[int] = None,
) -> bool:
    """v6.2: Arranca el Worker Bun (v6.1) y espera a que termine.

    Publica ``_pending_blocks.json`` con los bloques del workspace, arranca el
    worker vía ``subprocess.run()`` con timeout, y devuelve True si el worker
    completó (exit code 0), False si falló o hizo timeout.

    v6.8.2 F2: verifica si el puerto 8090 ya está en uso antes de intentar
    arrancar otro Worker Bun. Si ya hay uno corriendo, lo reutiliza.

    Args:
        workspace_dir: Directorio del workspace (donde viven los bloque_NN.md).
        timeout: Segundos máximos (default: ``WORKER_BUN_TIMEOUT`` de config).

    Returns:
        True si el worker completó (exit code 0), False si falló o timeout.
    """
    import subprocess
    import socket as _socket
    try:
        from contexto_zai.config import WORKER_BUN_DIR, WORKER_BUN_TIMEOUT as _DEFAULT_TIMEOUT
    except ImportError:
        logger.warning("v6.2: no se pudo importar WORKER_BUN_DIR, fallback desactivado")
        return False
    timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT
    if not Path(WORKER_BUN_DIR).exists():
        logger.warning("v6.2: WORKER_BUN_DIR no existe: %s", WORKER_BUN_DIR)
        return False

    # v6.8.2 F2: verificar si el puerto 8090 ya está en uso (Worker Bun existente)
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
        logger.info("v6.8.2 F2: puerto %d en uso — Worker Bun ya está corriendo, reutilizando",
                   WORKER_BUN_PORT)
        # Hay un Worker Bun corriendo. Esperar a que procese los bloques del
        # _pending_blocks.json y devolver True (asumimos que el worker existente
        # procesará los bloques porque lee el _pending_blocks.json del workspace).
        # Darle tiempo para que procese.
        import time as _time
        _time.sleep(min(timeout, 30))  # esperar hasta 30s o timeout
        return True

    env = {**_os.environ, "CZAI_WORKSPACE_DIR": str(workspace_dir)}
    try:
        result = subprocess.run(
            ["bun", "run", "cli.ts", "run"],
            cwd=WORKER_BUN_DIR,
            env=env,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info("v6.2: Worker Bun completó exitosamente.")
            return True
        logger.warning("v6.2: Worker Bun falló (exit code %d). stderr: %s",
                       result.returncode, (result.stderr or "")[:500])
        return False
    except subprocess.TimeoutExpired:
        logger.warning("v6.2: Worker Bun timeout tras %ds.", timeout)
        return False
    except FileNotFoundError:
        logger.warning("v6.2: 'bun' no está en PATH. Fallback desactivado.")
        return False
    except Exception as e:
        logger.warning("v6.2: Error arrancando Worker Bun: %s", e)
        return False


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


def _enriquecer_bloques_con_fallback(
    blocks: list,
    workspace_dir: Path | str,
    chat_label: str = "",
) -> list:
    """v6.2: Fase 2 — enriquecer bloques con resumen + extracción, con fallback.

    Orquesta el enriquecimiento de los bloques que no tienen RESUMEN: al inicio.
    El flujo:
    1. Filtra bloques sin RESUMEN:.
    2. Si no hay → devuelve [] (nada que hacer).
    3. Check proxy APA disponible.
    4. Si proxy OK: arranca Worker Bun, espera con timeout.
       - Re-verifica qué bloques quedaron sin RESUMEN:.
       - Si todos completaron → devuelve [] (worker OK).
       - Si algunos fallaron → construye pending_tasks solo para esos.
    5. Si proxy caído: construye pending_tasks para todos los bloques sin resumen.

    Args:
        blocks: Lista de ThematicBlock.
        workspace_dir: Directorio del workspace.
        chat_label: Etiqueta del chat (opcional).

    Returns:
        Lista de SubagentTask (vacía si todo OK, con tareas si fallback necesario).
    """
    # 1. Bloques sin RESUMEN:
    bloques_sin_resumen = [b for b in blocks if not b.tiene_resumen(workspace_dir=workspace_dir)]

    if not bloques_sin_resumen:
        logger.info("v6.2: Todos los bloques ya tienen resumen. Nada que hacer.")
        return []

    logger.info("v6.2: %d bloque(s) sin RESUMEN. Activando orquestación con fallback.",
                len(bloques_sin_resumen))

    # 3. Check proxy APA
    proxy_ok = _proxy_apa_disponible()
    logger.info("v6.2: Proxy APA: %s", "disponible" if proxy_ok else "no disponible")

    if proxy_ok:
        # 4. Arrancar Worker Bun
        logger.info("v6.2: Arrancando Worker Bun para %d bloque(s)...", len(bloques_sin_resumen))
        worker_ok = _arrancar_worker_y_esperar(workspace_dir=workspace_dir)

        if worker_ok:
            # Re-verificar qué bloques quedaron sin RESUMEN:
            bloques_aun_sin_resumen = [
                b for b in bloques_sin_resumen if not b.tiene_resumen(workspace_dir=workspace_dir)
            ]
            if not bloques_aun_sin_resumen:
                logger.info("v6.2: Worker Bun completó todos los bloques. Fallback no necesario.")
                return []
            logger.info("v6.2: Worker Bun falló en %d bloque(s). Fallback al agente.",
                        len(bloques_aun_sin_resumen))
            bloques_para_fallback = bloques_aun_sin_resumen
        else:
            logger.info("v6.2: Worker Bun no completó. Fallback al agente para todos los bloques.")
            bloques_para_fallback = bloques_sin_resumen
    else:
        logger.info("v6.2: Proxy APA no disponible. Fallback al agente para todos los bloques.")
        bloques_para_fallback = bloques_sin_resumen

    # Construir pending_tasks para los bloques que el worker no procesó
    pending_tasks = []
    for bloque in bloques_para_fallback:
        task = _construir_pending_task_para_bloque(bloque, chat_label=chat_label)
        pending_tasks.append(task)

    return pending_tasks


def _enriquecer_bloques_post_run(
    result: "OrchestratorResult",
    workspace_dir: Path | str,
    chat_label: str = "",
) -> "OrchestratorResult":
    """v6.2: Post-procesa un OrchestratorResult para añadir fallback de bloques.

    Llamada por ``pipeline.run()`` después de ``orch.activate()``. Examina los
    bloques físicos del workspace, identifica los que no tienen RESUMEN:, y
    orquesta el enriquecimiento (proxy APA → worker, si no → fallback al agente).

    Las pending_tasks que devuelve el Orchestrator original se conservan; las
    nuevas (fallback de bloques) se añaden a la lista.

    Args:
        result: OrchestratorResult devuelto por orch.activate().
        workspace_dir: Directorio del workspace.
        chat_label: Etiqueta del chat (opcional).

    Returns:
        El mismo OrchestratorResult con pending_tasks actualizadas.
    """
    try:
        # Listar bloques físicos del workspace
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

        # Orquestar enriquecimiento
        fallback_tasks = _enriquecer_bloques_con_fallback(
            blocks=blocks,
            workspace_dir=workspace_dir,
            chat_label=chat_label,
        )

        # Añadir a pending_tasks existentes
        if fallback_tasks:
            if result.pending_tasks is None:
                result.pending_tasks = []
            result.pending_tasks.extend(fallback_tasks)
            logger.info("v6.2: %d tarea(s) de fallback añadidas a pending_tasks.",
                        len(fallback_tasks))
    except Exception as e:
        logger.warning("v6.2: Error en post-procesamiento de bloques: %s", e)
    return result


def _ejecutar_pending_tasks_obligatorias(
    result: "OrchestratorResult",
    workspace_dir: Path | str,
) -> "OrchestratorResult":
    """v6.3 F1: Ejecuta las pending_tasks antes de devolver el resultado.

    QUÉ SOLUCIONA: en v6.2 el proceso podía devolver `pending_tasks` sin
    ejecutar, dejando archivos como `02_decisiones_clave.md` vacíos ("0
    decisiones") aunque el agente hubiera publicado tareas de extracción.
    CÓMO LO HACE: intenta `collect_responses()` que ejecuta las tareas vía
    el proxy APA si está disponible. Si tras eso aún quedan pendientes, las
    mantiene en `result.pending_tasks` y loggea un warning (no las oculta).

    Args:
        result: OrchestratorResult devuelto por orch.activate() + post-run.
        workspace_dir: Directorio del workspace.

    Returns:
        El mismo OrchestratorResult con pending_tasks actualizadas.
    """
    if not result.pending_tasks:
        logger.info("v6.3 F1: no hay pending_tasks que ejecutar.")
        return result

    initial_count = len(result.pending_tasks)
    logger.info("v6.3 F1: %d pending_task(s) detectada(s). Intentando resolver...", initial_count)

    # Intentar collect_responses() que ejecuta vía proxy APA si está disponible
    try:
        from contexto_zai.pipeline import collect_responses
        applied = collect_responses(workspace_dir=str(workspace_dir))
        logger.info("v6.3 F1: collect_responses() aplicó %d respuesta(s).", applied)
    except Exception as e:
        logger.warning("v6.3 F1: collect_responses() falló: %s", e)
        applied = 0

    # Re-leer pending_tasks tras collect_responses
    try:
        from contexto_zai.coordinador.orquestador import Orquestador
        orch = Orquestador(workspace_dir=workspace_dir)
        remaining = orch.leer_tareas_pendientes()
    except Exception as e:
        logger.warning("v6.3 F1: no se pudo re-leer pending_tasks: %s", e)
        remaining = result.pending_tasks

    resolved = initial_count - len(remaining)
    if hasattr(result, "pending_tasks_resolved"):
        result.pending_tasks_resolved = resolved
    else:
        # OrchestratorResult no tiene el campo (versiones viejas)
        pass

    if remaining:
        logger.warning(
            "v6.3 F1: %d tarea(s) pendientes sin resolver tras collect_responses() "
            "(resueltas: %d de %d). El agente principal debe ejecutarlas con Task tool.",
            len(remaining), resolved, initial_count,
        )
        result.pending_tasks = remaining
    else:
        logger.info(
            "v6.3 F1: todas las pending_tasks resueltas (%d de %d).",
            resolved, initial_count,
        )
        result.pending_tasks = []

    return result


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
