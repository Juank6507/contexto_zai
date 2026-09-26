# contexto_zai/Documentación/spec_recuperacion_contexto_v6.0.md
# Spec v6.0 — Limpieza de bloques + Cascada de workers para resúmenes

**Versión:** 6.0
**Fecha:** 2026-09-25
**Autor:** Agente CZAI (Sesión 22, con consenso del Director)
**Estado:** Fases 1-3 implementadas. Fases 4-7 en implementación.
**Especifica continuación de:** spec v5.0 (proxy de subagentes + separación de plataforma).
**Spec asociada:** esta.
**Plan asociado:** plan_refactorizacion_v6.0.md.

---

## 1. Propósito

La v6.0 ataca dos problemas distintos que comparten raíz: **el contenido de los
bloques es caro de procesar y a veces inválido**. La v6.0 lo resuelve en dos
tiempos:

1. **Limpieza (Fases 1-3)**: corrige el empaquetado (temas grandes que revientan
   el límite de 70K), el índice multi-bloque (un tema que ya vivía en varios
   bloques pero que la metadata no podía reflejar), y el contenido de los
   intercambios del agente (JSON crudo de `tool_calls`, intercambios virtuales,
   etc.). Estas limpiezas no son nuevas funcionalidades: son fixes que la
   implementación de v5.0 dejó al descubierto.

2. **Cascada de workers (Fases 4-7)**: sustituye el flujo "el agente lanza N
   subagentes efímeros y cada uno lee el bloque completo" por una **cascada
   pipelined** que vive en un **Worker Bun persistente** (puerto 8090). El
   Worker 1 lee el bloque una vez y genera un resumen enfocado; los Workers 2-4
   leen **solo el resumen** (no el bloque) y producen en paralelo nombre
   legible, decisiones y temas principales. El Integrador aplica las 4
   respuestas juntas. Resultado: latencia mucho menor, tokens del agente
   ~0, y consistencia (todos los workers ven el mismo resumen).

## 2. Los 7 problemas que la v6.0 ataca

| # | Problema | Dónde vive | Fase |
|---|---|---|---|
| 1 | `BlockPacker.pack()` lanza `ValueError` si un tema supera 70K | `processing/block_packer.py` | F1 |
| 2 | `RecoveryMetadata.tema_a_archivo` es `dict[str, str]` (un tema → un archivo), pero un tema ya puede vivir en varios bloques | `models.py` | F2 |
| 3 | `query_context()` y `ProcesadorConsulta` no manejan `dict[str, list[str]]` | `pipeline.py`, `procesadores/procesador_consulta.py` | F2 |
| 4 | `EstadoGenerator` tiene falsos positivos: cuenta intercambios virtuales "Lee este link:" como si fueran reales (D1, A1, A3) | `generation/estado_generator.py` | F3 |
| 5 | `EstadoGenerator` A2 incluye JSON crudo de `tool_calls` en entregables | `generation/estado_generator.py` | F3 |
| 6 | `ContentCleaner` no parsea `tool_calls`: el contenido del agente llega con JSON crudo que contamina los bloques | `processing/content_cleaner.py` | F3 |
| 7 | Flujo de subagentes efímeros lento y caro: cada subagente lee el bloque completo, el agente gasta tokens en coordinación, no hay paralelismo real | `subagents/`, `coordinador/` | F4-F7 |

## 3. La solución: cascada de workers

### 3.1. Por qué una cascada

Hoy el flujo de subagentes es **abanico**: el agente lanza N subagentes
paralelos, cada uno lee el bloque completo (mismo contenido N veces), y cada
uno devuelve su parte. Eso multiplica el costo de lectura por N.

La v6.0 lo cambia por **cascada**: un solo Worker (Worker 1) lee el bloque
completo y genera un resumen enfocado; luego Workers 2-4 operan **en paralelo
sobre el resumen**, no sobre el bloque. El bloque se lee **una sola vez** por
bloque, no N veces.

