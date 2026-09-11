# contexto_zai/generation/__init__.py -- Subpaquete de generacion: estado, indice, decisiones, bloque y recovery_generator.
"""Paquete de generación del sistema Contexto Z.ai (v3.2).

Contiene los generadores de los 4 tipos de archivo de recuperación:
- 00_estado_actual.md (5 secciones v4.0: D1, D4, A1, A2, A3, A4)
- 01_indice_recuperacion.md (tabla tema -> archivo)
- 02_decisiones_clave.md (delegador a subagente LLM)
- bloque_XX.md (uno por bloque temático)

RecoveryGenerator orquesta los 4 generadores.
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
