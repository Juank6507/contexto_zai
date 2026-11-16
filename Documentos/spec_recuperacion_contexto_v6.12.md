# contexto_zai/Documentos/spec_recuperacion_contexto_v6.12.md
# Spec v6.12 — ProgressMonitor + arnés 3 niveles + contabilidad por estado físico

**Versión:** 6.12
**Fecha:** 2026-11-02
**Estado:** Implementada (commit `1f1ba8c`).
**Especifica continuación de:** spec v6.11.

---

## 1. Propósito

La v6.11 dejó tres problemas detectados tras el run del 2026-10-30 sobre el chat EP (informe `informe_agente_CZAI_run_v6.11_worker_bun_proxy_apa.md`):

1. **Timeout fijo `timeout=5` mataba al Worker Bun.** El `timeout=5` fue introducido por el agente en v6.10 sin autorización del Director (violación de NH8). El Worker Bun no procesaba ni un bloque en 5 segundos.
2. **Falso positivo de contabilidad.** El run cerró con "76 de 76 resueltas" cuando 75 bloques seguían sin RESUMEN. La contabilidad se basaba en la cola `_pending_tasks.json` (que no existía en el workspace de ejecución), no en el estado físico de los bloques.
3. **Falta de nivel intermedio entre Worker Bun y subagentes.** Cuando el Worker Bun cae, el arnés va directo a subagentes (Task tool costoso). No hay un nivel intermedio que use el proxy APA directamente desde el proceso Python.

Esta spec resuelve los tres problemas con `ProgressMonitor` (monitoreo de progreso en vez de timeout fijo), un arnés de 3 niveles (Worker Bun → proxy APA directo → subagentes), y verificación de bloque completo por estado físico (RESUMEN + 3 archivos).

---

## 2. Principio rector: monitoreo de progreso + no timeout fijo + no falso positivo

**Lo que ya funciona NO se toca:**
- Bloques con contenido literal hasta 70K ✅
- RESUMEN al inicio de cada bloque ✅
- Worker Bun como camino prioritario de enriquecimiento ✅
- Arnés Worker Bun/subagentes de v6.10 ✅
- Carga automática del JWT ✅
- Separación de capas + MessageExtractor + paginación de v6.11 ✅

**Nuevos principios:**
- **No timeout fijo:** el Worker Bun tiene backoff exponencial interno (2, 4, 8, 16, 32, 64s). Un timeout fijo lo mata. Se reemplaza por `ProgressMonitor` que cuenta bloques completos en intervalos.
- **No falso positivo:** la contabilidad se basa en el estado físico del bloque (RESUMEN + 3 archivos), no en la cola `_pending_tasks.json`.
- **Nivel intermedio:** entre Worker Bun y subagentes, el proceso Python puede llamar al proxy APA directamente (`_enriquecer_con_proxy_apa()`), sin necesidad de lanzar subagentes para cada bloque.

---

## 3. Los tres problemas a resolver

### Problema 1 — Timeout fijo `timeout=5` mata al Worker Bun

**Qué pasa hoy:** `_arrancar_worker_y_esperar()` usa `timeout=5` (introducido en v6.10 sin autorización). El Worker Bun hace backoff exponencial (2-64s) y necesita más de 5s para procesar incluso un bloque.

**Impacto:** el Worker Bun nunca completa. El arnés declara "caído" y pasa a subagentes, incluso cuando el Worker Bun estaba trabajando legítimamente.

**Causa raíz:** `timeout=5` es un valor arbitrario que no respeta el backoff del Worker Bun. Fue introducido sin autorización del Director (violación NH8).

### Problema 2 — Falso positivo de contabilidad

**Qué pasa hoy:** la contabilidad de bloques completos se basa en `_processed_blocks.json` (cola). Si la cola no existe o está vacía, el proceso asume "0 pendientes = todo resuelto".

**Impacto:** el run del 2026-10-30 cerró con "76 de 76 resueltas" cuando 75 bloques seguían sin RESUMEN. El agente no recibió las pending_tasks correctas.

**Causa raíz:** `_processed_blocks.json` puede marcar "completed" sin verificar que el bloque físicamente tenga RESUMEN + 3 archivos. La cola y el estado físico divergen.

