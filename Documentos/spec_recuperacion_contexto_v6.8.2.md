# contexto_zai/Documentos/spec_recuperacion_contexto_v6.8.2.md
# Spec v6.8.2 — Normalizar formato de temas + detectar Worker Bun existente

**Versión:** 6.8.2
**Fecha:** 2026-10-06
**Estado:** Pendiente de implementación.
**Especifica continuación de:** spec v6.8.

## 1. Propósito

La v6.8.1 logró que los bloques tengan RESUMEN al inicio y que el enriquecimiento
en cascada funcione end-to-end. El agente APA detectó 2 bugs menores que no
bloquean el proceso pero generan warnings ruidosos y dejan el índice
desactualizado. Esta spec los corrige sin tocar lo que ya funciona.

## 2. Principio rector: proteger lo existente

**Lo que ya funciona NO se toca:**
- Bloques con contenido literal hasta 70K ✅
- RESUMEN al inicio de cada bloque ✅
- pending_tasks de enriquecimiento que llegan al agente ✅
- Temas enriquecidos con nombres significativos ✅
- Tests atómicos y E2E que pasan ✅

Los fixes son quirúrgicos y no modifican ninguno de estos logros.

## 3. Los 2 bugs a corregir

### Bug 1 — Mezcla de formatos en `tema_a_archivo` (índice desactualizado)

**Qué pasa:** El metadata tiene 61 temas. 9 están en formato string (los
provisionales `documento_externo_NN`) y 52 están en formato lista (los
enriquecidos como `["bloque_01.md"]`). Cuando el regenerador del índice
intenta procesar ambos formatos juntos, las listas causan
`TypeError: unhashable type: 'list'` y el índice no se actualiza.

**Impacto:** El índice solo muestra los 9 temas provisionales, no los 52
enriquecidos. Los bloques y el metadata están correctos, pero el índice está
desactualizado.

**Causa raíz:** El integrador escribe temas como string
(`"documento_externo_0": "bloque_01.md"`). El enriquecimiento escribe temas
como lista (`"chat_sdd_flow": ["bloque_01.md"]`). El regenerador del índice
no puede mezclar ambos formatos.

### Bug 2 — Worker Bun choca consigo mismo en el puerto 8090

**Qué pasa:** El Paso 7 de la estrategia arranca el Worker Bun manualmente.
Después, `collect_responses()` intenta arrancar otro Worker Bun, choca con el
primero en el puerto 8090, y muere. El proceso cae al fallback (subagentes),
que funciona correctamente pero es más lento y ruidoso.

**Impacto:** No se pierden datos, pero el proceso es más lento y el warning
es ruidoso.

**Causa raíz:** `_arrancar_worker_y_esperar()` no verifica si ya hay un
Worker Bun corriendo antes de intentar arrancar otro.

## 4. Soluciones

### F1 — Normalizar formato de `tema_a_archivo` (siempre lista)

**Archivos:** `coordinador/integrador_respuestas.py`, `generation/indice_generator.py`.

**Qué se hace:**
1. El integrador escribe temas como lista, no como string:
   `"documento_externo_0": ["bloque_01.md"]` en vez de
   `"documento_externo_0": "bloque_01.md"`.
2. El regenerador del índice (`_regenerar_indice_recuperacion` en
   `integrador_respuestas.py`) maneja ambos formatos con `isinstance(v, list)`
   para ser tolerante con metadata pre-v6.8.2.
3. El `IndiceGenerator` también maneja ambos formatos (ya lo hace, pero se
   verifica).
4. Los temas provisionales (`documento_externo_NN`) se eliminan del metadata
   cuando el enriquecimiento los reemplaza por temas significativos.

**Lo que NO se toca:**
- Los bloques físicos (bloque_NN.md con contenido literal + RESUMEN).
- Los RESUMENES al inicio.
- Los temas enriquecidos (ya están en formato lista).
- Las pending_tasks de enriquecimiento.

### F2 — Detectar Worker Bun existente antes de arrancar otro

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. `_arrancar_worker_y_esperar()` verifica si el puerto 8090 ya está en uso
   antes de intentar arrancar un Worker Bun nuevo.
2. Si el puerto está en uso, asume que ya hay un Worker Bun corriendo y lo
   reutiliza (espera a que procese los bloques del `_pending_blocks.json`).
3. Si el puerto no está en uso, arranca un Worker Bun nuevo (comportamiento
   actual).
4. Esto elimina el warning ruidoso y permite que el Worker Bun existente
   procese los bloques sin choque.

**Lo que NO se toca:**
- El fallback a subagentes (sigue funcionando si el Worker Bun falla por
  otra razón).
- Las pending_tasks de enriquecimiento (siguen llegando al agente).
- El Worker Bun en sí (no se modifica su código).

## 5. Archivos intervenidos

| Archivo | Cambio |
|---|---|
| `coordinador/integrador_respuestas.py` | F1: escribir temas como lista, manejar ambos formatos, eliminar provisionales al enriquecer. |
| `generation/indice_generator.py` | F1: verificar tolerancia a ambos formatos (ya existe, solo se confirma). |
| `pipeline.py` | F2: detectar puerto 8090 en uso antes de arrancar Worker Bun. |

## 6. Tests con datos reales

1. **Test F1 (formato normalizado):** verificar con datos reales que:
   - El metadata escribe todos los temas como lista (no string).
   - El regenerador del índice no falla con `unhashable type: 'list'`.
   - El índice se actualiza con todos los temas (provisionales + enriquecidos).
   - Los temas provisionales se eliminan cuando el enriquecimiento los reemplaza.
   - Datos reales: reproducir las condiciones del agente APA (3 documentos, 9
     bloques, mezcla de temas provisionales y enriquecidos).

2. **Test F2 (Worker Bun existente):** verificar con datos reales que:
   - Si el puerto 8090 está en uso, no se intenta arrancar otro Worker Bun.
   - El Worker Bun existente procesa los bloques.
   - Si el puerto 8090 no está en uso, se arranca uno nuevo (comportamiento actual).
   - Datos reales: mock del puerto en uso, verificar que no se lanza
     `subprocess.run` para arrancar Worker Bun.

---

**Fin de la spec v6.8.2.**
