# contexto_zai/subagents/estado_subagent.py -- Subagente de estado actual: lee el bloque del tema del ultimo intercambio y extrae contexto.
"""Subagente de estado actual (v3.2).

Lee el archivo temático que contiene el tema del último intercambio
y extrae todo el contexto del tema para construir el estado actual.
Entrega el contexto completo al agente principal y desaparece.
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

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from contexto_zai.subagents.launcher import SubagentLauncher, SubagentResponse

if TYPE_CHECKING:
    from contexto_zai.models import Exchange, RecoveryMetadata

logger = logging.getLogger(__name__)

@dataclass
class EstadoContext:
    """Contexto extraído del tema activo.

    Attributes:
        tema: Tema al que pertenece el último intercambio.
        archivo_leido: Ruta del archivo temático leído.
        contexto: Texto completo del contexto del tema.
    """

    tema: str
    archivo_leido: str
    contexto: str

class EstadoSubagent:
    """Subagente que lee el bloque del tema del último intercambio.

    Args:
        launcher: SubagentLauncher para invocar el Task.
        blocks_dir: Directorio donde están los bloques temáticos.

    Usage:
        >>> sub = EstadoSubagent(launcher=launcher, blocks_dir="./contexto_recuperacion")
        >>> context = sub.run(exchange=ultimo_exchange, metadata=meta)
    """

    def __init__(
        self,
        launcher: SubagentLauncher,
        blocks_dir: Path | str = "contexto_recuperacion",
    ) -> None:
        self._launcher = launcher
        self._blocks_dir = Path(blocks_dir)

    def run(
        self,
        exchange: "Exchange",
        metadata: Optional["RecoveryMetadata"] = None,
    ) -> EstadoContext:
        """Lee el bloque del tema del último intercambio.

        Args:
            exchange: Último intercambio del chat.
            metadata: Metadata con mapeo tema->archivo.

        Returns:
            EstadoContext con el contexto extraído.
        """
        tema = exchange.topic
        archivo = None

        # Buscar el archivo del tema en la metadata
        if metadata:
            archivo = metadata.archivo_para_tema(tema)

        # Fallback: buscar archivo por nombre de tema en el directorio
        if not archivo:
            archivo = self._find_block_for_tema(tema)

        # Si no se encuentra archivo, devolver contexto vacío
        if not archivo:
            logger.warning(
                "No se encontro archivo para tema '%s'. Directorio: %s",
                tema, self._blocks_dir,
            )
            return EstadoContext(
                tema=tema,
                archivo_leido="",
                contexto=f"[No se encontró archivo para tema '{tema}']",
            )

        archivo_path = self._blocks_dir / archivo
        prompt = self._build_prompt(tema, exchange)

        response: SubagentResponse = self._launcher.launch(
            prompt=prompt,
            files_to_read=[str(archivo_path)],
            description=f"Extraer contexto del tema '{tema}' para el estado actual",
        )

        return EstadoContext(
            tema=tema,
            archivo_leido=str(archivo_path),
            contexto=response.content if response.success else f"[Error: {response.error}]",
        )

    def _find_block_for_tema(self, tema: str) -> Optional[str]:
        """Busca el archivo que contiene el tema en el directorio de bloques."""
        if not self._blocks_dir.exists():
            return None
        for f in self._blocks_dir.iterdir():
            if f.is_file() and f.name.startswith("bloque_") and f.suffix == ".md":
                # Buscar el tema en el contenido del archivo
                content = f.read_text(encoding="utf-8")
                if tema in content:
                    return f.name
        return None

    def _build_prompt(self, tema: str, exchange: "Exchange") -> str:
        """Construye el prompt para extraer el contexto del tema."""
        return f"""Lee el archivo temático y extrae TODO el contexto disponible sobre el tema
'{tema}'. El último intercambio del Director fue:

"{exchange.director_msg.content}"

Tu objetivo es entregar el contexto operativo completo del tema:
- Decisiones relevantes tomadas
- Archivos mencionados
- Estado de entregables
- Restricciones o preferencias activas
- Errores abiertos

No resumas. Entrega el contexto completo necesario para que el agente
principal pueda continuar el trabajo sin ambigüedad."""

    def __repr__(self) -> str:
        return f"EstadoSubagent(blocks_dir={self._blocks_dir!r})"

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
    # -- Validación interna --
    print("=== Validacion de estado_subagent.py ===\n")

    import tempfile
    from contexto_zai.models import Exchange, Message, MessageRole, RecoveryMetadata

    # Test 1: subagente devuelve contexto
    def mock_invoker(prompt: str) -> str:
        return "Contexto completo del tema validaciones: se decidió X, se modificó Y."

    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear archivo de bloque
        bloque_path = Path(tmpdir) / "bloque_01.md"
        bloque_path.write_text("# Bloque\n\nContenido del tema validaciones...", encoding="utf-8")

        launcher = SubagentLauncher(task_invoker=mock_invoker)
        sub = EstadoSubagent(launcher=launcher, blocks_dir=tmpdir)

        ex = Exchange(
            id=1,
            director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="test pytest"),
            topic="validaciones",
            start_timestamp=1,
            end_timestamp=2,
        )
        ctx = sub.run(ex)
        assert ctx.tema == "validaciones"
        assert "Contexto completo" in ctx.contexto
        assert "bloque_01.md" in ctx.archivo_leido
        print(f"[OK] Contexto extraido del archivo correcto")

    # Test 2: sin archivo encontrado
    with tempfile.TemporaryDirectory() as tmpdir:
        launcher = SubagentLauncher(task_invoker=mock_invoker)
        sub = EstadoSubagent(launcher=launcher, blocks_dir=tmpdir)
        ctx = sub.run(ex)
        assert ctx.archivo_leido == ""
        assert "No se encontró" in ctx.contexto
        print(f"[OK] Sin archivo: mensaje de error")

    # Test 3: con metadata que mapea tema -> archivo
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "bloque_02.md").write_text("...", encoding="utf-8")
        meta = RecoveryMetadata()
        meta.registrar_tema("validaciones", "bloque_02.md")
        launcher = SubagentLauncher(task_invoker=mock_invoker)
        sub = EstadoSubagent(launcher=launcher, blocks_dir=tmpdir)
        ctx = sub.run(ex, metadata=meta)
        assert "bloque_02.md" in ctx.archivo_leido
        print(f"[OK] Con metadata: archivo correcto desde mapeo")

    print("\n[PASS] estado_subagent.py: todos los tests pasaron")
