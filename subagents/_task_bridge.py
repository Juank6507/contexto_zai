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
    """Lanza un subagente con la herramienta Task de Z.ai (v3.6: vía Task Bridge Server).

    Esta funcion es llamada por SubagentLauncher._default_invoker.
    Usa el Task Bridge Server HTTP para enviar el prompt al agente
    (que tiene acceso al Task tool real) y recibir la respuesta.

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

    # v3.6: Usar Task Bridge Server HTTP
    # El pipeline Python envía el prompt al server HTTP
    # El agente (que tiene Task tool) lee el pending, ejecuta el Task, y envía el resultado
    try:
        import httpx
        import uuid

        task_id = str(uuid.uuid4())[:8]

        # Extraer files_to_read y description del prompt (si están embebidos)
        files_to_read = []
        description = "Subagente task"
        # Buscar líneas de archivos en el prompt
        for line in prompt.split("\n"):
            if line.strip().startswith("- /") or line.strip().startswith("- C:"):
                files_to_read.append(line.strip().lstrip("- ").strip())

        # Enviar request al Task Bridge Server
        bridge_url = "http://localhost:8087"
        resp = httpx.post(
            f"{bridge_url}/task-request",
            json={
                "prompt": prompt,
                "files_to_read": files_to_read,
                "description": description,
            },
            timeout=10.0,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Task Bridge Server error: {resp.status_code}")
        task_id = resp.json().get("id", task_id)

        # Polling: esperar a que el agente ejecute el Task y devuelva el resultado
        max_wait = 300  # 5 minutos máximo
        waited = 0
        while waited < max_wait:
            import time
            time.sleep(2)
            waited += 2
            try:
                resp = httpx.get(f"{bridge_url}/task-result/{task_id}", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success", True):
                        return data.get("result", "")
                    else:
                        raise RuntimeError(f"Task failed: {data.get('error', 'unknown')}")
                # 202 = still pending, seguir esperando
            except httpx.HTTPError:
                pass

        raise RuntimeError(f"Timeout esperando Task {task_id} ({max_wait}s)")

    except ImportError:
        pass

    # Fallback: intentar el método antiguo (scope global)
    try:
        import importlib
        task_module = importlib.import_module("tools")

        if hasattr(task_module, "Task"):
            task_fn = task_module.Task
        elif hasattr(task_module, "launch_task"):
            task_fn = task_module.launch_task
        else:
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
