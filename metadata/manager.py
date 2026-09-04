# contexto_zai/metadata/manager.py -- Gestor de metadata: lee/escribe _metadata.json con mapeo tema->archivo y ultimo_timestamp.
"""Gestor de la metadata de recuperación (v3.2).

Lee y escribe el archivo `_metadata.json` que trackea:
- chat_id y share_id de la sesión
- ultimo_timestamp procesado (para actualización incremental)
- mapeo tema -> archivo (unicidad garantizada)
- subtemas derivados (registro de subdivisiones)
- ultima_activacion (ISO timestamp)

La metadata es la fuente de verdad del proceso: si el proceso se
reinicia, lee la metadata y sabe dónde quedó. Permite que múltiples
sesiones del agente compartan el mismo estado.

Atómico standalone: importa config y models, nada más del proyecto.
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
for _ in range(5):
    if _os.path.isdir(_os.path.join(_candidate, 'contexto_zai')):
        if _candidate not in _sys.path:
            _sys.path.insert(0, _candidate)
        break
    _candidate = _os.path.dirname(_candidate)
else:
    _parent = _os.path.dirname(_here)
    if _parent not in _sys.path:
        _sys.path.insert(0, _parent)

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from contexto_zai.config import METADATA_FILENAME
from contexto_zai.models import RecoveryMetadata

logger = logging.getLogger(__name__)

class MetadataManager:
    """Lee y escribe la metadata de recuperación.

    Args:
        output_dir: Directorio donde vive el archivo _metadata.json.
        filename: Nombre del archivo (por defecto _metadata.json).

    Usage:
        >>> mgr = MetadataManager(output_dir="./contexto_recuperacion")
        >>> meta = mgr.read()  # crea vacía si no existe
        >>> meta.registrar_tema("validaciones", "bloque_01.md")
        >>> mgr.write(meta)
    """

    def __init__(
        self,
        output_dir: Path | str = "contexto_recuperacion",
        filename: str = METADATA_FILENAME,
    ) -> None:
        self._output_dir = Path(output_dir)
        self._filename = filename
        self._path = self._output_dir / filename
        logger.debug(
            "MetadataManager inicializado: %s", self._path
        )

    # -- API pública ------------------------------------------------

    def read(self) -> RecoveryMetadata:
        """Lee la metadata del archivo. Si no existe, devuelve una vacía.

        Returns:
            RecoveryMetadata con el contenido del archivo, o vacía.
        """
        if not self._path.exists():
            logger.info(
                "Archivo de metadata no existe, creando vacio: %s", self._path
            )
            return RecoveryMetadata()

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            meta = RecoveryMetadata(**data)
            logger.debug(
                "Metadata leida: chat_id=%s, ultimo_ts=%s, temas=%d",
                meta.chat_id,
                meta.ultimo_timestamp,
                len(meta.tema_a_archivo),
            )
            return meta
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Error leyendo metadata %s: %s", self._path, e)
            return RecoveryMetadata()

    def write(self, metadata: RecoveryMetadata) -> None:
        """Escribe la metadata al archivo.

        Crea el directorio si no existe.

        Args:
            metadata: RecoveryMetadata a serializar.
        """
        self._output_dir.mkdir(parents=True, exist_ok=True)
        data = metadata.model_dump()
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Metadata escrita: %s", self._path)

    def update(self, **kwargs) -> RecoveryMetadata:
        """Actualiza campos de la metadata y la escribe.

        Lee la metadata actual, aplica los cambios indicados y la escribe.

        Args:
            **kwargs: Campos a actualizar (chat_id, share_id,
                ultimo_timestamp, total_exchanges, ultima_activacion).

        Returns:
            La metadata actualizada.
        """
        meta = self.read()
        for key, value in kwargs.items():
            if hasattr(meta, key):
                setattr(meta, key, value)
            else:
                logger.warning("Campo desconocido en metadata: %s", key)
        self.write(meta)
        return meta

    def register_tema(self, tema: str, archivo: str) -> RecoveryMetadata:
        """Registra un tema en un archivo.

        Lee la metadata, registra el tema (validando unicidad) y la escribe.

        Args:
            tema: Nombre del tema.
            archivo: Nombre del archivo donde vive el tema.

        Returns:
            La metadata actualizada.

        Raises:
            ValueError: Si el tema ya existe en otro archivo (violación unicidad).
        """
        meta = self.read()
        meta.registrar_tema(tema, archivo)
        self.write(meta)
        return meta

    def register_subtema(
        self,
        tema_padre: str,
        subtema: str,
        archivo: str,
    ) -> RecoveryMetadata:
        """Registra un subtema derivado de una subdivisión.

        Args:
            tema_padre: Nombre del tema original que se subdividió.
            subtema: Nombre del subtema derivado.
            archivo: Archivo donde vive el subtema.

        Returns:
            La metadata actualizada.
        """
        meta = self.read()
        meta.registrar_subtema(tema_padre, subtema, archivo)
        self.write(meta)
        return meta

    def get_ultimo_timestamp(self) -> float:
        """Devuelve el último timestamp procesado."""
        return self.read().ultimo_timestamp

    def set_ultimo_timestamp(self, timestamp: float) -> RecoveryMetadata:
        """Actualiza el último timestamp procesado."""
        return self.update(ultimo_timestamp=timestamp)

    def get_archivo_for_tema(self, tema: str) -> Optional[str]:
        """Devuelve el archivo que contiene el tema, o None si no está registrado."""
        return self.read().archivo_para_tema(tema)

    def touch_activacion(self) -> RecoveryMetadata:
        """Marca la última activación con el timestamp ISO actual."""
        iso = datetime.now(timezone.utc).isoformat()
        return self.update(ultima_activacion=iso)

    def exists(self) -> bool:
        """Verifica si el archivo de metadata existe."""
        return self._path.exists()

    def reset(self) -> None:
        """Elimina el archivo de metadata (si existe)."""
        if self._path.exists():
            self._path.unlink()
            logger.info("Metadata eliminada: %s", self._path)

    # -- Propiedades ------------------------------------------------

    @property
    def path(self) -> Path:
        """Ruta completa del archivo de metadata."""
        return self._path

    def __repr__(self) -> str:
        return f"MetadataManager(path={self._path!r})"

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
    # -- Validación interna de manager.py (atómico standalone) --
    print("=== Validacion de metadata/manager.py ===\n")

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MetadataManager(output_dir=Path(tmpdir))

        # Test 1: read() en archivo inexistente devuelve vacío
        assert not mgr.exists()
        meta = mgr.read()
        assert meta.chat_id == ""
        assert meta.tema_a_archivo == {}
        print(f"[OK] read() en archivo inexistente: metadata vacía")

        # Test 2: write() crea el archivo
        meta.chat_id = "abc-123"
        meta.share_id = "def-456"
        meta.ultimo_timestamp = 1234567890
        mgr.write(meta)
        assert mgr.exists()
        print(f"[OK] write() crea archivo: {mgr.path.name}")

        # Test 3: read() recupera lo escrito
        meta2 = mgr.read()
        assert meta2.chat_id == "abc-123"
        assert meta2.share_id == "def-456"
        assert meta2.ultimo_timestamp == 1234567890
        print(f"[OK] read() recupera datos: chat_id={meta2.chat_id}")

        # Test 4: register_tema
        mgr.register_tema("validaciones", "bloque_01.md")
        mgr.register_tema("configuracion_proyecto", "bloque_01.md")  # mismo archivo
        meta3 = mgr.read()
        assert meta3.tema_a_archivo["validaciones"] == "bloque_01.md"
        assert meta3.tema_a_archivo["configuracion_proyecto"] == "bloque_01.md"
        print(f"[OK] register_tema: 2 temas en bloque_01.md")

        # Test 5: violación de unicidad lanza error
        try:
            mgr.register_tema("validaciones", "bloque_02.md")
            assert False, "Debería lanzar ValueError"
        except ValueError as e:
            assert "Violación de unicidad" in str(e)
            print(f"[OK] Unicidad: violacion detectada correctamente")

        # Test 6: register_subtema
        mgr.register_subtema("validaciones", "validaciones_server", "bloque_02.md")
        meta4 = mgr.read()
        assert "validaciones_server" in meta4.tema_a_archivo
        assert meta4.tema_a_archivo["validaciones_server"] == "bloque_02.md"
        assert "validaciones_server" in meta4.subtemas_derivados["validaciones"]
        print(f"[OK] register_subtema: 'validaciones_server' registrado")

        # Test 7: get_archivo_for_tema
        assert mgr.get_archivo_for_tema("validaciones") == "bloque_01.md"
        assert mgr.get_archivo_for_tema("validaciones_server") == "bloque_02.md"
        assert mgr.get_archivo_for_tema("no_existe") is None
        print(f"[OK] get_archivo_for_tema: consultas OK")

        # Test 8: get/set_ultimo_timestamp
        mgr.set_ultimo_timestamp(9999999)
        assert mgr.get_ultimo_timestamp() == 9999999
        print(f"[OK] get/set_ultimo_timestamp: {mgr.get_ultimo_timestamp()}")

        # Test 9: touch_activacion
        mgr.touch_activacion()
        meta5 = mgr.read()
        assert meta5.ultima_activacion != ""
        # Formato ISO: contiene 'T' y 'Z'
        assert "T" in meta5.ultima_activacion
        print(f"[OK] touch_activacion: {meta5.ultima_activacion}")

        # Test 10: update con múltiples campos
        mgr.update(chat_id="new-id", total_exchanges=42)
        meta6 = mgr.read()
        assert meta6.chat_id == "new-id"
        assert meta6.total_exchanges == 42
        print(f"[OK] update: chat_id={meta6.chat_id}, total_exchanges={meta6.total_exchanges}")

        # Test 11: reset elimina el archivo
        mgr.reset()
        assert not mgr.exists()
        print(f"[OK] reset: archivo eliminado")

        # Test 12: archivo corrupto -> metadata vacía
        # Crear archivo con JSON inválido
        mgr._path.parent.mkdir(parents=True, exist_ok=True)
        mgr._path.write_text("{invalid json", encoding="utf-8")
        meta7 = mgr.read()
        assert meta7.chat_id == ""  # Recuperado como vacío
        print(f"[OK] Archivo corrupto: recuperado como vacio")

    print("\n[PASS] metadata/manager.py: todos los tests pasaron")