```
HOY (abanico, v5.0):

  agente
    │
    ├─ Task[nombre]      ──→ lee bloque completo (70K)  ──→ nombre
    ├─ Task[decisiones]  ──→ lee bloque completo (70K)  ──→ decisiones
    └─ Task[temas]       ──→ lee bloque completo (70K)  ──→ temas

  Costo: 3× lectura del bloque. 3× tokens de entrada.
  Latencia: ~60s (Task tool overhead) × 3, en paralelo si el agente los lanza juntos.


v6.0 (cascada):

  Worker Bun persistente (puerto 8090)
    │
    ├─ Worker 1 (resumen)  ──→ lee bloque completo (70K)  ──→ resumen (3-5K)
    │                                                       + escribe al inicio del bloque
    │
    ├─ Worker 2 (nombre)   ──→ lee resumen (3-5K)          ──→ nombre legible
    ├─ Worker 3 (decisiones) ──→ lee resumen (3-5K)         ──→ decisiones
    └─ Worker 4 (temas)     ──→ lee resumen (3-5K)          ──→ temas principales

  Costo: 1× lectura del bloque + 3× lectura del resumen.
  Latencia: ~15s (LLM directo) × 2 niveles, en cascada.
```

### 3.2. Por qué el resumen vive al inicio del bloque

El resumen que produce Worker 1 se **escribe al inicio del bloque físico**
(`bloque_NN.md`), como un bloque de markdown `## RESUMEN DEL BLOQUE` antes del
primer intercambio. Esto significa que:

- **`query_context()` puede usarlo como atajo** sin lanzar subagente: si la
  pregunta es genérica, lee solo el `## RESUMEN DEL BLOQUE` (3-5K) en vez del
  bloque completo (70K).
- **Workers 2-4 no tienen que ir al bloque físico**: leen el resumen (que ya
  está en disco), no el bloque. Eso es 1/15 del tamaño.
- **Idempotente**: si el proceso se corre dos veces, el resumen se
  regenera (no se acumula). Si el bloque cambia, el resumen se invalida y se
  regenera.

### 3.3. Por qué un Worker Bun persistente

El Worker Bun vive como un **servicio persistente** en el sandbox de Z.ai,
escuchando en el puerto 8090. Esto da tres cosas:

1. **Sin overhead de Task tool**: el LLM se llama directo vía
   `internal-api.z.ai/v1/chat/completions`. Latencia 5-15s en vez de 30-60s.
2. **Paralelismo real**: Workers 2-4 corren en paralelo real (peticiones HTTP
   simultáneas), no "en paralelo" vía el agente.
3. **Independencia del agente**: el agente no gasta ni un token en coordinar.
   `pipeline.run()` publica los bloques pendientes en `_pending_blocks.json` y
   el Worker Bun los procesa en background. El agente solo llama a
   `collect_responses()` cuando los necesita integrados.

El Worker Bun **extiende** el proxy de subagentes de v5.0: misma arquitectura
(lee archivos + llama al LLM directo + escribe respuestas en `_responses/`),
pero con su propio archivo de entrada (`_pending_blocks.json` en vez de
`_pending_tasks.json`).

## 4. Dónde vive el coordinador

El coordinador es el **Worker Bun persistente**. Vive como un servicio del
sandbox de Z.ai, junto al proxy de subagentes v5.0:

```
┌────────────────────────────────────────────────────────────────┐
│  SANDBOX DE Z.AI                                                │
│                                                                 │
│  ┌────────────────┐  ┌──────────────────────┐  ┌─────────────┐  │
│  │ Proceso CZAI   │  │ Proxy v5.0           │  │ Worker Bun  │  │
│  │ (Python)       │  │ (subagentes genéricos│  │ v6.0        │  │
│  │                │  │  puerto 8091)        │  │ (cascada de │  │
│  │ pipeline.run() │  │                      │  │  bloques)   │  │
│  │  → _pending_   │  │                      │  │  puerto 8090│  │
│  │    blocks.json │  │                      │  │             │  │
│  │                │  │                      │  │ 1. Lee      │  │
│  │ collect_       │  │                      │  │    _pending_│  │
│  │  responses()   │  │                      │  │    blocks   │  │
│  │  ← _responses/ │  │                      │  │ 2. Worker 1 │  │
│  │                │  │                      │  │    resumen  │  │
│  └────────────────┘  └──────────────────────┘  │ 3. Workers  │  │
│                            ▲                   │    2-4 //   │  │
│                            │                   │ 4. Escribe  │  │
│                            │                   │    _responses│  │
│                            │                   └──────┬──────┘  │
│                            │                          │         │
│                            │                          │ HTTP    │
│                            │                          ▼         │
│                            └────────► internal-api.z.ai/v1/     │
│                                       chat/completions          │
│                                                  │              │
│                                                  ▼              │
│                                       glm-4-plus (LLM real)    │
└─────────────────────────────────────────────────────────────────┘
                          ▲
                          │ El agente NO interviene en la cascada
                          │ Solo llama pipeline.run() y collect_responses()
                          ▲
                  ┌───────┴─────────┐
                  │  AGENTE (Z.ai)  │
                  │                 │
                  │  pipeline.run()  │──→ proceso genera archivos +
                  │                  │    publica bloques pendientes
                  │  collect_        │──→ proceso integra respuestas
                  │  responses()     │    del Worker Bun
                  └─────────────────┘
```

