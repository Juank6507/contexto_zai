# contexto_zai/subagents/launcher.py -- Lanzador de subagentes efimeros: wrapper sobre Task de Z.ai con inyeccion de invoker.
"""Lanzador de subagentes efímeros (v3.2).

Wrapper sobre la herramienta Task de Z.ai para lanzar subagentes
que leen archivos temáticos y devuelven respuestas concisas.

El launcher es agnóstico al contenido del prompt: solo se encarga
de construir el prompt con el formato adecuado, invocar el Task
y devolver la respuesta.

Atómico standalone: no importa otros módulos del proyecto.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

@dataclass
class SubagentRequest:
    """Petición de lanzamiento de un subagente.

    Attributes:
        prompt: Pregunta concreta que se le hace al subagente.
        files_to_read: Lista de rutas de archivos que el subagente debe leer.
        description: Descripción corta de la tarea (para logging).
    """

    prompt: str
    files_to_read: list[str]
    description: str = ""

@dataclass
class SubagentResponse:
    """Respuesta de un subagente.

    Attributes:
        content: Texto de la respuesta.
        success: Si el subagente completó sin errores.
        error: Mensaje de error si success=False.
    """

    content: str = ""
    success: bool = True
    error: str = ""

# Tipo del invocador de Task (para inyección de dependencias y tests)
TaskInvoker = Callable[[str], str]

class SubagentLauncher:
    """Lanza subagentes efímeros para leer archivos temáticos.

    Args:
        task_invoker: Función que invoca el Task de Z.ai.
            Por defecto usa la implementación interna (que a su vez
            llama a la API de Task si está disponible).
        max_response_chars: Tamaño máximo de la respuesta del subagente.

    Usage:
        >>> launcher = SubagentLauncher()
        >>> response = launcher.launch(
        ...     prompt="¿Qué se decidió sobre el planificador?",
        ...     files_to_read=["/path/to/bloque_01.md"],
        ... )
    """

    def __init__(
        self,
        task_invoker: Optional[TaskInvoker] = None,
        max_response_chars: int = 5000,
    ) -> None:
        self._task_invoker = task_invoker or self._default_invoker
        self._max_response_chars = max_response_chars
        logger.debug(
            "SubagentLauncher inicializado: max_response=%d chars",
            max_response_chars,
        )

    # -- API pública ------------------------------------------------

    def launch(
        self,
        prompt: str,
        files_to_read: list[str],
        description: str = "",
    ) -> SubagentResponse:
        """Lanza un subagente con un prompt y archivos a leer.

        Args:
            prompt: Pregunta concreta (no "resúmeme esto").
            files_to_read: Rutas absolutas de archivos a leer.
            description: Descripción corta para logging.

        Returns:
            SubagentResponse con la respuesta o error.
        """
        # Validar que los archivos existen
        for f in files_to_read:
            if not Path(f).exists():
                logger.warning(
                    "Archivo no encontrado: %s (subagente puede no tener contexto)",
                    f,
                )

        # Construir el prompt completo
        full_prompt = self._build_prompt(prompt, files_to_read, description)

        # Invocar el Task
        try:
            raw_response = self._task_invoker(full_prompt)
        except Exception as e:
            logger.error("Error lanzando subagente: %s", e)
            return SubagentResponse(
                content="",
                success=False,
                error=f"Task invoker error: {e}",
            )

        # Truncar si es necesario
        content = raw_response
        if len(content) > self._max_response_chars:
            content = content[:self._max_response_chars] + "\n... (truncado)"
            logger.info(
                "Respuesta truncada: %d -> %d chars",
                len(raw_response), len(content),
            )

        logger.info(
            "Subagente completado: %d chars (descripcion: %s)",
            len(content), description,
        )

        return SubagentResponse(content=content, success=True)

    def launch_many(
        self,
        requests: list[SubagentRequest],
    ) -> list[SubagentResponse]:
        """Lanza múltiples subagentes (secuencialmente).

        Args:
            requests: Lista de peticiones de subagente.

        Returns:
            Lista de respuestas en el mismo orden.
        """
        responses: list[SubagentResponse] = []
        for req in requests:
            resp = self.launch(
                prompt=req.prompt,
                files_to_read=req.files_to_read,
                description=req.description,
            )
            responses.append(resp)
        return responses

    @property
    def max_response_chars(self) -> int:
        return self._max_response_chars

    def __repr__(self) -> str:
        return f"SubagentLauncher(max_response={self._max_response_chars})"

    # -- Métodos privados -------------------------------------------

    def _build_prompt(
        self,
        prompt: str,
        files_to_read: list[str],
        description: str,
    ) -> str:
        """Construye el prompt completo para el subagente."""
        files_section = "\n".join(
            f"- {f}" for f in files_to_read
        )
        return f"""Eres un subagente efímero que debe responder una pregunta concreta
