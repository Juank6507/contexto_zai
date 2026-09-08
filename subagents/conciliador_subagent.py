# contexto_zai/subagents/conciliador_subagent.py -- Subagente Nivel 3: consolida índices parciales (v3.6).
"""Subagente Conciliador (Nivel 3) para documentos grandes (v3.6).

Recibe los índices parciales de los subagentes N2, los consolida
en un índice único sin duplicados, genera un resumen final coherente,
y devuelve el resultado al agente principal.

Flujo:
1. Recibe lista de IndiceParcial de los N2.
2. Usa DocumentoConciliador para consolidar (deduplicar temas).
3. Lanza subagente N3 para reorganizar temas + generar resumen final.
4. Devuelve DocumentoIndexResult al agente principal.
5. N3 se cierra.

Atómico standalone: importa launcher, conciliador, models.
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

from contexto_zai.config import DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS
from contexto_zai.models import Attachment, IndiceConsolidado, IndiceParcial
from contexto_zai.processing.conciliador import (
    Conciliador,
    DocumentoConciliador,
    ThemeSection,
)
from contexto_zai.subagents.documento_indexer_subagent import DocumentoIndexResult
from contexto_zai.subagents.launcher import SubagentLauncher, SubagentResponse

logger = logging.getLogger(__name__)


class ConciliadorSubagent:
    """Subagente Nivel 3: consolida índices parciales de N2 (v3.6).

    Args:
        launcher: SubagentLauncher para invocar el Task de N3.
        conciliador: Conciliador concreto para consolidar índices.

    Usage:
        >>> n3 = ConciliadorSubagent(launcher=launcher, conciliador=DocumentoConciliador())
        >>> result = n3.run(indices_parciales, attachment)
        >>> if result.success:
        ...     print(result.resumen_breve)
        ...     print(result.temas_nombres)
    """

    def __init__(
        self,
        launcher: SubagentLauncher,
        conciliador: Optional[Conciliador] = None,
    ) -> None:
        self._launcher = launcher
        self._conciliador = conciliador or DocumentoConciliador()
        logger.debug(
            "ConciliadorSubagent inicializado: conciliador=%s",
            type(self._conciliador).__name__,
        )

    # ── API pública ──────────────────────────────────────────────

    def run(
        self,
        indices_parciales: list[IndiceParcial],
        attachment: Attachment,
        archivo_indexado_path: Optional[Path] = None,
    ) -> DocumentoIndexResult:
        """Ejecuta el flujo de Nivel 3: consolidar + generar resumen final.

        Args:
            indices_parciales: Lista de IndiceParcial de los N2.
            attachment: Attachment con metadata del documento.
            archivo_indexado_path: Ruta donde se guardó el archivo (opcional).

        Returns:
            DocumentoIndexResult con resumen final, temas consolidados y success.
        """
        if not indices_parciales:
            logger.warning("N3: sin índices parciales para consolidar")
            return DocumentoIndexResult(
                attachment_id=attachment.file_id,
                filename=attachment.filename,
                success=False,
                error="Sin índices parciales para consolidar",
            )

        # 1. Consolidar índices (deduplicación local, sin subagente)
        consolidado = self._conciliador.conciliar(
            respuestas=[],
            indices_parciales=indices_parciales,
        )

        # 2. Lanzar subagente N3 para reorganizar temas + generar resumen final
        prompt = self._build_n3_prompt(consolidado, attachment)

        try:
            response: SubagentResponse = self._launcher.launch(
                prompt=prompt,
                files_to_read=[],
                description=f"Consolidar índices de {attachment.filename}",
            )
        except Exception as e:
            logger.error("N3: error lanzando subagente: %s", e)
            # Fallback: usar el resumen del conciliador local
            return DocumentoIndexResult(
                attachment_id=attachment.file_id,
                filename=attachment.filename,
                resumen_breve=consolidado.resumen_final,
                temas_detectados=consolidado.temas_consolidados,
                archivo_indexado_path=archivo_indexado_path,
                success=True,
            )

        if not response.success:
            logger.warning("N3: subagente falló: %s", response.error)
            # Fallback: usar el resumen del conciliador local
            return DocumentoIndexResult(
                attachment_id=attachment.file_id,
                filename=attachment.filename,
                resumen_breve=consolidado.resumen_final,
                temas_detectados=consolidado.temas_consolidados,
                archivo_indexado_path=archivo_indexado_path,
                success=True,
            )

        # 3. Parsear respuesta del N3 para obtener resumen final mejorado
        resumen_final, temas_reorganizados = self._parse_n3_response(
            response.content, consolidado,
        )

        # Truncar resumen si excede el máximo
        if len(resumen_final) > DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS:
            resumen_final = resumen_final[:DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS - 3] + "..."

        logger.info(
            "N3: %d índices parciales → %d temas consolidados, resumen %d chars",
            len(indices_parciales), len(temas_reorganizados), len(resumen_final),
        )

        return DocumentoIndexResult(
            attachment_id=attachment.file_id,
            filename=attachment.filename,
            resumen_breve=resumen_final,
            temas_detectados=temas_reorganizados,
            archivo_indexado_path=archivo_indexado_path,
            success=True,
        )

    # ── Métodos privados ─────────────────────────────────────────

    def _build_n3_prompt(
        self,
        consolidado: IndiceConsolidado,
        attachment: Attachment,
    ) -> str:
        """Construye el prompt para el subagente N3."""
        # Preparar resumen de índices parciales para el prompt
        indices_summary = []
        for ip in consolidado.indices_parciales:
            temas_str = ", ".join(
                f"{t.tema} ({len(t.secciones)} sec.)"
                for t in (ip.temas if isinstance(ip.temas, list) else [])
            )
            indices_summary.append(
                f"Porción {ip.porcion_id}: {temas_str or 'sin temas'}"
            )

        indices_text = "\n".join(indices_summary)

        # Preparar temas consolidados actuales
        temas_actuales = "\n".join(
            f"- {t.tema}: {t.descripcion}"
            for t in consolidado.temas_consolidados
        )

        return f"""Eres un subagente conciliador (Nivel 3) de documentos grandes.

