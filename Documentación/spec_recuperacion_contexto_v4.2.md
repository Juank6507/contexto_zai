# Spec v4.2 — El proceso contexto_zai como bibliotecario que sirve al agente

**Versión:** 4.2
**Fecha:** 2026-09-13
**Autor:** Agente CZAI (Sesión 17, con consenso del Director)
**Estado:** Pendiente de validación por el Director.
**Especifica continuación de:** spec v4.0 (enmendada v4.1 por H9 mal enfocado, ahora corregida).
**Spec asociada:** esta.
**Plan asociado:** plan_refactorizacion_v4.2.md.

---

## 1. Propósito

El proceso contexto_zai es un **bibliotecario** que sirve al agente. Su función es mantener la información disponible, saber cómo llegar a ella, y —sobre todo— mantener la ventana de contexto del agente lo más libre posible.

El agente es el protagonista. El proceso es su herramienta. Todo lo que el proceso hace existe para que el agente trabaje mejor, no para complicarle la vida.

## 2. Principios rectores

### 2.1. El proceso sirve al agente

El proceso no le pide al agente que haga trabajo manual de coordinación. El proceso hace el trabajo pesado (extraer, clasificar, empaquetar) sin molestar al agente, y cuando necesita subagentes, se lo comunica de forma que el agente solo tenga que lanzarlos y esperar el resultado estructurado.

### 2.2. El agente hace dos cosas y solo dos

1. Lee el contexto entregado por el proceso (los tres archivos de entrada, o las respuestas estructuradas a sus consultas).
2. Lanza subagentes cuando los necesita.

Todo lo demás lo hace el proceso, apoyándose en subagentes cuando hace falta.

### 2.3. La eficiencia define el camino

Un solo subagente que lee y analiza es más eficiente que varios subagentes que hay que coordinar. La coordinación entre subagentes consume más recursos que la lectura directa.

Por eso:
- **Tarea mediana** (contenido que cabe en un solo subagente): un solo subagente que lee y responde.
- **Tarea grande** (contenido que no cabe en un solo subagente): se divide en lotes, un subagente por lote, y al final se consolida. El flujo de 3 niveles que ya existe (N1 divide, N2 en paralelo, N3 concilia) es el mecanismo para estos casos, y se conserva.

### 2.4. Lo que funciona se conserva

Un proyecto o script robusto no parte de "esto no sirve". Parte de "esto funciona para cierto caso, y para otros casos hay otro camino". El código que ya demostró que cumple su cometido se reutiliza, no se descarta.

## 3. Los cuatro mecanismos de ampliación de contexto

El proceso tiene cuatro formas de entregarle contexto al agente. Todas comparten el mismo patrón: tomar una fuente de contenido, procesarla, y entregarle contexto al agente.

| # | Mecanismo | Origen del contenido | Introducido en |
|---|---|---|---|
| 1 | Links externos escritos en el chat | URL en un mensaje del Director | v3.4 |
| 2 | Archivos adjuntos del chat (attachments) | Botón "+" del chat de Z.ai | v3.5 |
| 3 | Documentos muy grandes (attachments >50K tokens) | Attachment grande | v3.6 |
| 4 | Fuentes externas (URLs o archivos fuera del chat) | Link o archivo que el agente recibe | v4.0 (M9) |

Hoy cada mecanismo tiene su propio flujo, sus propias clases, y su propio mecanismo de coordinación. Esta spec los unifica.

## 4. Las mejoras semánticas

Además de los cuatro mecanismos de ampliación, el proceso necesita subagentes para mejorar la calidad de los tres archivos de entrada y de la clasificación:

- **D4** — interpretar las restricciones activas del Director en el tema actual.
- **A1 truncado** — resumir el contenido truncado cuando el tema activo es muy largo.
- **Decisiones reales** — distinguir decisiones reales de aprobaciones genéricas, con su alcance.
- **Nombres legibles** — asignar nombres semánticos a los subtemas (no `general_general_2026sep09_2026sep09_2`).
- **Clasificación de temas** — clasificar intercambios por tema real, no solo por regex.

Hoy cada una intenta llamar `sub.run()` síncrono, lo que causa deadlock. Esta spec las unifica y corrige.

