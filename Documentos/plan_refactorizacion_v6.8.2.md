# contexto_zai/Documentos/plan_refactorizacion_v6.8.2.md
# Plan v6.8.2 — Normalizar formato de temas + detectar Worker Bun existente

**Versión:** 6.8.2
**Fecha:** 2026-10-06
**Estado:** Pendiente.
**Continuación de:** plan v6.8.
**Spec asociada:** spec_recuperacion_contexto_v6.8.2.md

## Objetivo

Corregir 2 bugs menores detectados por el agente APA sin tocar lo que ya
funciona (bloques con RESUMEN, contenido literal, pending_tasks, temas
enriquecidos).

## Principio: proteger lo existente

Lo que ya funciona NO se toca. Los fixes son quirúrgicos.

## Fases

### F1 — Normalizar formato de `tema_a_archivo` (siempre lista)

**Archivos:** `coordinador/integrador_respuestas.py`.

**Qué se hace:**
1. Cuando el integrador registra un tema en `tema_a_archivo`, lo escribe
   como lista: `"documento_externo_0": ["bloque_01.md"]` en vez de
   `"documento_externo_0": "bloque_01.md"`.
2. El regenerador del índice (`_regenerar_indice_recuperacion`) maneja
   ambos formatos (string y lista) con `isinstance(v, list)` para ser
   tolerante con metadata pre-v6.8.2.
3. Cuando el enriquecimiento reemplaza un tema provisional por uno
   significativo, el tema provisional se elimina del `tema_a_archivo`.

**Lo que NO se toca:**
- Bloques físicos, RESUMENES, temas enriquecidos, pending_tasks.

**Tests con datos reales:**
- Reproducir las condiciones del APA: 3 documentos, 9 bloques, mezcla de
  temas provisionales (string) y enriquecidos (lista).
- Verificar que el regenerador del índice no falla con `unhashable type`.
- Verificar que el índice se actualiza con todos los temas.
- Verificar que los temas provisionales se eliminan al enriquecer.

### F2 — Detectar Worker Bun existente antes de arrancar otro

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. `_arrancar_worker_y_esperar()` verifica si el puerto 8090 ya está en
   uso antes de intentar arrancar un Worker Bun nuevo.
2. Si el puerto está en uso, asume que ya hay un Worker Bun corriendo y
   lo reutiliza (espera a que procese los bloques).
3. Si el puerto no está en uso, arranca uno nuevo (comportamiento actual).
4. La verificación del puerto usa `socket.connect_ex(("localhost", 8090))`
   que es cross-platform (Windows y Linux).

**Lo que NO se toca:**
- El Worker Bun en sí, el fallback a subagentes, las pending_tasks.

**Tests con datos reales:**
- Mock del puerto 8090 en uso, verificar que no se lanza `subprocess.run`.
- Mock del puerto 8090 libre, verificar que se lanza `subprocess.run`
  (comportamiento actual).

### F3 — Validación end-to-end

**Qué se hace:**
1. Ejecutar todos los `__main__` atómicos.
2. Ejecutar los 30+ tests E2E.
3. Validar con datos reales que:
   - El índice se regenera sin `unhashable type: 'list'`.
   - El índice muestra todos los temas (provisionales + enriquecidos).
   - Los temas provisionales se eliminan al enriquecer.
   - El Worker Bun no choca si ya hay uno corriendo.

---

**Fin del plan v6.8.2.**
