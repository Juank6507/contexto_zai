# Spec v4.3 — El `00_estado_actual.md` como punto de entrada ordenado al contexto del proyecto

**Versión:** 4.3
**Fecha:** 2026-09-15
**Autor:** Agente CZAI (Sesión 18, con consenso del Director)
**Estado:** Pendiente de validación por el Director.
**Especifica continuación de:** spec v4.2 (bibliotecario que sirve al agente + unificación ampliar_contexto/query_context + soporte para links /s/ de Z.ai).
**Spec asociada:** esta.
**Plan asociado:** plan_refactorizacion_v4.3.md.

---

## 1. Propósito

El `00_estado_actual.md` es el primer archivo que el agente lee cuando pierde contexto. Hasta v4.2 cumple un único rol: decirle al agente **qué estaba pasando cuando se cortó** (última instrucción del Director, restricciones activas, entregables, errores abiertos, siguiente paso).

La v4.3 amplía ese rol. El archivo pasa a ser **el punto de entrada ordenado al contexto del proyecto** — no solo resumen operativo, sino también **visión general del proyecto** y **guía de uso del resto del contexto**.

El agente que pierde contexto debe poder, al leer solo este archivo, entender tres cosas:

1. **Por qué existe este proyecto y qué se persigue** (la visión general).
2. **Qué estaba pasando cuando se cortó** (lo que ya cubre v4.2).
3. **Cómo usar el resto del contexto** que tiene a su disposición (índice, decisiones, bloques, mecanismos del proceso).

Sin estas tres cosas, el agente retoma el hilo operativo pero no tiene el "norte" para priorizar, ni sabe qué arneses tiene ni cuándo usarlos.

## 2. Principios rectores

### 2.1. Lo que funciona se conserva

Las secciones actuales (D1, D4, A1, A2, A3, A4) cumplen su cometido y no se modifican. La v4.3 **añade** dos secciones nuevas, no reemplaza las existentes.

### 2.2. El proceso fija la guía de uso

La guía de uso del contexto (qué leer primero, qué arneses hay, cuándo usarlos) es **fija**: la decide el proceso, no el agente. Se incluye como template en cada regeneración del `00_estado_actual.md`. El agente la consume, no la escribe.

### 2.3. La visión general es mixta: parte agente, parte subagente

La "visión general del proyecto" tiene dos componentes:

- **Componente A — Objetivo del proyecto (fijo, escrito por el agente).** Es una declaración de alto nivel de por qué existe el proyecto y qué persigue. La decide el agente al arrancar el proyecto, en un archivo aparte. El proceso la referencia, no la deriva.

- **Componente B — Síntesis de lo que existe (dinámica, generada por subagente).** Es una valoración de todo el contexto disponible en el momento de la activación: los tres archivos de recuperación, la visión general del Componente A, y (si hace falta) los resúmenes del bloque actual y de otros bloques que complementen la información. Un subagente lo produce respondiendo a uno o varios prompts.

### 2.4. La síntesis se actualiza en cada `pipeline.run()`

El Componente B se regenera cada vez que el proceso corre `pipeline.run()` — porque lo que existe cambia (se agregan bloques, se toman decisiones, se amplía contexto). El Componente A solo cambia si el agente lo reescribe.

### 2.5. Intervenciones quirúrgicas

Las dos secciones nuevas viven al inicio del `00_estado_actual.md` — antes de las secciones operativas existentes (D1, D4, A1, A2, A3, A4). No se toca el resto del archivo.

## 3. Las dos secciones nuevas

### 3.1. Sección `G0` — Visión general del proyecto

Aparece al inicio del `00_estado_actual.md`. Tiene dos subsecciones:

#### `G0.A — Objetivo del proyecto`

- **Origen:** archivo `03_objetivo_proyecto.md` en el workspace. Lo escribe el agente (o el Director) al arrancar el proyecto. El proceso solo lo lee y lo embebe en el `00_estado_actual.md`.
- **Contenido:** uno o dos párrafos que responden a: por qué existe este proyecto, qué se persigue, qué es lo importante. Es declaración de intención, no estado operativo.
- **Si no existe el archivo:** el proceso deja un placeholder visible: *"Objetivo del proyecto no declarado. Crea `03_objetivo_proyecto.md` en el workspace para que aparezca aquí."* — el agente lo ve y decide si lo crea.