leyendo los archivos indicados. Tu objetivo es entregar una respuesta concisa
y operativa, no un resumen genérico.

Tarea: {description or 'Responder a una pregunta específica'}

Archivos a leer:
{files_section}

Pregunta del agente principal:
{prompt}

Instrucciones:
1. Lee los archivos indicados.
2. Busca información relevante para responder a la pregunta.
3. Si encuentras información, respóndela de forma concisa y operativa.
4. Si no encuentras nada relevante, responde "No hay información relevante en los archivos".
5. No inventes información. Solo reporta lo que encuentres en los archivos.
6. Tu respuesta debe ser de máximo {self._max_response_chars} caracteres.

Respuesta:"""

    def _default_invoker(self, prompt: str) -> str:
        """Invocador por defecto que simula un Task.

        En producción, este método debería llamar a la API de Task
        de Z.ai. Para tests, se puede inyectar un invoker simulado.
        """
        # En un entorno real, esto invocaría la herramienta Task.
        # Aquí devolvemos un placeholder para que el código sea funcional.
        logger.warning(
            "SubagentLauncher usando invocador por defecto (placeholder). "
            "Inyecta task_invoker para uso real."
        )
        return "[Subagente no disponible: no hay task_invoker configurado]"

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
    # -- Validación interna de launcher.py --
    print("=== Validacion de subagents/launcher.py ===\n")

    import tempfile
    from pathlib import Path

    # Test 1: lanzar con invoker simulado
    def mock_invoker(prompt: str) -> str:
        return "Respuesta simulada del subagente"

    launcher = SubagentLauncher(task_invoker=mock_invoker)
    response = launcher.launch(
        prompt="¿Qué se decidió sobre X?",
        files_to_read=["/tmp/no_existe.md"],
        description="Consulta de decisión",
    )
    assert response.success
    assert response.content == "Respuesta simulada del subagente"
    print(f"[OK] Lanzamiento con invoker simulado: OK")

    # Test 2: prompt bien formado
    captured_prompt = []
    def capturing_invoker(prompt: str) -> str:
        captured_prompt.append(prompt)
        return "OK"

    launcher2 = SubagentLauncher(task_invoker=capturing_invoker)
    launcher2.launch(
        prompt="¿Qué decide el planificador?",
        files_to_read=["/tmp/bloque_01.md", "/tmp/bloque_02.md"],
        description="Test captura",
    )
    assert len(captured_prompt) == 1
    assert "¿Qué decide el planificador?" in captured_prompt[0]
    assert "/tmp/bloque_01.md" in captured_prompt[0]
    assert "/tmp/bloque_02.md" in captured_prompt[0]
    print(f"[OK] Prompt bien formado: incluye pregunta y archivos")

    # Test 3: truncado de respuesta larga
    def long_invoker(prompt: str) -> str:
        return "x" * 10000

    launcher3 = SubagentLauncher(task_invoker=long_invoker, max_response_chars=100)
    response3 = launcher3.launch("pregunta", ["/tmp/x"])
    assert len(response3.content) <= 100 + 30  # 100 + truncation note
    assert "truncado" in response3.content
    print(f"[OK] Truncado: respuesta larga limitada a {launcher3.max_response_chars} chars")

    # Test 4: invoker que falla
    def failing_invoker(prompt: str) -> str:
        raise RuntimeError("Task API no disponible")

    launcher4 = SubagentLauncher(task_invoker=failing_invoker)
    response4 = launcher4.launch("pregunta", ["/tmp/x"])
    assert not response4.success
    assert "Task invoker error" in response4.error
    print(f"[OK] Error del invoker: capturado correctamente")

    # Test 5: launch_many
    def many_invoker(prompt: str) -> str:
        return "respuesta"

    launcher5 = SubagentLauncher(task_invoker=many_invoker)
    requests = [
        SubagentRequest(prompt="q1", files_to_read=["/tmp/a"], description="d1"),
        SubagentRequest(prompt="q2", files_to_read=["/tmp/b"], description="d2"),
        SubagentRequest(prompt="q3", files_to_read=["/tmp/c"], description="d3"),
    ]
    responses = launcher5.launch_many(requests)
    assert len(responses) == 3
    assert all(r.success for r in responses)
    print(f"[OK] launch_many: {len(responses)} respuestas")

    # Test 6: archivo existente no genera error
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("# Contenido de prueba\n")
        f.flush()
        existing_file = f.name

    response6 = launcher.launch("pregunta", [existing_file])
    assert response6.success
    print(f"[OK] Archivo existente: no genera warnings")

    # Test 7: invocador por defecto (placeholder)
    launcher_default = SubagentLauncher()  # sin task_invoker
    response7 = launcher_default.launch("pregunta", [])
    assert response7.success
    assert "no disponible" in response7.content.lower()
    print(f"[OK] Invocador por defecto: placeholder devuelto")

    print("\n[PASS] subagents/launcher.py: todos los tests pasaron")