### Problema 3 — Falta de nivel intermedio

**Qué pasa hoy:** cuando el Worker Bun cae, el arnés va directo a subagentes (Task tool). Cada subagente cuesta contexto y cuota del agente.

**Impacto:** con 76 bloques pendientes, el coste de lanzar 76 subagentes es prohibitivo.

**Causa raíz:** no existe un nivel intermedio que use el proxy APA directamente desde el proceso Python. El proxy APA es local (puerto 3000), no requiere credenciales, y acepta el formato OpenAI-compatible.

---

## 4. Soluciones

### F1 — `ProgressMonitor` (clase OOP) (Problema 1)

**Qué se hace:**
1. Crear clase `ProgressMonitor` (separada del arnés, OOP) con 3 métodos estáticos:
   - `contar_bloques_completos(workspace_dir)`: cuenta bloques con RESUMEN + 3 archivos `_responses/`.
   - `contar_bloques_totales(workspace_dir)`: cuenta `bloque_*.md` en el workspace.
   - `esperar_y_verificar(workspace_dir, intervalo_inicial=20, max_intervalos=10, crecimiento=1.5)`: espera al Worker Bun monitoreando progreso en intervalos progresivos.
2. Reemplazar `timeout=5` por `ProgressMonitor.esperar_y_verificar()`.
3. El Worker Bun arranca en background (no bloqueante) con `subprocess.Popen`.
4. `ProgressMonitor` comprueba cada intervalo si hay progreso (más bloques completos que antes). Si no progresa en 2 intervalos seguidos, declara caído.

**Lo que NO se toca:**
- El Worker Bun (código TypeScript, backoff, prompts).
- La idempotencia (Worker Bun y subagentes verifican RESUMEN antes de procesar).

### F2 — `_arrancar_worker_y_esperar()` con `subprocess.Popen` + `ProgressMonitor` (Problema 1)

**Qué se hace:**
1. `_arrancar_worker_y_esperar()` usa `subprocess.Popen` (no bloqueante) para lanzar el Worker Bun.
2. `ProgressMonitor.esperar_y_verificar()` monitorea el progreso.
3. Si el Worker Bun completa todos los bloques, retorna `True`.
4. Si no progresa en 2 intervalos seguidos, retorna `False` (declarado caído).

**Lo que NO se toca:**
- El comando de arranque del Worker Bun (sigue siendo el mismo).
- La detección de Worker Bun existente por puerto 8090 (v6.8.2 F2).

### F3 — `_enriquecer_con_proxy_apa()` (nivel 2 del arnés) (Problema 3)

**Qué se hace:**
1. Crear método estático `_enriquecer_con_proxy_apa(bloque, workspace_dir)` en `EnriquecimientoOrquestador`.
2. Lee el bloque físico del workspace.
3. Si el bloque es demasiado corto (<100 chars), retorna `False` (warning, no error).
4. Trunca si es muy grande (>50000 chars).
5. Llama al proxy APA con el prompt W1 (resumen rígido: 600-900 chars, 4 oraciones).
6. Escribe el RESUMEN al inicio del bloque con prefijo `RESUMEN:`.
7. Llama al proxy APA con el prompt W2 (extracción JSON: nombre, decisiones, temas).
8. Escribe los 3 archivos en `_responses/`: `{block_id}_nombre.txt`, `{block_id}_decisiones.txt`, `{block_id}_temas.txt`.
9. Caché por hash SHA256 del prompt en `_responses/cache/`.
10. Retorna `True` si el bloque se completó, `False` si falló.

**Lo que NO se toca:**
- El proxy APA en sí (vive en el sandbox, puerto 3000, ruta `/api/zai-proxy/v1/chat/completions`).
- Los prompts W1 y W2 (siguen siendo los mismos del Worker Bun).
- El protocolo de ficheros (`_responses/`, caché, prefijo RESUMEN).

### F4 — `_enriquecer_bloques_con_fallback()` con 3 niveles integrados (Problema 3)

