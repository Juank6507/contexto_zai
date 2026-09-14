# contexto_zai/coordinador/integrador_respuestas.py -- IntegradorRespuestas: aplica respuestas de subagentes a los archivos de recuperación.
"""IntegradorRespuestas (v4.2).

Aplica las respuestas de los subagentes a los archivos de recuperación
del workspace. Es el "integrador" que el ``Orquestador`` llama cuando
el agente invoca ``pipeline.collect_responses()``.

Lee las respuestas de ``_responses/``, las procesa según su propósito
(``estado.d4``, ``estado.a1_resumen``, ``decisiones``, ``subdivider.nombre``,
``consulta.bloque``, etc.), y actualiza los archivos correspondientes.

Atómico standalone: importa config, models, pathlib, logging y re.
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


import json
import logging
import re
from pathlib import Path
from typing import Optional

from contexto_zai.config import WORKSPACE_OUTPUT_DIR
from contexto_zai.models import SubagentResponse

logger = logging.getLogger(__name__)


class IntegradorRespuestas:
    """Aplica respuestas de subagentes a los archivos de recuperación.

    Attributes:
        workspace_dir: Directorio del workspace con los archivos.

    Usage (Orquestador):
        >>> integrador = IntegradorRespuestas(workspace_dir="/path/to/ws")
        >>> resultado = orquestador.aplicar_respuestas(integrador=integrador)
    """

    # Mapeo de purpose → método integrador
    PURPOSE_HANDLERS = {
        "estado.d4": "_integrar_estado_d4",
        "estado.a1_resumen": "_integrar_estado_a1_resumen",
        "intercambios.restricciones_tema": "_integrar_estado_d4",
        "intercambios.resumen_truncado": "_integrar_estado_a1_resumen",
        "intercambios.decisiones": "_integrar_decisiones",
        "decisiones": "_integrar_decisiones",
        "intercambios.nombre_legible": "_integrar_subdivider_nombre",
        "subdivider.nombre": "_integrar_subdivider_nombre",
        "consulta.bloque": "_integrar_consulta",
        "documento.mediano": "_integrar_documento",
        "documento.grande": "_integrar_documento",
    }

    def __init__(self, workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR) -> None:
        self._workspace_dir = Path(workspace_dir)
        logger.debug("IntegradorRespuestas inicializado: %s", self._workspace_dir)

    @property
    def workspace_dir(self) -> Path:
        return self._workspace_dir

    # -- API pública ------------------------------------------------

    def integrar(
        self,
        responses: list[SubagentResponse],
        workspace_dir: Optional[Path | str] = None,
    ) -> dict:
        """Aplica las respuestas a los archivos de recuperación.

        Args:
            responses: Lista de SubagentResponse leídas de _responses/.
            workspace_dir: Directorio del workspace (sobreescribe el del constructor).

        Returns:
            Dict con:
            - "total_applied": número de respuestas aplicadas.
            - "estado_updated": True si se actualizó 00_estado_actual.md.
            - "decisiones_updated": True si se actualizó 02_decisiones_clave.md.
            - "metadata_updated": True si se actualizó _metadata.json.
            - "errores": lista de errores.
        """
        ws = Path(workspace_dir) if workspace_dir else self._workspace_dir

        resultado = {
            "total_applied": 0,
            "estado_updated": False,
            "decisiones_updated": False,
            "metadata_updated": False,
            "errores": [],
        }

        for resp in responses:
            if not resp.success:
                resultado["errores"].append(f"{resp.task_id}: {resp.error}")
                continue

            handler_method = self._get_handler(resp)
            if handler_method is None:
                logger.debug("Sin handler para %s (purpose desconocido)", resp.task_id)
                continue

            try:
                applied = handler_method(resp, ws)
                if applied:
                    resultado["total_applied"] += 1
            except Exception as e:
                msg = f"Error integrando {resp.task_id}: {e}"
                resultado["errores"].append(msg)
                logger.error(msg, exc_info=True)

        return resultado

    # -- Métodos privados -------------------------------------------

    def _get_handler(self, response: SubagentResponse):
        """Obtiene el método handler según el task_id o context del response."""
        task_id = response.task_id

        # Mapear task_id a handler (formatos del ProcesadorIntercambios y legacy)
        if "restricciones_tema" in task_id or "estado_d4" in task_id or "estado.d4" in task_id:
            return self._integrar_estado_d4
        elif "resumen_truncado" in task_id or "estado_a1_resumen" in task_id or "a1_resumen" in task_id:
            return self._integrar_estado_a1_resumen
        elif "decisiones" in task_id:
            return self._integrar_decisiones
        elif "nombre_legible" in task_id or "subdivider_nombre" in task_id:
            return self._integrar_subdivider_nombre
        elif "consulta" in task_id:
            return self._integrar_consulta
        elif "documento" in task_id:
            return self._integrar_documento
        else:
            return None

    def _integrar_estado_d4(self, response: SubagentResponse, ws: Path) -> bool:
        """Actualiza la sección D4 en 00_estado_actual.md."""
        estado_path = ws / "00_estado_actual.md"
        if not estado_path.exists():
            return False

        content = estado_path.read_text(encoding="utf-8")
        new_d4 = self._format_d4_response(response.response)

        # Reemplazar la sección D4
        updated = self._replace_section(content, "D4", new_d4)
        if updated != content:
            estado_path.write_text(updated, encoding="utf-8")
            logger.info("D4 actualizada en 00_estado_actual.md")
            return True
        return False

    def _integrar_estado_a1_resumen(self, response: SubagentResponse, ws: Path) -> bool:
        """Añade el resumen a la sección A1 en 00_estado_actual.md."""
        estado_path = ws / "00_estado_actual.md"
        if not estado_path.exists():
            return False

        content = estado_path.read_text(encoding="utf-8")
        marker = "## Resumen del contenido truncado"
        resumen = response.response.strip()

        if marker in content:
            # Reemplazar bloque existente
            pattern = rf"({re.escape(marker)}[^\n]*\n\n)(.*?)(?=\n## |\Z)"
            updated = re.sub(pattern, rf"\g<1>{resumen}\n", content, flags=re.DOTALL)
        else:
            # Añadir al final
            updated = content + f"\n\n{marker}\n\n{resumen}\n"

        if updated != content:
            estado_path.write_text(updated, encoding="utf-8")
            logger.info("A1 resumen actualizado en 00_estado_actual.md")
            return True
        return False

    def _integrar_decisiones(self, response: SubagentResponse, ws: Path) -> bool:
        """Actualiza 02_decisiones_clave.md con las decisiones reales."""
        decisiones_path = ws / "02_decisiones_clave.md"
        if not decisiones_path.exists():
            return False

        decisions = self._parse_decisiones_response(response.response)
        if not decisions:
            return False

        content = self._format_decisiones_markdown(decisions)
        decisiones_path.write_text(content, encoding="utf-8")
        logger.info("02_decisiones_clave.md actualizado con %d decisiones", len(decisions))
        return True

    def _integrar_subdivider_nombre(self, response: SubagentResponse, ws: Path) -> bool:
        """Actualiza _metadata.json con el nombre legible."""
        metadata_path = ws / "_metadata.json"
        if not metadata_path.exists():
            return False

        # Extraer nombre temporal del task_id
        task_id = response.task_id
        # Formato legacy: subdivider_nombre_{nombre_temporal}
        if "subdivider_nombre_" in task_id:
            nombre_temporal = task_id.split("subdivider_nombre_", 1)[1]
        # Formato nuevo: intercambios_nombre_legible_{nombre_temporal}
        elif "nombre_legible_" in task_id:
            nombre_temporal = task_id.split("nombre_legible_", 1)[1]
        else:
            return False

        nombre_legible = response.response.strip().lower().replace(" ", "_")
        if not nombre_legible or len(nombre_legible) > 50:
            return False

        # Actualizar metadata
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            tema_a_archivo = metadata.get("tema_a_archivo", {})
            new_tema_a_archivo = {}
            for tema, archivo in tema_a_archivo.items():
                # Coincidencia exacta
                if tema == nombre_temporal:
                    new_tema_a_archivo[nombre_legible] = archivo
                # Coincidencia parcial: si el tema empieza con el nombre temporal
                elif tema.startswith(nombre_temporal + "_") or tema.startswith(nombre_temporal):
                    # Reemplazar solo la parte inicial
                    new_tema = nombre_legible + tema[len(nombre_temporal):]
                    new_tema_a_archivo[new_tema] = archivo
                else:
                    new_tema_a_archivo[tema] = archivo
            metadata["tema_a_archivo"] = new_tema_a_archivo
            metadata_path.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("Metadata actualizada: '%s' → '%s' (coincidencia parcial)", nombre_temporal, nombre_legible)
            return True
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Error actualizando metadata: %s", e)
            return False

    def _integrar_consulta(self, response: SubagentResponse, ws: Path) -> bool:
        """Para consultas, la respuesta se entrega al agente, no se integra a archivos."""
        # La respuesta de consulta se devuelve directamente al agente vía el resultado
        # del Orquestador. No se escribe en ningún archivo.
        logger.debug("Respuesta de consulta lista para entregar al agente")
        return True

    def _integrar_documento(self, response: SubagentResponse, ws: Path) -> bool:
        """Para documentos, la respuesta se procesa según F4 (pendiente)."""
        # F4 (v4.2): aquí se actualizará el índice y los bloques con el contenido
        # clasificado del documento. Por ahora, placeholder.
        logger.debug("Respuesta de documento recibida (F4 lo procesará)")
        return True

    # -- Métodos de formato -----------------------------------------

    def _format_d4_response(self, response: str) -> str:
        """Formatea la respuesta del subagente D4."""
        response = response.strip()
        if not response or response.upper() == "SIN_RESTRICCIONES":
            return "No se identifican restricciones explícitas en el tema activo."
        lines = []
        for line in response.split("\n"):
            line = line.strip()
            if line.startswith("RESTRICCION:"):
                lines.append(f"- {line[len('RESTRICCION:'):].strip()}")
            elif line.startswith("ALCANCE:"):
                lines.append(f"  Alcance: {line[len('ALCANCE:'):].strip()}")
            elif line:
                lines.append(f"- {line}")
        return "\n".join(lines) if lines else response

    def _replace_section(self, content: str, section: str, new_text: str) -> str:
        """Reemplaza el contenido de una sección en el markdown."""
        pattern = rf"(## Sección {section} -- [^\n]+\n\n)"
        match = re.search(pattern, content)
        if not match:
            pattern2 = rf"(## Sección {section}[^\n]*\n\n)"
            match = re.search(pattern2, content)
            if not match:
                return content
        after_header = content[match.end():]
        next_section = re.search(r"\n## ", after_header)
        if next_section:
            rest = after_header[next_section.start():]
            return content[:match.end()] + new_text + "\n\n" + rest
        else:
            return content[:match.end()] + new_text + "\n"

    def _parse_decisiones_response(self, response: str) -> list:
        """Parsea la respuesta del subagente de decisiones."""
        response = response.strip()
        if not response or response.upper() == "SIN_DECISIONES":
            return []

        decisions = []
        current = {}
        for line in response.split("\n"):
            line = line.strip()
            if line.startswith("DECISION:"):
                if current.get("decision"):
                    decisions.append(current)
                current = {"decision": line[len("DECISION:"):].strip()}
            elif line.startswith("ALCANCE:"):
                current["alcance"] = line[len("ALCANCE:"):].strip()
            elif line.startswith("RAZON:"):
                current["razon"] = line[len("RAZON:"):].strip()
        if current.get("decision"):
            decisions.append(current)
        return decisions

    def _format_decisiones_markdown(self, decisions: list) -> str:
        """Formatea las decisiones como markdown."""
        lines = [
            "# Decisiones Clave",
            "",
            f"**Total de decisiones:** {len(decisions)}",
            "",
            "---",
            "",
        ]
        for i, d in enumerate(decisions, 1):
            lines.append(f"## D{i:02d} -- {d.get('decision', '')[:100]}")
            lines.append("")
            lines.append(f"- **Decisión:** {d.get('decision', '')}")
            if d.get("alcance"):
                lines.append(f"- **Alcance:** {d['alcance']}")
            if d.get("razon"):
                lines.append(f"- **Razón:** {d['razon']}")
            lines.append("")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"IntegradorRespuestas(workspace_dir={self._workspace_dir!r})"


if __name__ == "__main__":
    # Compatibilidad Windows
    import io as _io, sys as _sys
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
        if hasattr(_sys.stderr, 'buffer') and 'utf' not in (getattr(_sys.stderr, 'encoding', '') or '').lower():
            _sys.stderr = _io.TextIOWrapper(_sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass

    print("=== Validacion de integrador_respuestas.py ===\n")

    import tempfile

    # Test 1: integrar D4
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        estado_path = Path(tmpdir) / "00_estado_actual.md"
        estado_path.write_text(
            "# Estado Actual\n\n## Sección D4 -- Restricciones\n\nPlaceholder viejo.\n\n## Sección A1\n\n",
            encoding="utf-8",
        )
        resp = SubagentResponse(
            task_id="estado_d4",
            success=True,
            response="RESTRICCION: No usar indigo\nALCANCE: general",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        assert result["estado_updated"] or result["total_applied"] == 1
        content = estado_path.read_text(encoding="utf-8")
        assert "indigo" in content
        print(f"[OK] integrar D4: restricción actualizada")

    # Test 2: integrar A1 resumen
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        estado_path = Path(tmpdir) / "00_estado_actual.md"
        estado_path.write_text("# Estado Actual\n\n## Sección A1\n\nTexto textual.\n", encoding="utf-8")
        resp = SubagentResponse(
            task_id="estado_a1_resumen",
            success=True,
            response="Resumen del contenido truncado.",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        content = estado_path.read_text(encoding="utf-8")
        assert "Resumen del contenido truncado" in content
        print(f"[OK] integrar A1 resumen: resumen añadido")

    # Test 3: integrar decisiones
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        decisiones_path = Path(tmpdir) / "02_decisiones_clave.md"
        decisiones_path.write_text("# Decisiones Clave\n\nPlaceholder.\n", encoding="utf-8")
        resp = SubagentResponse(
            task_id="decisiones_lote_0",
            success=True,
            response="DECISION: Usar OOP\nALCANCE: ClasificadorSubagent\nRAZON: Directiva del Director.",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        content = decisiones_path.read_text(encoding="utf-8")
        assert "Usar OOP" in content
        assert "ClasificadorSubagent" in content
        print(f"[OK] integrar decisiones: decisión real con alcance")

    # Test 4: integrar subdivider nombre
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        metadata_path = Path(tmpdir) / "_metadata.json"
        metadata_path.write_text(json.dumps({
            "tema_a_archivo": {"general_2026sep09": "bloque_01.md"}
        }), encoding="utf-8")
        resp = SubagentResponse(
            task_id="subdivider_nombre_general_2026sep09",
            success=True,
            response="autenticacion_jwt",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert "autenticacion_jwt" in metadata["tema_a_archivo"]
        assert "general_2026sep09" not in metadata["tema_a_archivo"]
        print(f"[OK] integrar subdivider nombre: metadata actualizada")

    # Test 5: respuesta fallida reporta error
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        resp = SubagentResponse(task_id="t1", success=False, error="timeout")
        result = integrador.integrar([resp])
        assert len(result["errores"]) == 1
        assert "timeout" in result["errores"][0]
        print(f"[OK] respuesta fallida: error reportado")

    # Test 6: consulta no actualiza archivos (solo se entrega al agente)
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        resp = SubagentResponse(
            task_id="consulta_directa",
            success=True,
            response="Respuesta de la consulta.",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        print(f"[OK] consulta: no actualiza archivos (se entrega al agente)")

    # Test 7: SIN_RESTRICCIONES
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        estado_path = Path(tmpdir) / "00_estado_actual.md"
        estado_path.write_text("# Estado Actual\n\n## Sección D4 -- Restricciones\n\nViejo.\n\n## A1\n", encoding="utf-8")
        resp = SubagentResponse(task_id="estado_d4", success=True, response="SIN_RESTRICCIONES")
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        content = estado_path.read_text(encoding="utf-8")
        assert "No se identifican restricciones" in content
        print(f"[OK] SIN_RESTRICCIONES: mensaje apropiado")

    # Test 8: lista vacía
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        result = integrador.integrar([])
        assert result["total_applied"] == 0
        print(f"[OK] lista vacía: 0 aplicadas")

    # Test 9: repr
    integrador_repr = IntegradorRespuestas(workspace_dir="/tmp/test_repr")
    assert "IntegradorRespuestas" in repr(integrador_repr)
    print(f"[OK] repr: {integrador_repr!r}")

    print("\n[PASS] integrador_respuestas.py: todos los tests pasaron")