## 5. Fases 1-3 — Limpieza (implementadas)

Las Fases 1-3 son fixes que se aplicaron durante la implementación de v6.0
para desbloquear las Fases 4-7. No están en la spec v5.0 porque se
descubrieron al intentar implementar la cascada.

### 5.1. Fase 1 — `BlockPacker.pack()` reparte intercambios de temas grandes

**Problema**: si un tema individual tiene >70K tokens (intercambios largos
sobre el mismo tema), `BlockPacker.pack()` lanza `ValueError` porque no cabe
en un solo bloque. El proceso entero aborta.

**Solución**: `BlockPacker.pack()` detecta temas que exceden el límite y **los
reparte en varios bloques**, sin necesidad del `Subdivider`. El `Subdivider`
sigue existiendo para subdividir por subtemas (otro mecanismo), pero el
`BlockPacker` ya no aborta: si un tema no cabe en un bloque, lo parte en
tantos bloques como haga falta.

**Detalle**: el reparto es **por intercambios completos** (no se parte un
intercambio por la mitad). Cada bloque resultante tiene el encabezado del
tema (con un sufijo `_parte_N` si hay más de uno).

### 5.2. Fase 2 — `RecoveryMetadata.tema_a_archivo` multi-bloque

**Problema**: el campo `tema_a_archivo` es `dict[str, str]` (un tema → un
archivo). Pero desde v4.5 un mismo tema puede vivir en varios bloques (por
ejemplo, "autenticacion_jwt" puede tener intercambios en `bloque_02.md`,
`bloque_05.md` y `bloque_08.md`). El `dict[str, str]` solo recordaba el
último archivo, perdiendo los demás.

**Solución**: el campo pasa a ser `dict[str, list[str]]` (un tema → varios
archivos). El método `registrar_tema()` pasa de **unicidad estricta** (lanzar
`ValueError` si un tema ya existe en otro archivo) a **idempotente** (un tema
puede estar en varios bloques; si ya está registrado, lo añade a la lista si
no estaba).

**Migración**: si el `_metadata.json` tiene el formato viejo (`dict[str, str]`),
se migra automáticamente al formato nuevo (`dict[str, list[str]]`) la primera
vez que se lee.

### 5.3. Fase 2b — `query_context()` y `ProcesadorConsulta` manejan multi-bloque

**Problema**: `query_context()` en `pipeline.py` y `ProcesadorConsulta` en
`procesadores/procesador_consulta.py` asumen `dict[str, str]`. Cuando un tema
está en varios bloques, solo consultan el último.

**Solución**: ambos se actualizan para manejar `dict[str, list[str]]`. Cuando
un tema está en N bloques, se leen los N (en paralelo si el proxy de v5.0
está disponible, secuencialmente si no).

### 5.4. Fase 3 — `EstadoGenerator` + `ContentCleaner` arreglan el contenido

La Fase 3 son **4 fixes reaplicados** en `EstadoGenerator` (algunos ya habían
estado aplicados y se perdieron; otros son nuevos) y **1 fix nuevo** en
`ContentCleaner`:

- **D1** (última instrucción del Director): filtra intercambios virtuales del
  tipo "Lee este link:". Antes, si el último mensaje del Director era un
  "Lee este link:" automático (que el agente genera cuando el Director le
  pasa un link), D1 lo usaba como instrucción real. Ahora D1 busca el
  último intercambio **real** del Director.
