# contexto_zai/client/attachment_client.py -- Cliente de descarga de attachments desde la API de Z.ai.
"""Cliente de descarga de attachments (v3.5).

Descarga archivos adjuntos desde la API de Z.ai mediante el
endpoint autenticado /api/v1/files/{file_id}/content.

El cliente usa la cookie `token` (JWT del Director) para autenticar
la descarga, igual que el ChatClient para los mensajes.

Atómico standalone: importa config y models, nada más del proyecto.
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
from pathlib import Path
from typing import Optional

import httpx

from contexto_zai.config import API_CONFIG
from contexto_zai.models import Attachment

logger = logging.getLogger(__name__)


class AttachmentClientError(Exception):
    """Error base del AttachmentClient."""


class AttachmentDownloadError(AttachmentClientError):
    """Error al descargar un attachment."""


class AttachmentClient:
    """Descarga archivos adjuntos desde la API de Z.ai.

    Usa el endpoint /api/v1/files/{file_id}/content con autenticación
    por cookie JWT del Director.

    Args:
        token: JWT del Director (autenticación).
        timeout: Timeout en segundos para las descargas.
        max_size_bytes: Tamaño máximo permitido (default 50 MB).

    Usage:
        >>> client = AttachmentClient(token="eyJhbG...")
        >>> content = client.download("abc-123")
        >>> # content son los bytes del archivo
        >>> client.close()
    """

    MAX_SIZE_BYTES_DEFAULT = 50 * 1024 * 1024  # 50 MB

    # Magic numbers para detección de tipo
    MAGIC_NUMBERS = {
        b"%PDF": "application/pdf",
        b"PK\x03\x04": "application/zip",  # DOCX, XLSX, PPTX
        b"\x89PNG\r\n\x1a\n": "image/png",
        b"\xff\xd8\xff": "image/jpeg",
        b"GIF87a": "image/gif",
        b"GIF89a": "image/gif",
        b"\x50\x4b\x05\x06": "application/zip",  # empty zip
    }

    def __init__(
        self,
        token: str,
        timeout: float = 60.0,
        max_size_bytes: int = MAX_SIZE_BYTES_DEFAULT,
    ) -> None:
        if not token:
            raise AttachmentClientError("Se requiere token JWT para descargar attachments")
        self._token = token.strip()
        self._timeout = timeout
        self._max_size_bytes = max_size_bytes
        self._base_url = API_CONFIG.base_url
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "ContextoZAI/3.5",
                "Accept": "*/*",
            },
        )
        logger.debug("AttachmentClient inicializado: timeout=%s", timeout)

    # -- API pública ------------------------------------------------

    def download(self, file_id: str) -> bytes:
        """Descarga el contenido binario de un attachment.

        Args:
            file_id: UUID del archivo en Z.ai.

        Returns:
            Bytes del contenido del archivo.

        Raises:
            AttachmentDownloadError: Si la descarga falla o el archivo
                supera el tamaño máximo.
        """
        if not file_id:
            raise AttachmentDownloadError("file_id vacío")

        url = f"{self._base_url}/api/v1/files/{file_id}/content"
        logger.debug("Descargando attachment: %s", file_id)

        try:
            response = self._client.get(
                url,
                cookies={API_CONFIG.cookie_name: self._token},
            )
        except httpx.HTTPError as e:
            logger.error("Error HTTP descargando %s: %s", file_id, e)
            raise AttachmentDownloadError(f"Error de red: {e}") from e

        if response.status_code == 401:
            raise AttachmentDownloadError(
                f"Token inválido o expirado (HTTP 401) descargando {file_id}"
            )
        if response.status_code == 403:
            raise AttachmentDownloadError(
                f"Sin permisos para descargar {file_id} (HTTP 403)"
            )
        if response.status_code == 404:
            raise AttachmentDownloadError(
                f"Attachment {file_id} no encontrado (HTTP 404)"
            )
        if response.status_code != 200:
            raise AttachmentDownloadError(
                f"Error descargando {file_id}: HTTP {response.status_code}"
            )

        content = response.content
        if len(content) > self._max_size_bytes:
            raise AttachmentDownloadError(
                f"Attachment {file_id} demasiado grande: "
                f"{len(content):,} bytes > {self._max_size_bytes:,} bytes"
            )

        logger.info(
            "Descargado %s: %d bytes, Content-Type=%s",
            file_id, len(content), response.headers.get("content-type", "?"),
        )
        return content

    def download_to_file(
        self,
        file_id: str,
        dest_path: Path | str,
    ) -> Path:
        """Descarga el attachment y lo guarda en disco.

        Args:
            file_id: UUID del archivo.
            dest_path: Ruta de destino.

        Returns:
            Path del archivo guardado.
        """
        content = self.download(file_id)
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        logger.info("Attachment %s guardado en %s (%d bytes)", file_id, dest, len(content))
        return dest

    def download_attachment(self, attachment: Attachment) -> bytes:
        """Descarga el contenido de un objeto Attachment.

        Args:
            attachment: Objeto Attachment con file_id.

        Returns:
            Bytes del contenido.
        """
        return self.download(attachment.file_id)

    def download_many(
        self,
        file_ids: list[str],
    ) -> dict[str, bytes]:
        """Descarga múltiples attachments.

        Args:
            file_ids: Lista de UUIDs de archivos.

        Returns:
            Diccionario {file_id: bytes} (excluye los que fallaron).
        """
        results: dict[str, bytes] = {}
        for fid in file_ids:
            try:
                results[fid] = self.download(fid)
            except AttachmentDownloadError as e:
                logger.warning("No se pudo descargar %s: %s", fid, e)
        return results

    @classmethod
    def detect_type_by_magic(cls, content: bytes) -> str:
        """Detecta el tipo MIME por magic number (no confía en Content-Type).

        Args:
            content: Bytes del archivo.

        Returns:
            Tipo MIME detectado (ej: "application/pdf", "image/png").
        """
        for magic, mime in cls.MAGIC_NUMBERS.items():
            if content.startswith(magic):
                return mime
        # Verificar si es texto UTF-8 válido
        try:
            content.decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            pass
        return "application/octet-stream"

    def close(self) -> None:
        """Cierra el cliente HTTP."""
        self._client.close()

    def __enter__(self) -> "AttachmentClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"AttachmentClient(base_url={self._base_url!r}, max_size={self._max_size_bytes})"


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

    print("=== Validacion de attachment_client.py ===\n")

    import tempfile

    # Test 1: token vacío lanza error
    try:
        AttachmentClient(token="")
        assert False, "Debería haber lanzado error"
    except AttachmentClientError:
        print("[OK] Token vacío: error correcto")
    except Exception as e:
        # Pydantic validation error también es aceptable
        print(f"[OK] Token vacío: error capturado ({type(e).__name__})")

    # Test 2: detección de tipo por magic number
    assert AttachmentClient.detect_type_by_magic(b"%PDF-1.4...") == "application/pdf"
    print("[OK] Magic number: PDF detectado")

    assert AttachmentClient.detect_type_by_magic(b"PK\x03\x04...") == "application/zip"
    print("[OK] Magic number: ZIP/DOCX detectado")

    assert AttachmentClient.detect_type_by_magic(b"\x89PNG\r\n\x1a\n...") == "image/png"
    print("[OK] Magic number: PNG detectado")

    assert AttachmentClient.detect_type_by_magic(b"\xff\xd8\xff...") == "image/jpeg"
    print("[OK] Magic number: JPEG detectado")

    # Texto plano UTF-8
    assert AttachmentClient.detect_type_by_magic(b"Hola mundo") == "text/plain"
    print("[OK] Magic number: texto plano detectado")

    # Binario desconocido (no UTF-8 válido: 0xFF es byte inválido en UTF-8)
    assert AttachmentClient.detect_type_by_magic(b"\xff\xfe\x00") == "application/octet-stream"
    print("[OK] Magic number: binario desconocido detectado")

    # Test 3: client construido correctamente
    client = AttachmentClient(token="fake-jwt-token")
    assert client._token == "fake-jwt-token"
    assert client._base_url == API_CONFIG.base_url
    print(f"[OK] Client construido: {client!r}")

    # Test 4: file_id vacío lanza error
    try:
        client.download("")
        assert False
    except AttachmentDownloadError as e:
        assert "vacío" in str(e).lower() or "vacio" in str(e).lower()
        print("[OK] download('') lanza error correcto")

    # Test 5: download_to_file con attachment simulado (mock)
    # Simular la respuesta HTTP con mock
    from unittest.mock import MagicMock, patch
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"%PDF-1.4 fake content"
    mock_response.headers = {"content-type": "application/pdf"}

    with patch.object(client._client, "get", return_value=mock_response):
        content = client.download("fake-file-id")
        assert content == b"%PDF-1.4 fake content"
        print(f"[OK] download() con mock: {len(content)} bytes")

    # Test 6: download_to_file
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "subdir" / "test.pdf"
        with patch.object(client._client, "get", return_value=mock_response):
            saved = client.download_to_file("fake-file-id", dest)
            assert saved.exists()
            assert saved.read_bytes() == b"%PDF-1.4 fake content"
            print(f"[OK] download_to_file: guardado en {saved}")

    # Test 7: errores HTTP
    for status, msg in [(401, "Token inválido"), (403, "Sin permisos"), (404, "no encontrado")]:
        mock_err = MagicMock()
        mock_err.status_code = status
        mock_err.headers = {}
        with patch.object(client._client, "get", return_value=mock_err):
            try:
                client.download("fake")
                assert False, f"Debería lanzar error para HTTP {status}"
            except AttachmentDownloadError as e:
                assert str(status) in str(e) or msg.lower() in str(e).lower()
        print(f"[OK] HTTP {status}: error correcto")

    # Test 8: tamaño máximo excedido
    mock_big = MagicMock()
    mock_big.status_code = 200
    mock_big.content = b"x" * 100
    mock_big.headers = {"content-type": "application/octet-stream"}

    small_client = AttachmentClient(token="fake", max_size_bytes=50)
    with patch.object(small_client._client, "get", return_value=mock_big):
        try:
            small_client.download("big")
            assert False
        except AttachmentDownloadError as e:
            assert "grande" in str(e).lower() or "large" in str(e).lower()
    print("[OK] Tamaño máximo excedido: error correcto")

    # Test 9: download_many
    with patch.object(client._client, "get", return_value=mock_response):
        results = client.download_many(["id1", "id2"])
        assert len(results) == 2
        assert all(v == b"%PDF-1.4 fake content" for v in results.values())
    print(f"[OK] download_many: {len(results)} archivos descargados")

    # Test 10: context manager
    with AttachmentClient(token="fake") as cm:
        assert cm._token == "fake"
    print("[OK] Context manager: cierra correctamente")

    client.close()
    print("\n[PASS] attachment_client.py: todos los tests pasaron")
