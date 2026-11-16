# contexto_zai/Documentación/spec_recuperacion_contexto_v4.4.md
# Spec v4.4 — Sistema de indexado consistente + multi-chat + subagentes cableados

**Versión:** 4.4
**Fecha:** 2026-09-16
**Autor:** Agente CZAI (Sesión 19, con consenso del Director)
**Estado:** Pendiente de validación por el Director.
**Especifica continuación de:** spec v4.3 (00_estado_actual como punto de entrada ordenado + fixes huecos APA + creación automática de 03_objetivo_proyecto.md).
**Spec asociada:** esta.
**Plan asociado:** plan_refactorizacion_v4.4.md.

---

## 1. Propósito

El proceso contexto_zai es un bibliotecario que sirve al agente. Su función es mantener la información del proyecto **disponible, de calidad y accesible rápidamente**, para que el agente no se quede sin contexto.

La v4.4 ataca 6 problemas vigentes detectados durante la conciliación con el Director. No toca el empaquetado de bloques (que se mantiene secuencial como hoy) ni los bugs ya resueltos en v4.2/v4.3 (Bug A links /s/ y /c/, Bug B files_updated, Bug Windows FileExistsError).

## 2. Los 3 procesos del proceso (crear, ampliar, recuperar)

El proceso hace 3 cosas distintas según el momento. Es importante diferenciarlas porque cada una tiene reglas propias:

### 2.1. Crear contexto

Es cuando el agente **recién empieza** un proyecto. El proceso captura la información inicial que el agente necesita para poder tomar buenas decisiones: recupera el chat actual, lo clasifica, lo organiza en bloques, y registra todo en el workspace.

**Genera los 4 archivos de recuperación**: NO. Los archivos de recuperación se generan solo al recuperar contexto.

**Excepción**: si al crear contexto no existe `03_objetivo_proyecto.md`, el proceso lo crea automáticamente con la cascada documentación → bloques → contenido mínimo (esto ya está implementado en v4.3 F5).

### 2.2. Ampliar contexto

Es cuando el agente **está trabajando bien** (no perdió contexto) y recibe información nueva: el Director le pasa un documento, un link de otro chat, o un archivo. El proceso incorpora esa información al workspace **sin tocar lo que ya funciona**. El agente sigue trabajando sin interrupción; simplemente tiene más información disponible para cuando la necesite.

**Genera los 4 archivos de recuperación**: NO. Se incorpora la info nueva a bloques + índice, sin generar los archivos de recuperación.

**Excepción** (regla del Director): si se amplía desde otro chat del proyecto y no se ha recuperado el chat actual, se generan los 4 archivos de recuperación con ese chat (porque es la última información del proyecto disponible).

**Información de varios chats coexiste**: cuando el agente amplía contexto desde varios chats, la información de todos ellos coexiste en el workspace, bien indexada y accesible. El agente puede consultar cualquier bloque sin importar de qué chat vino.

### 2.3. Recuperar contexto

Es el momento crítico: el agente **perdió contexto** (se le comprimió la ventana, se quedó sin saber qué estaba haciendo). El proceso le entrega de golpe toda la información que necesita para retomar el hilo.

**Genera los 4 archivos de recuperación**: SÍ. Los 4 archivos se generan (o actualizan) en este momento.

### 2.4. Los 4 archivos de recuperación

| # | Archivo | Qué le dice al agente | Cuándo se genera |
|---|---|---|---|
| 1 | `00_estado_actual.md` | Qué estaba pasando (última instrucción, restricciones, entregables, errores, siguiente paso) + G0.A (objetivo) + G0.B (síntesis dinámica) + G1 (guía de uso) | Al recuperar contexto |
| 2 | `01_indice_recuperacion.md` | Mapa de temas → archivos de bloque, con chat de procedencia | Al recuperar contexto |
| 3 | `02_decisiones_clave.md` | Decisiones formales del Director con alcance | Al recuperar contexto |
| 4 | `03_objetivo_proyecto.md` | Objetivo del proyecto (fijo, escrito por agente/Director) + se crea automáticamente si no existe | Al crear contexto (y se mantiene) |

