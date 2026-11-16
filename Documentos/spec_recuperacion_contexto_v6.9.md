# contexto_zai/Documentos/spec_recuperacion_contexto_v6.9.md
# Spec v6.9 — Eliminar camino duplicado: link /s/ pasa por el mismo flujo que archivos externos

**Versión:** 6.9
**Fecha:** 2026-10-08
**Estado:** Pendiente de implementación.
**Especifica continuación de:** spec v6.8.4.

## 1. Propósito

La v6.8.4 funciona correctamente para archivos externos (APA 01/03/04):
bloques con contenido literal, RESUMEN al inicio, temas enriquecidos, sin
provisionales, índice correcto. Pero cuando el agente APA procesó un link
`/s/` de Z.ai sobre un workspace que ya tenía 9 bloques APA, el proceso
**sobrescribió los bloques existentes** porque el link `/s/` delega a
`pipeline.run()` que numera desde `bloque_01` sin verificar colisiones.

Esto viola la spec v4.4 que dice: "ampliar contexto incorpora información
nueva al workspace **sin tocar lo que ya funciona**" y la spec v6.7 que
dice: "crear, ampliar y actualizar contexto usan el mismo código vía OOP".

## 2. No olvidar del DTI

- **NH1**: Corregir un bug sin diagnóstico y consenso previo — el diagnóstico
  está hecho y conciliado con el Director.
- **NH8**: Actuar sin autorización — el Director autorizó esta spec.
- **NH14**: Tomar decisiones de arquitectura relevantes sin consenso — la
  eliminación del camino duplicado fue consensuada con el Director.
- **NH18**: Reescribir un archivo completo cuando solo se necesitan cambios
  quirúrgicos — los cambios son quirúrgicos en `ampliar_contexto()`.
- **NH19**: Ejecutar cambios sin verificar que no se rompe funcionalidad
  existente — se valida con datos reales antes de entregar.
- **NH23**: Modificar código que no fue solicitado — solo se toca lo que
  el Director pidió: eliminar el camino duplicado del link `/s/`.

## 3. El problema

### Cómo funciona hoy (el bug)

Cuando `ampliar_contexto()` recibe un link `/s/` de Z.ai:

1. Detecta el patrón `/s/` en la URL.
2. Delega a `pipeline.run()` (recuperación completa de chat).
3. `pipeline.run()` ejecuta `RecoveryCycle` que numera bloques desde
   `bloque_01` sin verificar si ya existen.
4. Los bloques existentes se sobrescriben.
5. El metadata queda inconsistente (`archivo_a_source` no se actualiza).

### Cómo funcionan los archivos externos (que sí funciona)

Cuando `ampliar_contexto()` recibe un archivo externo:

1. El `ProcesadorDocumento` divide el documento en lotes.
2. Los subagentes extraen contenido literal.
3. `IntegradorRespuestas._integrar_documento()` escribe cada bloque usando
   `_siguiente_nombre_bloque()` que lee el workspace y encuentra el número
   más alto disponible.
4. Los bloques existentes se preservan.
5. El metadata se actualiza correctamente.

### La desviación del diseño

La spec v4.4 dice: "ampliar contexto incorpora información nueva al
workspace sin tocar lo que ya funciona". La spec v6.7 dice: "crear, ampliar
y actualizar contexto usan el mismo código vía OOP".

El código actual viola ambas specs: el link `/s/` usa un camino distinto
(`pipeline.run()` → `RecoveryCycle`) que no preserva los bloques existentes.

## 4. Lo que no se puede retroceder (proteger lo existente)

**Lo que ya funciona NO se toca:**
- Bloques con contenido literal hasta 70K ✅
- RESUMEN al inicio de cada bloque ✅
- pending_tasks de enriquecimiento que llegan al agente ✅
- Temas enriquecidos con nombres significativos ✅
- Formato lista en tema_a_archivo ✅
- Sin temas provisionales (v6.8.4) ✅
- Verificación del Worker Bun (v6.8.3) ✅
- Captura de fallback_tasks (v6.8.3) ✅
- Índice regenerado tras enriquecimiento (v6.8.4) ✅
- Archivos externos procesados correctamente ✅
- Clasificación de intercambios del chat (MessageClassifier) ✅
- Empaquetado secuencial (BlockPacker) ✅
- Generación de los 4 archivos de recuperación según cronología ✅

## 5. El problema que nos trajo hasta aquí

Este bug es la manifestación concreta del problema arquitectónico que
planteaste al principio de toda esta conversación: "No entiendo porque
ampliar contexto y actualizar contexto van por dos caminos diferentes para
tareas similares y no se usa la OOP como se establece en toda la
documentación de referencia."

Hemos estado corrigiendo síntomas (bugs 1-11, Worker Bun, provisionales,
formato lista, etc.) sin abordar la causa raíz: el camino duplicado del
link `/s/`. Esta spec la aborda directamente.

## 6. Solución

### F1 — Eliminar la delegación del link /s/ a pipeline.run()

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. Eliminar el bloque de código en `ampliar_contexto()` que detecta `/s/`
   y delega a `pipeline.run()`.
2. El link `/s/` pasa por el mismo camino que un archivo externo: se descarga
   el contenido del chat compartido (usando `ChatClient.extract_all()` con
   el `share_id`), se procesa el contenido como una fuente externa.
