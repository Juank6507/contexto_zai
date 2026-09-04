"""Paquete de subagentes del sistema Contexto Z.ai (v3.2).

Subagentes especializados:
- SubagentLauncher: wrapper sobre Task de Z.ai.
- EstadoSubagent: extrae contexto del tema del último intercambio.
- BarridoSubagent: busca información sobre un tema en un archivo.
- DecisionesSubagent: extrae decisiones con LLM (no regex).
- MantenimientoSubagent: actualización incremental de archivos.
"""

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