## 3. Los 2 caminos del proceso

Cuando el proceso procesa un chat, tiene 2 caminos:

### 3.1. Camino de recuperación completa

Lee **TODOS** los mensajes del chat, desde el primero hasta el último. Los clasifica, los organiza en bloques, y genera los archivos de recuperación desde cero.

Lo usa cuando:
- Es la primera vez que procesa ese chat.
- El agente perdió contexto y necesita recuperar.
- Llega un chat distinto al que ya tiene en el workspace.

### 3.2. Camino incremental

Lee **SOLO los mensajes nuevos** que llegaron después de la última vez que se procesó el chat. Los añade a los bloques que ya existen, sin releer todo lo anterior.

Lo usa cuando:
- El chat ya se procesó antes y es el MISMO chat.
- Solo hay novedades (mensajes nuevos desde la última vez).

## 4. La lógica de decisión (los 4 casos)

El proceso tiene que **entender su situación antes de actuar**. Para eso, hace 2 preguntas:

1. "¿Existe metadata en el workspace?"
2. "¿El chat que me llega es el MISMO que el de la metadata?"

Y según las respuestas, decide entre 4 casos:

| Caso | Pregunta 1 | Pregunta 2 | Qué hace el proceso |
|---|---|---|---|
| 1. Primera vez | NO (no hay metadata) | — | Camino de recuperación completa |
| 2. Mismo chat, sin cambios | SÍ | SÍ (mismo `chat_id`), sin mensajes nuevos | No hace nada (o muy poco) |
| 3. Mismo chat, con novedades | SÍ | SÍ (mismo `chat_id`), con mensajes nuevos | Camino incremental (procesar solo el diff) |
| 4. Otro chat distinto | SÍ | NO (distinto `chat_id`) | Camino de recuperación completa (no incremental) |

**El caso 4 es el bug del paso 4** que explotó. Tras la v4.4, el proceso lo detecta y va por recuperación completa, sin fallar.

Para responder a la pregunta 2, cuando llega un link `/s/`, el proceso primero descubre de qué chat se trata (leyendo el árbol del share) y después compara ese `chat_id` con el que está guardado en la metadata.

## 5. Los 3 sistemas de indexado

El proceso tiene hoy 5 sistemas de indexado desconectados entre sí. La v4.4 los unifica en **3 sistemas conectados**, cada uno con un rol claro:

### 5.1. Sistema 1 — Índice de temas → bloques (el `tema_a_archivo`, mejorado)

**Qué hace**: mapa "tema → archivo(s) de bloque". Es el que usa `query_context()` para encontrar candidatos en milisegundos.

**Estado hoy**: existe pero asume un solo chat y se queda viejo en el ciclo incremental.

**Cambios en v4.4**:
- Se regenera en cada cambio (no solo en recovery). El `IncrementalCycle` lo actualiza después de añadir mensajes nuevos.
- Soporta múltiples chats: cada bloque sabe de qué chat vino (registrado en la metadata).
- Es la **fuente única de verdad** para saber dónde está cada tema.

### 5.2. Sistema 2 — Índice de resúmenes (nuevo, aprovechando los `RESUMEN:` abandonados)

**Qué hace**: mapa "bloque → resumen breve". Cada bloque (del chat o externo) tiene un resumen de ~500 caracteres que dice de qué trata. El agente puede leer estos resúmenes SIN lanzar subagentes.

**De dónde sale**: los `RESUMEN:` ya existen en los `bloque_externo_*.md` (los escribió el subagente indexador). Para los bloques del chat, los resúmenes se generan con el subagente modo `RESUMEN_TRUNCADO` (ya existe).

**Cambios en v4.4**:
- Nuevo archivo `04_resumenes_bloques.md` en el workspace, que recolecta los resúmenes de todos los bloques (del chat + externos).
- Se regenera en cada cambio (cuando se añade un bloque nuevo, se añade su resumen).
- `query_context()` lo usa como atajo: si la pregunta es genérica y un resumen la responde, el agente lee el resumen directamente (sin lanzar subagente). Si el resumen no basta, recién ahí lanza subagente sobre el bloque completo.

