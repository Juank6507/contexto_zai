# contexto_zai/process/__init__.py -- Subpaquete de orquestacion: Orchestrator, RecoveryCycle, IncrementalCycle.
"""Paquete de orquestación del proceso autónomo (v3.2).

Orquestadores:
- Orchestrator: punto de entrada que el agente activa.
- RecoveryCycle: ciclo completo (pasos 5-9).
- IncrementalCycle: actualización incremental (paso 10).
"""

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

from contexto_zai.process.incremental_cycle import IncrementalCycle
from contexto_zai.process.orchestrator import Orchestrator
from contexto_zai.process.recovery_cycle import RecoveryCycle

__all__ = ["Orchestrator", "RecoveryCycle", "IncrementalCycle"]