3. El contenido extraído del chat se trata como cualquier otra fuente:
   se llena el bloque con el contenido literal, se le asigna un nombre
   `bloque_NN` (empezando desde el último existente con
   `_siguiente_nombre_bloque()`), se enriquece, y se actualiza el metadata.
4. Los bloques existentes se preservan automáticamente porque
   `_siguiente_nombre_bloque()` lee el workspace.

### F2 — Extraer contenido del chat /s/ como fuente externa

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. Cuando `ampliar_contexto()` recibe un link `/s/`:
   - Extraer el `share_id` de la URL.
   - Usar `ChatClient.extract_all(share_id=share_id)` para obtener los
     mensajes del chat compartido.
   - Construir intercambios con `ExchangeBuilder` y clasificarlos con
     `MessageClassifier` (igual que hace `RecoveryCycle`).
   - Pero en vez de pasarlos por `BlockPacker` (que numera desde 1),
     pasarlos por `IntegradorRespuestas._integrar_documento()` (que
     usa `_siguiente_nombre_bloque()`).
2. El contenido del chat se escribe como bloques nuevos sin sobrescribir
   los existentes.
3. Los bloques nuevos se enriquecen (RESUMEN + temas) igual que los
   externos.
4. La generación de los 4 archivos de recuperación depende de la
   cronología (Principio 3 de v6.7): si los intercambios del chat son
   cronológicos y posteriores al último timestamp del workspace, se generan.

### F3 — Actualizar el metadata correctamente

**Archivos:** `pipeline.py`, `coordinador/integrador_respuestas.py`.

**Qué se hace:**
1. `archivo_a_source` se actualiza con el origen del link `/s/`
   (source_type="url", source_path=<url>, share_id=<share_id>).
2. `tema_a_archivo` se actualiza con los temas del chat (generados por el
   enriquecimiento, no provisionales).
3. `ultimo_timestamp` se actualiza si los intercambios del chat son
   posteriores.
4. No hay inconsistencia entre el metadata y los archivos físicos.

### F4 — Tests con datos reales

**Archivos:** `tests/test_v42_e2e.py`, `__main__` de `pipeline.py`.

**Qué se hace:**
1. Test: workspace con 3 bloques existentes → ampliar con link `/s/`
   (mockeado) → los 3 bloques existentes se preservan → los bloques nuevos
   se numeran desde `bloque_04`.
2. Test: ampliar con link `/s/` → el metadata `archivo_a_source` registra
   el origen correcto (url, share_id).
3. Test: ampliar con link `/s/` → si los intercambios son cronológicos y
   posteriores, se generan los 4 archivos de recuperación.
4. Test: ampliar con link `/s/` → si no son cronológicos, no se generan
   los 4 archivos.
5. Test de regresión: ampliar con archivo externo sigue funcionando igual.

## 7. Archivos intervenidos

| Archivo | Cambio |
|---|---|
| `pipeline.py` | F1: eliminar delegación a `pipeline.run()`. F2: extraer contenido del chat como fuente externa. F3: actualizar metadata. |
| `coordinador/integrador_respuestas.py` | F3: registrar origen del link `/s/` en `archivo_a_source`. |
| `tests/test_v42_e2e.py` | F4: tests con datos reales. |

## 8. Lo que NO se toca

- `BlockPacker` — no se modifica (sigue numerando desde 1, pero ya no se
  usa para ampliar contexto, solo para `pipeline.run()`).
- `RecoveryCycle` — no se modifica (sigue funcionando para recuperación
  completa de chat desde `pipeline.run()`).
- `IncrementalCycle` — no se modifica.
- `IntegradorRespuestas._integrar_documento()` — no se modifica (ya
  preserva bloques existentes con `_siguiente_nombre_bloque()`).
- `ContextoGenerator` — no se modifica.
- Worker Bun — no se modifica.
- Prompts de enriquecimiento — no se modifican.

## 9. Flujo unificado tras v6.9

```
ampliar_contexto(source_type, source_path)
│
├─ source_type == "file"
│   └─ ProcesadorDocumento → subagentes extractores → _integrar_documento()
│       └─ _siguiente_nombre_bloque() → preserva existentes
│
├─ source_type == "url" con /s/ de Z.ai
│   └─ ChatClient.extract_all(share_id) → ExchangeBuilder → MessageClassifier
│       → _integrar_documento() (mismo camino que file)
│       └─ _siguiente_nombre_bloque() → preserva existentes
│
├─ source_type == "url" con /c/ de Z.ai
│   └─ ChatClient.extract_all(chat_id) → ExchangeBuilder → MessageClassifier
│       → _integrar_documento() (mismo camino que file)
│       └─ _siguiente_nombre_bloque() → preserva existentes
│
└─ source_type == "url" externa (no Z.ai)
    └─ ProcesadorDocumento → subagentes extractores → _integrar_documento()
        └─ _siguiente_nombre_bloque() → preserva existentes

Todos los caminos terminan en _integrar_documento() que:
1. Escribe bloque_NN.md (preservando existentes)
2. Registra en archivo_a_source
3. No crea temas provisionales (v6.8.4)
4. El enriquecimiento genera los temas reales
5. El índice se regenera tras enriquecimiento (v6.8.4)
6. Los 4 archivos se generan si la cronología lo determina (Principio 3)
```

**Ya no hay dos caminos. Hay uno solo.**

---

**Fin de la spec v6.9.**