#### `G0.B — Síntesis del contexto disponible`

- **Origen:** generada por un subagente de síntesis (`SintesisContextoSubagent`), invocado por `ProcesadorIntercambios` en modo `SINTESIS_CONTEXTO` (nuevo modo del enum `ModoClasificador`).
- **Input del subagente:**
  1. Los tres archivos de recuperación actuales (`00_estado_actual.md` sección operativa + `01_indice_recuperacion.md` + `02_decisiones_clave.md`).
  2. La visión general del Componente A (`03_objetivo_proyecto.md`).
  3. Los resúmenes del bloque activo actual (lo que ya está en `A1`).
  4. Si el subagente lo necesita: resúmenes de otros bloques que complementen (los lee del `_metadata.json` y de los `RESUMEN:` que ya contienen los `bloque_externo_*.md`).
- **Output del subagente:** un texto de máximo ~1.500 caracteres (≈500 tokens) que responde a: *"Dado todo lo que existe en el contexto del proyecto, ¿cuál es el panorama actual? ¿Qué temas están activos? ¿Qué se está decidiendo? ¿Qué falta por hacer?"*.
- **Cuándo se genera:** cada vez que el proceso corre `pipeline.run()` (con `ProcesadorIntercambios.procesar(modo="SINTESIS_CONTEXTO")` → el `EntregadorTareas` publica la tarea → el agente lanza el subagente → `collect_responses()` lo aplica).
- **Si el subagente falla o no se lanza:** el proceso deja un placeholder visible: *"Síntesis del contexto no disponible. Ejecuta `pipeline.collect_responses()` para generarla."*

### 3.2. Sección `G1` — Guía de uso del contexto

Aparece justo después de `G0`. Es un texto **fijo** que el proceso incluye siempre (template hardcodeado). El agente lo consume, no lo escribe.

Contenido de la guía (en texto plano, conciso):

```
## Cómo usar este contexto

1. Estás leyendo 00_estado_actual.md — el resumen ejecutivo del proyecto.
   Empieza por aquí siempre.

2. Si necesitas encontrar información específica, consulta:
   - 01_indice_recuperacion.md → mapa de bloques temáticos (qué tema está en qué archivo).
   - 02_decisiones_clave.md → decisiones formales tomadas (no repetir lo ya decidido).

3. Si necesitas detalle de un tema, lanza una consulta al proceso:
   - pipeline.query_context("tu pregunta") → el proceso identifica bloques candidatos
     y te devuelve prompts para lanzar subagentes que los lean.

4. Si el Director te pasa un documento o link nuevo para incorporar:
   - pipeline.ampliar_contexto(source_type, source_path, jwt, metadata)
   - Para links /s/ de otros chats de Z.ai: metadata={"jwt": "..."}.

5. Si el proceso publicó tareas pendientes (en _pending_tasks.json):
   - Lee _pending_tasks.json.
   - Lanza los subagentes con el Task tool.
   - Llama pipeline.collect_responses() para que el proceso integre las respuestas.

6. Los bloques temáticos viven como archivos bloque_*.md en este workspace.
   NO los leas directamente en tu ventana — son muy grandes.
   Usa query_context() o lanza subagentes para consultarlos.
```

## 4. Arquitectura: reutilización del patrón v4.2

La generación de la sección `G0.B` (síntesis) usa el mismo patrón diferido que ya funciona para D4, A1, decisiones, nombres legibles, CLASIFICACION_TEMAS y CONSULTA_BLOQUE:

1. `ProcesadorIntercambios.procesar(modo="SINTESIS_CONTEXTO", ...)` prepara la tarea con `IntercambiosClasificadorSubagent.build_prompt()` (nuevo modo).
2. El `EntregadorTareas` publica la tarea en `_pending_tasks.json`.
3. El agente lanza el subagente con el Task tool.
4. El subagente escribe su respuesta en `_responses/`.
5. El agente llama a `pipeline.collect_responses()`.
6. El `IntegradorRespuestas._integrar_sintesis_contexto()` lee la respuesta y actualiza la sección `G0.B` del `00_estado_actual.md`.

