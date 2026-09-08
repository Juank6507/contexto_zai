# contexto_zai/subagents/documento_indexer_subagent.py -- Subagente que lee, clasifica y resume documentos adjuntos.
"""Subagente indexador de documentos (v3.5).

Subagente efímero que lee un documento adjunto (PDF, DOCX, TXT, etc.)
usando su propio contexto independiente, lo clasifica por temas, genera
un resumen breve, y actualiza el índice de materias. El agente principal
recibe solo el resumen + referencia al índice, no el contenido completo.

Flujo:
1. Descarga el archivo con AttachmentClient.
2. Lo guarda en temp/ para que el subagente pueda leerlo.
3. Lanza subagente con prompt estructurado.
4. El subagente lee el archivo (con Read o pdfplumber) y devuelve
   resumen + clasificación por temas.
5. Parsea la respuesta estructurada.
6. Mueve el archivo de temp/ a indexed/ para futuras consultas.
7. Devuelve DocumentoIndexResult al agente principal.

Atómico standalone: importa launcher, attachment_client, models.
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
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from contexto_zai.config import (
    ATTACHMENTS_INDEXED_DIR,
    ATTACHMENTS_TEMP_DIR,
    DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS,
)
from contexto_zai.models import Attachment
from contexto_zai.subagents.launcher import SubagentLauncher, SubagentResponse

logger = logging.getLogger(__name__)


# ── Modelos de salida ─────────────────────────────────────────────


@dataclass
class ThemeSection:
    """Sección temática detectada en un documento.

    Attributes:
        tema: Nombre del tema (snake_case).
        descripcion: Descripción corta del tema.
        secciones: Lista de secciones o subtemas dentro del tema.
    """

    tema: str
    descripcion: str = ""
    secciones: list[str] = field(default_factory=list)


@dataclass
class DocumentoIndexResult:
    """Resultado de indexar un documento.

    Attributes:
        attachment_id: file_id del attachment.
        filename: Nombre del archivo.
        resumen_breve: Resumen breve (≤ DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS).
        temas_detectados: Lista de temas detectados.
        archivo_indexado_path: Ruta donde quedó guardado el archivo para futuras consultas.
        success: Si la indexación fue exitosa.
        error: Mensaje de error si success=False.
    """

    attachment_id: str
    filename: str
    resumen_breve: str = ""
    temas_detectados: list[ThemeSection] = field(default_factory=list)
    archivo_indexado_path: Optional[Path] = None
    success: bool = False
    error: str = ""

    @property
    def temas_nombres(self) -> list[str]:
        """Lista de nombres de temas."""
        return [t.tema for t in self.temas_detectados]


# ── Subagente indexador de documentos ─────────────────────────────


class DocumentoIndexerSubagent:
    """Subagente que lee, clasifica y resume un documento adjunto.

    Args:
        launcher: SubagentLauncher para invocar el Task de Z.ai.
        attachment_client: AttachmentClient para descargar el archivo.
        max_resumen_chars: Tamaño máximo del resumen breve.
        temp_dir: Directorio temporal para descargar el archivo.
        indexed_dir: Directorio definitivo para archivos indexados.

    Usage:
        >>> sub = DocumentoIndexerSubagent(launcher=launcher, attachment_client=client)
        >>> result = sub.run(attachment)
        >>> if result.success:
        ...     print(result.resumen_breve)
        ...     print(result.temas_nombres)
    """

    def __init__(
        self,
        launcher: SubagentLauncher,
        attachment_client,
        max_resumen_chars: int = DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS,
        temp_dir: Path | str = ATTACHMENTS_TEMP_DIR,
        indexed_dir: Path | str = ATTACHMENTS_INDEXED_DIR,
    ) -> None:
        self._launcher = launcher
        self._attachment_client = attachment_client
        self._max_resumen_chars = max_resumen_chars
        self._temp_dir = Path(temp_dir)
        self._indexed_dir = Path(indexed_dir)
        logger.debug(
            "DocumentoIndexerSubagent inicializado: max_resumen=%d, temp=%s, indexed=%s",
            max_resumen_chars, self._temp_dir, self._indexed_dir,
        )

    # ── API pública ──────────────────────────────────────────────

    def run(self, attachment: Attachment) -> DocumentoIndexResult:
        """Lee, clasifica y resume el documento adjunto.

        Args:
            attachment: Objeto Attachment con file_id y filename.

        Returns:
            DocumentoIndexResult con el resumen, temas y ruta del archivo indexado.
        """
        # 1. Descargar el archivo
        try:
            content_bytes = self._attachment_client.download(attachment.file_id)
        except Exception as e:
            logger.error("Error descargando attachment %s: %s", attachment.file_id, e)
            return DocumentoIndexResult(
                attachment_id=attachment.file_id,
                filename=attachment.filename,
                success=False,
                error=f"Download error: {e}",
            )

        # 2. Guardar en temp/
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        safe_filename = self._sanitize_filename(attachment.filename)
        temp_path = self._temp_dir / f"{attachment.file_id}_{safe_filename}"
        try:
            temp_path.write_bytes(content_bytes)
        except Exception as e:
            logger.error("Error guardando archivo temporal %s: %s", temp_path, e)
            return DocumentoIndexResult(
                attachment_id=attachment.file_id,
                filename=attachment.filename,
                success=False,
                error=f"Temp file error: {e}",
            )

        # 3. Construir prompt para el subagente
        prompt = self._build_prompt(attachment, temp_path)

        # 4. Lanzar subagente
        try:
            response: SubagentResponse = self._launcher.launch(
                prompt=prompt,
                files_to_read=[str(temp_path)],
                description=f"Indexar documento {attachment.filename}",
            )
        except Exception as e:
            logger.error("Error lanzando subagente: %s", e)
            return DocumentoIndexResult(
                attachment_id=attachment.file_id,
                filename=attachment.filename,
                archivo_indexado_path=temp_path,
                success=False,
                error=f"Subagent launch error: {e}",
            )

        if not response.success:
            return DocumentoIndexResult(
                attachment_id=attachment.file_id,
                filename=attachment.filename,
                archivo_indexado_path=temp_path,
                success=False,
                error=f"Subagent error: {response.error}",
            )

        # 5. Parsear respuesta
        resumen, temas = self._parse_response(response.content)

        # Truncar resumen si excede el máximo
        if len(resumen) > self._max_resumen_chars:
            resumen = resumen[: self._max_resumen_chars - 3] + "..."

        # 6. Mover de temp/ a indexed/
        self._indexed_dir.mkdir(parents=True, exist_ok=True)
        indexed_path = self._indexed_dir / temp_path.name
        try:
            if indexed_path.exists():
                indexed_path.unlink()  # sobrescribir si ya existe
            temp_path.rename(indexed_path)
        except Exception as e:
            logger.warning("Error moviendo a indexed/: %s. Queda en temp/", e)
            indexed_path = temp_path  # fallback: queda en temp

        logger.info(
            "Documento indexado: %s (%d temas, resumen=%d chars, archivo=%s)",
            attachment.filename, len(temas), len(resumen), indexed_path.name,
        )

        return DocumentoIndexResult(
            attachment_id=attachment.file_id,
            filename=attachment.filename,
            resumen_breve=resumen,
            temas_detectados=temas,
            archivo_indexado_path=indexed_path,
            success=True,
        )

    # ── Métodos privados ─────────────────────────────────────────

    def _build_prompt(self, attachment: Attachment, file_path: Path) -> str:
        """Construye el prompt para el subagente indexador."""
        return f"""Eres un subagente indexador de documentos. Tu objetivo es leer
