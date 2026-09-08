# context/exporter.py -- Exportador de contexto: empaqueta todos los archivos en un .zip con instrucciones de recuperacion.
"""Exportador de contexto (v3.4).

Empaqueta todos los archivos del contexto (estado, indice,
decisiones, bloques, metadata, grafos) en un .zip con
instrucciones de recuperacion y metadata del paquete.

El paquete se guarda en download/ o donde el Director indique.

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ContextExporter:
    """Empaqueta el contexto del proyecto en un .zip.

    Args:
        workspace_dir: Directorio donde estan los archivos del contexto.
            Por defecto /home/z/my-project/contexto_recuperacion/.

    Usage:
        >>> exporter = ContextExporter()
        >>> path = exporter.export(chat_id="abc-123")
        >>> print(f"Exportado en: {path}")
    """

    def __init__(
        self,
        workspace_dir: Path | str = "/home/z/my-project/contexto_recuperacion",
    ) -> None:
        self._workspace_dir = Path(workspace_dir)
        logger.debug("ContextExporter inicializado: workspace=%s", self._workspace_dir)

    # ── API publica ────────────────────────────────────────────

    def export(
        self,
        chat_id: str = "",
        output_dir: Path | str = "/home/z/my-project/download",
    ) -> Optional[Path]:
        """Empaqueta el contexto en un .zip.

        Args:
            chat_id: ID del chat para nombrar el archivo.
            output_dir: Directorio donde guardar el .zip.

        Returns:
            Ruta del .zip creado, o None si no habia archivos.
        """
        if not self._workspace_dir.exists():
            logger.warning("Directorio de contexto no existe: %s", self._workspace_dir)
            return None

        # Recopilar archivos del contexto
        context_files = self._collect_files()
        if not context_files:
            logger.warning("No hay archivos de contexto para exportar")
            return None

        # Generar metadata del paquete
        paquete_meta = self._build_paquete_meta(chat_id, context_files)

        # Generar instrucciones de recuperacion
        instrucciones = self._build_instrucciones(chat_id, context_files)

        # Nombre del archivo
        fecha = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_chat_id = chat_id[:8] if chat_id else "default"
        zip_name = f"contexto_exportado_{safe_chat_id}_{fecha}.zip"

        # Crear el .zip
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        zip_path = output_path / zip_name

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Escribir metadata del paquete
            zf.writestr("_paquete.json", json.dumps(paquete_meta, indent=2, ensure_ascii=False))

            # Escribir instrucciones
            zf.writestr("_instrucciones_recuperacion.md", instrucciones)

            # Escribir archivos del contexto
            for filepath, arcname in context_files:
                zf.write(filepath, arcname)

        logger.info(
            "Contexto exportado: %s (%d archivos, %s)",
            zip_path, len(context_files), self._format_size(zip_path.stat().st_size),
        )
        return zip_path

    def __repr__(self) -> str:
        return f"ContextExporter(workspace={self._workspace_dir!r})"

    # ── Metodos privados ───────────────────────────────────────

    def _collect_files(self) -> list[tuple[Path, str]]:
        """Recopila todos los archivos del contexto.

        Returns:
            Lista de tuplas (filepath, arcname) donde arcname
            es el nombre del archivo dentro del .zip.
        """
        files: list[tuple[Path, str]] = []

        for filepath in sorted(self._workspace_dir.iterdir()):
            if filepath.is_file():
                files.append((filepath, filepath.name))

        logger.debug("Recopilados %d archivos del contexto", len(files))
        return files

    def _build_paquete_meta(
        self,
        chat_id: str,
        context_files: list[tuple[Path, str]],
    ) -> dict:
        """Construye la metadata del paquete."""
        # Leer _metadata.json si existe
        meta_path = self._workspace_dir / "_metadata.json"
        total_exchanges = 0
        total_temas = 0

        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                total_exchanges = meta.get("total_exchanges", 0)
                total_temas = len(meta.get("tema_a_archivo", {}))
            except (json.JSONDecodeError, ValueError):
                pass

        return {
            "chat_id": chat_id,
            "fecha_exportacion": datetime.now(timezone.utc).isoformat(),
            "total_intercambios": total_exchanges,
            "total_temas": total_temas,
            "total_archivos": len(context_files),
            "version_spec": "3.4",
        }

    def _build_instrucciones(
        self,
        chat_id: str,
        context_files: list[tuple[Path, str]],
    ) -> str:
        """Genera las instrucciones de recuperacion para el agente nuevo."""
        filenames = [arcname for _, arcname in context_files]

        return f"""# Instrucciones de Recuperacion de Contexto

## Que es este paquete

Este paquete contiene la memoria completa del proyecto hasta el momento de la exportacion.
Incluye el estado actual, el indice de temas, las decisiones tomadas, los bloques tematicos
con todo el contenido del chat, y la metadata del proceso.

