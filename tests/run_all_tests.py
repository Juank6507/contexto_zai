# Destino: /home/z/my-project/tests/run_all_tests.py
"""Runner que ejecuta todos los tests del proyecto Contexto Z.ai.

Ejecuta:
1. Auto-tests de cada módulo atómico (contexto_zai/**/*.py con __main__).
2. Tests de integración en tests/.
3. Test E2E en tests/test_e2e_pipeline.py.

Uso:
    python tests/run_all_tests.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))


def run_atomic_tests() -> tuple[int, int]:
    """Ejecuta los auto-tests __main__ de cada módulo atómico."""
    print("\n" + "=" * 60)
    print("FASE 1: Auto-tests de módulos atómicos")
    print("=" * 60)

    atomic_files = [
        "contexto_zai/config.py",
        "contexto_zai/models.py",
        "contexto_zai/client/browser_session.py",
        "contexto_zai/client/auth_client.py",
        "contexto_zai/client/chat_client.py",
        "contexto_zai/processing/exchange_builder.py",
        "contexto_zai/processing/content_cleaner.py",
        "contexto_zai/processing/classifier.py",
        "contexto_zai/processing/block_packer.py",
        "contexto_zai/processing/subdivider.py",
        "contexto_zai/metadata/manager.py",
        "contexto_zai/generation/bloque_generator.py",
        "contexto_zai/generation/estado_generator.py",
        "contexto_zai/generation/indice_generator.py",
        "contexto_zai/generation/decisiones_generator.py",
        "contexto_zai/generation/recovery_generator.py",
        "contexto_zai/detection/lexic_trigger.py",
        "contexto_zai/detection/token_counter.py",
        "contexto_zai/detection/self_questions.py",
        "contexto_zai/subagents/launcher.py",
        "contexto_zai/subagents/estado_subagent.py",
        "contexto_zai/subagents/barrido_subagent.py",
        "contexto_zai/subagents/decisiones_subagent.py",
        "contexto_zai/subagents/mantenimiento_subagent.py",
        "contexto_zai/process/recovery_cycle.py",
        "contexto_zai/process/incremental_cycle.py",
        "contexto_zai/process/orchestrator.py",
        "contexto_zai/pipeline.py",
    ]

    passed = 0
    failed = 0
    for f in atomic_files:
        path = WORKSPACE_ROOT / f
        if not path.exists():
            print(f"  ⚠️  {f}: ARCHIVO NO ENCONTRADO")
            failed += 1
            continue
        result = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            env={"PYTHONPATH": str(WORKSPACE_ROOT), "PATH": ""},
        )
        # Contar como pasado si el script termina con exit code 0
        if result.returncode == 0:
            # Extraer última línea informativa
            last_line = result.stdout.strip().split("\n")[-1] if result.stdout.strip() else ""
            print(f"  ✅ {f}")
            passed += 1
        else:
            print(f"  ❌ {f}")
            if result.stderr:
                # Mostrar las últimas 3 líneas del error
                for line in result.stderr.strip().split("\n")[-3:]:
                    print(f"      {line}")
            failed += 1
    return passed, failed


def run_integration_tests() -> tuple[int, int]:
    """Ejecuta los tests de integración en tests/."""
    print("\n" + "=" * 60)
    print("FASE 2: Tests de integración")
    print("=" * 60)

    integration_tests = [
        "tests/test_classifier_packer_subdivider.py",
        "tests/test_estado_indice_generation.py",
        "tests/test_recovery_cycle.py",
    ]
    passed = 0
    failed = 0
    for f in integration_tests:
        path = WORKSPACE_ROOT / f
        if not path.exists():
            print(f"  ⚠️  {f}: ARCHIVO NO ENCONTRADO")
            failed += 1
            continue
        result = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            env={"PYTHONPATH": str(WORKSPACE_ROOT), "PATH": ""},
        )
        if result.returncode == 0:
            print(f"  ✅ {f}")
            passed += 1
        else:
            print(f"  ❌ {f}")
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
        print(f"  ⚠️  test_e2e_pipeline.py: NO ENCONTRADO")
        return 0, 1
    result = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(WORKSPACE_ROOT), "PATH": ""},
    )
    if result.returncode == 0:
        print(f"  ✅ tests/test_e2e_pipeline.py")
        return 1, 0
    else:
        print(f"  ❌ tests/test_e2e_pipeline.py")
        if result.stderr:
            for line in result.stderr.strip().split("\n")[-3:]:
                print(f"      {line}")
        return 0, 1


def main():
    print("=" * 60)
    print("RUNNER DE TESTS DEL PROYECTO CONTEXTO Z.AI v3.2")
    print("=" * 60)

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
    print(f"RESULTADO FINAL")
    print(f"  Total tests ejecutados: {total_passed + total_failed}")
    print(f"  Pasaron: {total_passed}")
    print(f"  Fallaron: {total_failed}")
    print("=" * 60)
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
