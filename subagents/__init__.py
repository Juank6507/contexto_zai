# contexto_zai/subagents/__init__.py -- Subpaquete de subagentes: launcher y 4 subagentes especializados.
"""Paquete de subagentes del sistema Contexto Z.ai (v3.2).

Subagentes especializados:
- SubagentLauncher: wrapper sobre Task de Z.ai.
- EstadoSubagent: extrae contexto del tema del último intercambio.
- BarridoSubagent: busca información sobre un tema en un archivo.
- DecisionesSubagent: extrae decisiones con LLM (no regex).
- MantenimientoSubagent: actualización incremental de archivos.
- DiscriminatorSubagent (v3.4): subdivide un tema grande en subtemas específicos (Capa 3).
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

from contexto_zai.subagents.barrido_subagent import BarridoSubagent
from contexto_zai.subagents.decisiones_subagent import DecisionesSubagent
from contexto_zai.subagents.discriminator_subagent import (
    DiscriminatorSubagent,
    SubdivisionProposal,
    SubtemaProposal,
)
from contexto_zai.subagents.documento_indexer_subagent import (
    DocumentoIndexResult,
    DocumentoIndexerSubagent,
    ThemeSection,
)
from contexto_zai.subagents.estado_subagent import EstadoSubagent
from contexto_zai.subagents.launcher import SubagentLauncher
from contexto_zai.subagents.mantenimiento_subagent import MantenimientoSubagent

__all__ = [
    "SubagentLauncher",
    "EstadoSubagent",
    "BarridoSubagent",
    "DecisionesSubagent",
    "MantenimientoSubagent",
    "DiscriminatorSubagent",
    "SubdivisionProposal",
    "SubtemaProposal",
    "DocumentoIndexerSubagent",
    "DocumentoIndexResult",
    "ThemeSection",
]