Documento: {attachment.filename}
Partes procesadas: {len(consolidado.indices_parciales)}

Índices parciales recibidos de los N2:
{indices_text}

Temas consolidados (tras deduplicación):
{temas_actuales or "(sin temas)"}

Tu tarea:
1. Revisa los temas consolidados.
2. Reubica los temas en categorías coherentes si es necesario.
3. Si hay temas muy similares que no se fusionaron, fúndelos.
4. Genera un resumen final del documento completo (máximo {DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS} caracteres).

Formato de respuesta EXACTO:

RESUMEN_FINAL: <resumen coherente del documento completo>

TEMAS_REORGANIZADOS:
<tema1>
<tema2>
<tema3>

Reglas:
- El resumen debe ser revelador y específico del documento.
- Los temas deben estar en snake_case, uno por línea.
- Máximo 5 temas reorganizados.

Respuesta:"""

    @staticmethod
    def _parse_n3_response(
        content: str,
        consolidado: IndiceConsolidado,
    ) -> tuple[str, list[ThemeSection]]:
        """Parsea la respuesta del N3.

        Args:
            content: Contenido de la respuesta del subagente N3.
            consolidado: Índice consolidado local (fallback).

        Returns:
            Tupla (resumen_final, temas_reorganizados).
        """
        import re

        # Extraer RESUMEN_FINAL
        resumen_match = re.search(
            r"RESUMEN_FINAL:\s*(.+?)(?=\n\s*TEMAS_REORGANIZADOS:|\Z)",
            content,
            re.DOTALL,
        )
        resumen_final = resumen_match.group(1).strip() if resumen_match else ""

        # Extraer TEMAS_REORGANIZADOS
        temas_match = re.search(
            r"TEMAS_REORGANIZADOS:\s*\n(.+)",
            content,
            re.DOTALL,
        )

        temas_reorganizados: list[ThemeSection] = []
        if temas_match:
            temas_text = temas_match.group(1).strip()
            for line in temas_text.split("\n"):
                line = line.strip().lstrip("-").strip()
                if not line:
                    continue
                # Buscar el tema en los consolidados
                tema_normalized = Conciliador._normalize_tema_for_dedup(line)
                found = None
                for t in consolidado.temas_consolidados:
                    if Conciliador._normalize_tema_for_dedup(t.tema) == tema_normalized:
                        found = t
                        break
                if found:
                    temas_reorganizados.append(found)
                else:
                    # Tema nuevo mencionado por N3, añadirlo
                    temas_reorganizados.append(ThemeSection(
                        tema=Conciliador._sanitize_tema_name(line),
                        descripcion="",
                        secciones=[],
                    ))
        else:
            # Si N3 no reorganizó, usar los consolidados originales
            temas_reorganizados = list(consolidado.temas_consolidados)

        # Fallback: si no hay resumen, usar el del consolidado
        if not resumen_final:
            resumen_final = consolidado.resumen_final

        return resumen_final, temas_reorganizados

    def __repr__(self) -> str:
        return (
            f"ConciliadorSubagent(conciliador={type(self._conciliador).__name__})"
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

    print("=== Validacion de conciliador_subagent.py ===\n")

    from contexto_zai.models import Attachment, IndiceParcial
    from contexto_zai.processing.conciliador import ThemeSection
    from contexto_zai.subagents.launcher import SubagentLauncher

    # Mock invoker para N3
    def mock_n3_invoker(prompt: str) -> str:
        return """RESUMEN_FINAL: Documento procesado en 3 partes. Contiene autenticación JWT, configuración de base de datos, validaciones con pytest y documentación del proyecto.

