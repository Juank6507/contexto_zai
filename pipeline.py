# contexto_zai/pipeline.py -- Entry point del proceso: funcion run() que activa la recuperacion de contexto.
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
) -> OrchestratorResult:
    """Activa el proceso de recuperación de contexto.

    Es la función principal que el agente invoca cuando detecta
    pérdida de contexto o el Director lo indica.

    Args:
        chat_id: UUID interno del chat (viene en metadatos del gateway).
        jwt: JWT del Director.
        trigger: Tipo de disparador.
        reason: Razón legible de la activación.
        chat_label: Etiqueta del chat.
        workspace_dir: Directorio donde se escriben los archivos
            de recuperación en el workspace del agente.
        download_dir: Directorio de descarga (copia para el Director).

    Returns:
        OrchestratorResult con el resultado de la activación.

    Example:
        >>> from contexto_zai.pipeline import run
        >>> from contexto_zai.models import DetectionTrigger
        >>> result = run(
        ...     chat_id="13b43432-...",
        ...     jwt="eyJhbG...",
        ...     trigger=DetectionTrigger.EXPLICITO,
        ...     reason="Director indicó pérdida de contexto",
        ... )
        >>> if result.success:
        ...     print(f"Recuperacion: ciclo={result.cycle_used}")
    """
    orch = Orchestrator(
        chat_id=chat_id,
        jwt=jwt,
        workspace_dir=workspace_dir,
        download_dir=download_dir,
    )
    return orch.activate(
        trigger=trigger,
        reason=reason,
        chat_label=chat_label,
    )

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
    """Prepara la consulta al proceso de contexto con una pregunta concreta (F4 v4.2).

    Usa ``ProcesadorConsulta`` para identificar bloques candidatos, decidir
    el modo (directo o distribuido según tamaño), y publicar las tareas vía
    el ``Orquestador``. El agente lanza los subagentes con el Task tool y
    llama a ``collect_responses()`` para recibir la respuesta consolidada.

    Args:
        question: Pregunta concreta del agente.
        max_results: Máximo de bloques a consultar.
        workspace_dir: Directorio donde están los archivos de recuperación.

    Returns:
        Dict con:
        - "mode": "directo" o "distribuido"
        - "question": la pregunta original
        - "prompts": lista de prompts (1 para directo, N para distribuido)
        - "bloques": lista de nombres de bloques candidatos
        - "total_tokens": tamaño total estimado de los bloques
        - "pending_tasks": lista de SubagentTask publicadas
        - Si no hay contexto: {"error": "No hay contexto recuperado..."}
        - Si no hay candidatos: {"error": "No hay información relevante..."}

    Example:
        >>> from contexto_zai.pipeline import query_context, collect_responses
        >>> result = query_context("¿Qué se decidió sobre OOP?")
        >>> if "pending_tasks" in result:
        ...     # El agente lanza los subagentes con el Task tool
        ...     # Los subagentes escriben en _responses/
        ...     applied = collect_responses()
    """
    from contexto_zai.config import QUERY_MAX_RESULTS
    from contexto_zai.coordinador import Orquestador
    from contexto_zai.procesadores import ProcesadorConsulta

    effective_max = min(max_results, QUERY_MAX_RESULTS)
    workspace = Path(workspace_dir)

    # Crear Orquestador + ProcesadorConsulta
    orquestador = Orquestador(workspace_dir=workspace)
    procesador = ProcesadorConsulta(
        workspace_dir=workspace,
        orquestador=orquestador,
    )

    # Procesar la consulta
    result = procesador.procesar(pregunta=question, max_results=effective_max)

    # Si hay error, devolverlo
    if "error" in result:
        return result

    # Convertir pending_tasks a prompts para compatibilidad con el contrato anterior
    prompts = [t.prompt for t in result.get("pending_tasks", [])]

    return {
        "mode": result.get("modo", "directo"),
        "question": question,
        "prompts": prompts,
        "bloques": result.get("bloques_candidatos", []),
        "total_tokens": result.get("total_tokens", 0),
        "pending_tasks": result.get("pending_tasks", []),
    }


# -- v4.2: Coordinación proceso-agente (F2) ----------------------------------


