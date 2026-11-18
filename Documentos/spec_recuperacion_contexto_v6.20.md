# Spec v6.20 — Reorganización del pipeline + Crítico subagente + subproceso de archivos

**Versión:** 6.20
**Fecha:** 2026-11-16
**Estado:** Implementada.
**Especifica continuación de:** spec v6.19.

## 1. Propósito

Reorganizar el pipeline en un solo camino, con la cascada como único mecanismo de acceso al LLM, el bucle W3 con Crítico subagente, el ciclo D7 que manda al W3, y un subproceso nuevo que genera los 4 archivos de recuperación con una sola llamada al LLM.

## 2. Decisiones conciliadas

1. Orden descendente dentro de cada bloque (no solo entre bloques).
2. Bloques se llaman bloques_NN (cronológico) y bloques_temáticos_NN (no cronológico).
3. Crítico del W3 es un subagente que valida fidelidad al contenido (no solo formato).
4. Sin excepción automática por tamaño de bloque.
5. D7 manda a pending task, el W3 corrige, el agente es última opción.
6. Subproceso de archivos: una sola llamada al LLM, genera 00/01/02/03.
7. Daemon unificado: chat_id, force_rebuild, /collect-responses, /generar-archivos.
8. Hash SHA256 en ambas ramas, piden autorización al Director.
9. Eliminadas copias viejas (Worker Bun v6.0 y daemon roto).

## 3. Criterios de aceptación (9)

1. Los intercambios dentro de cada bloque están en orden descendente.
2. Los bloques cronológicos se llaman bloques_NN y los no cronológicos bloques_temáticos_NN.
3. El Crítico subagente valida fidelidad al contenido del bloque.
4. No hay excepción por tamaño de bloque.
5. El D7 manda a pending task y el W3 corrige; el agente es última opción.
6. El subproceso de archivos hace una sola llamada al LLM y genera 00/01/02/03.
7. El 03 se genera solo la primera vez.
8. El daemon pasa chat_id, force_rebuild, y tiene /generar-archivos.
9. El hash se compara en ambas ramas y pide autorización al Director.

**Fin de la spec v6.20.**