TEMAS_REORGANIZADOS:
auth_jwt
config_db
validaciones_pytest
documentacion"""

    # Test 1: flujo completo con 3 índices parciales
    launcher = SubagentLauncher(task_invoker=mock_n3_invoker)
    n3 = ConciliadorSubagent(launcher=launcher)

    indices_parciales = [
        IndiceParcial(
            porcion_id=1,
            temas=[
                ThemeSection(tema="auth_jwt", descripcion="Auth", secciones=["login", "logout"]),
                ThemeSection(tema="config_db", descripcion="DB config", secciones=["sqlite"]),
            ],
            resumen_parcial="Porción 1 sobre auth y config.",
        ),
        IndiceParcial(
            porcion_id=2,
            temas=[
                ThemeSection(tema="validaciones_pytest", descripcion="Tests", secciones=["unitarias"]),
                ThemeSection(tema="auth_jwt", descripcion="Más auth", secciones=["cookie"]),
            ],
            resumen_parcial="Porción 2 sobre validaciones.",
        ),
        IndiceParcial(
            porcion_id=3,
            temas=[
                ThemeSection(tema="documentacion", descripcion="Docs", secciones=["spec_v3"]),
            ],
            resumen_parcial="Porción 3 sobre docs.",
        ),
    ]

    att = Attachment(
        file_id="test-001", filename="doc_grande.pdf",
        content_type="application/pdf", size=1652025,
    )

    result = n3.run(indices_parciales, att)

    assert result.success, f"Debe ser success, error: {result.error}"
    assert result.filename == "doc_grande.pdf"
    assert "autenticación JWT" in result.resumen_breve or "auth" in result.resumen_breve.lower()
    assert len(result.temas_detectados) == 4  # auth_jwt, config_db, validaciones_pytest, documentacion
    assert len(result.resumen_breve) <= 500
    print(f"[OK] Flujo completo: {len(result.temas_detectados)} temas, resumen {len(result.resumen_breve)} chars")

    # Test 2: sin índices parciales → error
    result_empty = n3.run([], att)
    assert not result_empty.success
    assert "Sin índices" in result_empty.error
    print(f"[OK] Sin índices parciales: error correcto")

    # Test 3: N3 que falla → fallback al conciliador local
    def failing_n3_invoker(prompt: str) -> str:
        raise RuntimeError("Task API no disponible")

    launcher_fail = SubagentLauncher(task_invoker=failing_n3_invoker)
    n3_fail = ConciliadorSubagent(launcher=launcher_fail)

    result_fallback = n3_fail.run(indices_parciales, att)
    assert result_fallback.success  # fallback funciona
    assert len(result_fallback.temas_detectados) > 0  # tiene temas del consolidado local
    print(f"[OK] N3 que falla: fallback al conciliador local ({len(result_fallback.temas_detectados)} temas)")

    # Test 4: respuesta mal formada del N3
    def malformed_n3_invoker(prompt: str) -> str:
        return "No tiene el formato esperado"

    launcher_mal = SubagentLauncher(task_invoker=malformed_n3_invoker)
    n3_mal = ConciliadorSubagent(launcher=launcher_mal)

    result_mal = n3_mal.run(indices_parciales, att)
    assert result_mal.success
    # Sin resumen del N3, usa el del consolidado local
    assert len(result_mal.resumen_breve) > 0  # tiene resumen del fallback
    print(f"[OK] Respuesta mal formada: fallback funciona")

    # Test 5: _build_n3_prompt
    consolidado = IndiceConsolidado(
        indices_parciales=indices_parciales,
        temas_consolidados=[
            ThemeSection(tema="auth_jwt", descripcion="Auth", secciones=["login"]),
        ],
    )
    prompt = n3._build_n3_prompt(consolidado, att)
    assert "doc_grande.pdf" in prompt
    assert "3" in prompt  # 3 partes
    assert "auth_jwt" in prompt
    assert "RESUMEN_FINAL:" in prompt
    assert "TEMAS_REORGANIZADOS:" in prompt
    print(f"[OK] _build_n3_prompt: incluye filename, partes, temas y formato")

    # Test 6: _parse_n3_response
    resp_content = """RESUMEN_FINAL: Resumen de prueba del documento.

TEMAS_REORGANIZADOS:
auth_jwt
config_db
documentacion"""
    consolidado_test = IndiceConsolidado(
        temas_consolidados=[
            ThemeSection(tema="auth_jwt", descripcion="Auth", secciones=["login"]),
            ThemeSection(tema="config_db", descripcion="DB", secciones=["sqlite"]),
            ThemeSection(tema="documentacion", descripcion="Docs", secciones=["spec"]),
        ],
    )
    resumen, temas = ConciliadorSubagent._parse_n3_response(resp_content, consolidado_test)
    assert "Resumen de prueba" in resumen
    assert len(temas) == 3
    assert any(t.tema == "auth_jwt" for t in temas)
    print(f"[OK] _parse_n3_response: resumen + 3 temas reorganizados")

    # Test 7: repr
    r = repr(n3)
    assert "ConciliadorSubagent" in r
    print(f"[OK] repr: {r}")

    print("\n[PASS] conciliador_subagent.py: todos los tests pasaron")
