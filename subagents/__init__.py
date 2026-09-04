# contexto_zai/subagents/__init__.py -- Subpaquete de subagentes: launcher y 4 subagentes especializados.
"""Paquete de subagentes del sistema Contexto Z.ai (v3.2).

Subagentes especializados:
- SubagentLauncher: wrapper sobre Task de Z.ai.
- EstadoSubagent: extrae contexto del tema del último intercambio.
- BarridoSubagent: busca información sobre un tema en un archivo.
- DecisionesSubagent: extrae decisiones con LLM (no regex).
- MantenimientoSubagent: actualización incremental de archivos.
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

from contexto_zai.subagents.barrido_subagent import BarridoSubagent
from contexto_zai.subagents.decisiones_subagent import DecisionesSubagent
from contexto_zai.subagents.estado_subagent import EstadoSubagent
from contexto_zai.subagents.launcher import SubagentLauncher
from contexto_zai.subagents.mantenimiento_subagent import MantenimientoSubagent

__all__ = [
    "SubagentLauncher",
    "EstadoSubagent",
    "BarridoSubagent",
    "DecisionesSubagent",
    "MantenimientoSubagent",
]
