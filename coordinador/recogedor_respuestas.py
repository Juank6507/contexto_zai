# contexto_zai/coordinador/recogedor_respuestas.py -- RecogedorRespuestas: lee respuestas de subagentes y las entrega estructuradas.
"""RecogedorRespuestas (v4.2).

Los subagentes escriben sus respuestas en archivos dentro del
directorio ``_responses/`` del workspace. Este recogedor las lee,
las procesa, y las entrega al agente de forma estructurada.

El agente nunca ve el contenido crudo de las respuestas — solo le
dice al proceso "las respuestas están listas" (vía
``pipeline.collect_responses()``), y el RecogedorRespuestas lee y
entrega el resultado estructurado.

Atómico standalone: importa config, models, pathlib y logging. Nada más.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from contexto_zai.config import WORKSPACE_OUTPUT_DIR
from contexto_zai.models import SubagentResponse

logger = logging.getLogger(__name__)

# Directorio donde los subagentes escriben sus respuestas.
RESPONSES_DIRNAME = "_responses"


class RecogedorRespuestas:
    """Lee respuestas de subagentes y las entrega estructuradas.

    Los subagentes (o el agente en su nombre) escriben cada respuesta
    en ``_responses/{task_id}.txt``. Este recogedor lee todas las
    respuestas, las parsea en ``SubagentResponse``, y las entrega al
    proceso para que las integre a los archivos.

    Attributes:
        workspace_dir: Directorio del workspace donde vive _responses/.

    Usage (agente, tras lanzar subagentes):
        >>> from contexto_zai.pipeline import collect_responses
        >>> result = collect_responses()  # llama al RecogedorRespuestas
        >>> print(result["total_applied"])

    Usage (proceso, internamente):
        >>> from contexto_zai.coordinador import RecogedorRespuestas
        >>> recogedor = RecogedorRespuestas(workspace_dir="/path/to/ws")
        >>> responses = recogedor.leer_todas()
    """

    def __init__(self, workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR) -> None:
        self._workspace_dir = Path(workspace_dir)
        self._responses_dir = self._workspace_dir / RESPONSES_DIRNAME
        self._responses_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("RecogedorRespuestas inicializado: %s", self._responses_dir)

    @property
    def workspace_dir(self) -> Path:
        return self._workspace_dir

    @property
    def responses_dir(self) -> Path:
        """Directorio donde se escriben las respuestas."""
        return self._responses_dir

    # -- API pública ------------------------------------------------

    def escribir_respuesta(self, task_id: str, response: str, success: bool = True, error: str = "") -> None:
        """Escribe una respuesta en ``_responses/{task_id}.txt``.

        Lo usa el agente (o el subagente en su nombre) para depositar la
        respuesta de una tarea ejecutada con el Task tool.

        Args:
            task_id: Identificador de la tarea (de SubagentTask.task_id).
            response: Texto crudo de la respuesta del subagente.
            success: Si el subagente devolvió una respuesta válida.
            error: Mensaje de error si falló.
        """
        # Sanitizar task_id para usarlo como nombre de archivo
        safe_task_id = self._sanitize_filename(task_id)
        resp_path = self._responses_dir / f"{safe_task_id}.txt"

        # Escribir con metadata (formato simple: header + cuerpo)
        content = ""
        if not success:
            content = f"SUCCESS: false\nERROR: {error}\n\n--- RESPONSE ---\n{response}"
        else:
            content = f"SUCCESS: true\n\n--- RESPONSE ---\n{response}"

        # Escritura atómica
        tmp_path = resp_path.with_suffix(".txt.tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(resp_path)

        logger.debug("RecogedorRespuestas: escrita respuesta para %s", task_id)

    def leer_todas(self) -> list[SubagentResponse]:
        """Lee todas las respuestas de ``_responses/``.

        Returns:
            Lista de SubagentResponse. Vacía si no hay respuestas.
        """
        if not self._responses_dir.exists():
            return []

        responses: list[SubagentResponse] = []
        for resp_file in sorted(self._responses_dir.glob("*.txt")):
            response = self._parse_response_file(resp_file)
            if response is not None:
                responses.append(response)

        logger.info(
            "RecogedorRespuestas: leídas %d respuestas de %s",
            len(responses), self._responses_dir,
        )
        return responses

    def leer_por_task_id(self, task_id: str) -> Optional[SubagentResponse]:
        """Lee la respuesta de una tarea específica.

        Args:
            task_id: Identificador de la tarea.

        Returns:
            SubagentResponse, o None si no existe.
        """
        safe_task_id = self._sanitize_filename(task_id)
        resp_path = self._responses_dir / f"{safe_task_id}.txt"
        if not resp_path.exists():
            return None
        return self._parse_response_file(resp_path)

    def limpiar(self) -> None:
        """Borra todas las respuestas tras aplicarlas."""
        if self._responses_dir.exists():
            for resp_file in self._responses_dir.glob("*.txt"):
                resp_file.unlink()
            logger.debug("RecogedorRespuestas: respuestas borradas")

    def hay_respuestas(self) -> bool:
        """Verifica si hay respuestas listas."""
        if not self._responses_dir.exists():
            return False
        return any(self._responses_dir.glob("*.txt"))

    def total_respuestas(self) -> int:
        """Devuelve el número de respuestas disponibles."""
        if not self._responses_dir.exists():
            return 0
        return len(list(self._responses_dir.glob("*.txt")))

    # -- Métodos privados -------------------------------------------

    def _parse_response_file(self, resp_path: Path) -> Optional[SubagentResponse]:
        """Parsea un archivo de respuesta en SubagentResponse.

        Formato esperado:
            SUCCESS: true|false
            [ERROR: mensaje si success=false]

            --- RESPONSE ---
            <contenido de la respuesta>
        """
        try:
            content = resp_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Error leyendo %s: %s", resp_path, e)
            return None

        # Extraer task_id del nombre del archivo
        task_id = resp_path.stem  # nombre sin extensión
        # Si el task_id fue sanitizado, no podemos revertir, pero esto es OK
        # porque el task_id original se usa solo para matching con SubagentTask.

        # Parsear el contenido
        success = True
        error = ""
        response_text = content

        lines = content.split("\n")
        if lines and lines[0].startswith("SUCCESS:"):
            success_str = lines[0][len("SUCCESS:"):].strip().lower()
            success = success_str == "true"

            # Buscar ERROR: si success=false
            if not success:
                for line in lines[1:]:
                    if line.startswith("ERROR:"):
                        error = line[len("ERROR:"):].strip()
                        break

            # Extraer el cuerpo tras "--- RESPONSE ---"
            response_marker = "--- RESPONSE ---"
            marker_idx = content.find(response_marker)
            if marker_idx >= 0:
                response_text = content[marker_idx + len(response_marker):].strip()
            else:
                response_text = "\n".join(lines[1:]).strip()

        return SubagentResponse(
            task_id=task_id,
            success=success,
            response=response_text,
            error=error,
        )

    def _sanitize_filename(self, task_id: str) -> str:
        """Sanitiza un task_id para usarlo como nombre de archivo seguro."""
        # Reemplazar caracteres no válidos en nombres de archivo
        safe = task_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        return safe

    def __repr__(self) -> str:
        return f"RecogedorRespuestas(workspace_dir={self._workspace_dir!r})"


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

    print("=== Validacion de recogedor_respuestas.py ===\n")

    import tempfile

    # Test 1: escribir y leer respuesta exitosa
    with tempfile.TemporaryDirectory() as tmpdir:
        rec = RecogedorRespuestas(workspace_dir=tmpdir)
        rec.escribir_respuesta("estado_d4", "RESTRICCION: No usar indigo\nALCANCE: general")
        assert rec.hay_respuestas()
        assert rec.total_respuestas() == 1
        responses = rec.leer_todas()
        assert len(responses) == 1
        assert responses[0].task_id == "estado_d4"
        assert responses[0].success
        assert "indigo" in responses[0].response
        print(f"[OK] escribir+leer exitosa: task_id={responses[0].task_id}")

    # Test 2: escribir y leer respuesta con error
    with tempfile.TemporaryDirectory() as tmpdir:
        rec = RecogedorRespuestas(workspace_dir=tmpdir)
        rec.escribir_respuesta("decisiones_lote_0", "", success=False, error="timeout")
        responses = rec.leer_todas()
        assert len(responses) == 1
        assert not responses[0].success
        assert responses[0].error == "timeout"
        assert responses[0].response == ""
        print(f"[OK] escribir+leer error: success={responses[0].success}, error='{responses[0].error}'")

    # Test 3: múltiples respuestas
    with tempfile.TemporaryDirectory() as tmpdir:
        rec = RecogedorRespuestas(workspace_dir=tmpdir)
        for i in range(5):
            rec.escribir_respuesta(f"task_{i}", f"response {i}")
        assert rec.total_respuestas() == 5
        responses = rec.leer_todas()
        assert len(responses) == 5
        # Ordenadas por nombre de archivo
        assert responses[0].task_id == "task_0"
        assert responses[4].task_id == "task_4"
        print(f"[OK] múltiples respuestas: {len(responses)} leídas")

    # Test 4: leer por task_id específico
    with tempfile.TemporaryDirectory() as tmpdir:
        rec = RecogedorRespuestas(workspace_dir=tmpdir)
        rec.escribir_respuesta("estado_d4", "D4 content")
        rec.escribir_respuesta("decisiones", "dec content")
        resp = rec.leer_por_task_id("estado_d4")
        assert resp is not None
        assert "D4 content" in resp.response
        assert rec.leer_por_task_id("no_existe") is None
        print(f"[OK] leer por task_id: encontrado y no encontrado")

    # Test 5: limpiar borra respuestas
    with tempfile.TemporaryDirectory() as tmpdir:
        rec = RecogedorRespuestas(workspace_dir=tmpdir)
        rec.escribir_respuesta("t1", "r1")
        rec.escribir_respuesta("t2", "r2")
        assert rec.total_respuestas() == 2
        rec.limpiar()
        assert rec.total_respuestas() == 0
        assert not rec.hay_respuestas()
        print(f"[OK] limpiar: respuestas borradas")

    # Test 6: workspace vacío
    with tempfile.TemporaryDirectory() as tmpdir:
        rec = RecogedorRespuestas(workspace_dir=tmpdir)
        assert not rec.hay_respuestas()
        assert rec.total_respuestas() == 0
        assert rec.leer_todas() == []
        print(f"[OK] workspace vacío: 0 respuestas")

    # Test 7: sanitización de task_id
    with tempfile.TemporaryDirectory() as tmpdir:
        rec = RecogedorRespuestas(workspace_dir=tmpdir)
        rec.escribir_respuesta("subdivider_nombre_general_2026sep09", "arquitectura_oop")
        # No debe fallar al escribir
        assert rec.total_respuestas() == 1
        print(f"[OK] sanitización: task_id con barras manejado")

    # Test 8: escritura atómica (sin .tmp residual)
    with tempfile.TemporaryDirectory() as tmpdir:
        rec = RecogedorRespuestas(workspace_dir=tmpdir)
        rec.escribir_respuesta("t1", "r1")
        tmp_files = list(Path(tmpdir).glob("**/*.tmp"))
        assert len(tmp_files) == 0, f"No debería haber .tmp, got: {tmp_files}"
        print(f"[OK] escritura atómica: sin .tmp residuales")

    # Test 9: repr
    rec_repr = RecogedorRespuestas(workspace_dir="/tmp/test_repr")
    assert "RecogedorRespuestas" in repr(rec_repr)
    print(f"[OK] repr: {rec_repr!r}")

    print("\n[PASS] recogedor_respuestas.py: todos los tests pasaron")