## 5. La consulta bajo demanda

Cuando el agente trabaja normalmente y necesita detalle de un tema histórico, le pregunta al proceso. El proceso identifica los bloques candidatos y le devuelve una respuesta consolidada. Esto ya funciona (M8) y se conserva como uno de los tres usos del procesador.

## 6. Arquitectura: dos clases principales

### 6.1. Clase 1 — Procesador de contexto

Responsabilidad: procesar una fuente y entregarle el resultado al agente o al proceso, según corresponda.

Tres subclases, según el tipo de input:

#### `ProcesadorDocumento`

Para los cuatro mecanismos de ampliación (links del chat, attachments, archivos externos, URLs).

- Recibe un documento (link, attachment, archivo, URL).
- Decide según tamaño:
  - **Trivialmente pequeño** (<1K tokens): el agente lo lee directo.
  - **Mediano** (1K–50K tokens): un subagente que lee, clasifica y resume.
  - **Grande** (>50K tokens): el flujo de 3 niveles (N1 divide, N2 en paralelo, N3 concilia), coordinado por el `Orquestador`.
- Clasifica el contenido en temas, genera resumen, actualiza el índice y los bloques.
- Las variantes de origen (link del chat vs attachment vs archivo externo vs URL) son solo cómo se obtiene el contenido, no cambios al procesamiento.

Reutiliza:
- `DocumentoIndexerSubagent` (lo que sirve de su lógica de lectura y clasificación).
- El `Divisor` y el `Conciliador` del flujo de 3 niveles (para el caso grande).
- El `DocumentDelegator` (la decisión de delegar o no).

#### `ProcesadorIntercambios`

Para las mejoras semánticas (D4, A1 truncado, decisiones reales, nombres legibles, clasificación de temas).

- Recibe intercambios del chat.
- Según el modo:
  - `RESTRICCIONES_TEMA` — interpreta las restricciones del Director (D4).
  - `RESUMEN_TRUNCADO` — resume el contenido truncado (A1).
  - `DECISIONES` — detecta decisiones reales con alcance.
  - `NOMBRE_LEGIBLE` — asigna nombres semánticos a subtemas.
  - `CLASIFICACION_TEMAS` — clasifica intercambios por tema real.
- Le pide al `Orquestador` que gestione la ejecución del subagente.
- Devuelve el resultado estructurado al proceso para que actualice los archivos.

Reutiliza:
- `ClasificadorSubagent` (H1) como clase base.
- Los modos del `IntercambiosClasificadorSubagent` (RESTRICCIONES_TEMA, RESUMEN_TRUNCADO, etc.).
- Los generadores (Estado, Decisiones, Subdivider) dejan de intentar llamar subagentes — le piden al `ProcesadorIntercambios`.

#### `ProcesadorConsulta`

Para responder preguntas del agente sobre bloques (lo que hoy hace `query_context`).

- Recibe una pregunta del agente.
- Identifica bloques candidatos por keyword search.
- Decide según tamaño total de los bloques:
  - **Cabe en un subagente** (<100K tokens): un solo subagente que lee los bloques y responde.
  - **No cabe** (>100K tokens): divide en lotes, un subagente por lote, consolida al final.
- Le pide al `Orquestador` que gestione la ejecución.
- Devuelve la respuesta consolidada al agente.

Reutiliza:
- La lógica de `query_context` (M8) que ya funciona.
- Los modos del `IntercambiosClasificadorSubagent` (modo `CONSULTA_BLOQUE`).

### 6.2. Clase 2 — Coordinador proceso-agente

Responsabilidad: ser la herramienta del agente. Existe para ayudarlo, no para hacerlo menos eficiente. Vive aparte de la clase de procesamiento, porque es un mecanismo transversal que sirve para todos los procesadores.

Tres subclases:

#### `EntregadorTareas`

El proceso le entrega al agente las tareas que necesita.

- El proceso publica las tareas (prompts) en un lugar accesible.
- El agente lee esas tareas y lanza los subagentes.
- El proceso no lanza nada — solo le dice al agente qué necesita.
- El "lugar accesible" son archivos en el workspace (`_pending_tasks.json`), no un mini-servicio HTTP. Simples, inspeccionables, sin polling.

