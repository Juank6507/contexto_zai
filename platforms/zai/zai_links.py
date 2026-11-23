"""contexto_zai/platforms/zai/zai_links.py -- Implementacion Zai de PlatformLinks (v7.0 F2).

Envuelve ``AttachmentClient`` (descarga de attachments via
``/api/v1/files/{file_id}/content`` con autenticacion JWT). NO lo
reemplaza: la abstraccion vive aqui, la implementacion HTTP sigue en
``client/attachment_client.py``.

Inyeccion por constructor: si un llamador no inyecta nada, se usa la
implementacion Zai por defecto (construye un ``AttachmentClient`` con
el JWT).
"""
from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
_package_root = None
for _ in range(10):
    if not _os.path.isfile(_os.path.join(_candidate, '__init__.py')):
        break
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

from contexto_zai.platforms.interfaces import PlatformLinks
from contexto_zai.client.attachment_client import AttachmentClient

logger = logging.getLogger(__name__)


class ZaiLinks(PlatformLinks):
    """Implementacion Zai de ``PlatformLinks``.

    Envuelve ``AttachmentClient`` para descargar attachments y listar
    los attachments de un chat.

    Args:
        jwt: JWT del Director (autenticacion para descargar).
        download_dir: Directorio base donde se guardan los attachments
            descargados. Si es None, se usa el directorio temporal del
            sistema.

    Usage:
        >>> links = ZaiLinks(jwt="eyJhbG...")
        >>> path = links.download_attachment("file-uuid-123", "doc.pdf")
        >>> attachments = links.list_attachments("chat-uuid-456")
    """

    def __init__(
        self,
        jwt: str = "",
        download_dir: Optional[Path | str] = None,
    ) -> None:
        self._jwt = jwt or ""
        self._download_dir = Path(download_dir) if download_dir else None
        if self._jwt:
            self._client = AttachmentClient(token=self._jwt)
        else:
            # Sin JWT, no podemos descargar. Se acepta por simetria con
            # la interfaz pero los metodos lanzaran error.
            self._client = None
            logger.warning(
                "ZaiLinks: jwt vacio, no se podran descargar attachments."
            )

    # -- PlatformLinks API -------------------------------------------

    def download_attachment(self, file_id: str, filename: str) -> str:
        """Descarga un attachment y lo guarda en disco. Devuelve la ruta.

        Delega en ``AttachmentClient.download_to_file``. El archivo se
        guarda en ``download_dir / filename``. Si ``download_dir`` es
        None, se usa el directorio actual.

        Args:
            file_id: UUID del archivo en Zai.
            filename: Nombre de archivo destino (sin ruta).

        Returns:
            Ruta local donde se guardo el attachment.
        """
        if self._client is None:
            raise RuntimeError(
                "ZaiLinks.download_attachment requiere jwt. "
                "Inyecta jwt=... al construir ZaiLinks."
            )
        dest_dir = self._download_dir or Path(".")
        dest = dest_dir / filename
        saved = self._client.download_to_file(file_id, dest)
        logger.info(
            "ZaiLinks.download_attachment: %s guardado en %s (%d bytes)",
            file_id, saved, saved.stat().st_size if saved.exists() else 0,
        )
        return str(saved)

    def list_attachments(self, chat_id: str) -> list:
        """Lista los attachments de un chat.

        Zai no tiene un endpoint directo para listar attachments por
        chat. Los attachments se descubren via el batch endpoint de
        mensajes (campo ``files`` de cada mensaje crudo). Esta funcion
        devuelve una lista vacia por defecto; el descubrimiento real lo
        hace ``MessageExtractor`` cuando procesa el batch crudo.

        Args:
            chat_id: UUID interno del chat.

        Returns:
            Lista vacia (override en subclase o usa ``MessageExtractor``
            para descubrir attachments via batch).
        """
        logger.info(
            "ZaiLinks.list_attachments: chat %s — Zai no tiene endpoint "
            "directo, devuelve []. Usa MessageExtractor para descubrir "
            "attachments via batch.",
            chat_id[:12] if chat_id else "N/A",
        )
        return []

    def __repr__(self) -> str:
        has_client = self._client is not None
        return f"ZaiLinks(has_client={has_client}, download_dir={self._download_dir!r})"