Reutiliza:
- `IntercambiosClasificadorSubagent` (nuevo modo `SINTESIS_CONTEXTO` en el enum).
- `ProcesadorIntercambios.procesar()`.
- `Orquestador` + `EntregadorTareas` + `RecogedorRespuestas` (sin cambios).
- `IntegradorRespuestas` (nuevo handler `_integrar_sintesis_contexto`).

## 5. El nuevo archivo `03_objetivo_proyecto.md`

- **Ubicación:** workspace (junto a `00_estado_actual.md`, `01_indice_recuperacion.md`, `02_decisiones_clave.md`).
- **Quién lo crea:** el agente (o el Director) manualmente al arrancar el proyecto.
- **Formato:** markdown, 1-2 párrafos, sin estructura obligatoria.
- **Rol:** fuente única de la declaración de objetivo. El proceso lo lee pero no lo modifica.
- **Si no existe:** el proceso lo detecta y avisa en `G0.A` con un placeholder.
- **No se incluye en el export_context:** el `.zip` de exportación entre agentes **no** incluye `03_objetivo_proyecto.md` porque es específico del proyecto, no del contexto recuperado. El agente que recibe el `.zip` debe crear el suyo propio. *(Esta decisión se revisa si el Director indica lo contrario.)*

## 6. El flujo completo (actualización del flujo v4.2)

### 6.1. Cuando el agente pierde contexto

1. El agente llama a `pipeline.run()`.
2. El proceso extrae, clasifica y empaqueta (sin subagentes).
3. El proceso genera los 3 archivos de entrada con lo que tiene (regex fallback):
   - `00_estado_actual.md` con `G0.A` (objetivo, si existe el archivo) + `G0.B` (placeholder pendiente) + `G1` (guía fija) + secciones operativas (D1, D4, A1, A2, A3, A4).
   - `01_indice_recuperacion.md` y `02_decisiones_clave.md` sin cambios.
4. El proceso prepara las tareas pendientes (D4, A1, decisiones, nombres, CLASIFICACION_TEMAS, y ahora también **SINTESIS_CONTEXTO**).
5. `pipeline.run()` termina y le devuelve al agente: "terminé lo que podía, y tengo N tareas pendientes en `_pending_tasks.json`".
6. El agente lee `_pending_tasks.json`.
7. El agente lanza los subagentes con el Task tool (puede ser en paralelo).
8. Los subagentes escriben sus respuestas en `_responses/`.
9. El agente llama a `pipeline.collect_responses()`.
10. El `RecogedorRespuestas` lee las respuestas, el `IntegradorRespuestas` las aplica (actualiza D4, A1, decisiones, nombres, bloques, índice, metadata, y ahora también **`G0.B` del `00_estado_actual.md`**).
11. El proceso le devuelve al agente el resultado estructurado.
12. El agente lee el `00_estado_actual.md` actualizado (con síntesis incluida) y retoma el hilo.

### 6.2. Cuando el agente necesita detalle de un tema (consulta bajo demanda)

Sin cambios respecto a v4.2.

### 6.3. Cuando el Director entrega un documento (ampliación de contexto)

Sin cambios respecto a v4.2 (incluye soporte para links `/s/` de Z.ai añadido en v4.2).

### 6.4. Cuando se importa un paquete de contexto (export/import)

Sin cambios respecto a v4.2.

## 7. Lo que se conserva de versiones anteriores

- Todos los principios de la spec v4.2 (bibliotecario que sirve al agente, dos clases principales, coordinación por archivos).
- Los tres archivos de recuperación como salida principal del proceso.
- El flujo de 3 niveles (N1/N2/N3) para documentos grandes.
- Los modos existentes del `IntercambiosClasificadorSubagent` (RESTRICCIONES_TEMA, RESUMEN_TRUNCADO, DECISIONES, NOMBRE_LEGIBLE, CLASIFICACION_TEMAS, CONSULTA_BLOQUE).
- El soporte para links `/s/` de Z.ai (v4.2).
- El guard relajado de `query_context()` (v4.2 — no exige `01_indice_recuperacion.md`).
- Los temas reales en `tema_a_archivo` para bloques externos (v4.2 unificación).
- El fix Windows `unlink()` antes de `rename()` (v4.2).
- El cambio de umbral `PARTITION_THRESHOLD_TOKENS = 30000` (v4.2).