un documento y generar un índice estructurado que permita al agente principal
saber de qué trata sin haberlo leído.

Documento a indexar: {attachment.filename}
Tipo: {attachment.content_type}
Tamaño: {attachment.size:,} bytes
Ruta del archivo: {file_path}

Tu tarea:
1. Lee el archivo en {file_path} usando la herramienta Read.
2. Identifica los temas principales que se discuten en el documento.
3. Genera un resumen breve del documento (máximo {self._max_resumen_chars} caracteres).
4. Lista los temas con sus secciones para que el agente principal pueda
   consultarlos después.

Formato de respuesta EXACTO (respeta el formato):

RESUMEN: <resumen breve del documento, máx {self._max_resumen_chars} chars>

TEMA: <nombre_snake_case>
DESCRIPCION: <descripción corta del tema>
SECCIONES: <sección1, sección2, sección3>

TEMA: <nombre_snake_case>
DESCRIPCION: <descripción corta>
SECCIONES: <sección1, sección2>

(Repetir bloque TEMA/DESCRIPCION/SECCIONES por cada tema detectado)

Reglas:
- Nombres de tema en snake_case (sin espacios, sin acentos).
- Máximo 5 temas.
- Cada tema debe tener al menos 1 sección.
- El resumen debe ser conciso y revelador (no genérico).
- No incluyas el contenido completo del documento.

