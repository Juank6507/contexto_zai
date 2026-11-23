# contexto_zai/coordinador/__init__.py -- Paquete coordinador: clases que coordinan proceso y agente.
"""Paquete coordinador (v4.2).

Contiene las clases que hacen de puente entre el proceso Python y el
agente principal. El proceso es herramienta del agente: estas clases
existen para ayudarlo, no para hacerlo menos eficiente.

Exporta:
- EntregadorTareas: el proceso le entrega al agente las tareas que necesita.
- RecogedorRespuestas: lee respuestas de los subagentes y las entrega estructuradas.
- Orquestador: coordina el flujo completo entre el agente y el proceso.
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


from contexto_zai.coordinador.entregador_tareas import EntregadorTareas
from contexto_zai.coordinador.recogedor_respuestas import RecogedorRespuestas
from contexto_zai.coordinador.orquestador import Orquestador
from contexto_zai.coordinador.integrador_respuestas import IntegradorRespuestas

__all__ = ["EntregadorTareas", "RecogedorRespuestas", "Orquestador", "IntegradorRespuestas"]
