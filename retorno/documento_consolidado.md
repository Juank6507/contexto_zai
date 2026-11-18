# Documento consolidado de retorno — contexto_zai v6.20

**Fecha:** 2026-11-16
**Versión:** 6.20
**Proyecto:** contexto_zai
**Agente:** CZAI

## Aprendizajes genéricos

### A1 — Crítico subagente para validación de calidad
El Crítico del bucle W3 debe ser un subagente que valide principalmente la fidelidad del resumen al contenido del bloque, no solo el formato. El formato (longitud, oraciones, etiquetas) es secundario. La fidelidad al contenido es lo primario.

### A2 — Una sola llamada al LLM para archivos de recuperación
Los 4 archivos de recuperación (00, 01, 02, 03) se generan con una sola llamada al LLM, no 4 llamadas separadas. Esto es más eficiente y mantiene coherencia entre los archivos.

### A3 — Pedir autorización antes de regenerar
Cuando el hash de un archivo cambia, el proceso no debe simplemente eliminar y regenerar. Debe explicar qué cambió y pedir autorización al Director antes de proceder.

## Anti-patrones

### AP20 — Excepción por tamaño de bloque
No debe existir excepción automática que acepte resúmenes sin validar solo porque el bloque es chico. El Crítico siempre valida.

### AP20-bis — Daemon que sobrescribe el estado
El daemon no debe sobrescribir el estado publicado por el proceso (waiting_for_agent con done). Debe respetar el estado que el proceso establece.

