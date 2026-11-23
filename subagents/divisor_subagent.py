# contexto_zai/subagents/divisor_subagent.py -- Subagente Nivel 1: divide documento + lanza N2 en paralelo (v3.6).
"""Subagente Divisor (Nivel 1) para documentos grandes (v3.6).

Recibe un documento grande, lo particiona en porciones manejables,
y lanza subagentes de Nivel 2 en paralelo para procesar cada porción.
Cada N2 clasifica su porción y devuelve un índice parcial.
El N1 acumula todos los índices parciales y se cierra.

Flujo:
1. Recibe documento grande (path del archivo).
2. Particiona en N porciones (usa DocumentoDivisor).
3. Lanza N subagentes N2 en paralelo (max 3 a la vez).
4. Cada N2 devuelve su índice parcial.
5. N1 acumula los índices parciales.
6. N1 se cierra (el proceso luego pasa los índices al N3).

Atómico standalone: importa launcher, divisor, models.
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
from typing import Callable, Optional

from contexto_zai.config import (
    MAX_SUBAGENTES_N2_PARALELOS,
    MAX_TOKENS_POR_SUBAGENTE_N2,
)
from contexto_zai.models import Attachment, IndiceParcial, Porcion
from contexto_zai.processing.conciliador import ThemeSection
from contexto_zai.processing.divisor import Divisor, DocumentoDivisor
from contexto_zai.subagents.launcher import SubagentLauncher, SubagentResponse

logger = logging.getLogger(__name__)


class DivisorSubagent:
    """Subagente Nivel 1: divide documento + lanza N2 en paralelo (v3.6).

    Args:
        launcher: SubagentLauncher para invocar los Tasks de N2.
        divisor: Divisor concreto para particionar el documento.
        max_paralelos: Máximo de subagentes N2 en paralelo (default 3).

    Usage:
        >>> n1 = DivisorSubagent(launcher=launcher, divisor=DocumentoDivisor())
        >>> indices_parciales = n1.run(attachment, documento_path)
        >>> # Luego el proceso pasa indices_parciales al N3 (ConciliadorSubagent)
    """

    def __init__(
        self,
        launcher: SubagentLauncher,
        divisor: Optional[Divisor] = None,
        max_paralelos: int = MAX_SUBAGENTES_N2_PARALELOS,
    ) -> None:
        self._launcher = launcher
        self._divisor = divisor or DocumentoDivisor()
        self._max_paralelos = max_paralelos
        logger.debug(
            "DivisorSubagent inicializado: max_paralelos=%d, divisor=%s",
            max_paralelos, type(self._divisor).__name__,
        )

    # ── API pública ──────────────────────────────────────────────

    def run(
        self,
        attachment: Attachment,
        documento_path: Path | str,
    ) -> list[IndiceParcial]:
        """Ejecuta el flujo de Nivel 1: particionar + lanzar N2 + acumular.

        Args:
            attachment: Objeto Attachment con metadata del documento.
            documento_path: Ruta del archivo descargado.

        Returns:
            Lista de IndiceParcial (uno por cada N2 lanzado).
        """
        documento_path = Path(documento_path)

        # 1. Particionar documento
        porciones = self._divisor.particionar(
            documento_path,
            max_tokens_por_porcion=MAX_TOKENS_POR_SUBAGENTE_N2,
        )

        if not porciones:
            logger.warning(
                "No se pudo particionar el documento %s. Devolviendo lista vacía.",
                attachment.filename,
            )
            return []

        logger.info(
            "N1: documento '%s' particionado en %d porciones",
            attachment.filename, len(porciones),
        )

        # 2. Lanzar N2 en paralelo
        responses = self._divisor.lanzar_subagentes(
            porciones=porciones,
            launcher=self._launcher,
            max_paralelos=self._max_paralelos,
            prompt_builder=self._build_n2_prompt(attachment),
        )

        # 3. Parsear respuestas en IndiceParcial
        indices_parciales = self._parse_responses(responses, porciones)

        logger.info(
            "N1: %d/%d N2 completados exitosamente",
            sum(1 for ip in indices_parciales if ip.temas or ip.resumen_parcial),
            len(responses),
        )

        return indices_parciales

    # ── Métodos privados ─────────────────────────────────────────

    def _build_n2_prompt(self, attachment: Attachment) -> Callable[[Porcion], str]:
        """Construye el prompt builder para los subagentes N2.

        Args:
            attachment: Attachment con metadata del documento.

        Returns:
            Función que recibe una Porcion y devuelve su prompt.
        """
        def prompt_builder(porcion: Porcion) -> str:
            return f"""Eres un subagente clasificador de documentos (Nivel 2).