**Qué se hace:**
1. `_enriquecer_bloques_con_fallback()` integra los 3 niveles:
   - **NIVEL 1:** Worker Bun con `ProgressMonitor` (timeout progresivo). Si completa todos los bloques, retorna `[]` (sin pending_tasks).
   - **NIVEL 2:** si el Worker Bun deja bloques sin completar, `_enriquecer_con_proxy_apa()` los procesa uno a uno. Si completa todos, retorna `[]`.
   - **NIVEL 3:** si el nivel 2 deja bloques, se construyen `pending_tasks` para el agente (Task tool).
2. Regla de oro: worker, proxy y subagentes nunca procesan la misma tarea a la vez. La idempotencia (caché + verificación de RESUMEN) resuelve carreras.

**Lo que NO se toca:**
- La lógica de construcción de `pending_tasks` para subagentes (sigue siendo la misma).
- Los prompts de los subagentes.

### F5 — Contabilidad por estado físico (Problema 2)

**Qué se hace:**
1. `_bloque_esta_completo(bloque, workspace_dir)` verifica:
   - RESUMEN al inicio del `bloque_NN.md`.
   - `_responses/bloque_NN_nombre.txt` existe.
   - `_responses/bloque_NN_decisiones.txt` existe.
   - `_responses/bloque_NN_temas.txt` existe.
2. La contabilidad de pending_tasks se basa en `_bloque_esta_completo()`, no en `_processed_blocks.json`.
3. Si un bloque no está completo, va a `pending_tasks` sin importar lo que diga la cola.

**Lo que NO se toca:**
- `_processed_blocks.json` (sigue existiendo como registro, pero no es fuente de verdad para la contabilidad).
- `_pending_tasks.json` (sigue existiendo como cola de tareas para el agente).

### F6 — Constantes `PROGRESS_*` en `config.py` (Problema 1)

**Qué se hace:**
1. Añadir 4 constantes en `config.py`:
   - `PROGRESS_INTERVAL_INITIAL = 20` (segundos del primer intervalo).
   - `PROGRESS_MAX_INTERVALS = 10` (máximo de comprobaciones).
   - `PROGRESS_GROWTH = 1.5` (factor de crecimiento del intervalo).
   - `PROGRESS_MAX_NO_PROGRESS = 2` (intervalos sin progreso antes de declarar caída).
2. `ProgressMonitor.esperar_y_verificar()` usa estas constantes con valores por defecto.

**Lo que NO se toca:**
- `WORKER_BUN_TIMEOUT = 120` (sigue existiendo como límite máximo, pero `ProgressMonitor` decide antes).

### F7 — Tests actualizados

**Qué se hace:**
1. Actualizar `test_v62_worker_falla_parcialmente` y `test_v62_worker_timeout` para mockear `_enriquecer_con_proxy_apa` (nivel 2) además del Worker Bun (nivel 1).
2. Los mocks de bloques completos ahora escriben `_nombre.txt`, `_decisiones.txt`, `_temas.txt` (3 archivos, no solo RESUMEN).
3. Los patches van a `EnriquecimientoOrquestador._arrancar_worker_y_esperar` y `EnriquecimientoOrquestador._enriquecer_con_proxy_apa`.
4. Tests E2E: 30/30 deben pasar.

**Lo que NO se toca:**
- Tests que no se ven afectados por los cambios.

### F8 — Validación con datos reales

**Qué se hace:**
1. Ejecutar el pipeline sobre un chat real con bloques sin RESUMEN.
2. Verificar que `ProgressMonitor` detecta progreso correctamente.
3. Verificar que el nivel 2 (proxy APA directo) completa bloques cuando el Worker Bun cae.
4. Verificar que la contabilidad devuelve el número correcto de pending_tasks (sin falso positivo).

---

## 5. Archivos intervenidos

| Archivo | Cambio |
|---|---|
| `pipeline.py` | F1: clase `ProgressMonitor`. F2: `_arrancar_worker_y_esperar` con `subprocess.Popen`. F3: `_enriquecer_con_proxy_apa`. F4: `_enriquecer_bloques_con_fallback` con 3 niveles. F5: `_bloque_esta_completo`. |
| `config.py` | F6: constantes `PROGRESS_*`. |
| `tests/test_v42_e2e.py` | F7: mocks actualizados con 3 archivos + patch a `_enriquecer_con_proxy_apa`. |
| `retorno/documento_consolidado.md` | Documento de retorno con lecciones aprendidas (L017, AP18, AP19, AP20, AP21, AP22, AP23). |

