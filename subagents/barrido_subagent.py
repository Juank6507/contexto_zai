# Destino: /home/z/my-project/contexto_zai/subagents/barrido_subagent.py
"""Subagente de barrido por temas (v3.2).

Un subagente por cada archivo relevante (identificado vía índice).
Recibe una pregunta concreta sobre el tema. Si encuentra información,
responde; si no, no. Cuando todos han respondido, se cierran.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from contexto_zai.subagents.launcher import SubagentLauncher, SubagentResponse

if TYPE_CHECKING:
    from contexto_zai.models import RecoveryMetadata

logger = logging.getLogger(__name__)


@dataclass
class BarridoResult:
    """Resultado de un barrido por temas.

    Attributes:
        archivo: Archivo leído.
        pregunta: Pregunta formulada.
        respuesta: Respuesta del subagente.
        success: Si el subagente completó sin error.
    """

    archivo: str
    pregunta: str
    respuesta: str = ""
    success: bool = True


class BarridoSubagent:
    """Subagente que busca información sobre un tema en un archivo.

    Args:
        launcher: SubagentLauncher para invocar el Task.
        blocks_dir: Directorio donde están los bloques temáticos.
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
        archivo: str,
        pregunta: str,
    ) -> BarridoResult:
        """Lanza un subagente que lee un archivo y responde una pregunta.

        Args:
            archivo: Nombre del archivo temático a leer.
            pregunta: Pregunta concreta sobre el tema.

        Returns:
            BarridoResult con la respuesta.
        """
        archivo_path = self._blocks_dir / archivo

        if not archivo_path.exists():
            logger.warning("Archivo no encontrado para barrido: %s", archivo_path)
            return BarridoResult(
                archivo=archivo,
                pregunta=pregunta,
                respuesta=f"[Archivo no encontrado: {archivo}]",
                success=False,
            )

        prompt = self._build_prompt(pregunta)

        response: SubagentResponse = self._launcher.launch(
            prompt=prompt,
            files_to_read=[str(archivo_path)],
            description=f"Barrido: buscar info sobre pregunta en {archivo}",
        )

        return BarridoResult(
            archivo=archivo,
            pregunta=pregunta,
            respuesta=response.content if response.success else f"[Error: {response.error}]",
            success=response.success,
        )

    def run_many(
        self,
        archivos_preguntas: list[tuple[str, str]],
    ) -> list[BarridoResult]:
        """Lanza múltiples subagentes de barrido (uno por archivo).

        Args:
            archivos_preguntas: Lista de (archivo, pregunta).

        Returns:
            Lista de BarridoResult en el mismo orden.
        """
        return [self.run(archivo, pregunta) for archivo, pregunta in archivos_preguntas]

    def _build_prompt(self, pregunta: str) -> str:
        return f"""Lee el archivo temático y busca información que responda a esta
pregunta del agente principal:

"{pregunta}"

Si encuentras información relevante, respóndela de forma concisa.
Si no hay nada relevante, responde exactamente: "No hay información relevante en los archivos"."""

    def __repr__(self) -> str:
        return f"BarridoSubagent(blocks_dir={self._blocks_dir!r})"


if __name__ == "__main__":
    print("=== Validación de barrido_subagent.py ===\n")

    import tempfile
    from pathlib import Path

    def mock_invoker(prompt: str) -> str:
        if "pregunta1" in prompt:
            return "Info encontrada sobre pregunta1"
        return "No hay información relevante en los archivos"

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "bloque_01.md").write_text("contenido", encoding="utf-8")
        Path(tmpdir, "bloque_02.md").write_text("contenido", encoding="utf-8")

        launcher = SubagentLauncher(task_invoker=mock_invoker)
        sub = BarridoSubagent(launcher=launcher, blocks_dir=tmpdir)

        # Test 1: encuentra info
        r1 = sub.run("bloque_01.md", "pregunta1 sobre X")
        assert r1.success
        assert "Info encontrada" in r1.respuesta
        print(f"✓ Encuentra información relevante")

        # Test 2: no encuentra info
        r2 = sub.run("bloque_02.md", "pregunta2 sobre Y")
        assert r2.success
        assert "No hay información" in r2.respuesta
        print(f"✓ Reporta ausencia de información")

        # Test 3: archivo no existe
        r3 = sub.run("no_existe.md", "pregunta")
        assert not r3.success
        print(f"✓ Archivo no encontrado: error reportado")

        # Test 4: run_many
        results = sub.run_many([
            ("bloque_01.md", "pregunta1"),
            ("bloque_02.md", "pregunta2"),
        ])
        assert len(results) == 2
        print(f"✓ run_many: {len(results)} resultados")

    print("\n✅ barrido_subagent.py: todos los tests pasaron")
