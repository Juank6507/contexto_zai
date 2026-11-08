# contexto_zai/Documentos/spec_recuperacion_contexto_v6.8.4.md
# Spec v6.8.4 — Eliminar temas provisionales + regenerar índice tras enriquecimiento

**Versión:** 6.8.4
**Fecha:** 2026-10-07
**Estado:** Pendiente de implementación.
**Especifica continuación de:** spec v6.8.3.

## 1. Propósito

La v6.8.3 logró que los bloques tengan RESUMEN al inicio, contenido literal,
y 57 temas enriquecidos con nombres significativos. Pero el metadata todavía
contiene 9 temas provisionales (`documento_externo_*` y
`grande_ampliar_*`) que ensucian el índice. Esta spec los elimina de raíz.

## 2. Principio rector: proteger lo existente

**Lo que ya funciona NO se toca:**
- Bloques con contenido literal hasta 70K ✅
- RESUMEN al inicio de cada bloque ✅
- pending_tasks de enriquecimiento que llegan al agente ✅
- Temas enriquecidos con nombres significativos ✅
- Formato lista en tema_a_archivo ✅
- Verificación del Worker Bun (v6.8.3) ✅
- Captura de fallback_tasks (v6.8.3) ✅

## 3. El problema

### Problema 1 — Los bloques no necesitan temas provisionales

Los bloques tienen su nombre propio (`bloque_NN.md`). El enriquecimiento
encuentra los bloques leyendo el disco (`ws.glob("bloque_*.md")`), no leyendo
`tema_a_archivo`. Los temas provisionales (`documento_externo_0`,
`grande_ampliar_apa_03_txt_documento_externo_0`) son un invento innecesario
que ensucia el metadata y el índice.

### Problema 2 — El índice no se regenera tras el enriquecimiento

Después de que el enriquecimiento asigna los temas reales, el índice debería
reflejarlos. Hoy el índice se regenera antes del enriquecimiento, con los
temas provisionales. Después del enriquecimiento, los temas reales se añaden
al metadata pero el índice no se vuelve a regenerar.

## 4. Soluciones

### F1 — No crear temas provisionales al integrar bloques

**Archivos:** `coordinador/integrador_respuestas.py`.

**Qué se hace:**
1. `_integrar_documento()` no registra temas provisionales en `tema_a_archivo`.
   El bloque se escribe con su nombre `bloque_NN.md` y se registra en
   `archivo_a_source` (procedencia), pero sin tema en `tema_a_archivo`.
2. El índice se regenera con los bloques que sí tengan tema (los del chat
   y los ya enriquecidos). Los bloques sin tema no aparecen en el índice
   hasta que el enriquecimiento los clasifique.
3. Esto elimina de raíz los 3 bugs del APA: truncamiento, prefijos
   contaminados, y duplicados por prefijo. No hay temas provisionales
   que truncar, contaminar, o duplicar.

### F2 — Regenerar el índice después del enriquecimiento

**Archivos:** `pipeline.py`, `coordinador/integrador_respuestas.py`.

**Qué se hace:**
1. Después de que `_enriquecer_bloques_con_fallback()` termina (ya sea
   Worker Bun o subagentes de fallback), `collect_responses()` regenera
   el índice leyendo el metadata actualizado con los temas enriquecidos.
2. La función `_regenerar_indice_recuperacion` del integrador se invoca
   con el metadata actualizado, que ahora tiene los temas reales.
3. El índice refleja los temas reales, no los provisionales.

### F3 — _normalizar_bloques_externos elimina provisionales residuales

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. `_normalizar_bloques_externos()` elimina del `tema_a_archivo` cualquier
   tema que empiece con `documento_externo_` o `grande_ampliar_` cuando
   el bloque al que apunta ya tiene temas enriquecidos.
2. Esto limpia los provisionales que queden de versiones anteriores o
   de corridas previas.

## 5. Archivos intervenidos

| Archivo | Cambio |
|---|---|
| `coordinador/integrador_respuestas.py` | F1: no registrar temas provisionales. F2: regenerar índice tras enriquecimiento. |
| `pipeline.py` | F2: invocar regeneración del índice tras enriquecimiento. F3: limpiar provisionales residuales. |

## 6. Lo que NO se toca

- Bloques físicos (nombre, contenido, RESUMEN).
- Worker Bun (código, prompts, detección de puerto).
- pending_tasks (captura del valor de retorno).
- Temas enriquecidos (ya están en formato lista).
- Tests atómicos y E2E (se actualizan para reflejar que no hay provisionales).

## 7. Tests con datos reales

1. **Test F1 (sin temas provisionales):** verificar con datos reales que:
   - El bloque se crea sin tema en `tema_a_archivo`.
   - El bloque sí está en `archivo_a_source`.
   - `query_context` no encuentra el bloque por tema (correcto: no tiene tema).
   - Datos reales: documento APA procesado, verificar metadata.

2. **Test F2 (índice tras enriquecimiento):** verificar con datos reales que:
   - Después del enriquecimiento, el índice tiene los temas reales.
   - El índice no tiene temas provisionales.
   - Datos reales: documento APA procesado + enriquecimiento simulado.

3. **Test F3 (limpieza de provisionales):** verificar con datos reales que:
   - Metadata con temas provisionales + enriquecidos → después de normalizar,
     los provisionales se eliminan.
   - Datos reales: metadata con mezcla de provisionales y enriquecidos.

---

**Fin de la spec v6.8.4.**
