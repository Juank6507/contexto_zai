# contexto_zai/Documentación/spec_recuperacion_contexto_v4.0.md
# Spec v4.0 — El proceso contexto_zai como bibliotecario siempre disponible

**Versión:** 4.0
**Fecha:** 2026-09-09
**Autor:** Agente CZAI (Sesión 11)
**Estado:** Pendiente de validación por el Director.
**Especifica continuación de:** spec v3.6 (JWT automático + subagentes paralelos).
**Concilia:** mejoras M3, M4, M6, M7, M8, M9, M10 acordadas con el Director en Sesión 11. (M5 descartado: el bookmarklet funciona como está.)

---

## 1. Problema

La spec v3.6 dejó resuelta la extracción de mensajes, la clasificación temática y la indexación de documentos grandes con subagentes paralelos de 3 niveles. Quedaron 6 problemas sin resolver:

### Problema 1 — El `00_estado_actual.md` no sirve para recuperar contexto

El `EstadoGenerator` actual usa 8 secciones (D1-D4 + A1-A4). Algunas secciones se llenan con patrones regex estrechos que capturan poco. La sección A4 ("siguiente paso lógico") siempre dice "continuar con la instrucción del Director". D2 y D3 duplican información que ya vive en `02_decisiones_clave.md` (D3) o que se puede capturar mejor en A1 (D2).

**Esto es crítico:** el momento para el que existe el proceso es la compresión de contexto, y el archivo que el agente lee en ese momento no cumple su función.

Tras una compresión de contexto, el agente lee **tres** archivos como puntos de entrada obligatorios:
1. `00_estado_actual.md` — le dice dónde quedó, qué estaba haciendo, qué sigue.
2. `01_indice_recuperacion.md` — le dice qué temas existen y en qué archivo está cada uno.
3. `02_decisiones_clave.md` — le dice cuál fue la última decisión que tomó el Director sobre la tarea pendiente, para retomarla exactamente donde se acordó.

Sin los tres, el agente no puede retomar el hilo. Por eso M3 (estado actual con 5 secciones, no 8) y M4 (decisiones con subagente) son las dos prioridades más altas de esta spec.

### Problema 2 — Las decisiones detectadas son mayormente falsos positivos

El `DecisionesGenerator` usa 19 patrones regex para detectar decisiones. En la prueba real de la Sesión 11 detectó 31 "decisiones", pero la mayoría son frases como "Correcto", "Continua con lo Milestone V2 a..." — no son decisiones reales, son aprobaciones o continuaciones.

### Problema 3 — El agente todavía lee los archivos directamente

Hoy el agente, cuando necesita consultar el contexto, abre `00_estado_actual.md`, `01_indice_recuperacion.md` y los bloques en su propia ventana. Eso consume su contexto. No existe un mecanismo de consulta bajo demanda donde el proceso haga el trabajo pesado y le devuelva solo la respuesta completa.

### Problema 4 — La ampliación de contexto solo funciona para attachments del chat

El `DocumentoIndexerSubagent` solo se activa cuando el pipeline detecta attachments en los mensajes del chat. No existe una forma de que el agente le pase al proceso un link externo o un documento que el Director acaba de entregarle.

### Problema 5 — Los nombres de los temas son ilegibles

El `Subdivider._subdivide_temporal` genera nombres compuestos ilegibles como `general_general_2026sep09_2026sep09_2_2026sep09_2_2026sep09_2` cuando subdivide recursivamente. Cuando el agente busca "¿dónde está lo de JWT?", el índice no puede responder porque los nombres no tienen semántica.

### Problema 6 — El pipeline muere silenciosamente en background

Cuando se lanza `pipeline.run()` en background (proceso Python separado con ThreadPoolExecutor + polling HTTP al TaskBridgeServer), el proceso puede morir sin dejar traceback. No hay mecanismo de diagnóstico para saber qué lo mata.

### Problema 7 — Los subagentes fallan silenciosamente

