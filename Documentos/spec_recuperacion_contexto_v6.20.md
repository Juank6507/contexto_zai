# Spec v6.20 — W3 externo a la cascada + Crítico subagente + subproceso de archivos

**Versión:** 6.20
**Fecha:** 2026-11-18
**Estado:** Implementada.

## 1. Propósito

El W3 es el bucle externo que llama a la cascada como servicio de acceso al LLM. La cascada no sabe nada del Crítico ni del W3. El Crítico valida después de que la cascada devuelve la respuesta.

## 2. Arquitectura

```
W3 (ciclo de enriquecimiento y calidad)
│
├── 1. Llamar a la cascada para que el LLM genere el resumen
│   └── La cascada intenta sus 3 niveles (Worker Bun → Proxy Z.ai → subagentes)
│
├── 2. El Crítico valida la respuesta (fidelidad al contenido)
│
├── 3. Si no pasa → mandar feedback y volver al paso 1
│
└── 4. Hasta 5 iteraciones. Si no completa → pending task
```

## 3. Criterios de aceptación (10)

1. El W3 es el bucle externo que llama a la cascada.
2. La cascada no sabe nada del Crítico ni del W3.
3. El Crítico valida después de que la cascada devuelve la respuesta.
4. Si el Crítico falla, el W3 manda feedback y vuelve a llamar a la cascada.
5. Orden descendente dentro de cada bloque.
6. bloques_NN y bloques_temáticos_NN.
7. Sin excepción por tamaño de bloque.
8. Hash en ambas ramas, pide autorización.
9. Subproceso de archivos: una sola llamada LLM.
10. Daemon unificado con chat_id, force_rebuild, /collect-responses, /generar-archivos.

**Fin de la spec v6.20.**
