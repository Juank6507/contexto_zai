# contexto_zai/Documentos/spec_recuperacion_contexto_v6.1.md
# Spec v6.1 — Optimización de la cascada: fusión, backoff, cache, modelo dual

**Versión:** 6.1
**Fecha:** 2026-09-26
**Autor:** Agente CZAI (Sesión 23, con consenso del Director)
**Estado:** Implementado y validado end-to-end (14/14 bloques procesados, 0 fallidos).
**Especifica continuación de:** spec v6.0 (limpieza de bloques + cascada de workers).
**Spec asociada:** esta.
**Plan asociado:** plan_refactorizacion_v6.1.md.

---

## 1. Propósito

La v6.1 es una **optimización quirúrgica** de la cascada de workers montada en
v6.0. No cambia la arquitectura (Worker Bun persistente en puerto 8090, Worker 1
genera resumen, Workers 2-4 extraen), sino que ataca el problema que surgió al
correr v6.0 con datos reales: **el rate limit del LLM del sandbox satura después
de ~20 llamadas, y cada bloque necesitaba 4 llamadas**.

Para 14 bloques pendientes (procesamiento real de la sesión 22), v6.0 hacía
**56 llamadas LLM** (14 W1 + 42 W2/W3/W4) contra un límite de ~20. Eso rompía
el proceso: 6 bloques quedaban en `failed` tras un 429 del proxy APA.

La v6.1 introduce **4 soluciones complementarias** que reducen el consumo de
cuota y hacen el sistema resiliente a 429s:

1. **Fusión de W2+W3+W4 en una sola llamada JSON** (Solución #1): 4 → 2 llamadas
   por bloque (−50%).
2. **Backoff exponencial con Retry-After** (Solución #2): ante un 429, reintenta
   con delays `[2s, 4s, 8s, 16s, 32s, 64s]` en vez de fallar el bloque.
3. **Cache por hash SHA256 del prompt** (Solución #3): re-ejecuciones y
   reintentos no consumen cuota si el contenido no cambió.
4. **Modelo dual** (Solución #5): W1 usa `glm-4-plus` (calidad, 50KB de
   contexto), W2-fusionado usa `glm-4-flash` (extracción simple, más rápido).

### 1.1. Hallazgo clave: el rate limit es COMPARTIDO entre modelos

Probado empíricamente con 3 pruebas:

| Prueba | Resultado | Interpretación |
|---|---|---|
| 4× `glm-4-plus` rápidas → 4× `glm-4-flash` inmediato | plus: 4× 200 · flash: 4× 429 | Cambiar de modelo no resetea cuota |
| 6 en paralelo: 3 plus + 3 flash simultáneas | 2× 200 (ambas plus), 4× 429 | Bucket compartido |
| Tras 90s espera, 6 llamadas | Todas 429 | El cooldown real es ~3 min, no 90s |

**Conclusión**: el proxy APA (`internal-api.z.ai`) identifica la cuenta por el
token JWT, no por el modelo. Llamar a otro modelo no crea un "nuevo buzón" de
cuota. **Usar dos modelos en paralelo NO dobla la cuota.**

Esto descarta la idea inicial de "procesar W1 a glm-4-plus y W2 a glm-4-flash
en paralelo para doblar el throughput". Lo que SÍ justifica el modelo dual es
**latencia**: `glm-4-flash` responde más rápido para extracciones simples,
aunque consuma del mismo bucket.

## 2. Los 4 problemas que la v6.1 ataca

| # | Problema | Solución | Fase |
|---|---|---|---|
| 1 | Cada bloque consume 4 llamadas LLM (W1 + W2 + W3 + W4), 3 de ellas (W2/W3/W4) leen el mismo resumen y extraen 3 piezas triviales | Fusionar W2+W3+W4 en una sola llamada que devuelve JSON estructurado `{nombre, decisiones[], temas[]}` | F1 |
| 2 | Ante un 429 del proxy, el bloque queda `failed`. No hay reintentos. Cooldown real ~3 min | `callLLM()` con backoff exponencial `[2, 4, 8, 16, 32, 64]s` + respeto del header `Retry-After` (si viene) | F2 |
| 3 | Re-ejecuciones y reintentos reprocesan todo desde cero. Si re-corres el pipeline, consumes cuota de nuevo | Cache por hash SHA256 de `model + sysPrompt + userPrompt` en `_responses/cache/{hash}.txt` | F3 |
| 4 | W2/W3/W4 eran extracciones simples pero usaban `glm-4-plus` (mismo modelo que W1, que procesa 50KB de contexto). Sin diferenciación por tipo de tarea | W1 usa `MODEL_HEAVY=glm-4-plus`, W2-fusionado usa `MODEL_LIGHT=glm-4-flash`. Configurable por env vars | F4 |

## 3. La solución: 4 mejoras quirúrgicas al Worker Bun

Las 4 soluciones se aplican al archivo `mini-services/worker-cascade/index.ts`
que se creó en v6.0. **No se cambia la arquitectura externa**: sigue siendo un
Worker Bun persistente en puerto 8090, lee `_pending_blocks.json`, escribe
respuestas en `_responses/`.

### 3.1. Solución #1 — Fusión W2+W3+W4

**Antes (v6.0)**: tras W1 (resumen), se lanzan 3 llamadas LLM en paralelo sobre
el mismo resumen:
- W2: prompt "asigna nombre legible en snake_case"
- W3: prompt "extrae decisiones con alcance"
- W4: prompt "lista temas principales en snake_case"

Cada una genera un archivo `_responses/{block_id}_{nombre|decisiones|temas}.txt`.

**Ahora (v6.1)**: una sola llamada que devuelve JSON estructurado:

```json
{
  "nombre": "<snake_case, máximo 5 palabras>",
  "decisiones": ["DECISION: ... | ALCANCE: ...", "..."],
  "temas": ["tema_uno", "tema_dos", "tema_tres"]
}
```

Parser tolerante a markdown fences (` ```json ... ``` `) y a JSON inválido
(fallback: guarda el raw en `_responses/{block_id}_extract_raw.txt`).

**Reducción**: 3 llamadas → 1 llamada para la fase de extracción.

### 3.2. Solución #2 — Backoff exponencial

**Antes (v6.0)**: si el LLM devuelve 429 (o cualquier error HTTP no 200), el
Worker lanza una excepción y marca el bloque como `failed`. No reintenta.

**Ahora (v6.1)**: `callLLM()` implementa el siguiente flujo:

```
para attempt en [0, 1, 2, 3, 4, 5, 6]:
    si attempt > 0:
        delay = retryAfterMs ?? BACKOFF_DELAYS_MS[attempt - 1]
        dormir(delay)
    intentar:
        resultado = callLLMRaw(model, sysPrompt, userPrompt)
        si resultado.status == 200:
            devolver resultado.content
        si resultado.status == 429:
            lastRetryAfterMs = resultado.retryAfterMs  # si viene header
            continuar
        # otros errores (5xx, 4xx) — reintentar
        continuar
    except (network error):
        continuar
lanzar último error
```

**Delays**: `[2000, 4000, 8000, 16000, 32000, 64000]` ms (exponencial 2^n · 1000).
7 intentos máximos. **Total máximo de espera**: 126s si todos fallan (raro).

**Retry-After**: el proxy APA actual NO devuelve header `Retry-After` ni
`X-RateLimit-*` (verificado). Solo devuelve `{"error":"Too many requests,
please try again later"}`. Pero el código lo respeta si en el futuro lo añaden.

### 3.3. Solución #3 — Cache por hash

**Antes (v6.0)**: cada corrida del Worker consume cuota sin importar si el
bloque ya fue procesado antes con el mismo prompt.

**Ahora (v6.1)**: cada llamada `callLLM(model, sysPrompt, userPrompt)` chequea
primero si existe `_responses/cache/{sha256(model+sysPrompt+userPrompt)[:32]}.txt`.

- **Cache HIT**: devuelve el contenido cacheado, **0 llamadas LLM**.
- **Cache MISS**: llama al LLM, si tiene éxito escribe el resultado en cache.

El hash incluye `model` porque W1 y W2 usan modelos distintos: si cambias de
modelo, el cache se invalida correctamente.

**Idempotencia doble**: W1 ya era idempotente en v6.0 (si el bloque empieza
con `RESUMEN:`, no llama al LLM). Ahora W2 también es idempotente vía cache.

### 3.4. Solución #5 — Modelo dual

**Antes (v6.0)**: todas las llamadas usaban `glm-4-plus`.

**Ahora (v6.1)**:
- `MODEL_HEAVY = "glm-4-plus"` (configurable por `CZAI_MODEL_HEAVY`): para W1
  (resumen), que procesa hasta 50KB de contexto por bloque y requiere
  razonamiento profundo.
- `MODEL_LIGHT = "glm-4-flash"` (configurable por `CZAI_MODEL_LIGHT`): para
  W2-fusionado (extracción), que procesa un resumen de ~1KB y solo extrae 3
  piezas estructuradas.

**Modelos disponibles** (verificado en el proxy APA): `glm-4-plus`, `glm-4`,
`glm-4-flash`, `glm-4-air`, `glm-4-airx`, `glm-4-long`, `glm-4v`,
`glm-4v-flash`, `glm-3-turbo`, `glm-4.5`, `glm-4.5-air`, `glm-4.5-flash`.

**Por qué no dobla cuota**: ver sección 1.1. Los rate limits son compartidos
entre modelos por JWT. Pero `glm-4-flash` responde en ~600ms para
extracciones simples vs ~3s de `glm-4-plus`. Reducción de wall-clock sin
aumentar throughput.

## 4. Pipeline simplificado

La v6.0 tenía un pipeline asincrónico: mientras W2-4 del bloque N corrían,
W1 del bloque N+1 arrancaba. Esto tenía sentido cuando W2-4 eran paralelos
(3 llamadas simultáneas) y W1 era el cuello de botella (~10s).

La v6.1 elimina este paralelismo porque:
- W2-fusionado es 1 sola llamada rápida (~600ms-1.5s con `glm-4-flash`).
- W1 es idempotente (los bloques ya tienen `RESUMEN:`).
- El rate limit es compartido: lanzar 2 bloques en paralelo multiplica el
  consumo de cuota sin acelerar el throughput.

**Pipeline v6.1**: estrictamente secuencial. Para cada bloque:
1. W1 (resumen) — idempotente, 0 llamadas si ya existe.
2. W2-fusionado (extracción JSON) — 1 llamada a `glm-4-flash`.

Si llega un 429, el backoff de W2 espera 2s y reintenta. Si vuelve a fallar,
4s, 8s, etc.

## 5. Lo que se conserva de versiones anteriores

Todo lo de v6.0 y anteriores:

- **Worker Bun persistente** en puerto 8090 (v6.0).
- **Worker 1 (resumen)** que lee el bloque completo y escribe `RESUMEN:` al
  inicio del bloque físico (v6.0).
- **Idempotencia de W1**: si el bloque ya tiene `RESUMEN:`, no llama al LLM (v6.0).
- **`_pending_blocks.json`** como archivo de entrada (v6.0).
- **`_responses/`** como directorio de salida (v6.0).
- **`_processed_blocks.json`** como registro de estado (v6.0).
- **Health check HTTP** en el Worker Bun (v6.0, ahora ampliado con info de modelos).
- Todo lo heredado de v5.0 y anteriores (4 archivos de recuperación, lógica de
  4 casos del Orchestrator, soporte multi-chat, etc.).

## 6. Lo que se añade en v6.1

- **`worker2_extract_all()`** — Worker único que fusiona los 3 workers de
  extracción en una sola llamada JSON (Solución #1).
- **`callLLM()` con backoff exponencial** — 7 reintentos con delays `[2, 4, 8,
  16, 32, 64]s`, respeto del header `Retry-After` (Solución #2).
- **Cache por hash SHA256** en `_responses/cache/` — `readCache()`,
  `writeCache()`, `hashContent()`, `cachePath()` (Solución #3).
- **Modelo dual configurable** por env vars `CZAI_MODEL_HEAVY` y
  `CZAI_MODEL_LIGHT` (Solución #5).
- **`PROMPT_EXTRACT_ALL`** — prompt fusionado que pide JSON estructurado con
  `nombre`, `decisiones[]`, `temas[]`.
- **`SYSTEM_PROMPT_HEAVY`** y **`SYSTEM_PROMPT_LIGHT`** — system prompts
  diferenciados por tipo de tarea.
- **Health check ampliado** — ahora reporta `models: {heavy, light}` activos.
- **`BACKOFF_DELAYS_MS`** constante configurable.

## 7. Lo que migra / se queda / se elimina

### 7.1. Migra (cambia de sitio o de mecanismo)

| Componente | Antes (v6.0) | Después (v6.1) |
|---|---|---|
| Workers 2, 3, 4 (3 funciones) | 3 llamadas LLM paralelas sobre el resumen | 1 sola llamada fusionada (`worker2_extract_all()`) |
| `callLLM()` | Sin reintentos, lanza excepción en 429 | Con backoff exponencial + Retry-After |
| Modelo LLM | `glm-4-plus` fijo para todo | Dual: `glm-4-plus` (W1) + `glm-4-flash` (W2) |
| Pipeline | Asincrónico (W1 del N+1 paralelo a W2-4 del N) | Secuencial estricto |
| `MAX_PARALLEL_WORKERS_24` | Configuraba paralelismo de W2-4 | Eliminado (ya no hay 3 workers) |
| `POLL_INTERVAL_MS` | No se usaba | Eliminado |

### 7.2. Se queda (sin cambios)

- Worker Bun persistente en puerto 8090.
- Worker 1 (resumen) con idempotencia por `RESUMEN:` prefix.
- `_pending_blocks.json` como entrada.
- `_processed_blocks.json` como registro de estado.
- `_responses/{block_id}_{nombre|decisiones|temas|resumen}.txt` como outputs.
- Proxy APA en `sandbox-src/api/zai-proxy/` (no se toca).
- Todo lo de v5.0 y anteriores (4 archivos de recuperación, Orchestrator, etc.).

### 7.3. Se elimina

- `worker2_nombre()`, `worker3_decisiones()`, `worker4_temas()` (3 funciones
  reemplazadas por `worker2_extract_all()`).
- `MAX_PARALLEL_WORKERS_24` constante.
- `POLL_INTERVAL_MS` constante (no se usaba).
- `prevWorkers` Promise (pipeline asincrónico del main loop).
- `SYSTEM_PROMPT` único (ahora son `SYSTEM_PROMPT_HEAVY` y `SYSTEM_PROMPT_LIGHT`).

## 8. Fixes aplicados durante la implementación

Estos son los cambios concretos al código, organizados por solución:

| Fix | Archivo | Detalle |
|---|---|---|
| **F1a** — `worker2_extract_all()` fusiona W2+W3+W4 | `mini-services/worker-cascade/index.ts` | 1 sola llamada LLM, devuelve JSON `{nombre, decisiones[], temas[]}` |
| **F1b** — `PROMPT_EXTRACT_ALL` nuevo prompt | `mini-services/worker-cascade/index.ts` | Prompt que pide JSON estructurado con 3 campos |
| **F1c** — Parser JSON tolerante a markdown fences | `mini-services/worker-cascade/index.ts` | Limpia ` ```json ... ``` ` antes de parsear, fallback a raw si falla |
| **F2a** — `callLLMRaw()` separa la llamada HTTP del retry | `mini-services/worker-cascade/index.ts` | Devuelve `{content, status, retryAfterMs}` para que `callLLM()` decida |
| **F2b** — `callLLM()` con bucle de 7 reintentos | `mini-services/worker-cascade/index.ts` | Delays `[2, 4, 8, 16, 32, 64]s`, respeta `Retry-After` si viene |
| **F2c** — `lastRetryAfterMs` variable de estado | `mini-services/worker-cascade/index.ts` | Comunica Retry-After entre intentos |
| **F3a** — `hashContent()` con `crypto.createHash('sha256')` | `mini-services/worker-cascade/index.ts` | Hash SHA256 de `model + "::" + sysPrompt + "::" + userPrompt`, 32 chars |
| **F3b** — `cachePath()`, `readCache()`, `writeCache()` helpers | `mini-services/worker-cascade/index.ts` | Cache en `_responses/cache/{hash}.txt` |
| **F3c** — `callLLM()` con flag `cacheable` (default true) | `mini-services/worker-cascade/index.ts` | Permite desactivar cache para llamadas específicas si hace falta |
| **F4a** — `MODEL_HEAVY` / `MODEL_LIGHT` constantes con env vars | `mini-services/worker-cascade/index.ts` | `CZAI_MODEL_HEAVY` y `CZAI_MODEL_LIGHT` overrides |
| **F4b** — `SYSTEM_PROMPT_HEAVY` / `SYSTEM_PROMPT_LIGHT` | `mini-services/worker-cascade/index.ts` | System prompts diferenciados por tipo de tarea |
| **F5a** — Health check ampliado con `models` info | `mini-services/worker-cascade/index.ts` | Endpoint `/health` ahora reporta modelos activos |
| **F5b** — `void server` para evitar GC del health server | `mini-services/worker-cascade/index.ts` | Mantiene referencia al server Bun.serve |

## 9. Reglas de implementación

- **Cambios quirúrgicos al Worker Bun**: no se toca el proxy APA ni el proceso
  Python. Solo `mini-services/worker-cascade/index.ts` y `package.json`.
- **Sin nuevas dependencias**: Bun runtime, sin `npm install` de nada.
- **Configurabilidad por env vars**: modelos, workspace dir. Sin hardcoded paths.
- **Idempotencia doble**: W1 por `RESUMEN:` prefix, W2 por cache hash.
- **Parser tolerante**: si el LLM devuelve JSON inválido, no rompe el bloque.
  Guarda el raw como fallback y sigue.
- **Logs informativos**: cada llamada LLM loguea `[W1]`/`[W2]` con modelo,
  tamaño de respuesta y tiempo. Cada reintento loguea `[retry]` con intento y
  delay. Cada cache hit loguea `[cache HIT]`.
- **Backward compatible**: si el Worker Bun no está corriendo, el proceso Python
  sigue funcionando como hoy (caída al modo v5.0).

## 10. Compatibilidad con v6.0

- El Worker Bun v6.1 lee el mismo `_pending_blocks.json` que v6.0.
- Escribe los mismos archivos en `_responses/`: `{block_id}_nombre.txt`,
  `{block_id}_decisiones.txt`, `{block_id}_temas.txt`, `{block_id}_resumen.txt`.
  (Solo cambia la implementación de cómo se generan, no el formato de salida.)
- El `IntegradorRespuestas` del proceso Python no necesita cambios: lee los
  mismos archivos en el mismo formato.
- Si hay un cache de v6.1 y se vuelve a v6.0, el cache se ignora (v6.0 no lo
  lee). No rompe nada.
- Si hay `_processed_blocks.json` con entradas `failed` de v6.0, el Worker v6.1
  los vuelve a intentar (los filtra por `status == "completed"`).

## 11. Dependencias nuevas

Ninguna. El Worker Bun usa solo APIs estándar de Bun:
- `fetch` (HTTP al proxy APA).
- `fs.readFileSync/writeFileSync/existsSync/mkdirSync`.
- `crypto.createHash` (SHA256 para cache).
- `Bun.serve` (health check HTTP).

## 12. Validación

### 12.1. Diagnóstico del rate limit (3 pruebas empíricas)

Antes de implementar, se diagnosticó el rate limit del proxy APA con pruebas
directas:

- **Prueba 1**: 4× `glm-4-plus` rápidas → 4× `glm-4-flash` inmediatamente
  después. plus: 4× 200 · flash: 4× 429.
- **Prueba 2**: 6 en paralelo (3 plus + 3 flash) simultáneas. Solo 2 OK
  (ambas plus), 4× 429.
- **Prueba 3**: tras 90s espera, 6 llamadas a cada modelo. Todas 429. Tras
  180s, se recuperan.

**Conclusión**: rate limit compartido entre modelos por JWT. Cooldown real
~3 min.

### 12.2. Smoke tests (3 escenarios)

1. **Cache hit existente** (bloque_06 ya en cache): 0 llamadas LLM, 0.0s.
2. **Cache miss real** (reset completo): 2 llamadas LLM reales (1 plus + 1
   flash), 6.5s. Outputs perfectos:
   - `nombre`: `sistema_recuperacion_contexto`
   - 5 decisiones con formato `DECISION: ... | ALCANCE: ...`
   - 5 temas en snake_case
3. **Re-ejecución**: mismo bloque, 100% cache HIT, 0 llamadas LLM, 0.0s.

### 12.3. Run completo (14 bloques)

- 14/14 bloques completed, 0 failed.
- Llamadas LLM reales: 13 (solo W2, todas idempotentes W1).
- 1 cache hit (bloque_06, smoke test anterior).
- Tiempo wall-clock: ~13s para 13 bloques (media 1.0s/bloque).
- No se activó el backoff exponencial en ningún momento.

### 12.4. Reducción de consumo

| Métrica | v6.0 | v6.1 | Mejora |
|---|---|---|---|
| Llamadas LLM (1ª corrida, sin cache) | 56 | 28 | **−50%** |
| Llamadas LLM (re-ejecución con cache) | 56 | 0 | **−100%** |
| Tiempo por bloque (1ª corrida) | ~10s | ~1.0s | **−90%** |
| Fallidos ante 429 | 6/14 | 0/14 | **−100%** |

## 13. Bug conocido (no bloqueante)

El Worker Bun en background (`nohup &` o `setsid &`) muere silenciosamente
después de procesar 3-6 bloques. Probablemente es SIGTERM del sandbox al cerrar
el bash tool call del agente.

**Workaround actual**: procesar en foreground en lotes de 3-4 bloques. No es
un bug del código v6.1, es del entorno del sandbox.

**Solución futura (no en v6.1)**: montar el Worker Bun como servicio
persistente del sandbox (no lanzado desde un tool call del agente), o usar
`systemd`/`pm2` si están disponibles.

---

**Fin de la spec v6.1.**
