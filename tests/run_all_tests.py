# tests/run_all_tests.py -- Runner que ejecuta las 3 fases: auto-tests atomicos, tests de integracion y test E2E.

"""Runner que ejecuta todos los tests del proyecto Contexto Z.ai (v3.2 multiplataforma).

Detecta automaticamente la estructura del proyecto:
- Estructura A: archivos del paquete en <workspace>/contexto_zai/...
- Estructura B: archivos del paquete directamente en <workspace>/...

Ejecuta:
1. Auto-tests de cada modulo atomico (contexto_zai/**/*.py con __main__).
2. Tests de integracion en tests/.
3. Test E2E en tests/test_e2e_pipeline.py.

Uso:
    python tests/run_all_tests.py
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

import io
import os
import subprocess
import sys
from pathlib import Path

# ── Configurar stdout/stderr a UTF-8 (compatibilidad Windows) ──────
# Hacerlo ANTES de cualquier otra cosa para que los print funcionen.
try:
    if hasattr(sys.stdout, "buffer") and "utf" not in (getattr(sys.stdout, "encoding", "") or "").lower():
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    if hasattr(sys.stderr, "buffer") and "utf" not in (getattr(sys.stderr, "encoding", "") or "").lower():
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
except (AttributeError, io.UnsupportedOperation):
    pass

# ── Detectar workspace y configurar PYTHONPATH ─────────────────────
# Esto se hace ANTES de importar cualquier modulo de contexto_zai
# para que los tests puedan hacer `from contexto_zai.X import Y`.
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent

def detect_package_dir() -> Path:
    """Detecta donde estan los archivos del paquete contexto_zai.

    Estructura A: <workspace>/contexto_zai/config.py
    Estructura B: <workspace>/config.py (directamente en la raiz)
    """
    # Intentar estructura A: subfolder contexto_zai/
    subfolder = WORKSPACE_ROOT / "contexto_zai"
    if subfolder.is_dir() and (subfolder / "config.py").exists():
        return subfolder
    # Intentar estructura B: archivos en la raiz
    if (WORKSPACE_ROOT / "config.py").exists():
        return WORKSPACE_ROOT
    raise FileNotFoundError(
        "No se encontro el paquete contexto_zai. "
        f"Buscado en: {subfolder} y {WORKSPACE_ROOT}"
    )

def get_pythonpath() -> str:
    """Calcula el PYTHONPATH necesario para que las importaciones funcionen.

    Si la estructura es A (subfolder contexto_zai/), PYTHONPATH = WORKSPACE_ROOT.
    Si la estructura es B (archivos en raiz), PYTHONPATH = WORKSPACE_ROOT.parent.
    """
    pkg_dir = detect_package_dir()
    if pkg_dir == WORKSPACE_ROOT:
        # Estructura B: el nombre del paquete es el nombre del workspace.
        # Para que `from contexto_zai.X import Y` funcione, PYTHONPATH debe
        # apuntar al directorio padre del workspace.
        return str(WORKSPACE_ROOT.parent)
    else:
        # Estructura A: PYTHONPATH = WORKSPACE_ROOT
        return str(WORKSPACE_ROOT)

# Configurar PYTHONPATH para ESTE proceso (asi run_all_tests.py puede
# importar contexto_zai si lo necesita) y para los subprocess.
_current_pythonpath = get_pythonpath()
if _current_pythonpath not in sys.path:
    sys.path.insert(0, _current_pythonpath)

def run_atomic_tests() -> tuple[int, int]:
    """Ejecuta los auto-tests __main__ de cada modulo atomico."""
    print("\n" + "=" * 60)
    print("FASE 1: Auto-tests de modulos atomicos")
    print("=" * 60)

    pkg_dir = detect_package_dir()

    atomic_files = [
        "config.py",
        "models.py",
        "client/browser_session.py",
        "client/auth_client.py",
        "client/chat_client.py",
        "processing/exchange_builder.py",
        "processing/content_cleaner.py",
        "processing/classifier.py",
        "processing/block_packer.py",
        "processing/subdivider.py",
        "metadata/manager.py",
        "generation/bloque_generator.py",
        "generation/estado_generator.py",
        "generation/indice_generator.py",
        "generation/decisiones_generator.py",
        "generation/recovery_generator.py",
        "detection/lexic_trigger.py",
        "detection/token_counter.py",
        "detection/self_questions.py",
        "subagents/launcher.py",
        "subagents/estado_subagent.py",
        "subagents/barrido_subagent.py",
        "subagents/decisiones_subagent.py",
        "subagents/mantenimiento_subagent.py",
        "process/recovery_cycle.py",
        "process/incremental_cycle.py",
        "process/orchestrator.py",
        "pipeline.py",
    ]

    passed = 0
    failed = 0
    for f in atomic_files:
        path = pkg_dir / f
        if not path.exists():
            print(f"  [WARN]  {f}: ARCHIVO NO ENCONTRADO en {path}")
            failed += 1
            continue
        # Construir entorno con PYTHONPATH correcto
        env = os.environ.copy()
        env["PYTHONPATH"] = get_pythonpath()
        # Forzar UTF-8 en stdout (evita UnicodeEncodeError en Windows)
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            print(f"  [PASS]  {f}")
            passed += 1
        else:
            print(f"  [FAIL]  {f}")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-3:]:
                    print(f"      {line}")
            failed += 1
    return passed, failed

def run_integration_tests() -> tuple[int, int]:
    """Ejecuta los tests de integracion en tests/."""
    print("\n" + "=" * 60)
    print("FASE 2: Tests de integracion")
    print("=" * 60)

    integration_tests = [
        "test_classifier_packer_subdivider.py",
        "test_estado_indice_generation.py",
        "test_recovery_cycle.py",
    ]
    passed = 0
    failed = 0
    for f in integration_tests:
        path = WORKSPACE_ROOT / "tests" / f
        if not path.exists():
            print(f"  [WARN]  tests/{f}: NO ENCONTRADO")
            failed += 1
            continue
        env = os.environ.copy()
        env["PYTHONPATH"] = get_pythonpath()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            print(f"  [PASS]  tests/{f}")
            passed += 1
        else:
            print(f"  [FAIL]  tests/{f}")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-3:]:
                    print(f"      {line}")
            failed += 1
    return passed, failed

def run_e2e_tests() -> tuple[int, int]:
    """Ejecuta el test E2E."""
    print("\n" + "=" * 60)
    print("FASE 3: Test E2E")
    print("=" * 60)
    path = WORKSPACE_ROOT / "tests" / "test_e2e_pipeline.py"
    if not path.exists():
        print(f"  [WARN]  test_e2e_pipeline.py: NO ENCONTRADO")
        return 0, 1
    env = os.environ.copy()
    env["PYTHONPATH"] = get_pythonpath()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        env=env,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0:
        print(f"  [PASS]  tests/test_e2e_pipeline.py")
        return 1, 0
    else:
        print(f"  [FAIL]  tests/test_e2e_pipeline.py")
        if result.stderr:
            for line in result.stderr.strip().split("\n")[-5:]:
                print(f"      {line}")
        return 0, 1

def main():
    print("=" * 60)
    print("RUNNER DE TESTS DEL PROYECTO CONTEXTO Z.AI v3.2")
    print("=" * 60)

    # Mostrar estructura detectada
    try:
        pkg_dir = detect_package_dir()
        pythonpath = get_pythonpath()
        print(f"  Workspace: {WORKSPACE_ROOT}")
        print(f"  Paquete detectado en: {pkg_dir}")
        print(f"  PYTHONPATH: {pythonpath}")
        if pkg_dir == WORKSPACE_ROOT:
            print(f"  Estructura: B (archivos en raiz)")
        else:
            print(f"  Estructura: A (subfolder contexto_zai/)")
    except FileNotFoundError as e:
        print(f"  [ERROR] {e}")
        return 1

    total_passed = 0
    total_failed = 0

    p, f = run_atomic_tests()
    total_passed += p
    total_failed += f

    p, f = run_integration_tests()
    total_passed += p
    total_failed += f

    p, f = run_e2e_tests()
    total_passed += p
    total_failed += f

    print("\n" + "=" * 60)
    print("RESULTADO FINAL")
    print(f"  Total tests ejecutados: {total_passed + total_failed}")
    print(f"  Pasaron: {total_passed}")
    print(f"  Fallaron: {total_failed}")
    print("=" * 60)
    return 0 if total_failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