El `SubagentLauncher` y el `_task_bridge` devuelven `success=False` cuando el subagente falla, pero el llamador puede ignorar el error y seguir. El Director no se entera de que algo falló.

## 2. Solución

### Mejora M3 — `00_estado_actual.md` pasa de 8 secciones a 5

**Objetivo:** el `00_estado_actual.md` debe ser operativo: el agente, después de una compresión de contexto, debe poder retomar el trabajo leyendo solo ese archivo.

**Cambios al `EstadoGenerator`:**

Estructura nueva del archivo (5 secciones, no 8):

- **D1 — Última instrucción del Director:** textual, sin tocar. Como está hoy.
- **D4 — Restricciones activas del último tema:** las restricciones y preferencias del Director enfocadas al tema activo (no a los últimos 10 intercambios genéricos). Las interpreta un subagente, no regex.
- **A1 — Qué estaba haciendo el agente (con truncado inteligente):** toma el tema activo en orden cronológico. Si es muy largo, trunca a ~16K de contexto textual y le suma ~4K de resumen del contenido truncado hecho por un subagente. Esto es el "truncado inteligente": combina texto literal con resumen para no perder el hilo.
- **A2 — Entregables producidos:** los archivos mencionados en intercambios recientes. Patrones ampliados para capturar más tipos de rutas.
- **A3 — Errores abiertos:** los errores detectados en intercambios recientes. Patrones ampliados para detectar más tipos de errores ("Traceback", "Error", "Exception", "FileNotFound", "exit_code=1", "command failed", "timeout", etc.).
- **A4 — Siguiente paso lógico:** analiza los últimos intercambios para detectar qué quedó pendiente, en vez de repetir "continuar con la instrucción del Director".

**Secciones eliminadas:**
- D2 (contexto del tema activo) — se reemplaza por A1 con truncado inteligente, que ya captura el contexto del tema activo de forma completa.
- D3 (decisiones pendientes) — se elimina porque las decisiones ya viven en `02_decisiones_clave.md`. Para saber cuál fue la última decisión relevante, el agente consulta ese archivo.

**Reglas:**
- El subagente que interpreta D4 y hace el truncado inteligente de A1 es el mismo que se usa en M4 y M8 (ver M7 para la clase base común).
- Las cifras (~16K textual, ~4K resumen) son aproximadas, no rígidas, y se configuran en `config.py`.
- Intervención quirúrgica del `EstadoGenerator`: no se crea clase nueva paralela.

### Mejora M4 — `02_decisiones_clave.md` con subagente que detecta decisiones reales y su alcance

**Objetivo:** las decisiones documentadas deben ser reales, no falsos positivos. Y para cada decisión, capturar el alcance: a qué tarea se refiere, qué incluye, qué no incluye.

**Cambios al `DecisionesGenerator`:**

- Se mantiene la clase `DecisionesGenerator`.
- Se mantiene la signature `generate(exchanges, from_timestamp) -> (content, summary)`.
- El mecanismo de detección cambia: en vez de los 19 patrones regex, usa un subagente.
- El subagente recibe los intercambios en lotes (cantidad configurable en `config.py`), los lee, y distingue entre:
  - (a) Aprobaciones genéricas ("Correcto", "OK") — se descartan.
  - (b) Directivas operativas ("Quiero que reinicies como agente nuevo") — se documentan.
  - (c) Decisiones de arquitectura ("Usaremos 3 niveles de subagentes") — se documentan.
- Para cada decisión real, el subagente describe el alcance: a qué tarea se refiere, qué incluye, qué no incluye.
- El `DecisionesGenerator` arma el archivo final con la salida del subagente, deduplica (una decisión puede detectarse en varios lotes), y trunca al límite de tokens del archivo.
- El subagente es el mismo que se usa en M3 (D4, A1) y M8 (ver M7).
- Si el subagente falla, el error sube al Director — no se cae a fallback regex.

### Mejora M7 — Clase base común OOP para subagentes clasificadores