### 5.3. Sistema 3 — Índice legible para el agente (`01_indice_recuperacion.md`, regenerado)

**Qué hace**: archivo legible que el agente lee como uno de los 4 archivos de recuperación. Lista los temas con su archivo, tamaño, y de qué chat vino.

**Estado hoy**: existe pero se queda viejo en el ciclo incremental y no muestra el chat de procedencia.

**Cambios en v4.4**:
- Se regenera en cada cambio (no solo en recovery).
- Incluye los bloques externos (ya arreglado en v4.3 F0.1).
- Muestra de qué chat es cada bloque (nuevo, para soporte multi-chat).

### 5.4. Cómo trabajan juntos los 3 sistemas

Cuando el agente pregunta *"¿qué se decidió sobre JWT?"*:

1. **Sistema 1** (tema → bloques): busca "jwt" en el mapa de temas. Encuentra que el tema `autenticacion_jwt` está en `bloque_03.md`. **Milisegundos.**

2. **Sistema 2** (resúmenes): antes de lanzar subagente, mira el resumen de `bloque_03.md`. Si el resumen ya responde, el agente lo lee directo. **Sin subagente, instantáneo.**

3. **Sistema 3** (índice legible): si el agente quiere explorar más, abre `01_indice_recuperacion.md` y ve todos los temas disponibles, con su archivo y de qué chat vinieron. **Lectura directa, sin proceso.**

Solo si los 3 no bastan, el agente lanza subagente sobre el bloque completo.

## 6. Soporte multi-chat en la metadata

### 6.1. El problema hoy

El `_metadata.json` actual tiene un solo `chat_id` y un solo `ultimo_timestamp`. Asume que el workspace es de un solo chat. Si llegan dos chats, el segundo pisa al primero en la metadata.

### 6.2. La solución en v4.4

El `_metadata.json` se amplía para soportar múltiples chats:

- **Un solo archivo** `_metadata.json` con una lista de chats (cada uno con su `chat_id`, `ultimo_timestamp`, y `share_id`).
- El `tema_a_archivo` sigue siendo un solo mapa (tema → archivo), pero cada archivo sabe de qué chat vino (registrado en el `archivo_a_source`).
- El `archivo_a_source` se amplía para registrar el `chat_id` de cada bloque.

### 6.3. Cómo decide el proceso "mismo chat vs otro chat"

Cuando el proceso recibe un chat (por `chat_id` o por link `/s/`):

1. Descubre el `chat_id` real (si viene por `/s/`, lee el árbol del share para descubrirlo).
2. Busca ese `chat_id` en la lista de chats de la metadata.
3. Si lo encuentra → es el mismo chat → caso 2 o 3 (incremental).
4. Si no lo encuentra → es otro chat distinto → caso 4 (recuperación completa).

### 6.4. Qué pasa con los bloques del chat anterior

Cuando el proceso procesa un chat distinto (caso 4), **no borra los bloques del chat anterior**. Los bloques de ambos chats coexisten en el workspace. La metadata se amplía para registrar el nuevo chat, sin pisar al anterior.

El agente puede consultar cualquier bloque sin importar de qué chat vino — el `tema_a_archivo` los indexa a todos por igual.

## 7. Subagentes de calidad cableados por defecto

### 7.1. El problema hoy

El proceso tiene los mecanismos para generar info de calidad (subagentes clasificadores, namer, detector de decisiones, sintetizador), pero **la mayoría no se cablean por defecto**:

- El `Orchestrator` crea el `RecoveryCycle` con `enable_capa3=False`.
- El launcher no se pasa a los generadores (EstadoGenerator, DecisionesGenerator) ni al Subdivider.

Por eso en la práctica el agente ve:
- Clasificación por regex (no por subagente).
- Nombres por fecha (no legibles).
- Decisiones con falsos positivos (no reales).
- D4 genérico ("No se identifican restricciones").

### 7.2. La solución en v4.4

- El `Orchestrator` cablea por defecto los subagentes de calidad:
  - `enable_capa3=True` (clasificación por subagente en vez de regex).
  - El launcher se pasa a los generadores (EstadoGenerator, DecisionesGenerator) y al Subdivider.
