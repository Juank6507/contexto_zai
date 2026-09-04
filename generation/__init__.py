# contexto_zai/generation/__init__.py -- Subpaquete de generacion: estado, indice, decisiones, bloque y recovery_generator.
"""Paquete de generación del sistema Contexto Z.ai (v3.2).

Contiene los generadores de los 4 tipos de archivo de recuperación:
- 00_estado_actual.md (8 secciones D1-D4 + A1-A4)
- 01_indice_recuperacion.md (tabla tema -> archivo)
- 02_decisiones_clave.md (delegador a subagente LLM)
- bloque_XX.md (uno por bloque temático)

RecoveryGenerator orquesta los 4 generadores.
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

from contexto_zai.generation.bloque_generator import BloqueGenerator
from contexto_zai.generation.decisiones_generator import DecisionesGenerator
from contexto_zai.generation.estado_generator import EstadoGenerator
from contexto_zai.generation.indice_generator import IndiceGenerator
from contexto_zai.generation.recovery_generator import RecoveryGenerator

__all__ = [
    "EstadoGenerator",
    "IndiceGenerator",
    "DecisionesGenerator",
    "BloqueGenerator",
    "RecoveryGenerator",
]