**Objetivo:** los subagentes que hacen M3 (D4, A1), M4, M8 y la clasificación de documentos (N2 del flujo de 3 niveles) son el mismo patrón: reciben un contexto, hacen una tarea semántica, devuelven un texto estructurado. Unificarlos en una clase base OOP para evitar duplicar código.

**Cambios:**

- Crear `ClasificadorSubagent` (clase base abstracta en `subagents/`) con la lógica común:
  - `build_prompt(context)`: construye el prompt para el subagente. Cada subclase lo implementa.
  - `run(context)`: invoca el `SubagentLauncher` y devuelve la respuesta parseada.
  - `parse_response(raw)`: parsea la respuesta estructurada del subagente.
- `DocumentoIndexerSubagent` pasa a heredar de `ClasificadorSubagent`, reutiliza la lógica común. Su input es un archivo o link.
- Crear `IntercambiosClasificadorSubagent` (subclase) que también hereda de `ClasificadorSubagent`. Su input es una lista de intercambios del chat.
- El `Subdivider` (M7) usa el `IntercambiosClasificadorSubagent` para asignar nombres legibles cuando subdivide (en vez de generar nombres compuestos ilegibles).
- El `EstadoGenerator` (M3 D4, A1) usa el `IntercambiosClasificadorSubagent` para interpretar restricciones y hacer truncado inteligente.
- El `DecisionesGenerator` (M4) usa el `IntercambiosClasificadorSubagent` para detectar decisiones reales con alcance.
- La consulta del agente (M8) usa el `IntercambiosClasificadorSubagent` para responder consultas leyendo bloques.

**Reglas:**
- La clase base es abstracta: no se instancia directamente.
- Las subclases se diferencian por el input, no por la lógica de invocación.
- No se mantienen clases paralelas con fallback regex.

### Mejora M8 — Consulta bajo demanda al proceso (v4.0 revisada tras pruebas reales)

**Objetivo:** el agente consulta al proceso con una pregunta concreta y recibe una respuesta completa y abarcadora de lo que se preguntó, sin leer bloques en su ventana.

**Hallazgo crítico (Sesión 16):** Se probó con datos reales que los subagentes NO tienen acceso al Task tool. Solo el agente principal puede lanzar subagentes. Por lo tanto, el diseño de N1→N2×N→N3 con subagentes anidados no es viable para consultas. Se probó también que un subagente SÍ tiene acceso a `Read` y `Bash`, por lo que puede leer archivos directamente.

Se probó además que un solo subagente que lee varios bloques con `Read` produce respuestas más completas que múltiples subagentes leyendo un bloque cada uno, y requiere una sola invocación del Task tool en lugar de múltiples.

**Limitación descubierta:** un subagente tiene ~128K tokens de contexto. Si los bloques candidatos juntos superan ese límite, un solo subagente no puede leerlos todos.

**Mecanismo — dos modos según tamaño:**

La función `query_context(question, max_results=3)` en `pipeline.py` elige el modo automáticamente:

**Modo directo (pocos bloques, contenidos juntos < 100K tokens):**
1. La función identifica bloques candidatos (búsqueda por keyword en nombres de temas, contenido del índice, y contenido de los bloques).
2. La función lanza **un solo subagente** con el Task tool (una invocación).
3. El subagente recibe la pregunta y la lista de rutas de los bloques candidatos.
4. El subagente lee los bloques con `Read`, busca la respuesta, consolida.
5. El subagente devuelve la respuesta final.
6. La función devuelve la respuesta al agente.
- **Intervención del agente principal: 1 invocación del Task tool.** Sin polling, sin TaskBridgeServer.

**Modo distribuido (muchos bloques, contenidos juntos > 100K tokens):**
1. La función identifica bloques candidatos.
2. La función divide los bloques en lotes que quepan en el contexto de un subagente (~100K tokens por lote).
3. La función lanza **un subagente por lote** con el Task tool (múltiples invocaciones en paralelo en un solo mensaje).
4. Cada subagente lee los bloques de su lote y responde.
5. La función consolida las respuestas de todos los lotes (elimina duplicados, fusiona).
6. La función devuelve la respuesta consolidada al agente.
- **Intervención del agente principal: N invocaciones del Task tool en paralelo (en un solo mensaje).** Sin polling, sin TaskBridgeServer.

