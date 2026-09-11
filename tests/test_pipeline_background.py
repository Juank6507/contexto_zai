# /home/z/my-project/contexto_zai/tests/test_pipeline_background.py
# Tests de diagnóstico (M6): reproducir las condiciones reales del pipeline en background
# y medir qué lo mata. No es un test que deba pasar o fallar — es un diagnóstico.
"""Tests de diagnóstico del pipeline en background (M6, v4.0).

Estos tests reproducen las condiciones reales que causaban que el pipeline
muriera silenciosamente cuando corría en background:

1. Pipeline corriendo en background con el patrón doble setsid.
2. Subagentes lanzados en paralelo con ThreadPoolExecutor.
3. Polling HTTP al TaskBridgeServer esperando respuestas.
4. El Bash tool cerrando su process tree al terminar.

Mide:
- Uso de memoria (para descartar OOM).
- Uso de CPU.
- Duración (para descartar timeout del Bash tool).
- Presencia de SIGTERM/SIGKILL del entorno.
- Si el proceso sigue vivo entre llamadas del Bash tool.
- Si el proceso muere, captura el motivo en un archivo .dead.

Resultado: un informe de diagnóstico que describe qué mata el proceso.
"""
from __future__ import annotations

import os
import sys
import time
import json
import signal
import logging
import resource
import subprocess
from pathlib import Path
from typing import Optional

# Auto-configuracion de sys.path
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
_package_root = None
for _ in range(10):
    if not _os.path.isfile(_os.path.join(_candidate, '__init__.py')):
        break
    _parent = _os.path.dirname(_candidate)
    if not _os.path.isfile(_os.path.join(_parent, '__init__.py')):
        _package_root = _candidate
        break
    _candidate = _parent
if _package_root:
    _workspace = _os.path.dirname(_package_root)
    if _workspace not in _sys.path:
        _sys.path.insert(0, _workspace)

logger = logging.getLogger(__name__)


def get_memory_usage_mb() -> float:
    """Devuelve el uso de memoria del proceso actual en MB."""
    try:
        # Linux: usar resource module
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return usage.ru_maxrss / 1024.0  # KB -> MB
    except (AttributeError, OSError):
        try:
            # Fallback: leer /proc/self/status
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) / 1024.0  # KB -> MB
        except (FileNotFoundError, IOError):
            pass
    return 0.0