- **A1** (qué estaba haciendo el agente): filtra intercambios virtuales y
  usa el último exchange real para determinar el tema activo. Antes podía
  decir "el agente estaba leyendo un link" cuando en realidad estaba
  trabajando otra cosa.
- **A2** (entregables producidos): filtra el contenido JSON crudo de
  `tool_calls`. Antes, los `tool_calls` del agente (Write, Edit, Bash, etc.)
  aparecían como JSON en el contenido del intercambio, y A2 los detectaba
  como "rutas de archivos" porque el JSON contenía rutas. Ahora A2 solo
  procesa contenido limpio (gracias a la Fase 3b).
- **A3** (errores abiertos): filtra intercambios virtuales y `tool_calls`.
  Antes, falsos positivos: si un `tool_call` de Bash contenía la palabra
  "error" en sus argumentos, A3 lo marcaba como error real.

**Fase 3b** — `ContentCleaner._parse_tool_calls()` (nuevo):

Método nuevo en `processing/content_cleaner.py` que parsea los `tool_calls`
del contenido del agente y los formatea como **bloques legibles** en vez de
JSON crudo:

| tool_call | Formato legible |
|---|---|
| `Write` | `Archivo creado: ruta` + bloque de código con el contenido |
| `Edit` | `Archivo modificado: ruta` |
| `Bash` | `Comando: descripción` + bloque bash con el comando |
| `Read` | `Lectura: ruta` |
| `Task` | `Subagente lanzado: descripción` |

El JSON crudo de `tool_calls` se elimina del contenido limpio. Esto afecta
todo lo que lee intercambios formateados: `EstadoGenerator`, los subagentes de
consulta, los bloques físicos, y el resumen que genera Worker 1 en la
cascada.

## 6. Fases 4-7 — Cascada de workers (en implementación)

### 6.1. Fase 4 — Worker Bun persistente + Worker 1 (resumen)

**Qué se monta**:

1. Un servicio Bun que escucha en el puerto 8090 y lee
   `_pending_blocks.json` periódicamente.
2. Por cada bloque pendiente, lanza **Worker 1**: lee el bloque completo,
   genera un resumen enfocado que cubre:
   - **Tema central** del bloque (1-2 frases).
   - **Decisiones** que se tomaron (lista de bullets).
   - **Temas** que aparecen (lista de keywords).
   - **Actividad** del agente (qué hizo: archivos creados, comandos, etc.).
3. El resumen se escribe al inicio del bloque físico (`bloque_NN.md`), como
   un bloque `## RESUMEN DEL BLOQUE` antes del primer intercambio.
4. El bloque se marca como procesado (se elimina de `_pending_blocks.json`).

**Por qué un Worker 1**: centraliza la lectura del bloque. Si Workers 2-4
tuvieran que leer el bloque completo, multiplicarían el costo por 3. Con
Worker 1 produciendo un resumen de 3-5K, Workers 2-4 leen 1/15 del tamaño.

### 6.2. Fase 5 — Workers 2-4 en paralelo sobre el resumen

**Qué se monta**:

1. Una vez que Worker 1 terminó (y el resumen está escrito), el Worker Bun
   lanza en paralelo:
   - **Worker 2** (nombre legible): lee el resumen y produce un nombre
     legible para el bloque (ej: `autenticacion_jwt_e2e` en vez de
     `bloque_03`).
   - **Worker 3** (decisiones): lee el resumen y extrae decisiones formales
     con alcance (quién decidió, qué, alcance, fecha).
   - **Worker 4** (temas principales): lee el resumen y extrae los temas
     principales con pesos (frecuencia + relevancia).
2. Los 3 workers escriben sus respuestas en `_responses/{block_id}_nombre.txt`,
   `_responses/{block_id}_decisiones.txt`, `_responses/{block_id}_temas.txt`.
3. El pipeline es **asincrónico**: el proceso no bloquea esperando a Workers
   2-4. Cuando el agente llama a `collect_responses()`, el proceso integra
   las que estén listas (igual que v5.0).

**Por qué sobre el resumen y no el bloque**: latencia. Un LLM que lee 3-5K
responde en ~5-8s. Un LLM que lee 70K responde en ~25-40s. Los 3 workers en
paralelo terminan en el tiempo del más lento (~8s), no en la suma.