**Umbral de decisión:** `QUERY_DIRECT_MODE_THRESHOLD_TOKENS` (configurable en `config.py`, default 100K). Si los bloques candidatos juntos superan este umbral, se usa modo distribuido.

**Reglas:**
- El agente nunca ve el contenido de los bloques, solo la respuesta.
- Si ningún bloque tiene match, la función responde que no hay información relevante.
- Si el subagente falla, el error sube al Director (no silencioso).
- No se usa TaskBridgeServer ni `_task_bridge.py` para consultas. El agente principal lanza los subagentes directamente con el Task tool.

### Mejora M9 — Ampliación de contexto desde fuentes externas

**Objetivo:** el Director puede pasarle al agente links o documentos para que se incorporen al contexto.

**Mecanismo:**

- Se agrega una función pública `ampliar_contexto(source_type, source_path, jwt, metadata)` en `pipeline.py`.
- Recibe `source_type` (`"url"` o `"file"`), `source_path` (la URL o ruta), `jwt` (si es URL de Z.ai), y `metadata` opcional.
- Para archivos:
  - Si el archivo es chico (menor a umbral configurable en `config.py`): el agente lo lee directo, el proceso no se involucra.
  - Si el archivo es grande: el proceso lo descarga y lo clasifica con el `DocumentoIndexerSubagent` existente (flujo de 3 niveles si > 50K tokens). Agrega el resultado como nuevos bloques al directorio `contexto_recuperacion/`. Actualiza `01_indice_recuperacion.md` y `_metadata.json`.
- Para URLs:
  - El proceso descarga el contenido con `requests` directamente dentro de `ampliar_contexto` (5 líneas, no se crea módulo `UrlDownloader` nuevo).
  - Lo clasifica igual que un archivo grande.
- Para distinguir bloques externos de los del chat, se agrega el campo `source` en `_metadata.json` (como mapeo paralelo `archivo → source`), no en el modelo `ThematicBlock`.

**Reglas:**
- Si la URL es de un chat de Z.ai (`/s/{share_id}` o `/c/{chat_id}`), el proceso usa el flujo normal de extracción de chat, no el de ampliación.
- Los archivos temporales van en `download/uploads/temp/`, los indexados en `download/uploads/indexed/`.
- No se crea módulo nuevo: la función va en `pipeline.py`, la descarga con `requests` va inline.

### Mejora M6 — Diagnosticar y arreglar la muerte silenciosa del pipeline en background

**Objetivo:** el pipeline muere silenciosamente cuando corre en background con subagentes en paralelo. Primero hay que diagnosticar qué lo mata, después intervenir lo que corresponda.

**Mecanismo (diagnóstico primero):**

- Se implementan tests que reproducen las condiciones reales:
  - El pipeline corriendo en background (no en foreground con timeout corto).
  - Subagentes lanzados en paralelo con `ThreadPoolExecutor`.
  - Polling HTTP al `TaskBridgeServer` esperando respuestas.
  - El Bash tool cerrando su process tree al terminar.
- Se miden: uso de memoria (para descartar OOM), uso de CPU, duración (para descartar timeout del Bash tool de 2 minutos), presencia de SIGTERM/SIGKILL del entorno.
- Se capturan logs en nivel DEBUG de los módulos `subagents._task_bridge`, `processing.divisor`, `process.recovery_cycle`, `subagents.divisor_subagent`.
- Se documenta el hallazgo.
- En función del diagnóstico, se interviene lo que corresponda (no se decide la intervención antes de saber qué falla).

**Reglas:**
- No se agrega handler de señales genérico ni heartbeat periódico antes del diagnóstico.
- Los tests reproducen condiciones reales, no casos sintéticos simplificados.

### Mejora M10 — Pulir exportación/importación de contexto

**Objetivo:** el `.zip` exportado ya funciona, pero las instrucciones de recuperación tienen un detalle de orden.