Estás procesando una porción de un documento grande.

Documento: {attachment.filename}
Porción: {porcion.id} ({porcion.paginas_str})
Tokens estimados: ~{porcion.tokens_estimados}

Tu tarea:
1. Lee el archivo PDF en la ruta indicada (solo las páginas {porcion.pagina_inicio} a {porcion.pagina_fin}).
2. Identifica los temas principales de esta porción.
3. Genera un resumen breve de esta porción (máximo 200 caracteres).
4. Lista los temas con sus secciones.

Formato de respuesta EXACTO:

RESUMEN: <resumen breve de la porción>

TEMA: <nombre_snake_case>
DESCRIPCION: <descripción corta del tema>
SECCIONES: <sección1, sección2>

(Repetir TEMA/DESCRIPCION/SECCIONES por cada tema detectado en esta porción)

Reglas:
- Nombres de tema en snake_case.
- Máximo 3 temas por porción.
- No incluyas contenido completo, solo resumen + índice.

Respuesta:"""
        return prompt_builder

    @staticmethod
    def _parse_responses(
        responses: list[SubagentResponse],
        porciones: list[Porcion],
    ) -> list[IndiceParcial]:
        """Parsea las respuestas de los N2 en IndiceParcial.

        Args:
            responses: Lista de SubagentResponse de los N2.
            porciones: Lista de Porcion correspondientes.

        Returns:
            Lista de IndiceParcial (uno por respuesta exitosa).
        """
        import re

        indices: list[IndiceParcial] = []
        for i, (resp, porcion) in enumerate(zip(responses, porciones)):
            if not resp.success or not resp.content:
                logger.warning(
                    "N2-%d (porción %d) falló: %s",
                    i + 1, porcion.id, resp.error or "sin contenido",
                )
                indices.append(IndiceParcial(
                    porcion_id=porcion.id,
                    temas=[],
                    resumen_parcial="",
                ))
                continue

            # Parsear resumen
            resumen_match = re.search(
                r"RESUMEN:\s*(.+?)(?=\n\s*TEMA:|\Z)",
                resp.content,
                re.DOTALL,
            )
            resumen = resumen_match.group(1).strip() if resumen_match else ""

            # Parsear temas
            pattern = re.compile(
                r"TEMA:\s*(\S+)\s*\n\s*DESCRIPCION:\s*(.+?)\s*\n\s*SECCIONES:\s*(.+?)(?=\n\s*TEMA:|\Z)",
                re.DOTALL,
            )
            temas: list[ThemeSection] = []
            for match in pattern.finditer(resp.content):
                nombre = match.group(1).strip()
                descripcion = match.group(2).strip()
                secciones_str = match.group(3).strip()
                secciones = [s.strip() for s in secciones_str.split(",") if s.strip()]
                temas.append(ThemeSection(
                    tema=nombre,
                    descripcion=descripcion,
                    secciones=secciones,
                ))

            indices.append(IndiceParcial(
                porcion_id=porcion.id,
                temas=temas,
                resumen_parcial=resumen,
            ))
            logger.debug(
                "N2-%d (porción %d): %d temas, resumen %d chars",
                i + 1, porcion.id, len(temas), len(resumen),
            )

        return indices

    def __repr__(self) -> str:
        return (
            f"DivisorSubagent(max_paralelos={self._max_paralelos}, "
            f"divisor={type(self._divisor).__name__})"
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

    print("=== Validacion de divisor_subagent.py ===\n")

    import tempfile
    from contexto_zai.models import Attachment, Porcion
    from contexto_zai.subagents.launcher import SubagentLauncher

    # Mock invoker que simula respuestas de N2
    def mock_n2_invoker(prompt: str) -> str:
        # Detectar qué porción es por el contenido del prompt
        if "Porción: 1" in prompt:
            return """RESUMEN: Porción 1 sobre autenticación y config.

TEMA: auth_jwt
DESCRIPCION: Sistema de autenticación JWT
SECCIONES: login, logout, refresh

TEMA: config_db
DESCRIPCION: Configuración de base de datos
SECCIONES: sqlite, prisma"""
        elif "Porción: 2" in prompt:
            return """RESUMEN: Porción 2 sobre validaciones.

TEMA: validaciones_pytest
DESCRIPCION: Tests con pytest
SECCIONES: unitarias, integracion

TEMA: auth_jwt
DESCRIPCION: Más sobre auth
SECCIONES: cookie, session"""
        elif "Porción: 3" in prompt:
            return """RESUMEN: Porción 3 sobre docs.