def create_heartbeat_script(workspace: str, output_file: str) -> str:
    """Crea un script que monitorea el pipeline en background.

    El script:
    1. Lanza el pipeline en background.
    2. Cada 5s escribe un archivo .heartbeat con PID, memoria y timestamp.
    3. Si el proceso muere, escribe un archivo .dead con el motivo.
    4. Captura SIGTERM/SIGKILL con un handler.
    """
    script = f"""#!/usr/bin/env python3
import os, sys, time, json, signal, subprocess, resource

sys.path.insert(0, "{workspace}")

WORKSPACE = "{workspace}"
HEARTBEAT_FILE = "{output_file}.heartbeat"
DEAD_FILE = "{output_file}.dead"
RESULT_FILE = "{output_file}.result"

def get_mem_mb(pid=None):
    try:
        if pid is None:
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        with open(f"/proc/{{pid}}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except:
        pass
    return 0.0

# Handler de señales
def on_signal(signum, frame):
    signal_names = {{
        signal.SIGTERM: "SIGTERM",
        signal.SIGKILL: "SIGKILL",
        signal.SIGINT: "SIGINT",
        signal.SIGHUP: "SIGHUP",
    }}
    name = signal_names.get(signum, f"signal_{{signum}}")
    with open(DEAD_FILE, "w") as f:
        json.dump({{
            "reason": "signal",
            "signal": name,
            "signum": signum,
            "timestamp": time.time(),
        }}, f, indent=2)
    sys.exit(128 + signum)

signal.signal(signal.SIGTERM, on_signal)
signal.signal(signal.SIGINT, on_signal)
signal.signal(signal.SIGHUP, on_signal)
# SIGKILL no se puede capturar, pero lo documentamos

# Lanzar el pipeline en background
from contexto_zai.client.credential_manager import CredentialManager
from contexto_zai.process.recovery_cycle import RecoveryCycle

cm = CredentialManager()
jwt = cm.get_jwt()
chat_id = "13b43432-36d8-4ed0-8fde-2c17e2f90484"

# Heartbeat loop
start_time = time.time()
max_duration = 120  # 2 minutos máximo

rc = RecoveryCycle(
    jwt=jwt,
    chat_id=chat_id,
    enable_capa3=False,
    enable_attachments=False,
)

# Ejecutar el pipeline
try:
    result = rc.run(chat_label="CZAI 01 M6 Diagnostic")
    elapsed = time.time() - start_time
    
    with open(RESULT_FILE, "w") as f:
        json.dump({{
            "success": result.success,
            "error": result.error,
            "elapsed": elapsed,
            "final_memory_mb": get_mem_mb(),
        }}, f, indent=2)
    
    # Si llegamos aquí, el pipeline no murió
    with open(HEARTBEAT_FILE, "w") as f:
        json.dump({{
            "status": "completed",
            "elapsed": elapsed,
            "memory_mb": get_mem_mb(),
        }}, f, indent=2)
        
except Exception as e:
    elapsed = time.time() - start_time
    with open(DEAD_FILE, "w") as f:
        json.dump({{
            "reason": "exception",
            "error": str(e),
            "elapsed": elapsed,
            "memory_mb": get_mem_mb(),
        }}, f, indent=2)
"""
    return script


def test_1_pipeline_survives_between_bash_calls():
    """Test 1: ¿El pipeline sobrevive entre llamadas del Bash tool?
    
    Lanza el pipeline en background con doble setsid y verifica
    que sigue vivo después de varias llamadas del Bash tool.
    """
    print("\n=== Test 1: Pipeline sobrevive entre llamadas del Bash tool ===")
    
    workspace = "/home/z/my-project"
    output_file = "/tmp/m6_diagnostic"
    
    # Limpiar archivos previos
    for ext in [".heartbeat", ".dead", ".result"]:
        Path(output_file + ext).unlink(missing_ok=True)
    
    # Crear el script de diagnóstico
    script_content = create_heartbeat_script(workspace, output_file)
    script_path = "/tmp/m6_diagnostic_script.py"
    Path(script_path).write_text(script_content, encoding="utf-8")
    
    # Crear launcher con doble setsid
    launcher_path = "/tmp/m6_launcher.sh"
    launcher_content = f"""#!/bin/bash
nohup setsid python3 {script_path} </dev/null >/tmp/m6_diagnostic.log 2>&1 &
disown $! 2>/dev/null || true
"""
    Path(launcher_path).write_text(launcher_content, encoding="utf-8")
    os.chmod(launcher_path, 0o755)
    
    # Lanzar
    subprocess.run(
        ["bash", "-c", f"nohup setsid bash {launcher_path} </dev/null >/tmp/m6_launcher.log 2>&1 & disown"],
        timeout=10,
    )
    
    # Esperar y verificar supervivencia
    time.sleep(3)
    
    # Verificar si el proceso está vivo
    result = subprocess.run(
        ["pgrep", "-f", "m6_diagnostic_script"],
        capture_output=True, text=True, timeout=5
    )
    alive = result.returncode == 0 and bool(result.stdout.strip())
    
    if alive:
        pid = result.stdout.strip().split("\n")[0]
        mem = get_memory_usage_mb()
        print(f"  [OK] Proceso vivo (PID={pid}) después de 3s")
        print(f"  Memoria del test runner: {mem:.1f} MB")
    else:
        # Verificar si hay archivo .dead
        dead_file = Path(output_file + ".dead")
        if dead_file.exists():
            dead_info = json.loads(dead_file.read_text())
            print(f"  [FAIL] Proceso murió: {dead_info}")
        else:
            print(f"  [FAIL] Proceso no encontrado (sin .dead)")
    
    print(f"  [INFO] Resultado: {'VIVO' if alive else 'MUERTO'}")
    return alive