Respuesta:"""

    def _parse_response(
        self,
        content: str,
    ) -> tuple[str, list[ThemeSection]]:
        """Parsea la respuesta del subagente en resumen + temas.

        Formato esperado:
            RESUMEN: <texto>

            TEMA: <nombre>
            DESCRIPCION: <desc>
            SECCIONES: <s1, s2, s3>

            TEMA: <nombre>
            ...
        """
        # Extraer RESUMEN (hasta el primer "TEMA:" o fin de texto)
        resumen_match = re.search(
            r"RESUMEN:\s*(.+?)(?=\n\s*TEMA:|\Z)",
            content,
            re.DOTALL,
        )
        resumen = resumen_match.group(1).strip() if resumen_match else ""

        # Extraer bloques TEMA/DESCRIPCION/SECCIONES
        pattern = re.compile(
            r"TEMA:\s*(\S+)\s*\n\s*DESCRIPCION:\s*(.+?)\s*\n\s*SECCIONES:\s*(.+?)(?=\n\s*TEMA:|\Z)",
            re.DOTALL,
        )

        temas: list[ThemeSection] = []
        for match in pattern.finditer(content):
            nombre = match.group(1).strip()
            descripcion = match.group(2).strip()
            secciones_str = match.group(3).strip()

            # Sanitizar nombre del tema (snake_case)
            nombre = self._sanitize_tema_name(nombre)

            # Parsear secciones separadas por coma
            secciones = [
                s.strip()
                for s in secciones_str.split(",")
                if s.strip()
            ]

            if nombre and descripcion:
                temas.append(ThemeSection(
                    tema=nombre,
                    descripcion=descripcion,
                    secciones=secciones,
                ))

        return resumen, temas

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Sanitiza un nombre de archivo para usarlo en disco.

        - Reemplaza espacios y caracteres especiales por '_'.
        - Elimina acentos.
        """
        if not filename:
            return "documento"
        # Normalizar acentos
        normalized = unicodedata.normalize("NFKD", filename)
        ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
        # Reemplazar caracteres no alfanuméricos (excepto . y -)
        sanitized = re.sub(r"[^a-zA-Z0-9.\-]", "_", ascii_str)
        return sanitized or "documento"

    @staticmethod
    def _sanitize_tema_name(name: str) -> str:
        """Convierte un nombre a snake_case válido."""
        if not name:
            return "tema"
        normalized = unicodedata.normalize("NFKD", name)
        ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
        ascii_str = ascii_str.lower()
        sanitized = re.sub(r"[^a-z0-9]+", "_", ascii_str)
        return sanitized.strip("_") or "tema"

    def __repr__(self) -> str:
        return (
            f"DocumentoIndexerSubagent(max_resumen={self._max_resumen_chars}, "
            f"temp={self._temp_dir.name}, indexed={self._indexed_dir.name})"
        )