## 8. Lo que se añade en v4.3

- **Sección `G0.A — Objetivo del proyecto`** en el `00_estado_actual.md`, leída del nuevo archivo `03_objetivo_proyecto.md` (escrito por el agente/Director).
- **Sección `G0.B — Síntesis del contexto disponible`** en el `00_estado_actual.md`, generada por subagente en modo `SINTESIS_CONTEXTO`.
- **Sección `G1 — Guía de uso del contexto`** en el `00_estado_actual.md`, texto fijo que el proceso incluye siempre.
- **Nuevo archivo `03_objetivo_proyecto.md`** en el workspace (escrito por el agente/Director, leído por el proceso).
- **Nuevo modo `SINTESIS_CONTEXTO`** en el enum `ModoClasificador` del `IntercambiosClasificadorSubagent`.
- **Nuevo prompt** `_prompt_sintesis_contexto()` en `IntercambiosClasificadorSubagent`.
- **Nuevo parser** `_parse_sintesis_contexto()` en `IntercambiosClasificadorSubagent`.
- **Nuevo handler** `_integrar_sintesis_contexto()` en `IntegradorRespuestas`.
- **`EstadoGenerator`** intervenido: la generación del `00_estado_actual.md` ahora ensambla `G0.A` + `G0.B` (placeholder si pendiente) + `G1` (fija) + secciones operativas existentes (D1, D4, A1, A2, A3, A4).
- **Fix Hueco 1:** `_integrar_documento()` invoca al `IndiceGenerator` después de actualizar `_metadata.json`, para que `01_indice_recuperacion.md` incluya los bloques externos (chat + externos).
- **Fix Hueco 2:** `_integrar_documento()` mejora la deduplicación de temas: distingue "clave existe apuntando al mismo bloque" (idempotente, no hace nada) vs "clave existe apuntando a otro bloque" (prefijar con filename, sufijo numérico si hace falta).

## 9. Lo que se desmonta

- Nada. La v4.3 es aditiva: solo añade secciones y mecanismos nuevos. No elimina ni reemplaza código existente.

## 10. Reglas de implementación

- **Cambios quirúrgicos:** solo se añade lo especificado. No se modifica el código que ya funciona.
- **Scripts atómicos y standalone:** los archivos nuevos (`SintesisContextoSubagent` si se hace atómico, o la extensión de `IntercambiosClasificadorSubagent`) son autónomos, se validan solos con auto-tests en su bloque `__main__`.
- **OOP:** las nuevas secciones son responsabilidad del `EstadoGenerator`, que ensambla el archivo completo. El subagente de síntesis se reutiliza vía `IntercambiosClasificadorSubagent` (extensión del enum, no clase nueva).
- **Tests individuales:** cada módulo nuevo o intervenido lleva auto-tests en `__main__`.
- **Tests E2E:** `tests/test_v42_e2e.py` se amplía con un test E2E que valida el flujo completo: `pipeline.run()` → SINTESIS_CONTEXTO publicada → subagente responde → `collect_responses()` → `00_estado_actual.md` actualizado con `G0.B`.
- **Comunicación de errores:** ningún subagente falla silenciosamente. Los errores suben al Director.
- **Lo que funciona se conserva.**

## 11. Compatibilidad con v4.2

- Todos los archivos existentes se conservan.
- Las funciones públicas (`run`, `status`, `export_context`, `import_context`, `index_document`, `index_document_large`, `query_context`, `ampliar_contexto`, `collect_responses`) mantienen su signature.
- Los flags `enable_capa3` y `enable_attachments` siguen funcionando.
- Los tests existentes siguen pasando. Los que prueban comportamiento que cambia se actualizan.
- Si el `03_objetivo_proyecto.md` no existe, el `00_estado_actual.md` se genera igual con un placeholder visible — no rompe nada.

## 12. Dependencias nuevas