## Como recuperar el contexto

1. **Descomprime este paquete** en `/home/z/my-project/contexto_recuperacion/`.

2. **Lee `00_estado_actual.md`** para saber donde quedo el proyecto.
   - Contiene 8 secciones: D1-D4 (Director) + A1-A4 (Agente).
   - D1: ultima instruccion del Director (literal).
   - D2: contexto del tema activo.
   - D3: decisiones pendientes.
   - D4: restricciones activas.
   - A1: que estaba haciendo el agente.
   - A2: entregables producidos.
   - A3: errores abiertos.
   - A4: siguiente paso logico.

3. **Lee `01_indice_recuperacion.md`** para saber que temas hay y en que bloque esta cada uno.
   - Tabla `tema -> archivo` con todos los temas mapeados.

4. **Si necesitas detalle de un tema**, lanza un subagente con Task que lea el bloque.
   - NO leas los bloques directamente (gastan tu memoria).
   - Task(prompt="Lee /home/z/my-project/contexto_recuperacion/{{bloque}}.md y responde: {{tu pregunta}}")

5. **Consultas `02_decisiones_clave.md`** para saber que decisiones ya se tomaron.
   - No re-decidas lo ya resuelto.

## Archivos incluidos en este paquete

{chr(10).join(f"- `{f}`" for f in filenames)}

## Metadata del paquete

- **chat_id origen:** {chat_id}
- **Fecha de exportacion:** {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}
- **Total de archivos:** {len(context_files)}
- **Version de spec:** v3.4
"""

    @staticmethod
    def _format_size(size: int) -> str:
        """Formatea un tamano en bytes a legible."""
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"


if __name__ == "__main__":
    import io as _io
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass

    print("=== Validacion de exporter.py ===\n")

    import tempfile

    # Test 1: exportar sin directorio de contexto
    exporter = ContextExporter(workspace_dir="/tmp/no_existe")
    result = exporter.export(chat_id="test")
    assert result is None
    print("[OK] Sin directorio: devuelve None")

    # Test 2: exportar con archivos de prueba
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "contexto"
        ws.mkdir()

        # Crear archivos de prueba
        (ws / "00_estado_actual.md").write_text("# Estado\n\nTest", encoding="utf-8")
        (ws / "01_indice_recuperacion.md").write_text("# Indice\n\nTest", encoding="utf-8")
        (ws / "02_decisiones_clave.md").write_text("# Decisiones\n\nTest", encoding="utf-8")
        (ws / "bloque_01.md").write_text("# Bloque 1\n\nTest", encoding="utf-8")
        (ws / "_metadata.json").write_text(
            json.dumps({
                "chat_id": "test-123",
                "total_exchanges": 10,
                "tema_a_archivo": {"tema1": "bloque_01.md", "tema2": "bloque_01.md"},
            }),
            encoding="utf-8",
        )

        output_dir = Path(tmpdir) / "output"
        exporter = ContextExporter(workspace_dir=ws)
        zip_path = exporter.export(chat_id="test-123", output_dir=output_dir)

        assert zip_path is not None
        assert zip_path.exists()
        assert zip_path.suffix == ".zip"
        print(f"[OK] Exportacion: {zip_path.name} ({zip_path.stat().st_size} bytes)")

        # Verificar contenido del .zip
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            assert "_paquete.json" in names
            assert "_instrucciones_recuperacion.md" in names
            assert "00_estado_actual.md" in names
            assert "01_indice_recuperacion.md" in names
            assert "02_decisiones_clave.md" in names
            assert "bloque_01.md" in names
            assert "_metadata.json" in names
            print(f"[OK] Contenido del .zip: {len(names)} archivos")

            # Verificar _paquete.json
            paquete = json.loads(zf.read("_paquete.json"))
            assert paquete["chat_id"] == "test-123"
            assert paquete["total_intercambios"] == 10
            assert paquete["total_temas"] == 2
            assert paquete["version_spec"] == "3.4"
            print(f"[OK] _paquete.json: chat_id={paquete['chat_id']}, temas={paquete['total_temas']}")

            # Verificar instrucciones
            instr = zf.read("_instrucciones_recuperacion.md").decode("utf-8")
            assert "Instrucciones de Recuperacion" in instr
            assert "00_estado_actual.md" in instr
            assert "test-123" in instr
            print(f"[OK] _instrucciones_recuperacion.md: generada correctamente")

    # Test 3: _format_size
    assert ContextExporter._format_size(500) == "500 B"
    assert ContextExporter._format_size(2048) == "2.0 KB"
    assert ContextExporter._format_size(1048576) == "1.0 MB"
    print("[OK] _format_size: formatos correctos")

    print("\n[PASS] exporter.py: todos los tests pasaron")
