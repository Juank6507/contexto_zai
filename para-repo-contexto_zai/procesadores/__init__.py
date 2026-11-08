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

from contexto_zai.procesadores.procesador_documento import ProcesadorDocumento
from contexto_zai.procesadores.procesador_intercambios import ProcesadorIntercambios
from contexto_zai.procesadores.procesador_consulta import ProcesadorConsulta

__all__ = ["ProcesadorDocumento", "ProcesadorIntercambios", "ProcesadorConsulta"]
