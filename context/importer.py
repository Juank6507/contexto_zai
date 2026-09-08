# context/importer.py -- Importador de contexto: descomprime un paquete .zip y lo carga en el workspace del agente.
"""Importador de contexto (v3.4).

Descomprime un paquete de contexto exportado (.zip) y lo
carga en el workspace del agente. Lee las instrucciones
de recuperacion y las devuelve para que el agente nuevo
sepa como usar el contexto.

Atomica standalone: no importa otros modulos del proyecto.
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

import json
import logging
import zipfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ContextImporter:
    """Descomprime un paquete de contexto y lo carga en el workspace.

    Args:
        workspace_dir: Directorio donde cargar los archivos.
            Por defecto /home/z/my-project/contexto_recuperacion/.

    Usage:
        >>> importer = ContextImporter()
        >>> instrucciones = importer.import_from("/path/to/contexto.zip")
        >>> if instrucciones:
        ...     print("Contexto cargado. Instrucciones:")
        ...     print(instrucciones)
    """

    def __init__(
        self,
        workspace_dir: Path | str = "/home/z/my-project/contexto_recuperacion",
    ) -> None:
        self._workspace_dir = Path(workspace_dir)
        logger.debug("ContextImporter inicializado: workspace=%s", self._workspace_dir)

    # ── API publica ────────────────────────────────────────────

    def find_packages(
        self,
        search_dir: Path | str = "/home/z/my-project/download",
    ) -> list[Path]:
        """Busca paquetes de contexto exportados en un directorio.

        Args:
            search_dir: Directorio donde buscar.

        Returns:
            Lista de rutas de archivos .zip que coinciden con el patron.
        """
        search_path = Path(search_dir)
        if not search_path.exists():
            return []

        packages = sorted(
            search_path.glob("contexto_exportado_*.zip"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        logger.info("Encontrados %d paquetes en %s", len(packages), search_path)
        return packages

    def import_from(
        self,
        zip_path: Path | str,
    ) -> Optional[str]:
        """Descomprime un paquete de contexto y lo carga.

        Args:
            zip_path: Ruta del archivo .zip.

        Returns:
            Contenido de las instrucciones de recuperacion, o None si fallo.
        """
        zip_path = Path(zip_path)
        if not zip_path.exists():
            logger.error("Paquete no encontrado: %s", zip_path)
            return None

        if not zipfile.is_zipfile(zip_path):
            logger.error("No es un .zip valido: %s", zip_path)
            return None

        # Crear directorio de destino
        self._workspace_dir.mkdir(parents=True, exist_ok=True)

        # Descomprimir
        instrucciones = None
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                # No sobrescribir _paquete.json ni _instrucciones en el workspace
                if name.startswith("_") and name not in ["_metadata.json", "_grafos_cambios.json"]:
                    if name == "_instrucciones_recuperacion.md":
                        instrucciones = zf.read(name).decode("utf-8")
                    continue

                # Extraer archivo
                target = self._workspace_dir / name
                target.write_bytes(zf.read(name))
                logger.debug("Extraido: %s", target)

        logger.info(
            "Contexto importado desde %s a %s",
            zip_path, self._workspace_dir,
        )
        return instrucciones

    def import_latest(
        self,
        search_dir: Path | str = "/home/z/my-project/download",
    ) -> Optional[str]:
        """Busca y carga el paquete mas reciente.

        Args:
            search_dir: Directorio donde buscar.

        Returns:
            Contenido de las instrucciones de recuperacion, o None si no hay paquetes.
        """
        packages = self.find_packages(search_dir)
        if not packages:
            logger.info("No se encontraron paquetes de contexto en %s", search_dir)
            return None

        latest = packages[0]  # El mas reciente (ordenado por mtime descendente)
        logger.info("Cargando paquete mas reciente: %s", latest.name)
        return self.import_from(latest)

    def verify(self) -> bool:
        """Verifica que los archivos del contexto estan completos.

        Returns:
            True si los archivos minimos existen.
        """
        required = [
            "00_estado_actual.md",
            "01_indice_recuperacion.md",
        ]
        for fname in required:
            if not (self._workspace_dir / fname).exists():
                logger.warning("Archivo faltante: %s", fname)
                return False
        logger.info("Verificacion OK: archivos minimos presentes")
        return True

    def __repr__(self) -> str:
        return f"ContextImporter(workspace={self._workspace_dir!r})"


if __name__ == "__main__":
    import io as _io
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass

    print("=== Validacion de importer.py ===\n")

    import tempfile

    # Test 1: find_packages sin directorio
    importer = ContextImporter()
    packages = importer.find_packages("/tmp/no_existe")
    assert packages == []
    print("[OK] find_packages sin directorio: []")

    # Test 2: import_from con archivo inexistente
    result = importer.import_from("/tmp/no_existe.zip")
    assert result is None
    print("[OK] import_from inexistente: None")

    # Test 3: import_from con .zip de prueba
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "workspace"
        output = Path(tmpdir) / "output"
        output.mkdir()

        # Crear un .zip de prueba
        zip_path = output / "contexto_exportado_test_20260101_120000.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("_paquete.json", json.dumps({"chat_id": "test", "version_spec": "3.4"}))
            zf.writestr("_instrucciones_recuperacion.md", "# Instrucciones\n\nTest de recuperacion")
            zf.writestr("00_estado_actual.md", "# Estado\n\nTest")
            zf.writestr("01_indice_recuperacion.md", "# Indice\n\nTest")
            zf.writestr("02_decisiones_clave.md", "# Decisiones\n\nTest")
            zf.writestr("bloque_01.md", "# Bloque\n\nTest")
            zf.writestr("_metadata.json", json.dumps({"chat_id": "test"}))

        # Importar
        importer2 = ContextImporter(workspace_dir=ws)
        instrucciones = importer2.import_from(zip_path)

        assert instrucciones is not None
        assert "Instrucciones" in instrucciones
        print(f"[OK] import_from: instrucciones recibidas ({len(instrucciones)} chars)")

        # Verificar archivos extraidos
        assert (ws / "00_estado_actual.md").exists()
        assert (ws / "01_indice_recuperacion.md").exists()
        assert (ws / "02_decisiones_clave.md").exists()
        assert (ws / "bloque_01.md").exists()
        assert (ws / "_metadata.json").exists()
        # _paquete.json y _instrucciones NO se extraen al workspace
        assert not (ws / "_paquete.json").exists()
        assert not (ws / "_instrucciones_recuperacion.md").exists()
        print(f"[OK] Archivos extraidos correctamente")

    # Test 4: find_packages con .zip de prueba
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir)
        (output / "contexto_exportado_a_20260101_120000.zip").write_bytes(b"PK")
        (output / "contexto_exportado_b_20260102_120000.zip").write_bytes(b"PK")
        (output / "otro_archivo.txt").write_text("no zip")

        importer3 = ContextImporter()
        packages = importer3.find_packages(output)
        assert len(packages) == 2
        print(f"[OK] find_packages: {len(packages)} paquetes encontrados")

    # Test 5: import_latest
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        output = Path(tmpdir) / "output"
        output.mkdir()

        # Crear dos .zip (el segundo mas reciente)
        for i, name in enumerate(["contexto_exportado_a_20260101_120000.zip", "contexto_exportado_b_20260102_120000.zip"]):
            zp = output / name
            with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("_instrucciones_recuperacion.md", f"# Paquete {i}")
                zf.writestr("00_estado_actual.md", f"# Estado {i}")
                zf.writestr("01_indice_recuperacion.md", f"# Indice {i}")

        importer4 = ContextImporter(workspace_dir=ws)
        instr = importer4.import_latest(output)
        assert instr is not None
        print(f"[OK] import_latest: paquete mas reciente cargado")

    # Test 6: verify
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        ws.mkdir()
        (ws / "00_estado_actual.md").write_text("test")
        (ws / "01_indice_recuperacion.md").write_text("test")

        importer5 = ContextImporter(workspace_dir=ws)
        assert importer5.verify() is True
        print(f"[OK] verify: archivos minimos presentes")

        # Quitar un archivo
        (ws / "00_estado_actual.md").unlink()
        assert importer5.verify() is False
        print(f"[OK] verify: detecta archivo faltante")

    print("\n[PASS] importer.py: todos los tests pasaron")
