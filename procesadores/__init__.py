# contexto_zai/procesadores/__init__.py -- Paquete procesadores: clases que procesan fuentes y entregan contexto.
"""Paquete procesadores (v4.2).

Contiene las clases que procesan fuentes y entregan contexto al agente
o al proceso, según corresponda. Reutilizan el código existente
(DocumentoIndexerSubagent, IntercambiosClasificadorSubagent, etc.)
y lo conectan con el Orquestador para coordinar la ejecución de
subagentes con el agente principal.

Exporta:
- ProcesadorDocumento: procesa documentos (links, attachments, archivos, URLs).
- ProcesadorIntercambios: procesa intercambios del chat (D4, A1, decisiones, nombres).
- ProcesadorConsulta: responde preguntas del agente sobre bloques.
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
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
else:
    _parent = _os.path.dirname(_here)
    if _parent not in _sys.path:
        _sys.path.insert(0, _parent)


from contexto_zai.procesadores.procesador_documento import ProcesadorDocumento
from contexto_zai.procesadores.procesador_intercambios import ProcesadorIntercambios
from contexto_zai.procesadores.procesador_consulta import ProcesadorConsulta

__all__ = ["ProcesadorDocumento", "ProcesadorIntercambios", "ProcesadorConsulta"]