- Ninguna. Se usan las mismas dependencias ya instaladas.

## 13. Validación

- **`EstadoGenerator`:** auto-test que verifica que el `00_estado_actual.md` generado incluye las tres secciones nuevas (`G0.A`, `G0.B`, `G1`) en orden, además de las existentes.
- **`EstadoGenerator` sin objetivo:** auto-test que verifica el placeholder visible en `G0.A` cuando `03_objetivo_proyecto.md` no existe.
- **`IntercambiosClasificadorSubagent` modo `SINTESIS_CONTEXTO`:** auto-test que verifica el prompt y el parser.
- **`IntegradorRespuestas._integrar_sintesis_contexto`:** auto-test que verifica la actualización de `G0.B` en el `00_estado_actual.md`.
- **Test E2E:** `tests/test_v42_e2e.py` ampliado con un test que valida el flujo completo de síntesis: publicar tarea → simular respuesta del subagente → `collect_responses()` → `G0.B` actualizada en `00_estado_actual.md`.

---

## 14. Huecos detectados por el agente APA (v4.3)

Durante la sesión de validación del proceso por parte del agente APA, se detectaron dos huecos reales en el tratamiento de bloques externos generados por `ampliar_contexto()`. Se documentan aquí para que consten como parte de la spec v4.3 y se cierren en la fase F0 del plan.

### 14.1. Hueco 1 — `01_indice_recuperacion.md` no se actualiza al agregar bloques externos

**Diagnóstico:** el `IndiceGenerator` solo se invoca desde `RecoveryGenerator.generate_all()` (dentro de `pipeline.run()`). Cuando `ampliar_contexto()` + `collect_responses()` agregan un bloque externo, `_integrar_documento()` actualiza `_metadata.json` pero **no regenera** `01_indice_recuperacion.md`. El índice queda stale respecto a la metadata: los bloques externos existen en `_metadata.json` pero no aparecen en `01_indice_recuperacion.md`.

**Consecuencia:** aunque `query_context()` (relajado en v4.2) ya no exige el índice como prerrequisito y busca directamente en `_metadata.json`, el archivo `01_indice_recuperacion.md` que el agente lee como uno de los tres archivos de recuperación no refleja los bloques externos. El agente puede no saber que esos bloques existen si solo consulta el índice.

**Fix:** `_integrar_documento()` debe invocar al `IndiceGenerator` después de actualizar `_metadata.json`, para regenerar `01_indice_recuperacion.md` con todos los bloques (chat + externos). El `IndiceGenerator._build_tema_a_archivo()` ya prioriza la metadata como fuente de verdad, así que solo necesita que se le pasen los bloques físicos del workspace.

### 14.2. Hueco 2 — Deduplicación de temas insuficiente en `_integrar_documento()`

**Diagnóstico:** la lógica actual de deduplicación (líneas 440-447 de `integrador_respuestas.py`) solo verifica si la clave del tema existe en `tema_a_archivo`. No verifica si la entrada existente apunta al **mismo bloque** (caso de reprocesamiento idempotente) o a **otro bloque distinto** (legítimo, dos documentos con perspectivas diferentes sobre el mismo tema).

**Consecuencia:** dos escenarios problemáticos:

1. **Reprocesar el mismo documento**: si el documento A se procesa dos veces, la primera vez crea `jwt → bloque_A`. La segunda vez ve que `jwt` existe → crea `A_jwt → bloque_A`. Ahora hay DOS entradas (`jwt` y `A_jwt`) apuntando al mismo bloque. Es una entrada fantasma.

2. **Múltiples temas con el mismo nombre en documentos distintos**: si dos documentos distintos ambos mencionan `autenticacion_jwt`, el segundo sobrescribe al primero con el prefijo, pero no hay control de colisión del prefijo (si `A_autenticacion_jwt` ya existe de un documento anterior `A`, se sobrescribe).

**Fix:** la deduplicación debe distinguir:

- Si la clave existe y apunta al **mismo bloque** → no hacer nada (idempotente, el bloque ya está registrado).
- Si la clave existe y apunta a **otro bloque distinto** → prefijar con filename: `{filename}_{tema}`.
- Si la clave prefijada también existe y apunta a **otro bloque distinto** → sufijo numérico: `{filename}_{tema}_2`, `{filename}_{tema}_3`, etc.
- Si la clave prefijada existe y apunta al **mismo bloque** → no hacer nada (idempotente en el prefijo).

### 14.3. Conciliación con el Punto 1 del consenso anterior

El Punto 1 del consenso anterior (reindexar bloques externos legacy con nombres genéricos) lo resuelve el agente APA con Vía C (9 subagentes cortos de etiquetado). Eso arregla el **pasado** (bloques pre-unificación con nombres genéricos `documento_externo_*`).

Los Huecos 1 y 2 de esta sección arreglan el **presente y futuro**: cada vez que se agregue un bloque externo nuevo (o se reprocese uno existente), el índice debe regenerarse y la deduplicación debe ser correcta.

**Las tres cosas coexisten sin conflicto**: el agente APA arregla los nombres legacy; nosotros arreglamos el código para que el comportamiento futuro sea consistente. Después de ambos, el índice queda consistente con la metadata y sin entradas fantasma.

### 14.4. Bug 1 (crítico) — Desconexión entre el prompt y el parser

**Diagnóstico:** durante la sesión de validación del agente APA, se detectó un bug crítico en el flujo `ampliar_contexto()` → `collect_responses()`. El `ProcesadorDocumento` genera prompts (`_build_documento_prompt()` y `_build_lote_prompt()`) que piden a los subagentes responder con `TEMA:` + `DESCRIPCION:` + `RESUMEN:` (sin `SECCIONES:`). Pero el `IntegradorRespuestas._parse_temas_documento()` exige los 3 campos: `TEMA:` + `DESCRIPCION:` + `SECCIONES:`. Como el subagente responde sin `SECCIONES:` (porque el prompt no se lo pidió), el regex no matchea, el parser devuelve lista vacía, y `_integrar_documento()` cae al nombre genérico `documento_externo_*`.

**Causa raíz:** el parser fue diseñado para el formato del `DocumentoIndexerSubagent._build_prompt_historico()` (que sí pide `SECCIONES:`), pero `ProcesadorDocumento` tiene sus propios prompts con un formato distinto. Dos formatos inconexos en el mismo proceso.

**Consecuencia:** todos los bloques externos procesados vía `ampliar_contexto()` (con `ProcesadorDocumento`) terminan con nombres genéricos, aunque los subagentes hayan extraído los temas correctamente. La unificación `query_context ↔ ampliar_contexto` (v4.2) funciona a nivel de metadata, pero la búsqueda por tema real nunca encuentra estos bloques porque el tema real nunca se registró.

**Bloqueo de la Vía C:** el Bug 1 bloquea la Vía C del agente APA (reindexar bloques legacy con subagentes cortos de etiquetado). La Vía C se apoya en `_integrar_documento()` para aplicar las respuestas, y si el parser no las procesa, los nombres legibles nunca llegan a `_metadata.json`. Hay que arreglar el Bug 1 **antes** de que el agente APA ejecute su Vía C.

**Fix (Opción B — alinear prompt con parser):** los prompts de `ProcesadorDocumento._build_documento_prompt()` y `_build_lote_prompt()` se modifican para pedir los 3 campos (`TEMA:` + `DESCRIPCION:` + `SECCIONES:`), alineándose con el formato del `DocumentoIndexerSubagent._build_prompt_historico()`. Esto elimina la ambigüedad de raíz y unifica el formato en todo el proceso.

**Justificación de la Opción B frente a la Opción A** (cambiar el parser para que `SECCIONES:` sea opcional):

1. **Consistencia con `DocumentoIndexerSubagent`:** ese subagente ya pide los 3 campos y funciona (se usa en el flujo `recovery_cycle.py`). No tiene sentido mantener dos formatos distintos.
2. **Las secciones son información útil:** `SECCIONES:` le dice al subagente que identifique qué partes del documento tratan ese tema. Esa información se guarda en `_metadata.json` y el agente la puede usar para consultar el documento fuente después.
3. **Principio "lo que funciona se conserva":** el formato de 3 campos ya funciona en `DocumentoIndexerSubagent`. Alinear `ProcesadorDocumento` a ese formato respeta el principio.