### 6.3. Fase 6 — Integrador reformado + consulta multi-bloque

**Qué se monta**:

1. **IntegradorRespuestas reformado** (`coordinador/integrador_respuestas.py`):
   - Antes integraba respuestas una por una (cada subagente entregaba una
     respuesta, y se aplicaba secuencialmente).
   - Ahora aplica **las 4 respuestas de un bloque juntas** (resumen + nombre
     + decisiones + temas), porque están correlacionadas (todas describen
     el mismo bloque) y juntas dan el cuadro completo.
   - Si falta alguna de las 4 (Worker caído, timeout), espera un ciclo
     antes de aplicar las que tenga. Si pasan 2 ciclos sin que lleguen
     todas, aplica las disponibles y marca el bloque como incompleto.

2. **Consulta de bloque reformada** (`procesadores/procesador_consulta.py`):
   - Antes, cuando el agente consultaba un tema, el `ProcesadorConsulta` leía
     **un solo bloque** (el primero que aparecía en `tema_a_archivo`).
   - Ahora usa el índice y lee **todos los bloques donde aparece el tema**
     (gracias a `dict[str, list[str]]` de Fase 2).
   - Si el tema está en 3 bloques, lanza 3 consultas (en paralelo si el
     proxy v5.0 está disponible) y consolida las 3 respuestas.

### 6.4. Fase 7 — Tests E2E y medición de latencia

**Qué se monta**:

1. **Tests E2E** que validan el flujo completo de la cascada:
   - Publicar N bloques pendientes.
   - El Worker Bun los procesa (Worker 1 → Workers 2-4).
   - El Integrador aplica las 4 respuestas por bloque.
   - Los archivos de recuperación (`01_indice_recuperacion.md`,
     `02_decisiones_clave.md`, `00_estado_actual.md`) reflejan los
     resultados.

2. **Medición de latencia**:
   - Tiempo total de la cascada vs. flujo v5.0 (subagentes efímeros).
   - Latencia por bloque (Worker 1 + Workers 2-4).
   - Latencia de `collect_responses()` con N bloques pendientes.
   - Documentación de resultados.

## 7. Lo que se conserva de versiones anteriores

Todo lo de v5.0 y anteriores:

- El proceso como **bibliotecario que sirve al agente** (v4.2).
- Las 2 clases principales (`Orchestrator`, `RecoveryCycle`/`IncrementalCycle`)
  y la coordinación por archivos (v4.2).
- Los 4 archivos de recuperación (`00_estado_actual.md`,
  `01_indice_recuperacion.md`, `02_decisiones_clave.md`,
  `03_objetivo_proyecto.md`) (v4.4).
- El índice multi-bloque y el `03_objetivo_proyecto.md` ampliado (v4.5).
- El **proxy de subagentes v5.0** (servicio que llama al LLM directo sin
  pasar por el agente).
- La **separación de plataforma** por interfaces (v5.0).
- Los modos del `IntercambiosClasificadorSubagent` (v4.4).
- El soporte multi-chat con lista de `chats_procesados` en la metadata (v4.4).
- Los 3 sistemas de indexado (temas→bloques, resúmenes, índice legible) (v4.4).
- La lógica de decisión de 4 casos (mismo chat vs otro chat) (v4.4).

## 8. Lo que se añade en v6.0

- **`BlockPacker.pack()` reparte temas grandes**: sin `ValueError`, sin
  `Subdivider` obligatorio (Fase 1).
- **`tema_a_archivo: dict[str, list[str]]`** (multi-bloque, Fase 2).
- **`registrar_tema()` idempotente** (un tema en varios bloques, Fase 2).
- **`query_context()` y `ProcesadorConsulta` manejan multi-bloque** (Fase 2b).
- **4 fixes reaplicados en `EstadoGenerator`** (D1, A1, A2, A3 — Fase 3).
- **`ContentCleaner._parse_tool_calls()`** (formatea `tool_calls` legiblemente,
  Fase 3b).
- **Worker Bun persistente** en puerto 8090 (Fase 4).
- **Worker 1 (resumen)** que lee el bloque completo y escribe resumen al
  inicio del bloque físico (Fase 4).