TEMA: documentacion
DESCRIPCION: Specs y manuales
SECCIONES: spec_v3, manual"""
        return "RESUMEN: Porción sin temas.\n"

    # Test 1: flujo completo con PDF real (CZAI-01.pdf)
    czai_pdf = Path("/home/z/my-project/contexto_zai/Documentación/CZAI-01.pdf")
    if czai_pdf.exists():
        launcher = SubagentLauncher(task_invoker=mock_n2_invoker)
        n1 = DivisorSubagent(launcher=launcher, max_paralelos=3)

        att = Attachment(
            file_id="test-001",
            filename="CZAI-01.pdf",
            content_type="application/pdf",
            size=1652025,
        )

        indices = n1.run(att, czai_pdf)

        assert len(indices) > 0, "Debe devolver al menos 1 índice parcial"
        print(f"[OK] PDF real: {len(indices)} índices parciales")
        for ip in indices[:3]:
            print(f"  Porción {ip.porcion_id}: {len(ip.temas)} temas, resumen {len(ip.resumen_parcial)} chars")
    else:
        print("[SKIP] CZAI-01.pdf no encontrado")

    # Test 2: documento inexistente → lista vacía
    launcher2 = SubagentLauncher(task_invoker=mock_n2_invoker)
    n1_b = DivisorSubagent(launcher=launcher2)
    att2 = Attachment(file_id="x", filename="noexiste.pdf", content_type="application/pdf", size=100)
    indices2 = n1_b.run(att2, "/tmp/no_existe.pdf")
    assert indices2 == []
    print(f"[OK] Documento inexistente: lista vacía")

    # Test 3: con pocas porciones (mock que devuelve 3 respuestas)
    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear PDF mock pequeño
        # Usar el PDF real pero con max_tokens pequeño para forzar varias porciones
        if czai_pdf.exists():
            launcher3 = SubagentLauncher(task_invoker=mock_n2_invoker)
            n1_c = DivisorSubagent(launcher=launcher3, max_paralelos=2)
            att3 = Attachment(
                file_id="test-003", filename="CZAI-01.pdf",
                content_type="application/pdf", size=1652025,
            )
            # El N1 lanza N2 en paralelo (max 2 a la vez)
            indices3 = n1_c.run(att3, czai_pdf)
            assert len(indices3) > 0
            # Verificar que cada índice tiene porcion_id válido
            for ip in indices3:
                assert ip.porcion_id > 0
            print(f"[OK] max_paralelos=2: {len(indices3)} índices parciales procesados")

    # Test 4: _parse_responses con respuesta mal formada
    from contexto_zai.subagents.launcher import SubagentResponse
    responses_malformed = [
        SubagentResponse(content="No tiene formato", success=True),
        SubagentResponse(content="", success=False, error="Task failed"),
    ]
    porciones_mock = [
        Porcion(id=1, contenido_path="/tmp/p1.pdf", tokens_estimados=1000, pagina_inicio=1, pagina_fin=10),
        Porcion(id=2, contenido_path="/tmp/p2.pdf", tokens_estimados=1000, pagina_inicio=11, pagina_fin=20),
    ]
    indices_malformed = DivisorSubagent._parse_responses(responses_malformed, porciones_mock)
    assert len(indices_malformed) == 2
    assert len(indices_malformed[0].temas) == 0  # sin temas
    assert len(indices_malformed[1].temas) == 0  # sin temas
    print(f"[OK] Respuestas mal formadas: 2 índices vacíos")

    # Test 5: _build_n2_prompt
    att5 = Attachment(file_id="x", filename="doc.pdf", content_type="application/pdf", size=100)
    n1_d = DivisorSubagent(launcher=launcher2)
    prompt_builder = n1_d._build_n2_prompt(att5)
    p_test = Porcion(id=1, contenido_path="/tmp/test.pdf", tokens_estimados=5000, pagina_inicio=1, pagina_fin=10)
    prompt = prompt_builder(p_test)
    assert "doc.pdf" in prompt
    assert "Porción: 1" in prompt
    assert "páginas 1-10" in prompt
    assert "RESUMEN:" in prompt
    assert "TEMA:" in prompt
    print(f"[OK] _build_n2_prompt: incluye filename, porción, páginas, formato")

    # Test 6: repr
    r = repr(n1_d)
    assert "DivisorSubagent" in r
    print(f"[OK] repr: {r}")

    print("\n[PASS] divisor_subagent.py: todos los tests pasaron")
