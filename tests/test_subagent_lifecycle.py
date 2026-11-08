# tests/test_subagent_lifecycle.py -- Test: lanza 3 subagentes en paralelo (estado, barrido, consulta) y muestra respuestas.
"""Test: lanza 3 subagentes en paralelo y muestra respuestas.

Lanza tres subagentes simultaneamente:
1. Estado: lee el bloque del tema del ultimo intercambio.
2. Barrido: busca informacion sobre un tema en los bloques.
3. Consulta: responde una pregunta concreta del chat.

Los tres se lanzan AL MISMO TIEMPO (en paralelo con hilos) y
cada uno devuelve su respuesta por separado.
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

import tempfile
import json
import threading
import time
from pathlib import Path
from dataclasses import dataclass

from contexto_zai.subagents.launcher import SubagentLauncher
from contexto_zai.subagents.estado_subagent import EstadoSubagent
from contexto_zai.subagents.barrido_subagent import BarridoSubagent
from contexto_zai.models import Exchange, Message, MessageRole, RecoveryMetadata


def _create_test_workspace():
    """Crea un workspace temporal con bloques tematicos de prueba."""
    tmpdir = tempfile.mkdtemp(prefix="czai_test_")
    ws = Path(tmpdir)

    (ws / "bloque_01.md").write_text("""# Bloque tematico: validaciones

## Exchange 1 -- [2026-09-04 10:00]

### Director:
Ejecuta el pytest de server.py y corrige si hay fallos.

### Agente:
Validacion de server.py: 5 tests passed, 0 failed.
Se corrigio el bug en la linea 42 de server.py.

---

## Exchange 2 -- [2026-09-04 11:00]

### Director:
Ahora valida router.py tambien.

### Agente:
Validacion de router.py: 3 tests passed, 0 failed.
Todos los endpoints funcionan correctamente.
""", encoding="utf-8")

    (ws / "bloque_02.md").write_text("""# Bloque tematico: configuracion_proyecto

## Exchange 3 -- [2026-09-04 12:00]

### Director:
Lee el worklog y el repositorio del proyecto.

### Agente:
Worklog leido. He clonado el repositorio contexto_zai.
La estructura del proyecto tiene 38 archivos Python.

---

## Exchange 4 -- [2026-09-04 13:00]

### Director:
Describe el proceso paso a paso.