- **Workers 2-4 en paralelo** sobre el resumen (Fase 5).
- **`IntegradorRespuestas` reformado** que aplica las 4 respuestas juntas
  (Fase 6).
- **Consulta multi-bloque** que lee todos los bloques donde aparece un tema
  (Fase 6).
- **Tests E2E + medición de latencia** (Fase 7).

## 9. Lo que migra / se queda / se elimina

### 9.1. Migra (cambia de sitio o de mecanismo)

| Componente | Antes (v5.0) | Después (v6.0) |
|---|---|---|
| Lectura del bloque por subagentes | Cada subagente lee el bloque completo | Worker 1 lee el bloque, Workers 2-4 leen el resumen |
| Coordinación de subagentes | `_pending_tasks.json` + proxy v5.0 | `_pending_blocks.json` + Worker Bun v6.0 (proxy v5.0 sigue para subagentes genéricos) |
| Resumen del bloque | En `04_resumenes_bloques.md` (archivo aparte) | Al inicio del bloque físico (`## RESUMEN DEL BLOQUE`) + sigue habiendo índice aparte |
| `tema_a_archivo` | `dict[str, str]` (un tema → un archivo) | `dict[str, list[str]]` (un tema → varios archivos) |
| `registrar_tema()` | Estricto (lanza `ValueError` si conflicto) | Idempotente (acumula en lista) |

### 9.2. Se queda (sin cambios)

- Los 4 archivos de recuperación (estructura y formato).
- La lógica de decisión de 4 casos en el `Orchestrator`.
- El soporte multi-chat con `chats_procesados`.
- Los modos del `IntercambiosClasificadorSubagent`.
- El proxy de subagentes v5.0 (sigue para subagentes genéricos, no para la
  cascada de bloques).
- La separación de plataforma por interfaces (PlatformAuth, PlatformChat,
  PlatformLinks, PlatformLLM).
- Los 3 sistemas de indexado (temas→bloques, resúmenes, índice legible).
- El flujo de 3 niveles (N1/N2/N3) para documentos grandes.

### 9.3. Se elimina

- El `ValueError` de `BlockPacker.pack()` cuando un tema supera 70K (Fase 1).
- El `04_resumenes_bloques.md` como archivo separado (los resúmenes viven
  al inicio de cada bloque físico, Fase 4).
- El `ResumenesGenerator` como generador independiente (su lógica se mueve al
  Worker 1 del Worker Bun, Fase 4).
- La unicidad estricta de `registrar_tema()` (Fase 2).

> **Nota**: `04_resumenes_bloques.md` y `ResumenesGenerator` fueron creados
> en v4.4 y eliminados en v4.5 (según historial). Si volvieron a aparecer
> en v5.0, se eliminan de nuevo en v6.0. Si no estaban, esta entrada no
> aplica. La regla en v6.0 es: **el resumen vive al inicio del bloque
> físico**, no en archivo aparte.

## 10. Fixes aplicados durante Fases 1-3 (resumen)

Estos fixes no estaban en la spec v5.0 original. Se aplicaron durante la
implementación de v6.0 para desbloquear las Fases 4-7:

| Fix | Archivo | Detalle |
|---|---|---|
| **F1** — `BlockPacker.pack()` reparte temas grandes | `processing/block_packer.py` | Antes: `ValueError` si un tema >70K. Ahora: reparte en varios bloques por intercambios completos. |
| **F2a** — `tema_a_archivo: dict[str, list[str]]` | `models.py` | Antes: `dict[str, str]`. Ahora: lista de archivos por tema. |
| **F2b** — `registrar_tema()` idempotente | `models.py` | Antes: `ValueError` si tema en otro archivo. Ahora: añade a la lista si no estaba. |
| **F2c** — `query_context()` multi-bloque | `pipeline.py` | Lee todos los bloques donde aparece el tema (no solo el último). |
| **F2d** — `ProcesadorConsulta` multi-bloque | `procesadores/procesador_consulta.py` | Igual que `query_context()`. |
| **F3a** — D1 filtra "Lee este link:" | `generation/estado_generator.py` | Usa último exchange real del Director, no virtual. |
| **F3b** — A1 filtra virtuales + último exchange real | `generation/estado_generator.py` | Tema activo basado en intercambios reales. |
| **F3c** — A2 filtra JSON de `tool_calls` | `generation/estado_generator.py` | No detecta rutas dentro de JSON de `tool_calls`. |
| **F3d** — A3 filtra virtuales y `tool_calls` | `generation/estado_generator.py` | No detecta "error" dentro de JSON de `tool_calls`. |
| **F3e** — `ContentCleaner._parse_tool_calls()` | `processing/content_cleaner.py` | Parsea `tool_calls` y los formatea como bloques legibles (Write, Edit, Bash, Read, Task). Elimina JSON crudo. |