- Los subagentes se lanzan en modo diferido (vía `ProcesadorIntercambios` + `EntregadorTareas`), como ya funciona en v4.2 para D4, A1, decisiones, nombres.
- El agente lee `_pending_tasks.json`, lanza los subagentes con el Task tool, y llama a `collect_responses()` para que el proceso los integre.

### 7.3. Subagentes que se cablean

| Subagente | Modo | Qué hace | Estado hoy |
|---|---|---|---|
| `IntercambiosClasificadorSubagent` | `RESTRICCIONES_TEMA` | Extrae restricciones reales del Director | ⚠️ Existe pero no se cablea |
| `IntercambiosClasificadorSubagent` | `RESUMEN_TRUNCADO` | Resume contenido truncado | ⚠️ Existe pero no se cablea |
| `IntercambiosClasificadorSubagent` | `DECISIONES` | Detecta decisiones reales con alcance | ⚠️ Existe pero no se cablea |
| `IntercambiosClasificadorSubagent` | `NOMBRE_LEGIBLE` | Asigna nombres legibles a subtemas | ⚠️ Existe pero no se cablea |
| `IntercambiosClasificadorSubagent` | `CLASIFICACION_TEMAS` | Clasifica intercambios por tema real | ⚠️ Existe pero no se cablea (`enable_capa3=False`) |
| `IntercambiosClasificadorSubagent` | `SINTESIS_CONTEXTO` | Sintetiza el panorama del proyecto (G0.B) | ✅ Cableado en v4.3 |

## 8. El ciclo incremental arreglado

### 8.1. El problema hoy

El `IncrementalCycle` tiene 2 problemas:

1. **Reempaqueta TODO**: cuando llega 1 mensaje nuevo, reempaqueta TODOS los bloques (viejos + nuevos) desde cero. Eso hace que 1 mensaje nuevo cueste lo mismo que 100.
2. **No regenera el índice**: después de añadir mensajes nuevos, no llama al `IndiceGenerator` ni actualiza el `tema_a_archivo` de la metadata correctamente.

### 8.2. La solución en v4.4

1. **Reempaquetado selectivo**: el `IncrementalCycle` solo reempaqueta los temas que recibieron intercambios nuevos. Los demás bloques no se tocan.
2. **Regeneración del índice**: después de añadir mensajes nuevos, el `IncrementalCycle`:
   - Actualiza el `tema_a_archivo` de la metadata (Sistema 1).
   - Regenera el `01_indice_recuperacion.md` (Sistema 3).
   - Actualiza el `04_resumenes_bloques.md` si un bloque cambió (Sistema 2).
3. **Acepta `share_id` externo**: igual que el `RecoveryCycle`, si llega un `share_id`, se salta `create_share()` y lo usa directamente.

## 9. Lo que se conserva de versiones anteriores

- Todos los principios de la spec v4.2 (bibliotecario que sirve al agente, dos clases principales, coordinación por archivos).
- Los 4 archivos de recuperación como salida principal del proceso.
- El flujo de 3 niveles (N1/N2/N3) para documentos grandes.
- Los modos del `IntercambiosClasificadorSubagent` (RESTRICCIONES_TEMA, RESUMEN_TRUNCADO, DECISIONES, NOMBRE_LEGIBLE, CLASIFICACION_TEMAS, SINTESIS_CONTEXTO, CONSULTA_BLOQUE).
- El soporte para links `/s/` y `/c/` de Z.ai (v4.2).
- El guard relajado de `query_context()` (v4.2 — no exige `01_indice_recuperacion.md`).
- Los temas reales en `tema_a_archivo` para bloques externos (v4.2 unificación).
- El fix Windows `unlink()` antes de `rename()` (v4.2).
- El cambio de umbral `PARTITION_THRESHOLD_TOKENS = 30000` (v4.2).
- Las secciones G0.A, G0.B, G1 del `00_estado_actual.md` (v4.3).
- La creación automática de `03_objetivo_proyecto.md` (v4.3 F5).
- Los fixes de los huecos APA (F0.1 índice regenerado, F0.2 deduplicación, F0.3 prompts con SECCIONES).
- El empaquetado secuencial de bloques (no se toca el `BlockPacker` ni el `Subdivider`).