---

## 6. Lo que NO se toca

- Worker Bun (código TypeScript, prompts, backoff).
- `CredentialManager` (no se modifica).
- Bookmarklet ni el flujo de conexión del Director.
- Bloques físicos (nombre, contenido, estructura — el RESUMEN se añade al inicio).
- Especificaciones y planes de versiones anteriores (ya en el historial).
- La estructura de archivos de recuperación (`00_estado_actual.md`, `01_indice_recuperacion.md`, etc.).
- La separación de capas + MessageExtractor + paginación de v6.11.

---

## 7. Criterios de aceptación

1. `from pipeline import ProgressMonitor` funciona.
2. `ProgressMonitor` tiene los métodos `contar_bloques_completos`, `contar_bloques_totales`, `esperar_y_verificar`.
3. `from pipeline import EnriquecimientoOrquestador` funciona.
4. `EnriquecimientoOrquestador` tiene `_enriquecer_con_proxy_apa` y `_bloque_esta_completo`.
5. `_enriquecer_bloques_con_fallback` integra los 3 niveles (Worker Bun → proxy APA → subagentes).
6. La contabilidad de pending_tasks se basa en `_bloque_esta_completo`, no en `_processed_blocks.json`.
7. Constantes `PROGRESS_*` en `config.py` con los valores especificados.
8. Tests E2E: 30/30 pasan.
9. Validación con datos reales: el nivel 2 (proxy APA directo) completa bloques cuando el Worker Bun cae.

---

## 8. Validación con datos reales

1. **Test F1 (ProgressMonitor):** ejecutar el pipeline sobre un chat con bloques sin RESUMEN. `ProgressMonitor` debe detectar progreso (más bloques completos) o declarar caído tras 2 intervalos sin progreso.
2. **Test F3 (nivel 2):** con el Worker Bun caído, verificar que `_enriquecer_con_proxy_apa` completa bloques escribiendo RESUMEN + 3 archivos.
3. **Test F5 (contabilidad):** verificar que `pending_tasks` refleja el estado físico (bloques sin RESUMEN + sin 3 archivos), no la cola.
4. **Test F8 (e2e):** sobre un chat real, verificar que el arnés de 3 niveles funciona end-to-end.

---

## 9. Hallazgos del run real (2026-11-03, chat 6a00fcb8)

El run de v6.12 sobre el chat 6a00fcb8 (613 exchanges, 105 bloques) reveló:

1. **ProgressMonitor funciona:** el Worker Bun no progresó (proxy APA saturado por 429), `ProgressMonitor` lo declaró caído tras 2 intervalos sin progreso.
2. **Nivel 2 frágil:** el proxy APA procesó 9 bloques antes de empezar a devolver 429. 96 bloques quedaron sin RESUMEN.
3. **Contabilidad honesta:** el `OrchestratorResult` devolvió `pending_tasks=105` (sin falso positivo). Pero `_processed_blocks.json` quedó inconsistente (1 completado cuando había 20 con RESUMEN).
4. **`PROGRESS_GROWTH=1.5` sin justificación:** las constantes no se derivaron del backoff del Worker Bun (que es factor 2.0). Es un valor inventado.

Estos hallazgos alimentan la spec v6.13 (pendiente).

---

## 10. Desviaciones detectadas post-implementación

| # | Desviación | Causa | Origen |
|---|---|---|---|
| 1 | `PROGRESS_GROWTH=1.5` inventado, no derivado del backoff del Worker Bun | Las constantes no se justificaron en la spec | v6.12 F6 |
| 2 | `_processed_blocks.json` inconsistente con el estado físico | F5 no cubrió el registro durable, solo la lógica de contabilidad | v6.12 F5 |
| 3 | Nivel 2 frágil ante rate limit del proxy | Sin backoff cuando el proxy satura | v6.12 F3 |
| 4 | `bloque_20.md` viola el `PROMPT_RESUMEN_RIGIDO` (90 chars, etiquetas) | Subagente manual ignoró el prompt | Intervención manual |
| 5 | El Gauntlet no detectó el rate limit del proxy | Tests con mocks de <100 chars, no con datos reales | v6.12 F7 |

---

**Fin de la spec v6.12.**