def collect_responses(
    workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
) -> dict:
    """F2 v4.2: Recoge las respuestas de los subagentes y las integra a los archivos.

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
        - "integradas": True si se aplicaron (F4 conectará el integrador).
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

    return orch.aplicar_respuestas(integrador=integrador)


# -- v4.0: Ampliación de contexto desde fuentes externas (M9) ----------------


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
        ATTACHMENTS_INDEXED_DIR,
        ATTACHMENTS_TEMP_DIR,
        WORKSPACE_OUTPUT_DIR as _WS_DIR,
    )

    workspace = Path(workspace_dir)
    metadata = metadata or {}

    # 1. Si es URL de Z.ai (/s/ o /c/), usar el flujo normal de extracción de chat
    if source_type == "url" and ("chat.z.ai/s/" in source_path or "chat.z.ai/c/" in source_path):
        return {
            "error": "URL de chat de Z.ai detectada. Use pipeline.run() con el chat_id correspondiente, no ampliar_contexto()."
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

    # 5. Si es grande, usar ProcesadorDocumento (F4 v4.2).
    # El ProcesadorDocumento decide según tamaño (mediano=un subagente, grande=3 niveles)
    # y publica las tareas en _pending_tasks.json. El agente lanza los subagentes y
    # llama a collect_responses() para que el Integrador actualice el contexto.
    from contexto_zai.coordinador import Orquestador
    from contexto_zai.procesadores import ProcesadorDocumento

    # Guardar en temp primero
    ATTACHMENTS_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    safe_filename = filename.replace(" ", "_").replace("/", "_")
    temp_path = ATTACHMENTS_TEMP_DIR / f"ampliar_{safe_filename}"
    temp_path.write_bytes(content_bytes)

    # F4: crear Orquestador + ProcesadorDocumento y procesar
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
    ATTACHMENTS_INDEXED_DIR.mkdir(parents=True, exist_ok=True)
    indexed_path = ATTACHMENTS_INDEXED_DIR / safe_filename
    if temp_path.exists():
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

    # Test 3: signature de run()
    import inspect
    sig = inspect.signature(run)
    expected_params = {"chat_id", "jwt", "trigger", "reason", "chat_label", "workspace_dir", "download_dir"}
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

    # Test 10 (v3.5): index_document con file_id inválido devuelve None
    result_invalid = index_document(
        file_id="invalid-uuid",
        jwt="fake-jwt",
        filename="test.pdf",
    )
    # Debe devolver None (no crashear) porque el JWT es falso
    assert result_invalid is None or (
        hasattr(result_invalid, "success") and not result_invalid.success
    ), "index_document debe manejar errores gracefully"
    print(f"[OK] index_document() con file_id inválido: maneja error correctamente")

    # Test 11 (v3.6): index_document_large disponible
    assert callable(index_document_large), "index_document_large debe ser callable"
    sig_large = inspect.signature(index_document_large)
    assert {"file_id", "jwt", "filename", "content_type", "size"} <= set(sig_large.parameters.keys())
    print(f"[OK] index_document_large(): disponible con {len(sig_large.parameters)} params")

    # Test 12 (v3.6): index_document_large con file_id inválido
    result_large_invalid = index_document_large(
        file_id="invalid-uuid",
        jwt="fake-jwt",
        filename="large.pdf",
        size=1652025,  # ~165K tokens → documento grande
    )
    assert result_large_invalid is None or (
        hasattr(result_large_invalid, "success") and not result_large_invalid.success
    ), "index_document_large debe manejar errores gracefully"
    print(f"[OK] index_document_large() con file_id inválido: maneja error")

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
        assert result["mode"] == "directo", f"Esperaba modo directo, obtuvo {result['mode']}"
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
        assert result2["mode"] == "directo"
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
        assert result["mode"] == "distribuido", f"Esperaba distribuido, obtuvo {result['mode']}"
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

    # Test 21 (v4.0): ampliar_contexto con URL de chat de Z.ai (debe rechazar)
    result = ampliar_contexto("url", "https://chat.z.ai/s/abc-123")
    assert "error" in result
    assert "chat de Z.ai" in result["error"]
    print(f"[OK] ampliar_contexto URL de Z.ai: rechazada (usar pipeline.run)")

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

    print("\n[PASS] pipeline.py: todos los tests pasaron")