**Cambios:**

- Intervenir `_build_instrucciones` en `context/exporter.py` para reordenar los pasos: primero leer los tres puntos de entrada (`00_estado_actual.md`, `01_indice_recuperacion.md`, `02_decisiones_clave.md`), después recién lanzar subagentes para detalle.
- No se agregan archivos nuevos al `.zip` — ya incluye `_instrucciones_recuperacion.md` y `_paquete.json`.
- Intervenir `import_context()` en `pipeline.py` para que devuelva el contenido de `_instrucciones_recuperacion.md` con el orden correcto (lo que ya hace, solo que con el orden nuevo).

**Reglas:**
- No se crea módulo nuevo.
- No se cambia la signature de `export_context()` ni `import_context()`.

## 3. Comunicación de errores de subagentes

**Regla general (aplica a M3, M4, M7, M8, M9):** cuando un subagente falla, el error no puede ser silencioso. La clase `SubagentLauncher` y el `_task_bridge` deben:

- Registrar el motivo del fallo (timeout, TaskBridgeServer no responde, subagente devolvió vacío, error de parseo, etc.) en el log con detalle.
- Devolver el error al llamador.
- El llamador (por ejemplo, `DecisionesGenerator`, `EstadoGenerator`, `query_context`, `ampliar_contexto`) propaga el error hacia arriba.
- Si el error llega al `pipeline.run()` y este está siendo invocado por el agente, el agente comunica el error al Director en su respuesta, en vez de continuar con fallback.

No existe el modo "light" con regex como fallback permanente.

## 4. Arquitectura final del proceso