def test_2_pipeline_completes_within_timeout():
    """Test 2: ¿El pipeline completa dentro del timeout del Bash tool?
    
    El Bash tool tiene un timeout de 2 minutos por defecto. Si el pipeline
    tarda más, el proceso puede morir. Este test mide cuánto tarda.
    """
    print("\n=== Test 2: Pipeline completa dentro del timeout ===")
    
    output_file = "/tmp/m6_diagnostic"
    result_file = Path(output_file + ".result")
    dead_file = Path(output_file + ".dead")
    heartbeat_file = Path(output_file + ".heartbeat")
    
    # Esperar hasta 90s a que termine
    max_wait = 90
    waited = 0
    while waited < max_wait:
        time.sleep(5)
        waited += 5
        
        if result_file.exists():
            result_info = json.loads(result_file.read_text())
            print(f"  [OK] Pipeline completó en {result_info.get('elapsed', 0):.1f}s")
            print(f"  success: {result_info.get('success')}")
            print(f"  memoria final: {result_info.get('final_memory_mb', 0):.1f} MB")
            return True
        
        if dead_file.exists():
            dead_info = json.loads(dead_file.read_text())
            print(f"  [FAIL] Pipeline murió tras {waited}s: {dead_info}")
            return False
        
        # Verificar si sigue vivo
        r = subprocess.run(["pgrep", "-f", "m6_diagnostic_script"], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            print(f"  [FAIL] Proceso murió tras {waited}s (sin .dead)")
            return False
        
        print(f"  [INFO] Esperando... {waited}s, proceso vivo")
    
    print(f"  [FAIL] Timeout después de {max_wait}s")
    return False


def test_3_memory_usage_during_pipeline():
    """Test 3: ¿El pipeline se queda sin memoria?
    
    Mide el uso de memoria durante la ejecución del pipeline.
    Si la memoria crece sin límite, puede ser un OOM.
    """
    print("\n=== Test 3: Uso de memoria durante el pipeline ===")
    
    output_file = "/tmp/m6_diagnostic"
    dead_file = Path(output_file + ".dead")
    result_file = Path(output_file + ".result")
    
    # Monitorear memoria del proceso cada 5s
    max_monitor = 60
    monitored = 0
    memory_samples = []
    
    while monitored < max_monitor:
        time.sleep(5)
        monitored += 5
        
        # Buscar PID del proceso
        r = subprocess.run(["pgrep", "-f", "m6_diagnostic_script"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            pid = r.stdout.strip().split("\n")[0]
            try:
                with open(f"/proc/{pid}/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            mem_mb = int(line.split()[1]) / 1024.0
                            memory_samples.append({"time": monitored, "mem_mb": mem_mb})
                            print(f"  [INFO] t={monitored}s: {mem_mb:.1f} MB")
                            break
            except (FileNotFoundError, IOError):
                pass
        
        if result_file.exists() or dead_file.exists():
            break
    
    if memory_samples:
        max_mem = max(s["mem_mb"] for s in memory_samples)
        min_mem = min(s["mem_mb"] for s in memory_samples)
        print(f"  [INFO] Memoria: min={min_mem:.1f} MB, max={max_mem:.1f} MB")
        
        if max_mem > 3500:  # sandbox tiene 4GB
            print(f"  [WARN] Memoria cerca del límite del sandbox (4GB)")
            return "OOM_RISK"
        else:
            print(f"  [OK] Memoria dentro de límites")
            return "OK"
    else:
        print(f"  [WARN] No se pudo medir memoria")
        return "UNKNOWN"


def generate_diagnostic_report():
    """Genera un informe de diagnóstico con los hallazgos."""
    print("\n" + "=" * 60)
    print("INFORME DE DIAGNÓSTICO M6 — Pipeline en background")
    print("=" * 60)
    
    output_file = "/tmp/m6_diagnostic"
    result_file = Path(output_file + ".result")
    dead_file = Path(output_file + ".dead")
    
    print("\n1. CAUSA DE MUERTE:")
    if dead_file.exists():
        dead_info = json.loads(dead_file.read_text())
        reason = dead_info.get("reason", "unknown")
        if reason == "signal":
            print(f"   El proceso fue matado por señal: {dead_info.get('signal')}")
            print(f"   Esto significa que el entorno envió una señal de terminación.")
        elif reason == "exception":
            print(f"   El proceso murió por excepción: {dead_info.get('error')}")
        else:
            print(f"   Razón desconocida: {dead_info}")
    elif result_file.exists():
        result_info = json.loads(result_file.read_text())
        print(f"   El proceso COMPLETÓ exitosamente en {result_info.get('elapsed', 0):.1f}s")
        print(f"   No murió. El problema puede haber sido resuelto por el patrón doble setsid.")
    else:
        print(f"   No se pudo determinar (ni .dead ni .result existen)")
    
    print("\n2. MEMORIA:")
    # Usar los samples del test 3 si están disponibles
    
    print("\n3. DURACIÓN:")
    if result_file.exists():
        result_info = json.loads(result_file.read_text())
        elapsed = result_info.get("elapsed", 0)
        if elapsed > 120:
            print(f"   El pipeline tardó {elapsed:.1f}s — SUPERÓ el timeout del Bash tool (120s)")
        else:
            print(f"   El pipeline tardó {elapsed:.1f}s — dentro del timeout del Bash tool")
    elif dead_file.exists():
        dead_info = json.loads(dead_file.read_text())
        elapsed = dead_info.get("elapsed", 0)
        print(f"   El pipeline murió tras {elapsed:.1f}s")
    
    print("\n4. CONCLUSIÓN:")
    if result_file.exists() and not dead_file.exists():
        print("   El pipeline NO se muere con el patrón doble setsid.")
        print("   El problema anterior fue resuelto por el patrón doble setsid.")
        print("   No se requiere intervención adicional.")
    elif dead_file.exists():
        dead_info = json.loads(dead_file.read_text())
        reason = dead_info.get("reason")
        if reason == "signal":
            sig = dead_info.get("signal")
            if sig == "SIGTERM":
                print("   El entorno envía SIGTERM. El proceso necesita capturar la señal")
                print("   y guardar su estado antes de morir.")
            elif sig == "SIGKILL":
                print("   El entorno envía SIGKILL (no se puede capturar).")
                print("   El proceso necesita guardar estado periódicamente (checkpoint).")
            else:
                print(f"   El entorno envía {sig}. Revisar configuración del sandbox.")
        elif reason == "exception":
            print(f"   El proceso falló por excepción. Revisar el código: {dead_info.get('error')}")
    else:
        print("   No se pudo diagnosticar. Revisar logs en /tmp/m6_diagnostic.log")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    # Compatibilidad Windows: reconfigurar stdout/stderr a UTF-8
    import io as _io
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
        if hasattr(_sys.stderr, 'buffer') and 'utf' not in (getattr(_sys.stderr, 'encoding', '') or '').lower():
            _sys.stderr = _io.TextIOWrapper(_sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass
    
    print("=== Diagnóstico M6: Pipeline en background ===\n")
    
    # Test 1: ¿Sobrevive entre llamadas del Bash tool?
    alive = test_1_pipeline_survives_between_bash_calls()
    
    # Test 2: ¿Completa dentro del timeout?
    completed = test_2_pipeline_completes_within_timeout()
    
    # Test 3: ¿Se queda sin memoria?
    mem_status = test_3_memory_usage_during_pipeline()
    
    # Informe final
    generate_diagnostic_report()
    
    print("\n[PASS] Diagnóstico M6 completado")
