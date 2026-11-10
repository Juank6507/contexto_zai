# contexto_zai/Documentos/spec_recuperacion_contexto_v6.16.md
# Spec v6.16 — Fixes de bugs v6.15 + checkpointing + paralelismo Nivel 2

**Versión:** 6.16
**Fecha:** 2026-11-09
**Estado:** Pendiente de implementación.
**Especifica continuación de:** spec v6.15.
**Sesión origen:** CZAI 6a00fcb8, elementos E+P del método DCEPI.

---

## 1. Propósito

Corregir los 7 bugs detectados en la iteración del Gauntlet v6.15. Los bugs van desde el cuelgue del script de entrega en Windows (bug 1) hasta la falta de checkpointing (bug 2+7), pasando por el contrato roto de `_pending_blocks.json` (bug 4) y la ausencia de paralelismo en Nivel 2 (bug 5).

---

## 2. Orden del proceso (19 pasos, sin cambios)

El pipeline se mantiene en 19 pasos (ver spec v6.14 §2). v6.16 corrige implementación, no orden.

---

## 3. Decisiones conciliadas por categoría

### Categoría 1 — Bug 1: test 2 de pipeline.py cuelga en Windows (1 problema)

| # | Problema | Decisión |
|---|---|---|
| 1 | El test 2 de `pipeline.py` `__main__` invoca `run(chat_id="invalid-chat", jwt="invalid-jwt")` y la cascada v6.15 cuelga intentando conexiones largas | Opción A: el test 2 usa un workspace vacío (sin bloques físicos). La cascada detecta 0 bloques sin RESUMEN y termina inmediatamente. El test verifica solo que `run()` devuelve `success=False` por JWT inválido, sin colgarse |

### Categoría 2 — Bug 2+7: checkpointing (1 problema, resuelve 2 bugs)

| # | Problema | Decisión |
|---|---|---|
| 2 | El proceso en background muere sin rastro cuando el Director deja de emitir prompts. No hay forma de retomar tras caída | **Checkpointing:** tras procesar cada bloque, escribir `_cascada_checkpoint.json` con: lista de bloques completos, lista de pendientes, timestamp. Al relanzar la cascada, leer el checkpoint y saltar los completos. La reanudación ocurre naturalmente cuando el Director envía el próximo prompt — no requiere cron watchdog |

### Categoría 3 — Bug 3: pending_tasks en memoria (1 problema)

| # | Problema | Decisión |
|---|---|---|
| 3 | `CascadaAccesoLLM._pending_tasks` se acumula en memoria y solo se escribe a disco al final del pipeline | Escribir pending_tasks en `_pending_tasks.json` tras cada bloque que cae a Nivel 3 (append, no sobrescribir) |

### Categoría 4 — Bug 4: Worker Bun no recibe bloques + constantes viejas (2 problemas)

| # | Problema | Decisión |
|---|---|---|
| 4a | `IntegradorRespuestas._integrar_documento()` no genera `_pending_blocks.json`. Solo `RecoveryCycle` lo hace. El Worker Bun no recibe los bloques externos | TODO punto que escriba bloques físicos debe generar o actualizar `_pending_blocks.json`. Es un contrato del pipeline. Aplica a: `RecoveryCycle` (ya lo hace), `IntegradorRespuestas._integrar_documento()`, y cualquier futuro generador de bloques |
| 4b | `_nivel1_worker_bun()` usa el viejo `ProgressMonitor.esperar_y_verificar()` con constantes 20s+40s=60s. Las constantes nuevas (5s×3=15s) están en `_esperar_y_verificar_progreso()` pero no se usan | `_nivel1_worker_bun()` debe usar `_esperar_y_verificar_progreso()` (5s×3=15s) en vez del viejo `ProgressMonitor` |

### Categoría 5 — Bug 5: Nivel 2 sin paralelismo (1 problema)

| # | Problema | Decisión |
|---|---|---|
| 5 | `_nivel2_proxy_zai()` procesa un bloque a la vez con llamada HTTP sincrónica | `ThreadPoolExecutor(max_workers=5)` en `_nivel2_proxy_zai()` para hacer 5 llamadas HTTP simultáneas al proxy. No tocar el proxy (Opción A — paralelismo en el cliente) |

### Categoría 6 — Bug 6: caché no invalidada por versión (1 problema)

| # | Problema | Decisión |
|---|---|---|
| 6 | El hash de caché se calcula solo con el hash del prompt, sin incluir la versión del pipeline | El hash de caché incluye la versión del pipeline (ej: `v6.16`). Si la versión cambia, el hash cambia y la caché se invalida |

### Categoría 7 — Encapsulamiento de tareas post-bloque (propuesta del Director)

| # | Problema | Decisión |
|---|---|---|
| 7 | Las tareas que se hacen tras procesar cada bloque (checkpoint, persistir pending_tasks, actualizar _processed_blocks, sincronizar _pending_blocks) son siempre las mismas y están dispersas | Encapsular en **función** `_post_bloque(workspace_dir, bloque, resultado, cascada)` que ejecuta la secuencia de pasos post-bloque. **Criterio del Actuador: función, no clase** — es stateless (toma el estado actual y lo persiste, no necesita preservar nada entre llamadas). La función vive en `pipeline.py` como método estático de `EnriquecimientoOrquestador` o como función del módulo |

---

## 4. Baremo táctico

### Gauntlet (7 pasos con datos reales, sin cambios)

Mismos 7 pasos que v6.14/v6.15.

### Criterios de aceptación (7 nuevos de v6.16 + 33 heredados = 40)

**Heredados de v6.15 (33):** mismos que spec v6.15 §4.

**Nuevos de v6.16 (7):**

34. El test 2 de `pipeline.py` `__main__` usa workspace vacío y no se cuelga. `run()` con JWT inválido devuelve `success=False` en menos de 5 segundos.
35. `_cascada_checkpoint.json` se escribe tras cada bloque procesado con lista de completos y pendientes.
36. Al relanzar `collect_responses()`, la cascada lee `_cascada_checkpoint.json` y salta los bloques ya completos.
37. `_pending_tasks.json` se actualiza tras cada bloque que cae a Nivel 3 (no solo al final del pipeline).
38. `IntegradorRespuestas._integrar_documento()` genera/actualiza `_pending_blocks.json` tras escribir cada bloque externo.
39. `_nivel1_worker_bun()` usa `_esperar_y_verificar_progreso()` (5s×3=15s), no el viejo `ProgressMonitor` (20s+40s=60s).
40. `_nivel2_proxy_zai()` usa `ThreadPoolExecutor(max_workers=5)` para procesar 5 bloques en paralelo. El hash de caché incluye la versión del pipeline.

---

**Fin de la spec v6.16.**