```
┌────────────────────────────────────────────────────────────────┐
│  AGENTE (sandbox Z.ai, ventana 128K tokens)                    │
│                                                                 │
│  1. Lee 00_estado_actual.md (5 secciones)                      │
│  2. Lee 01_indice_recuperacion.md                               │
│  3. Lee 02_decisiones_clave.md                                  │
│  4. Cuando necesita detalle, llama a query_context()           │
│                                                                 │
└──────────────────┬─────────────────────────────────────────────┘
                   │ llamada Python directa
                   ▼
┌────────────────────────────────────────────────────────────────┐
│  PIPELINE.PY (funciones públicas)                              │
│                                                                 │
│  - run() — construcción inicial                                │
│  - query_context(question, max_results) — consulta on-demand  │
│  - ampliar_contexto(source_type, source_path, jwt, metadata)   │
│  - export_context() / import_context()                         │
│  - index_document() / index_document_large()                   │
│                                                                 │
└──────────┬────────────────────────────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────────────────────────────┐
│  CLASIFICADORSUBAGENT (clase base OOP)                         │
│                                                                 │
│  - DocumentoIndexerSubagent (input: archivo/link)              │
│  - IntercambiosClasificadorSubagent (input: intercambios)      │
│                                                                 │
│  Usado por:                                                     │
│  - EstadoGenerator (D4, A1 truncado inteligente)              │
│  - DecisionesGenerator (detección con alcance)                 │
│  - Subdivider (nombres legibles al subdividir)                 │
│  - query_context (responder consultas por bloque)              │
│  - ampliar_contexto (clasificar documentos externos)           │
│                                                                 │
└──────────┬────────────────────────────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────────────────────────────┐
│  SUBAGENTLAUNCHER → _task_bridge → TaskBridgeServer (8087)     │
│                                                                 │
│  - Lanza subagentes vía Task tool de Z.ai                       │
│  - Si falla, error sube al Director (no silencioso)             │
│                                                                 │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  JWT_BRIDGE_SERVER (mini-servicio efímero, puerto 8086)         │
│                                                                 │
│  - Se levanta solo cuando hace falta el JWT                     │
│  - Recibe el JWT y lo guarda en ~/.czai/credentials.json        │
│  - Se cierra solo tras recibir el JWT                           │
│  - Bookmarklet usa URL dinámica: preview-chat-{chatId}.space-z.ai │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

## 5. Reglas de implementación (de `tareas_inmediatas.md`)

- **Cambios quirúrgicos:** solo se modifica lo que se concilió (M3, M4, M6, M7, M8, M9, M10). No se toca el código que ya funciona.
- **M5 descartado:** el bookmarklet funciona como está. Se agrega testing de sandbox nuevo y persistencia del JWT entre sesiones.
- **Scripts atómicos y standalone:** cada nuevo archivo (por ejemplo, `ClasificadorSubagent` base, `IntercambiosClasificadorSubagent` subclase) es autónomo, se valida solo con auto-tests en su bloque `__main__`.
- **Scripts de dependencia:** los que importan atómicos (por ejemplo, `EstadoGenerator` que ahora usa el subagente) se validan con tests en `tests/`.
- **No hardcoding:** todas las constantes nuevas (umbrales de tamaño, timeouts, lotes de subagente, configuración de truncado inteligente, etc.) van en `config.py` y se leen de variables de entorno o archivos de configuración.
- **Buenas prácticas:** type hints, docstrings, logging en todos los nuevos módulos y en los intervenidos.
- **OOP:** los subagentes se unifican en una clase base abstracta `ClasificadorSubagent` con dos subclases (autorizado por el Director en Sesión 11).
- **Tests individuales:** cada nuevo módulo lleva auto-tests en `__main__`. Cada módulo intervenido actualiza sus auto-tests.
- **Tests E2E:** `tests/test_v40_e2e.py` valida el flujo completo: extraer → clasificar → generar estado con 5 secciones y truncado inteligente → consultar via `query_context` → ampliar desde archivo externo → exportar → importar.
- **Comunicación de errores:** ningún subagente falla silenciosamente. Los errores suben al Director.

## 6. Compatibilidad con v3.6

- Todos los archivos existentes se conservan.
- Las funciones públicas (`run`, `status`, `export_context`, `import_context`, `index_document`, `index_document_large`) mantienen su signature.
- Se agregan nuevas funciones: `query_context()`, `ampliar_contexto()`.
- Los flags `enable_capa3` y `enable_attachments` siguen funcionando.
- Los tests existentes (47 atómicos + 10 E2E v3.6) siguen pasando. Los que prueban comportamiento que cambia en v4.0 (por ejemplo, los auto-tests del `EstadoGenerator` que esperaban 8 secciones) se actualizan para reflejar la nueva estructura de 5 secciones.
- El `00_estado_actual.md` cambia de 8 a 5 secciones. Es un cambio de spec explícito, autorizado por el Director.

## 7. Dependencias nuevas

- Ninguna. Se usan las mismas dependencias ya instaladas (`httpx`, `pydantic`, `pdfplumber`, `requests`).

## 8. Validación

Cada mejora incluye su validación:

- **M3:** auto-test del `EstadoGenerator` intervenido que verifica las 5 secciones presentes y no vacías, y que A1 contiene truncado inteligente (texto literal + resumen).
- **M4:** auto-test del `DecisionesGenerator` intervenido que verifica que las decisiones detectadas son reales (no "Correcto" ni aprobaciones genéricas) y que cada una incluye el alcance.
- **M7:** auto-test de `ClasificadorSubagent` base y sus dos subclases.
- **M8:** auto-test de `query_context` que simula una consulta y verifica que la respuesta viene consolidada y abarcadora.
- **M9:** auto-test de `ampliar_contexto` que procesa un archivo pequeño (devuelve `needs_agent_read=True`) y uno grande (lo indexa y agrega al contexto).
- **M6:** tests que reproducen el fallo real del pipeline en background y documentan qué lo mata.
- **M10:** test E2E que exporta en un workspace, importa en otro, y verifica que las instrucciones tienen los 3 puntos de entrada en el orden correcto.
- **M5 (testing):** test que levanta el bookmarklet en un sandbox nuevo, simula la conexión del Director, y verifica que el JWT persiste en `~/.czai/credentials.json` entre sesiones.

---

**Fin del documento 2.**
