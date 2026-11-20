# Documento consolidado de retorno — contexto_zai v6.20

**Fecha:** 2026-11-18
**Versión:** 6.20
**Proyecto:** contexto_zai
**Agente:** CZAI

## Aprendizajes genéricos

### A1 — El W3 usa la cascada, no al revés
El W3 es el bucle externo que llama a la cascada como servicio. La cascada no sabe nada del Crítico ni del W3. El Crítico valida después de que la cascada devuelve la respuesta.

### A2 — Crítico subagente para validación de calidad
El Crítico valida principalmente la fidelidad del resumen al contenido del bloque, no solo el formato.

### A3 — Una sola llamada al LLM para archivos de recuperación
Los 4 archivos de recuperación se generan con una sola llamada al LLM.

### A4 — Pedir autorización antes de regenerar
Cuando el hash de un archivo cambia, el proceso explica qué cambió y pide autorización al Director.