## 11. Reglas de implementación

- **Cambios quirúrgicos**: solo se modifica lo especificado. No se toca el
  código que ya funciona.
- **Scripts atómicos y standalone**: cada archivo intervenido lleva auto-tests
  en `__main__`.
- **OOP**: las nuevas funcionalidades son responsabilidad de las clases
  existentes (`BlockPacker`, `RecoveryMetadata`, `EstadoGenerator`,
  `ContentCleaner`, `IntegradorRespuestas`, `ProcesadorConsulta`).
- **Servicio persistente**: el Worker Bun es un servicio del sandbox, no un
  script efímero. Vive mientras el sandbox esté activo.
- **No hardcoding**: todas las constantes nuevas (puerto del Worker Bun,
  umbrales, timeouts) van en `config.py`.
- **Tests individuales**: cada módulo intervenido actualiza sus auto-tests.
- **Tests E2E**: `tests/test_v42_e2e.py` se amplía con tests que validan la
  cascada completa y la consulta multi-bloque.
- **Comunicación de errores**: ningún Worker falla silenciosamente. Si un
  Worker cae, el Integrador lo detecta y aplica las respuestas disponibles.
- **Lo que funciona se conserva**: el proxy v5.0 sigue para subagentes
  genéricos; no se rompe el flujo existente.

## 12. Compatibilidad con v5.0

- Todos los archivos existentes se conservan.
- Las funciones públicas (`run`, `status`, `export_context`, `import_context`,
  `index_document`, `index_document_large`, `query_context`,
  `ampliar_contexto`, `collect_responses`) mantienen su signature.
- Si el Worker Bun no está corriendo (puerto 8090 no responde), el proceso
  funciona como hoy (subagentes efímeros vía el proxy v5.0 o el Task tool).
- Si el `_metadata.json` tiene el formato viejo (`tema_a_archivo:
  dict[str, str]`), se migra automáticamente al formato nuevo (`dict[str,
  list[str]]`) la primera vez que se lee.
- Los tests existentes siguen pasando. Los que prueban comportamiento que
  cambia (unicidad estricta, `ValueError` de `BlockPacker`) se actualizan.

## 13. Dependencias nuevas

- **Bun runtime**: ya está instalado en el sandbox (lo usa el proxy v5.0).
- **`httpx`**: ya está instalado (lo usan los clientes HTTP de v5.0).
- No se añaden dependencias nuevas.

## 14. Validación

- **Fase 1**: auto-test que procesa un tema individual >70K y verifica que
  se reparte en varios bloques (sin `ValueError`).
- **Fase 2**: auto-test que registra un tema en varios bloques y verifica
  que `tema_a_archivo[tema]` es una lista con todos ellos.
- **Fase 2b**: auto-test que consulta un tema que está en 3 bloques y
  verifica que `query_context()` lee los 3.
- **Fase 3**: auto-tests por cada fix reaplicado (D1, A1, A2, A3) + auto-test
  de `_parse_tool_calls()` con los 5 tipos de `tool_call`.
- **Fase 4**: auto-test que publica un bloque pendiente, el Worker Bun lo
  procesa, y el bloque físico termina con el `## RESUMEN DEL BLOQUE` al
  inicio.
- **Fase 5**: auto-test que publica un bloque, el Worker Bun lanza Workers
  2-4 en paralelo, y los 3 escriben sus respuestas en `_responses/`.
- **Fase 6**: auto-test que el `IntegradorRespuestas` aplica las 4
  respuestas de un bloque juntas, y que `ProcesadorConsulta` lee varios
  bloques para un mismo tema.
- **Fase 7**: test E2E con la cascada completa + medición de latencia
  documentada.

---

**Fin de la spec v6.0.**