### Agente:
El proceso tiene 13 pasos. Empieza con la lectura del worklog...
""", encoding="utf-8")

    meta = RecoveryMetadata(
        chat_id="test-chat-id",
        share_id="test-share-id",
    )
    meta.registrar_tema("validaciones", "bloque_01.md")
    meta.registrar_tema("configuracion_proyecto", "bloque_02.md")
    (ws / "_metadata.json").write_text(
        json.dumps(meta.model_dump(), indent=2), encoding="utf-8"
    )
    return ws, meta


def _make_real_invoker():
    """Crea un task_invoker que lee el archivo real y responde.

    Simula lo que haria un subagente real: lee el archivo, busca
    la informacion solicitada y devuelve una respuesta concreta.
    """
    def invoker(prompt: str) -> str:
        time.sleep(0.1)  # simular latencia

        # El prompt contiene el nombre del archivo a leer
        # Buscar que archivo se pide leer
        for fname in ["bloque_01.md", "bloque_02.md"]:
            if fname in prompt:
                # Leer el archivo real del workspace de recuperacion
                ws = Path("/home/z/my-project/contexto_recuperacion")
                if not ws.exists():
                    ws = Path(_os.environ.get("CZAI_TEST_WS", ""))

                filepath = ws / fname
                if not filepath.exists():
                    # Buscar en directorios temporales
                    for tmp in Path(tempfile.gettempdir()).glob("czai_test_*"):
                        f = tmp / fname
                        if f.exists():
                            filepath = f
                            break

                if filepath.exists():
                    content = filepath.read_text(encoding="utf-8")

                    # Responder segun la pregunta
                    if "estado" in prompt.lower() or "contexto" in prompt.lower():
                        # Extraer contexto del tema
                        lines = [l for l in content.split("\n") if l.strip()]
                        return (
                            "CONTEXTO DEL TEMA ACTIVO:\n\n"
                            + "\n".join(lines[:20])
                        )

                    if "bug" in prompt.lower() or "error" in prompt.lower():
                        # Buscar menciones de bug o error
                        for line in content.split("\n"):
                            if "bug" in line.lower() or "error" in line.lower():
                                return f"ENCONTRADO: {line.strip()}"
                        return "No se encontro informacion sobre bugs."

                    if "worklog" in prompt.lower() or "repositorio" in prompt.lower():
                        for line in content.split("\n"):
                            if "worklog" in line.lower() or "repositorio" in line.lower():
                                return f"ENCONTRADO: {line.strip()}"
                        return "No se encontro informacion sobre worklog."

                    if "test" in prompt.lower() or "pytest" in prompt.lower():
                        for line in content.split("\n"):
                            if "test" in line.lower() or "pytest" in line.lower():
                                return f"ENCONTRADO: {line.strip()}"
                        return "No se encontro informacion sobre tests."

                    # Respuesta generica: devolver las primeras 10 lineas
                    return "CONTENIDO DEL ARCHIVO:\n" + "\n".join(content.split("\n")[:10])
                else:
                    return f"No se pudo leer el archivo {fname}"

        return "No hay informacion relevante en los archivos"
    return invoker


@dataclass
class SubagentResult:
    """Resultado de un subagente lanzado en paralelo."""
    name: str
    success: bool
    response: str
    duration: float


def main():
    print("=" * 60)
    print("TEST: 3 subagentes en paralelo")
    print("=" * 60)

    ws, meta = _create_test_workspace()
    _os.environ["CZAI_TEST_WS"] = str(ws)

    invoker = _make_real_invoker()
    launcher = SubagentLauncher(task_invoker=invoker)

    # Ultimo intercambio: tema "validaciones"
    ultimo_exchange = Exchange(
        id=2,
        director_msg=Message(seq=3, role=MessageRole.USER, timestamp=1788482900,
                             content="Ahora valida router.py tambien."),
        agent_msgs=[Message(seq=4, role=MessageRole.ASSISTANT, timestamp=1788482901,
                           content="Validacion de router.py: 3 tests passed.")],
        topic="validaciones",
        start_timestamp=1788482900,
        end_timestamp=1788482901,
    )

    # Preparar los 3 subagentes
    estado_sub = EstadoSubagent(launcher=launcher, blocks_dir=ws)
    barrido_sub = BarridoSubagent(launcher=launcher, blocks_dir=ws)

    # Resultados compartidos
    results: dict[str, SubagentResult] = {}
    lock = threading.Lock()

    def run_estado():
        """Fase 1: subagente de estado."""
        start = time.time()
        ctx = estado_sub.run(ultimo_exchange, metadata=meta)
        elapsed = time.time() - start
        with lock:
            results["estado"] = SubagentResult(
                name="Subagente de Estado",
                success=len(ctx.contexto) > 0,
                response=ctx.contexto,
                duration=elapsed,
            )

    def run_barrido():
        """Fase 2: subagente de barrido."""
        start = time.time()
        barrido_results = barrido_sub.run_many([
            ("bloque_01.md", "Que tests se ejecutaron y que bugs se corrigieron?"),
            ("bloque_02.md", "Que se hizo con el worklog y el repositorio?"),
        ])
        elapsed = time.time() - start
        response_parts = []
        for r in barrido_results:
            response_parts.append(f"[{r.archivo}] {r.respuesta}")
        with lock:
            results["barrido"] = SubagentResult(
                name="Subagente de Barrido",
                success=all(r.success for r in barrido_results),
                response="\n\n".join(response_parts),
                duration=elapsed,
            )

    def run_consulta():
        """Fase 3: subagente de consulta particular."""
        start = time.time()
        result = barrido_sub.run(
            archivo="bloque_01.md",
            pregunta="Que bug se corrigio en server.py y en que linea exacta?",
        )
        elapsed = time.time() - start
        with lock:
            results["consulta"] = SubagentResult(
                name="Subagente de Consulta",
                success=result.success,
                response=result.respuesta,
                duration=elapsed,
            )

    # Lanzar los 3 subagentes EN PARALELO
    print("\nLanzando 3 subagentes simultaneamente...\n")

    threads = [
        threading.Thread(target=run_estado, name="Estado"),
        threading.Thread(target=run_barrido, name="Barrido"),
        threading.Thread(target=run_consulta, name="Consulta"),
    ]

    start_all = time.time()
    for t in threads:
        t.start()

    for t in threads:
        t.join()
    total_time = time.time() - start_all

    # Mostrar resultados de cada subagente por separado
    print("=" * 60)
    print(f"SUBAGENTE 1: ESTADO (recuperacion del contexto)")
    print("=" * 60)
    r = results["estado"]
    print(f"Estado: {'EXITOSO' if r.success else 'FALLO'}")
    print(f"Duracion: {r.duration:.2f}s")
    print(f"Respuesta:")
    print(r.response[:500])
    print()

    print("=" * 60)
    print(f"SUBAGENTE 2: BARRIDO (busqueda de un tema)")
    print("=" * 60)
    r = results["barrido"]
    print(f"Estado: {'EXITOSO' if r.success else 'FALLO'}")
    print(f"Duracion: {r.duration:.2f}s")
    print(f"Respuesta:")
    print(r.response[:500])
    print()

    print("=" * 60)
    print(f"SUBAGENTE 3: CONSULTA (pregunta particular)")
    print("=" * 60)
    r = results["consulta"]
    print(f"Estado: {'EXITOSO' if r.success else 'FALLO'}")
    print(f"Duracion: {r.duration:.2f}s")
    print(f"Respuesta:")
    print(r.response[:500])
    print()

    # Resumen
    print("=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"Tiempo total (paralelo): {total_time:.2f}s")
    print(f"Tiempo suma secuencial: {sum(r.duration for r in results.values()):.2f}s")
    print(f"Subagentes exitosos: {sum(1 for r in results.values() if r.success)}/3")
    print()

    # Verificaciones
    all_success = all(r.success for r in results.values())
    if all_success:
        print("RESULTADO: LOS 3 SUBAGENTES COMPLETARON SUS TAREAS CORRECTAMENTE")
    else:
        failed = [r.name for r in results.values() if not r.success]
        print(f"RESULTADO: FALLO en {', '.join(failed)}")

    # Limpiar
    import shutil
    shutil.rmtree(ws)

    return 0 if all_success else 1


if __name__ == "__main__":
    _exit_code = 0
    try:
        _exit_code = main()
    except SystemExit:
        pass
    _sys.exit(_exit_code)