## 10. Lo que se añade en v4.4

- **Lógica de decisión de 4 casos** en el `Orchestrator` (mismo chat vs otro chat).
- **Soporte multi-chat en la metadata** (lista de chats con su `chat_id`, `ultimo_timestamp`, `share_id`).
- **3 sistemas de indexado conectados** (temas → bloques, resúmenes, índice legible).
- **Nuevo archivo `04_resumenes_bloques.md`** que recolecta los resúmenes de todos los bloques.
- **`query_context()` usa los resúmenes como atajo** antes de lanzar subagentes.
- **Subagentes de calidad cableados por defecto** (`enable_capa3=True`, launcher pasado a generadores).
- **`IncrementalCycle` arreglado**: reempaquetado selectivo + regeneración del índice + acepta `share_id`.
- **`IncrementalCycle` acepta `share_id` externo** (consistencia con `RecoveryCycle`).

## 11. Lo que se desmonta

- Nada. La v4.4 es aditiva: solo añade mecanismos nuevos y arregla los existentes. No elimina código que funciona.

## 12. Reglas de implementación

- **Cambios quirúrgicos:** solo se modifica lo especificado. No se toca el código que ya funciona.
- **Scripts atómicos y standalone:** cada archivo intervenido lleva auto-tests en `__main__`.
- **OOP:** las nuevas funcionalidades son responsabilidad de las clases existentes (Orchestrator, IncrementalCycle, IndiceGenerator, etc.).
- **No hardcoding:** todas las constantes nuevas van en `config.py`.
- **Tests individuales:** cada módulo intervenido actualiza sus auto-tests.
- **Tests E2E:** `tests/test_v42_e2e.py` se amplía con tests que validan los 4 casos de decisión, el soporte multi-chat, y el atajo de resúmenes en `query_context`.
- **Comunicación de errores:** ningún subagente falla silenciosamente.
- **Lo que funciona se conserva.**

## 13. Compatibilidad con v4.3

- Todos los archivos existentes se conservan.
- Las funciones públicas (`run`, `status`, `export_context`, `import_context`, `index_document`, `index_document_large`, `query_context`, `ampliar_contexto`, `collect_responses`) mantienen su signature.
- Los tests existentes siguen pasando. Los que prueban comportamiento que cambia se actualizan.
- Si el `_metadata.json` tiene el formato viejo (un solo chat), el proceso lo migra automáticamente al formato nuevo (lista de chats) la primera vez que se ejecuta.

## 14. Dependencias nuevas

- Ninguna. Se usan las mismas dependencias ya instaladas.

## 15. Validación

- **`Orchestrator` decisión de 4 casos:** auto-test que simula los 4 casos y verifica que el proceso elige el camino correcto.
- **Soporte multi-chat en metadata:** auto-test que procesa 2 chats distintos en el mismo workspace y verifica que ambos quedan registrados.
- **Sistema 1 (temas → bloques):** auto-test que verifica que el `tema_a_archivo` se actualiza tras un incremental.
- **Sistema 2 (resúmenes):** auto-test que verifica que `04_resumenes_bloques.md` se genera y que `query_context` lo usa como atajo.
- **Sistema 3 (índice legible):** auto-test que verifica que `01_indice_recuperacion.md` se regenera tras un incremental.
- **Subagentes cableados:** auto-test que verifica que el `RecoveryCycle` se crea con `enable_capa3=True` y launcher pasado a generadores.
- **`IncrementalCycle` reempaquetado selectivo:** auto-test que verifica que solo se reempaquetan los temas afectados.
- **`IncrementalCycle` acepta `share_id`:** auto-test que verifica que se salta `create_share()` si llega `share_id`.
- **Test E2E:** `tests/test_v42_e2e.py` ampliado con un test que valida el flujo completo multi-chat: procesar chat A → procesar chat B → ambos coexisten → `query_context` encuentra info de ambos.

---

**Fin de la spec v4.4.**