**Plan asociado:** fase F0.3 del plan v4.3.

---

## 15. Creación automática de `03_objetivo_proyecto.md` (v4.3)

### 15.1. El problema

La sección `G0.A — Objetivo del proyecto` del `00_estado_actual.md` (definida en la sección 3.1) lee el archivo `03_objetivo_proyecto.md` del workspace. Si el archivo no existe, la spec original decía que se dejara un "placeholder visible" — un aviso pidiendo al agente que lo creara.

El Director establece que esto no es correcto: **si el proceso detecta que el archivo no existe, lo crea**. No se queda esperando a que alguien lo escriba.

### 15.2. La dirección

El contenido inicial del archivo se obtiene en **cascada de dos fuentes**:

1. **Primero, de la documentación del proyecto.** El proceso lee los archivos de documentación que ya existen en el proyecto y extrae de ahí el objetivo declarado. La documentación del proyecto denomina al agente en función del proyecto, indica de qué trata y su objetivo — el proceso simplemente lo recoge y lo plasma en `03_objetivo_proyecto.md`.

2. **Si la documentación no existe o no tiene suficiente información, deriva el objetivo de los bloques existentes.** El proceso lee los bloques del workspace (`bloque_*.md` y `bloque_externo_*.md`) y sus temas reales en `_metadata.json`, y construye un objetivo tentativo. El Director puede confirmarlo o corregirlo después.

### 15.3. Archivos de documentación que el proceso lee (Caso A)

El proceso busca información de objetivo en estos archivos, en orden de prioridad:

1. `estrategia/agent-context/proyecto.md` — descripción del proyecto.
2. `estrategia/agent-context/identidad.md` — identidad del agente.
3. `estrategia/agent-context/entorno.md` — entorno de trabajo.
4. `upload/worklog_*.md` — worklogs que narran el proyecto.

Las rutas son relativas al workspace raíz del proyecto. Si el proceso no encuentra ninguno de estos archivos, cae al Caso B.

### 15.4. Derivación de bloques (Caso B)

Si la documentación no existe o no aporta suficiente información, el proceso deriva el objetivo leyendo los bloques del workspace:

- Lee `_metadata.json["tema_a_archivo"]` para saber qué temas hay.
- Para cada tema, lee el primer párrafo del bloque correspondiente.
- Construye un objetivo tentativo con la fórmula: *"Proyecto sobre [tema1], [tema2], [tema3]."* usando los 3-5 temas más representativos.

Este objetivo tentativo se escribe en `03_objetivo_proyecto.md` con un comentario al inicio indicando que es derivado automáticamente y que el Director puede corregirlo.

### 15.5. Cuándo se ejecuta

La creación automática se ejecuta **dentro de `EstadoGenerator.generate()`**, justo antes de leer el archivo para la sección `G0.A`. Es decir:

1. `EstadoGenerator._build_g0_a()` se ejecuta.
2. Si `03_objetivo_proyecto.md` no existe → llama a `_asegurar_objetivo_proyecto()`.
3. `_asegurar_objetivo_proyecto()` aplica la cascada (documentación → bloques) y crea el archivo.
4. `_build_g0_a()` lee el archivo recién creado y devuelve su contenido.

### 15.6. Lo que no se toca

- Si el archivo ya existe, el proceso **no lo sobrescribe**. El objetivo declarado por el Director/agente es prioritario.
- La cascada solo se ejecuta la primera vez (cuando el archivo no existe).
- Si el proceso no puede derivar el objetivo de ninguna fuente (ni documentación ni bloques), escribe un contenido mínimo: *"Proyecto sin objetivo declarado. Edita este archivo para declararlo."*

### 15.7. Compatibilidad

- Backward compatible: si `workspace_dir` no se pasa al `EstadoGenerator`, no se ejecuta la creación automática (igual que las secciones G0/G1).
- Si el archivo ya existe, el comportamiento es idéntico a la spec anterior (leer y devolver contenido).

**Plan asociado:** fase F5 del plan v4.3.

---

**Fin de la spec v4.3.**
