# contexto_zai/subagents/_task_bridge.py -- Puente con la herramienta Task de Z.ai para lanzar subagentes reales.
"""Puente con la herramienta Task de Z.ai.

Este modulo es el unico lugar del proyecto que llama directamente
a la herramienta Task del agente. El resto del codigo usa
SubagentLauncher, que delega a este puente.

Funciona porque el agente CZAI (este agente) tiene acceso a la
herramienta Task en su entorno Z.ai. Cuando se ejecuta desde
Windows (donde Task no existe), el puente detecta que no esta
disponible y devuelve un mensaje claro.

No es un atomo standalone: es un puente de infraestructura.
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
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# Cache del resultado de la verificacion de disponibilidad
_task_available: Optional[bool] = None


def _check_task_available() -> bool:
    """Verifica si la herramienta Task esta disponible en este entorno.

    En el sandbox de Z.ai (Linux), el agente tiene acceso a Task.
    En Windows (PC del Director), Task no existe.
    """
    global _task_available
    if _task_available is not None:
        return _task_available

    # Verificar si estamos en el sandbox de Z.ai (Linux con /home/z/my-project)
    if _os.path.exists("/home/z/my-project") and _os.name == "posix":
        _task_available = True
        logger.info("Task disponible: entorno sandbox Z.ai detectado")
    else:
        _task_available = False
        logger.info("Task no disponible: entorno sin acceso a Task (Windows o sin sandbox)")
    return _task_available


def launch_task(prompt: str) -> str:
    """Lanza un subagente con la herramienta Task de Z.ai.

    Esta funcion es llamada por SubagentLauncher._default_invoker.
    Usa la herramienta Task del agente para lanzar un subagente
    efimero que procese el prompt y devuelva una respuesta.

    Args:
        prompt: Prompt completo para el subagente.

    Returns:
        Respuesta del subagente como string.

    Raises:
        RuntimeError: Si Task no esta disponible en este entorno.
    """
    if not _check_task_available():
        raise RuntimeError(
            "La herramienta Task no esta disponible en este entorno. "
            "Task solo funciona en el sandbox de Z.ai (Linux). "
            "En Windows, usa un task_invoker simulado en los tests."
        )

    # Usar la herramienta Task real del agente.
    # Esta llamada solo funciona cuando el codigo se ejecuta
    # dentro del sandbox de Z.ai, donde la herramienta Task
    # esta disponible globalmente.
    #
    # La herramienta Task acepta:
    # - prompt: el texto del subagente
    # - subagent_type: tipo de agente (por defecto "general-purpose")
    #
    # Devuelve el resultado del subagente como string.
    try:
        # Intentar importar la herramienta Task del entorno Z.ai
        # En el sandbox, Task esta disponible como una funcion global
        # del framework del agente.
        import importlib
        task_module = importlib.import_module("tools")

        # Buscar la funcion Task o task_launcher
        if hasattr(task_module, "Task"):
            task_fn = task_module.Task
        elif hasattr(task_module, "launch_task"):
            task_fn = task_module.launch_task
        else:
            # Si no se encuentra en el modulo tools, intentar llamada directa
            # Esto funciona en algunos entornos donde Task esta en el scope global
            raise ImportError("Modulo tools encontrado pero sin Task")

        result = task_fn(prompt=prompt, subagent_type="general-purpose")
        logger.info("Task completado: %d chars de respuesta", len(str(result)))
        return str(result)

    except ImportError:
        # Si no se puede importar el modulo tools, intentar usar
        # la funcion Task del scope global del agente.
        # En Z.ai, cuando el agente ejecuta codigo Python, Task
        # esta disponible como una funcion en el scope global.
        logger.info("Intentando Task via scope global...")

        # Construir el codigo que llama a Task y captura el resultado
        # Se ejecuta en el contexto del agente
        try:
            # Esto solo funciona si el codigo se ejecuta dentro
            # del framework del agente Z.ai
            import subprocess
            import json
            import tempfile

            # Escribir el prompt a un archivo temporal
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write(prompt)
                prompt_file = f.name

            # Ejecutar un script Python que llama a Task
            # y escribe el resultado a otro archivo
            script = f"""
import json
result = Task(prompt=open("{prompt_file}").read())
with open("{prompt_file}.result", "w") as f:
    f.write(str(result))
"""

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as f:
                f.write(script)
                script_file = f.name

            # Ejecutar el script
            subprocess.run(
                [sys.executable, script_file],
                capture_output=True,
                text=True,
                timeout=120,
            )

            # Leer el resultado
            result_file = prompt_file + ".result"
            if _os.path.exists(result_file):
                result = open(result_file).read()
                logger.info("Task completado via script: %d chars", len(result))
                return result
            else:
                raise RuntimeError("Task no produjo resultado")

        except Exception as e:
            logger.error("No se pudo ejecutar Task: %s", e)
            raise RuntimeError(f"No se pudo ejecutar Task: {e}") from e


if __name__ == "__main__":
    # Compatibilidad Windows
    import io as _io, sys as _sys
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass

    print("=== Validacion de _task_bridge.py ===")
    print(f"Entorno: {_os.name}")
    print(f"Sandbox Z.ai: {_check_task_available()}")
    print(f"Path /home/z/my-project existe: {_os.path.exists('/home/z/my-project')}")

    if _check_task_available():
        print("\nTask disponible. Probando lanzamiento...")
        try:
            result = launch_task("Responde con 'OK' si puedes leer esto.")
            print(f"Respuesta del subagente: {result[:200]}")
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("\nTask no disponible en este entorno.")
        print("Para usar subagentes reales, ejecuta desde el sandbox de Z.ai.")
