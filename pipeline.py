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

    print("\n[PASS] pipeline.py: todos los tests pasaron")
