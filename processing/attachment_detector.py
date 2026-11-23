# contexto_zai/processing/attachment_detector.py -- Detector de attachments en mensajes del batch endpoint.
"""Detector de attachments (v3.5).

Recorre el JSON crudo del batch endpoint de Z.ai y extrae los
attachments (archivos adjuntos) que el Director ha enviado mediante
el botón "+" del chat.

El batch endpoint devuelve cada mensaje con un campo `files` (array)
que contiene la metadata de los attachments. Este módulo los detecta,
los convierte en objetos `Attachment`, y los devuelve listos para
que el proceso decida si delegar su lectura a un subagente.

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
from typing import Optional

from contexto_zai.models import Attachment

logger = logging.getLogger(__name__)


class AttachmentDetector:
    """Detecta attachments en mensajes del batch endpoint de Z.ai.

    El batch endpoint devuelve cada mensaje con un campo `files` (array).
    Cada entry tiene la estructura:
        {
            "type": "doc"|"file"|"image",
            "file": {
                "id": "UUID",
                "filename": "nombre.pdf",
                "meta": {
                    "content_type": "application/pdf",
                    "size": 1652025,
                    "cdn_url": "https://..."
                },
                "created_at": 1788445359
            },
            "media": "doc"|"file"|"image",
            "status": "uploaded"
        }

    Usage:
        >>> detector = AttachmentDetector()
        >>> raw = {"data": {"msg1": {"files": [...]}}}
        >>> attachments = detector.detect_in_raw_messages(raw)
    """

    def detect_in_raw_messages(self, raw_messages: dict) -> list[Attachment]:
        """Detecta attachments en el JSON crudo del batch endpoint.

        Args:
            raw_messages: Respuesta cruda del batch endpoint (con clave "data").

        Returns:
            Lista de objetos Attachment detectados.
        """
        attachments: list[Attachment] = []
        data = raw_messages.get("data", {})

        for msg_id, msg_raw in data.items():
            if not isinstance(msg_raw, dict):
                continue
            files = msg_raw.get("files", [])
            if not files:
                continue

            for file_entry in files:
                att = self._parse_file_entry(file_entry, msg_id)
                if att:
                    attachments.append(att)

        logger.info(
            "Detectados %d attachments en %d mensajes",
            len(attachments), len(data),
        )
        return attachments

    def detect_in_message(self, msg_id: str, msg_raw: dict) -> list[Attachment]:
        """Detecta attachments en un solo mensaje crudo.

        Args:
            msg_id: ID del mensaje.
            msg_raw: Contenido crudo del mensaje (con campo "files").

        Returns:
            Lista de attachments del mensaje.
        """
        files = msg_raw.get("files", []) if isinstance(msg_raw, dict) else []
        attachments: list[Attachment] = []
        for file_entry in files:
            att = self._parse_file_entry(file_entry, msg_id)
            if att:
                attachments.append(att)
        return attachments

    def deduplicate(self, attachments: list[Attachment]) -> list[Attachment]:
        """Elimina duplicados por file_id (manteniendo el primero).

        Args:
            attachments: Lista con posibles duplicados.

        Returns:
            Lista sin duplicados, orden original preservado.
        """
        seen: set[str] = set()
        unique: list[Attachment] = []
        for att in attachments:
            if att.file_id not in seen:
                seen.add(att.file_id)
                unique.append(att)
        return unique

    def filter_by_media(
        self,
        attachments: list[Attachment],
        media_type: str,
    ) -> list[Attachment]:
        """Filtra attachments por tipo de media.

        Args:
            attachments: Lista de attachments.
            media_type: Tipo a filtrar ("doc", "file", "image").

        Returns:
            Lista filtrada.
        """
        return [a for a in attachments if a.media == media_type]

    def filter_by_content_type(
        self,
        attachments: list[Attachment],
        content_type_prefix: str,
    ) -> list[Attachment]:
        """Filtra attachments por prefijo de content_type.

        Args:
            attachments: Lista de attachments.
            content_type_prefix: Prefijo a buscar ("application/pdf", "image/", etc.).

        Returns:
            Lista filtrada.
        """
        return [
            a for a in attachments
            if a.content_type.startswith(content_type_prefix)
        ]

    def get_messages_with_attachments(
        self,
        raw_messages: dict,
    ) -> dict[str, list[Attachment]]:
        """Mapea cada mensaje con attachments a sus attachments.

        Args:
            raw_messages: Respuesta cruda del batch endpoint.

        Returns:
            Diccionario {msg_id: [Attachment, ...]} solo para mensajes con attachments.
        """
        result: dict[str, list[Attachment]] = {}
        data = raw_messages.get("data", {})
        for msg_id, msg_raw in data.items():
            if not isinstance(msg_raw, dict):
                continue
            atts = self.detect_in_message(msg_id, msg_raw)
            if atts:
                result[msg_id] = atts
        return result

    # -- Métodos privados -------------------------------------------

    def _parse_file_entry(
        self,
        file_entry: dict,
        msg_id: str,
    ) -> Optional[Attachment]:
        """Parsea una entrada del campo `files` en un Attachment.

        Estructura esperada:
            {
                "type": "doc",
                "file": {
                    "id": "...",
                    "filename": "...",
                    "meta": {
                        "content_type": "...",
                        "size": 123,
                        "cdn_url": "..."
                    },
                    "created_at": 1788445359
                },
                "media": "doc",
                "status": "uploaded"
            }
        """
        if not isinstance(file_entry, dict):
            return None

        # El campo "file" contiene la metadata principal
        file_info = file_entry.get("file", {})
        if not isinstance(file_info, dict) or not file_info:
            # Algunas estructuras ponen la info directamente en file_entry
            if "id" in file_entry:
                file_info = file_entry
            else:
                return None

        file_id = file_info.get("id", "")
        if not file_id:
            return None

        meta = file_info.get("meta", {}) or {}
        filename = (
            file_info.get("filename", "")
            or meta.get("name", "")
            or file_entry.get("name", "")
        )
        content_type = meta.get("content_type", "application/octet-stream")
        size = meta.get("size", 0) or file_info.get("size", 0) or file_entry.get("size", 0)
        cdn_url = meta.get("cdn_url", "")
        created_at = file_info.get("created_at", 0) or file_entry.get("created_at", 0)
        media = file_entry.get("media", "") or file_entry.get("type", "file")
        status = file_entry.get("status", "uploaded")

        return Attachment(
            file_id=file_id,
            filename=filename,
            content_type=content_type,
            size=size,
            url=f"/api/v1/files/{file_id}/content",
            cdn_url=cdn_url,
            ref_msg_id=msg_id,
            media=media,
            status=status,
            created_at=created_at,
        )

    def __repr__(self) -> str:
        return "AttachmentDetector()"


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

    print("=== Validacion de attachment_detector.py ===\n")

    detector = AttachmentDetector()

    # Test 1: mensaje sin attachments → lista vacía
    raw_empty = {"data": {"msg1": {"role": "user", "files": []}}}
    result = detector.detect_in_raw_messages(raw_empty)
    assert result == []
    print("[OK] Mensaje sin attachments: lista vacía")

    # Test 2: mensaje con 1 attachment PDF
    raw_one = {
        "data": {
            "msg1": {
                "role": "user",
                "files": [
                    {
                        "type": "doc",
                        "file": {
                            "id": "abc-123",
                            "filename": "doc.pdf",
                            "meta": {
                                "content_type": "application/pdf",
                                "size": 1652025,
                                "cdn_url": "https://cdn.example.com/doc.pdf",
                            },
                            "created_at": 1788445359,
                        },
                        "media": "doc",
                        "status": "uploaded",
                    }
                ],
            }
        }
    }
    result = detector.detect_in_raw_messages(raw_one)
    assert len(result) == 1
    att = result[0]
    assert att.file_id == "abc-123"
    assert att.filename == "doc.pdf"
    assert att.is_pdf
    assert att.size == 1652025
    assert att.url == "/api/v1/files/abc-123/content"
    assert att.ref_msg_id == "msg1"
    assert att.media == "doc"
    print(f"[OK] 1 attachment PDF detectado: {att.filename} ({att.size:,} bytes)")

    # Test 3: múltiples attachments en un mensaje
    raw_multi = {
        "data": {
            "msg1": {
                "role": "user",
                "files": [
                    {
                        "type": "doc", "media": "doc",
                        "file": {"id": "a1", "filename": "a.pdf", "meta": {"content_type": "application/pdf", "size": 100}},
                    },
                    {
                        "type": "file", "media": "file",
                        "file": {"id": "a2", "filename": "b.txt", "meta": {"content_type": "text/plain", "size": 200}},
                    },
                    {
                        "type": "image", "media": "image",
                        "file": {"id": "a3", "filename": "c.png", "meta": {"content_type": "image/png", "size": 300}},
                    },
                ],
            }
        }
    }
    result = detector.detect_in_raw_messages(raw_multi)
    assert len(result) == 3
    assert {a.file_id for a in result} == {"a1", "a2", "a3"}
    print(f"[OK] 3 attachments detectados (doc + file + image)")

    # Test 4: deduplicación
    dups = result + result
    unique = detector.deduplicate(dups)
    assert len(unique) == 3
    print(f"[OK] Deduplicación: {len(dups)} -> {len(unique)}")

    # Test 5: filtrar por media
    docs = detector.filter_by_media(result, "doc")
    assert len(docs) == 1 and docs[0].is_pdf
    images = detector.filter_by_media(result, "image")
    assert len(images) == 1 and images[0].is_image
    print(f"[OK] Filtro media: docs={len(docs)}, images={len(images)}")

    # Test 6: filtrar por content_type
    pdfs = detector.filter_by_content_type(result, "application/pdf")
    assert len(pdfs) == 1
    print(f"[OK] Filtro content_type: pdfs={len(pdfs)}")

    # Test 7: get_messages_with_attachments
    raw_msgs = {
        "data": {
            "msg1": {"role": "user", "files": [{"file": {"id": "x1", "filename": "a.pdf", "meta": {"size": 100}}}]},
            "msg2": {"role": "assistant", "files": []},
            "msg3": {"role": "user", "files": [{"file": {"id": "x2", "filename": "b.txt", "meta": {"size": 200}}}]},
        }
    }
    mapping = detector.get_messages_with_attachments(raw_msgs)
    assert set(mapping.keys()) == {"msg1", "msg3"}
    assert len(mapping["msg1"]) == 1
    assert len(mapping["msg3"]) == 1
    print(f"[OK] get_messages_with_attachments: {len(mapping)} mensajes con attachments")

    # Test 8: estructura vacía
    assert detector.detect_in_raw_messages({}) == []
    assert detector.detect_in_raw_messages({"data": {}}) == []
    print("[OK] Estructura vacía: lista vacía")

    # Test 9: file_entry mal formado (sin campo "file")
    raw_malformed = {
        "data": {
            "msg1": {
                "role": "user",
                "files": [
                    {"type": "doc"},  # sin "file"
                    "not-a-dict",
                    {"file": {}},  # file vacío
                    {"file": {"id": "valid", "filename": "ok.txt", "meta": {"size": 50}}},
                ],
            }
        }
    }
    result = detector.detect_in_raw_messages(raw_malformed)
    assert len(result) == 1, f"Debe detectar solo 1 válido, got {len(result)}"
    assert result[0].file_id == "valid"
    print("[OK] Estructura malformada: solo 1 attachment válido detectado")

    # Test 10: estructura alternativa (info directamente en file_entry)
    raw_alt = {
        "data": {
            "msg1": {
                "role": "user",
                "files": [
                    {
                        "id": "alt-1",
                        "filename": "alt.txt",
                        "media": "file",
                        "size": 100,
                    }
                ],
            }
        }
    }
    result = detector.detect_in_raw_messages(raw_alt)
    assert len(result) == 1
    assert result[0].file_id == "alt-1"
    print(f"[OK] Estructura alternativa: attachment detectado")

    # Test 11: detect_in_message
    single_msg_raw = {
        "role": "user",
        "files": [{"file": {"id": "s1", "filename": "s.pdf", "meta": {"size": 100, "content_type": "application/pdf"}}}],
    }
    single = detector.detect_in_message("s-msg", single_msg_raw)
    assert len(single) == 1
    assert single[0].file_id == "s1"
    print(f"[OK] detect_in_message: 1 attachment detectado")

    print("\n[PASS] attachment_detector.py: todos los tests pasaron")
