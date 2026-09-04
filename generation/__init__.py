"""Paquete de generación del sistema Contexto Z.ai (v3.2).

Contiene los generadores de los 4 tipos de archivo de recuperación:
- 00_estado_actual.md (8 secciones D1-D4 + A1-A4)
- 01_indice_recuperacion.md (tabla tema → archivo)
- 02_decisiones_clave.md (delegador a subagente LLM)
- bloque_XX.md (uno por bloque temático)

RecoveryGenerator orquesta los 4 generadores.
"""

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