#### `RecogedorRespuestas`

Los subagentes escriben sus respuestas en un lugar, este recogedor las lee, las procesa, y se las entrega al agente de forma estructurada.

- Los subagentes escriben en `_responses/{task_id}.txt`.
- El agente nunca ve el contenido crudo — solo le dice al proceso "las respuestas están listas".
- El `RecogedorRespuestas` lee, procesa, y entrega el resultado estructurado.
- El proceso integra el resultado a los archivos (actualiza D4, A1, decisiones, nombres, bloques, índice, metadata).

#### `Orquestador`

Coordina el flujo completo entre el agente y el proceso.

- Decide cuándo hay tareas pendientes.
- Decide cuándo todas las respuestas llegaron.
- Decide cuándo integrarlas a los archivos.
- Decide cuándo avisarle al agente que todo está listo.
- Reemplaza al `TaskBridgeServer` + polling por coordinación basada en archivos.

## 7. El flujo completo

### 7.1. Cuando el agente pierde contexto

1. El agente llama a `pipeline.run()`.
2. El proceso extrae, clasifica y empaqueta (sin subagentes).
3. El proceso genera los tres archivos de entrada con lo que tiene (regex, sin subagentes).
4. Cuando el proceso necesita subagentes para mejorar la calidad (D4, decisiones, A1, nombres, clasificación), el `ProcesadorIntercambios` prepara las tareas y se las entrega al `EntregadorTareas`.
5. `pipeline.run()` termina y le devuelve al agente: "terminé lo que podía, y tengo N tareas pendientes en `_pending_tasks.json`".
6. El agente lee `_pending_tasks.json` (eso es leer el contexto entregado por el proceso).
7. El agente lanza los subagentes con el Task tool (puede ser en paralelo).
8. Los subagentes escriben sus respuestas en `_responses/`.
9. El agente llama a `pipeline.collect_responses()` — le dice al proceso "las respuestas están en `_responses/`".
10. El `RecogedorRespuestas` lee las respuestas, el `Orquestador` las integra a los archivos.
11. El proceso le devuelve al agente el resultado estructurado: "apliqué N respuestas, los archivos están actualizados".
12. El agente lee los tres archivos de entrada (actualizados) y retoma el hilo.

### 7.2. Cuando el agente necesita detalle de un tema (consulta bajo demanda)

1. El agente llama a `pipeline.query_context("¿qué se decidió sobre JWT?")`.
2. El `ProcesadorConsulta` identifica bloques candidatos.
3. Si caben en un subagente: le pide al `EntregadorTareas` que publique una tarea.
4. El agente lee la tarea, lanza un subagente, el subagente escribe la respuesta.
5. El agente llama a `pipeline.collect_responses()`.
6. El `RecogedorRespuestas` lee la respuesta y se la entrega estructurada al agente.
7. El agente lee la respuesta y continúa trabajando.

### 7.3. Cuando el Director entrega un documento (ampliación de contexto)

1. El agente llama a `pipeline.ampliar_contexto(source_type, source_path, jwt)`.
2. El `ProcesadorDocumento` decide según tamaño:
   - **Pequeño:** devuelve `needs_agent_read: true`, el agente lo lee directo.
   - **Mediano:** le pide al `EntregadorTareas` que publique una tarea para un subagente que lee y clasifica.
   - **Grande:** usa el flujo de 3 niveles, coordinado por el `Orquestador`.
3. El agente lanza los subagentes según las tareas publicadas.
4. El `RecogedorRespuestas` lee las respuestas y el `Orquestador` las integra (actualiza bloques, índice, metadata).
5. El proceso le devuelve al agente el resultado estructurado.

### 7.4. Cuando se importa un paquete de contexto (export/import)

1. El agente llama a `pipeline.import_context(zip_path)`.
2. El proceso descomprime el `.zip` en `/home/z/my-project/contexto_recuperacion/`.
3. El proceso devuelve el contenido de `_instrucciones_recuperacion.md`.
4. El agente lee las instrucciones y los tres archivos de entrada.
5. Sin subagentes en este flujo — es puramente empaquetado y desempaquetado.

## 8. Lo que se conserva de versiones anteriores

