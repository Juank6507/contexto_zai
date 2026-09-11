# contexto_zai/subagents/__init__.py -- Subpaquete de subagentes: launcher, clase base OOP y subagentes especializados.
"""Paquete de subagentes del sistema Contexto Z.ai (v4.0).

Subagentes especializados:
- SubagentLauncher: wrapper sobre Task de Z.ai.
- ClasificadorSubagent (v4.0): clase base OOP abstracta para subagentes
  clasificadores. Define el patrón run/build_prompt/parse_response y la
  regla de comunicación de errores (error sube al Director, no silencioso).
- IntercambiosClasificadorSubagent (v4.0): subclase que recibe intercambios
  del chat. Soporta varios modos (M3 D4, M3 A1, M4, M7, M8).
- EstadoSubagent: extrae contexto del tema del último intercambio.
- BarridoSubagent: busca información sobre un tema en un archivo.
- DecisionesSubagent: extrae decisiones con LLM (no regex).
- MantenimientoSubagent: actualización incremental de archivos.
- DiscriminatorSubagent (v3.4): subdivide un tema grande en subtemas específicos (Capa 3).
- DivisorSubagent (v3.6): Nivel 1, divide documento grande + lanza N2 en paralelo.
- ConciliadorSubagent (v3.6): Nivel 3, consolida índices parciales de N2.
- DocumentoIndexerSubagent (v4.0): ahora hereda de ClasificadorSubagent.
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
from contexto_zai.subagents.clasificador_subagent import (
    ClasificadorResult,
    ClasificadorSubagent,
)
from contexto_zai.subagents.conciliador_subagent import ConciliadorSubagent
from contexto_zai.subagents.decisiones_subagent import DecisionesSubagent
from contexto_zai.subagents.discriminator_subagent import (
    DiscriminatorSubagent,
    SubdivisionProposal,
    SubtemaProposal,
)
from contexto_zai.subagents.divisor_subagent import DivisorSubagent
from contexto_zai.subagents.documento_indexer_subagent import (
    DocumentoIndexResult,
    DocumentoIndexerSubagent,
    ThemeSection,
)
from contexto_zai.subagents.estado_subagent import EstadoSubagent
from contexto_zai.subagents.intercambios_clasificador_subagent import (
    Decision,
    IntercambiosClasificadorSubagent,
    ModoClasificador,
    Restriccion,
)
from contexto_zai.subagents.launcher import SubagentLauncher
from contexto_zai.subagents.mantenimiento_subagent import MantenimientoSubagent

__all__ = [
    # v4.0 — Clase base OOP y subclase de intercambios
    "ClasificadorSubagent",
    "ClasificadorResult",
    "IntercambiosClasificadorSubagent",
    "ModoClasificador",
    "Decision",
    "Restriccion",
    # v3.2/v3.6 — Subagentes especializados existentes
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
    "DivisorSubagent",
    "ConciliadorSubagent",
]