# ── Auto-tests atómicos ───────────────────────────────────────────

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

    print("=== Validacion de documento_indexer_subagent.py ===\n")

    import tempfile
    from contexto_zai.models import Attachment

    # Mock del AttachmentClient
    class MockAttachmentClient:
        def __init__(self, content: bytes = b"%PDF-1.4 test content"):
            self._content = content

        def download(self, file_id: str) -> bytes:
            if file_id == "fail-download":
                raise RuntimeError("network error")
            return self._content

    # Mock invoker que simula la respuesta del subagente
    def mock_invoker_valid(prompt: str) -> str:
        return """RESUMEN: Documento de 208 páginas con la memoria completa del proyecto CZAI. Incluye worklog de sesiones previas, especificación técnica del sistema de recuperación de contexto v3.0-v3.4, metodología de descubrimiento del JWT, y decisiones arquitectónicas.

TEMA: worklog_sesiones_anteriores
DESCRIPCION: Registro de las primeras 8 sesiones del agente CZAI con tareas y archivos modificados
SECCIONES: sesion_1_clonacion, sesion_2_processing, sesion_3_generation

TEMA: especificacion_recuperacion_contexto
DESCRIPCION: Spec técnica del sistema de recuperación de contexto
SECCIONES: arquitectura, modelos, limites_tokens

TEMA: metodologia_jwt
DESCRIPCION: Documentación del descubrimiento del JWT de autenticación
SECCIONES: cadena_descubrimiento, protocolo_cookie, endpoints_api"""

    # Test 1: subagente exitoso con PDF
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir) / "temp"
        indexed_dir = Path(tmpdir) / "indexed"

        launcher = SubagentLauncher(task_invoker=mock_invoker_valid)
        client = MockAttachmentClient(content=b"%PDF-1.4 fake pdf content")
        sub = DocumentoIndexerSubagent(
            launcher=launcher,
            attachment_client=client,
            temp_dir=temp_dir,
            indexed_dir=indexed_dir,
        )

        att = Attachment(
            file_id="abc-123",
            filename="CZAI-01.pdf",
            content_type="application/pdf",
            size=1652025,
        )

        result = sub.run(att)

        assert result.success, f"Debe ser success, error: {result.error}"
        assert result.filename == "CZAI-01.pdf"
        assert "memoria completa" in result.resumen_breve
        assert len(result.temas_detectados) == 3
        assert result.temas_detectados[0].tema == "worklog_sesiones_anteriores"
        assert "especificacion_recuperacion_contexto" in result.temas_nombres
        assert result.archivo_indexado_path is not None
        assert result.archivo_indexado_path.exists()
        # Archivo movido a indexed/
        assert result.archivo_indexado_path.parent == indexed_dir
        # Ya no está en temp/
        assert not (temp_dir / "abc-123_CZAI-01.pdf").exists()
        print(f"[OK] Subagente exitoso: 3 temas, resumen {len(result.resumen_breve)} chars")

    # Test 2: error de descarga
    with tempfile.TemporaryDirectory() as tmpdir:
        launcher = SubagentLauncher(task_invoker=mock_invoker_valid)
        client = MockAttachmentClient(content=b"test")
        sub = DocumentoIndexerSubagent(
            launcher=launcher, attachment_client=client,
            temp_dir=Path(tmpdir) / "temp", indexed_dir=Path(tmpdir) / "indexed",
        )
        att = Attachment(file_id="fail-download", filename="err.pdf", content_type="application/pdf")
        result = sub.run(att)
        assert not result.success
        assert "Download error" in result.error
        print(f"[OK] Error de descarga: capturado correctamente")

    # Test 3: subagente que falla (invoker lanza excepción)
    def failing_invoker(prompt: str) -> str:
        raise RuntimeError("Task API no disponible")

    with tempfile.TemporaryDirectory() as tmpdir:
        launcher = SubagentLauncher(task_invoker=failing_invoker)
        client = MockAttachmentClient()
        sub = DocumentoIndexerSubagent(
            launcher=launcher, attachment_client=client,
            temp_dir=Path(tmpdir) / "temp", indexed_dir=Path(tmpdir) / "indexed",
        )
        att = Attachment(file_id="abc-123", filename="test.pdf", content_type="application/pdf")
        result = sub.run(att)
        assert not result.success
        assert "Subagent" in result.error
        print(f"[OK] Subagente que falla: error capturado")

    # Test 4: respuesta mal formada del subagente
    def malformed_invoker(prompt: str) -> str:
        return "Esto no tiene el formato esperado, no hay RESUMEN ni TEMA"

    with tempfile.TemporaryDirectory() as tmpdir:
        launcher = SubagentLauncher(task_invoker=malformed_invoker)
        client = MockAttachmentClient()
        sub = DocumentoIndexerSubagent(
            launcher=launcher, attachment_client=client,
            temp_dir=Path(tmpdir) / "temp", indexed_dir=Path(tmpdir) / "indexed",
        )
        att = Attachment(file_id="abc-123", filename="test.pdf", content_type="application/pdf")
        result = sub.run(att)
        # Sigue siendo success (se guarda el archivo), pero sin temas detectados
        assert result.success
        assert result.resumen_breve == ""
        assert len(result.temas_detectados) == 0
        print(f"[OK] Respuesta mal formada: success pero sin temas")

    # Test 5: resumen truncado si excede máximo
    def long_resumen_invoker(prompt: str) -> str:
        long_resumen = "A" * 800  # excede 500
        return f"RESUMEN: {long_resumen}\n\nTEMA: tema1\nDESCRIPCION: desc\nSECCIONES: s1"

    with tempfile.TemporaryDirectory() as tmpdir:
        launcher = SubagentLauncher(task_invoker=long_resumen_invoker)
        client = MockAttachmentClient()
        sub = DocumentoIndexerSubagent(
            launcher=launcher, attachment_client=client, max_resumen_chars=500,
            temp_dir=Path(tmpdir) / "temp", indexed_dir=Path(tmpdir) / "indexed",
        )
        att = Attachment(file_id="abc-123", filename="test.pdf", content_type="application/pdf")
        result = sub.run(att)
        assert result.success
        assert len(result.resumen_breve) <= 500
        assert result.resumen_breve.endswith("...")
        print(f"[OK] Resumen truncado: {len(result.resumen_breve)} chars (≤500)")

    # Test 6: sanitización de nombres
    assert DocumentoIndexerSubagent._sanitize_filename("documento con espacios.pdf") == "documento_con_espacios.pdf"
    assert DocumentoIndexerSubagent._sanitize_filename("CZAI-01.pdf") == "CZAI-01.pdf"
    assert DocumentoIndexerSubagent._sanitize_filename("Configuración DB.docx") == "Configuracion_DB.docx"
    assert DocumentoIndexerSubagent._sanitize_filename("") == "documento"
    print(f"[OK] _sanitize_filename: acentos y espacios normalizados")

    # Test 7: sanitización de nombres de tema (snake_case)
    assert DocumentoIndexerSubagent._sanitize_tema_name("Auth JWT") == "auth_jwt"
    assert DocumentoIndexerSubagent._sanitize_tema_name("Configuración") == "configuracion"
    assert DocumentoIndexerSubagent._sanitize_tema_name("Tema-Con-Guiones") == "tema_con_guiones"
    assert DocumentoIndexerSubagent._sanitize_tema_name("") == "tema"
    print(f"[OK] _sanitize_tema_name: snake_case correcto")

    # Test 8: parsing de respuesta con 5 temas (límite)
    def many_themes_invoker(prompt: str) -> str:
        themes = "\n\n".join([
            f"TEMA: tema_{i}\nDESCRIPCION: desc {i}\nSECCIONES: s{i}a, s{i}b"
            for i in range(1, 8)  # 7 temas, más del límite de 5
        ])
        return f"RESUMEN: Resumen test\n\n{themes}"

    with tempfile.TemporaryDirectory() as tmpdir:
        launcher = SubagentLauncher(task_invoker=many_themes_invoker)
        client = MockAttachmentClient()
        sub = DocumentoIndexerSubagent(
            launcher=launcher, attachment_client=client,
            temp_dir=Path(tmpdir) / "temp", indexed_dir=Path(tmpdir) / "indexed",
        )
        att = Attachment(file_id="abc-123", filename="test.pdf", content_type="application/pdf")
        result = sub.run(att)
        assert result.success
        # El parser NO limita a 5 (eso lo hace el subagente en su prompt)
        # Aquí validamos que se parseen todos los que vengan
        assert len(result.temas_detectados) == 7
        print(f"[OK] Parsing: 7 temas detectados (subagente decide límite)")

    # Test 9: _build_prompt contiene info del archivo
        launcher = SubagentLauncher(task_invoker=mock_invoker_valid)
        client = MockAttachmentClient()
        sub = DocumentoIndexerSubagent(
            launcher=launcher, attachment_client=client,
            temp_dir=Path(tmpdir) / "temp", indexed_dir=Path(tmpdir) / "indexed",
        )
        att = Attachment(
            file_id="abc-123", filename="custom.pdf",
            content_type="application/pdf", size=99999,
        )
        # Necesitamos guardar el archivo primero para que el prompt tenga la ruta
        prompt = sub._build_prompt(att, Path("/fake/path/custom.pdf"))
        assert "custom.pdf" in prompt
        assert "application/pdf" in prompt
        assert "99,999" in prompt
        assert "RESUMEN:" in prompt
        assert "TEMA:" in prompt
        print(f"[OK] _build_prompt: incluye filename, tipo, tamaño y formato esperado")

    # Test 10: DocumentoIndexResult.temas_nombres
    result = DocumentoIndexResult(
        attachment_id="x", filename="x.pdf", success=True,
        temas_detectados=[
            ThemeSection(tema="t1", descripcion="d1", secciones=["s1"]),
            ThemeSection(tema="t2", descripcion="d2", secciones=["s2"]),
        ],
    )
    assert result.temas_nombres == ["t1", "t2"]
    print(f"[OK] DocumentoIndexResult.temas_nombres: {result.temas_nombres}")

    # Test 11: archivo ya existe en indexed/ (sobrescribe)
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir) / "temp"
        indexed_dir = Path(tmpdir) / "indexed"
        indexed_dir.mkdir(parents=True)
        # Pre-crear archivo con mismo nombre
        existing = indexed_dir / "abc-123_test.pdf"
        existing.write_bytes(b"old content")

        launcher = SubagentLauncher(task_invoker=mock_invoker_valid)
        client = MockAttachmentClient(content=b"new content")
        sub = DocumentoIndexerSubagent(
            launcher=launcher, attachment_client=client,
            temp_dir=temp_dir, indexed_dir=indexed_dir,
        )
        att = Attachment(file_id="abc-123", filename="test.pdf", content_type="application/pdf")
        result = sub.run(att)
        assert result.success
        # El archivo debe tener el contenido nuevo, no el viejo
        assert result.archivo_indexado_path.read_bytes() == b"new content"
        print(f"[OK] Archivo existente: sobrescrito correctamente")

    # Test 12: repr
    with tempfile.TemporaryDirectory() as tmpdir:
        launcher = SubagentLauncher(task_invoker=mock_invoker_valid)
        client = MockAttachmentClient()
        sub = DocumentoIndexerSubagent(
            launcher=launcher, attachment_client=client,
            temp_dir=Path(tmpdir) / "temp", indexed_dir=Path(tmpdir) / "indexed",
        )
        r = repr(sub)
        assert "DocumentoIndexerSubagent" in r
        assert "max_resumen=" in r
        print(f"[OK] repr: {r}")

    print("\n[PASS] documento_indexer_subagent.py: todos los tests pasaron")