- El protocolo de acceso del agente (3 escenarios: carga inicial, recuperación tras compresión, consulta bajo demanda).
- Los tres archivos de entrada (`00_estado_actual.md`, `01_indice_recuperacion.md`, `02_decisiones_clave.md`).
- La estructura de bloques y `_metadata.json`.
- El bookmarklet + `CredentialManager` para el JWT.
- La exportación/importación de contexto (`.zip`).
- El flujo de 3 niveles (N1/N2/N3) para documentos grandes.
- Los modos del `IntercambiosClasificadorSubagent`.
- El `DocumentDelegator` (decisión de delegar).
- Los generadores (Estado, Decisiones, Indice, Bloque).

## 9. Lo que se desmonta

- El H9 mal implementado (pending_tasks en memoria, `apply_subagent_responses` con respuestas pasadas por parámetro, generadores que llaman `sub.run()` síncrono).
- El `TaskBridgeServer` + polling HTTP (ya no se necesita — el `Orquestador` hace la coordinación con archivos).
- El `_task_bridge.py` con su polling a `localhost:8087` (queda como código legacy, no se usa en el flujo principal).
- La mezcla de mecanismos de ampliación desparramados por distintos archivos (se unifican bajo `ProcesadorDocumento`).

## 10. Reglas de implementación (de `tareas_inmediatas.md`)

- **Cambios quirúrgicos:** solo se modifica lo que se concilió. No se toca el código que ya funciona.
- **Scripts atómicos y standalone:** cada nuevo archivo es autónomo, se valida solo con auto-tests en su bloque `__main__`.
- **Scripts de dependencia:** los que importan atómicos se validan con tests en `tests/`.
- **No hardcoding:** todas las constantes nuevas van en `config.py`.
- **Buenas prácticas:** type hints, docstrings, logging en todos los nuevos módulos y en los intervenidos.
- **OOP:** las clases son robustas y reutilizables. Las subclases se diferencian por el input, no por la lógica de invocación.
- **Tests individuales:** cada nuevo módulo lleva auto-tests en `__main__`. Cada módulo intervenido actualiza sus auto-tests.
- **Tests E2E:** `tests/test_v42_e2e.py` valida el flujo completo.
- **Comunicación de errores:** ningún subagente falla silenciosamente. Los errores suben al Director.
- **Lo que funciona se conserva:** no se descarta código que demostró cumplir su cometido.

## 11. Compatibilidad con v4.0

- Todos los archivos existentes se conservan.
- Las funciones públicas (`run`, `status`, `export_context`, `import_context`, `index_document`, `index_document_large`, `query_context`, `ampliar_contexto`) mantienen su signature.
- Se agrega una nueva función: `collect_responses()`.
- Los flags `enable_capa3` y `enable_attachments` siguen funcionando (internamente usan `ProcesadorDocumento` y `ProcesadorIntercambios`).
- Los tests existentes siguen pasando. Los que prueban comportamiento que cambia se actualizan.

## 12. Dependencias nuevas

- Ninguna. Se usan las mismas dependencias ya instaladas (`httpx`, `pydantic`, `pdfplumber`, `requests`).

## 13. Validación

- **`ProcesadorDocumento`:** auto-test que procesa un archivo pequeño (devuelve `needs_agent_read=True`), uno mediano (un subagente), y uno grande (3 niveles).
- **`ProcesadorIntercambios`:** auto-test para cada modo (RESTRICCIONES_TEMA, RESUMEN_TRUNCADO, DECISIONES, NOMBRE_LEGIBLE, CLASIFICACION_TEMAS).
- **`ProcesadorConsulta`:** auto-test que simula una consulta y verifica que la respuesta viene consolidada.
- **`EntregadorTareas`:** auto-test que publica tareas en `_pending_tasks.json`.
- **`RecogedorRespuestas`:** auto-test que lee respuestas de `_responses/` y las entrega estructuradas.
- **`Orquestador`:** auto-test que coordina el flujo completo.
- **Test E2E:** `tests/test_v42_e2e.py` valida: `pipeline.run()` → proceso entrega tareas → agente lanza subagentes → proceso recoge respuestas → proceso entrega resultado estructurado → agente lo lee.

---

**Fin de la spec v4.2.**
