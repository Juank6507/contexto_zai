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

from contexto_zai.coordinador.entregador_tareas import EntregadorTareas
from contexto_zai.coordinador.recogedor_respuestas import RecogedorRespuestas
from contexto_zai.coordinador.orquestador import Orquestador
from contexto_zai.coordinador.integrador_respuestas import IntegradorRespuestas

__all__ = ["EntregadorTareas", "RecogedorRespuestas", "Orquestador", "IntegradorRespuestas"]
