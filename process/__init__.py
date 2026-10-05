# contexto_zai/process/__init__.py -- Subpaquete de orquestacion: Orchestrator, RecoveryCycle, IncrementalCycle.
"""Paquete de orquestación del proceso autónomo (v3.2).

Orquestadores:
- Orchestrator: punto de entrada que el agente activa.
- RecoveryCycle: ciclo completo (pasos 5-9).
- IncrementalCycle: actualización incremental (paso 10).
"""

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

from contexto_zai.process.incremental_cycle import IncrementalCycle
from contexto_zai.process.orchestrator import Orchestrator
from contexto_zai.process.recovery_cycle import RecoveryCycle

__all__ = ["Orchestrator", "RecoveryCycle", "IncrementalCycle"]
