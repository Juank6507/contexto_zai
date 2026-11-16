# contexto_zai/Documentos/plan_refactorizacion_v6.12.md
# Plan v6.12 — ProgressMonitor + arnés 3 niveles + contabilidad por estado físico

**Versión:** 6.12
**Fecha:** 2026-11-02
**Estado:** Implementado (commit `1f1ba8c`).
**Continuación de:** plan v6.11.
**Spec asociada:** spec_recuperacion_contexto_v6.12.md

---

## Objetivo

Implementar los 8 cambios especificados en la spec v6.12:
1. `ProgressMonitor` (clase OOP) con monitoreo de progreso.
2. `_arrancar_worker_y_esperar()` con `subprocess.Popen` + `ProgressMonitor`.
3. `_enriquecer_con_proxy_apa()` (nivel 2 del arnés).
4. `_enriquecer_bloques_con_fallback()` con 3 niveles integrados.
5. Contabilidad por estado físico (RESUMEN + 3 archivos).
6. Constantes `PROGRESS_*` en `config.py`.
7. Tests actualizados con mocks de 3 archivos.
8. Validación con datos reales.

---

## No olvidar del DTI

- NH1: diagnóstico y consenso previo — hecho (informe del EP del 2026-10-30, run v6.11).
- NH8: autorización del Director — concedida (orden del 2026-11-02).
- NH14: decisión de arquitectura consensuada — `ProgressMonitor` como clase OOP separada del arnés, 3 niveles del arnés, verificación de bloque completo. Todo conciliado con el Director.
- NH18: cambios quirúrgicos, no reescribir.
- NH19: validar antes de entregar.
- NH21: prohibido hardcoding de valores que deberían ser configurables — **las constantes `PROGRESS_*` deben justificarse** (desviación detectada: no se justificaron).
- NH23: solo tocar lo pedido.
- NH25: baremo de datos reales — validar contra el chat 6a00fcb8.

---

## Principio: monitoreo de progreso + no timeout fijo + no falso positivo

El Worker Bun tiene backoff exponencial interno. Un timeout fijo lo mata. Se reemplaza por `ProgressMonitor` que cuenta bloques completos en intervalos. La contabilidad se basa en el estado físico, no en la cola. Lo que ya funciona NO se toca.

---

## Fases

### F1 — `ProgressMonitor` (clase OOP)

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. Crear clase `ProgressMonitor` con 3 métodos estáticos:
   - `contar_bloques_completos(workspace_dir)`: cuenta bloques con RESUMEN + 3 archivos.
   - `contar_bloques_totales(workspace_dir)`: cuenta `bloque_*.md`.
   - `esperar_y_verificar(workspace_dir, intervalo_inicial, max_intervalos, crecimiento)`: monitorea progreso.
2. Separada del arnés (OOP puro).

**Lo que NO se toca:**
- El Worker Bun.
- La idempotencia.

### F2 — `_arrancar_worker_y_esperar()` con `subprocess.Popen` + `ProgressMonitor`

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. Usar `subprocess.Popen` (no bloqueante) para lanzar el Worker Bun.
2. `ProgressMonitor.esperar_y_verificar()` monitorea el progreso.
3. Si completa todos los bloques, retorna `True`.
4. Si no progresa en 2 intervalos seguidos, retorna `False`.

**Lo que NO se toca:**
- El comando de arranque del Worker Bun.
- La detección de Worker Bun existente por puerto 8090.

### F3 — `_enriquecer_con_proxy_apa()` (nivel 2)

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. Método estático `_enriquecer_con_proxy_apa(bloque, workspace_dir)`.
2. Lee el bloque físico.
3. Si <100 chars, retorna `False` (warning).
4. Si >50000 chars, trunca.
5. Llama al proxy APA con W1 (resumen rígido).
6. Escribe RESUMEN al inicio del bloque.
7. Llama al proxy APA con W2 (extracción JSON).
8. Escribe `_nombre.txt`, `_decisiones.txt`, `_temas.txt` en `_responses/`.
9. Caché por hash SHA256 en `_responses/cache/`.
10. Retorna `True` o `False`.

**Lo que NO se toca:**
- El proxy APA (vive en el sandbox).
- Los prompts W1 y W2.
- El protocolo de ficheros.

### F4 — `_enriquecer_bloques_con_fallback()` con 3 niveles

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. Integrar los 3 niveles:
   - NIVEL 1: Worker Bun con `ProgressMonitor`.
   - NIVEL 2: `_enriquecer_con_proxy_apa()` uno a uno.
   - NIVEL 3: construir `pending_tasks` para subagentes.
2. Regla de oro: worker, proxy y subagentes nunca procesan la misma tarea a la vez.

**Lo que NO se toca:**
- La lógica de construcción de `pending_tasks`.
- Los prompts de los subagentes.

### F5 — Contabilidad por estado físico

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. `_bloque_esta_completo(bloque, workspace_dir)` verifica RESUMEN + 3 archivos.
2. La contabilidad de `pending_tasks` se basa en `_bloque_esta_completo()`, no en `_processed_blocks.json`.

**Lo que NO se toca:**
- `_processed_blocks.json` (sigue como registro, no como fuente de verdad).
- `_pending_tasks.json` (sigue como cola).

### F6 — Constantes `PROGRESS_*` en `config.py`

**Archivos:** `config.py`.

**Qué se hace:**
1. Añadir 4 constantes:
   - `PROGRESS_INTERVAL_INITIAL = 20`
   - `PROGRESS_MAX_INTERVALS = 10`
   - `PROGRESS_GROWTH = 1.5`
   - `PROGRESS_MAX_NO_PROGRESS = 2`
2. `ProgressMonitor.esperar_y_verificar()` las usa con valores por defecto.

**⚠️ Desviación detectada:** las constantes no se justificaron. El backoff del Worker Bun es factor 2.0 (2, 4, 8, 16, 32, 64), no 1.5. La spec v6.10 ya tenía intervalos progresivos. v6.12 inventó el factor 1.5 sin derivación del baremo estratégico. Esto alimenta la spec v6.13.

**Lo que NO se toca:**
- `WORKER_BUN_TIMEOUT = 120` (sigue como límite máximo).

### F7 — Tests actualizados

**Archivos:** `tests/test_v42_e2e.py`.

**Qué se hace:**
1. Actualizar `test_v62_worker_falla_parcialmente`: añadir `patch` a `_enriquecer_con_proxy_apa`.
2. Actualizar `test_v62_worker_timeout`: añadir `patch` a `_enriquecer_con_proxy_apa`.
3. Los mocks de bloques completos escriben `_nombre.txt`, `_decisiones.txt`, `_temas.txt`.
4. Los patches van a `EnriquecimientoOrquestador._arrancar_worker_y_esperar` y `_enriquecer_con_proxy_apa`.
5. Tests E2E: 30/30 deben pasar.

**Lo que NO se toca:**
- Tests que no se ven afectados.

### F8 — Validación con datos reales

**Qué se hace:**
1. Ejecutar el pipeline sobre un chat real con bloques sin RESUMEN.
2. Verificar que `ProgressMonitor` detecta progreso.
3. Verificar que el nivel 2 completa bloques.
4. Verificar que la contabilidad devuelve el número correcto de `pending_tasks`.

---

## Orden de ejecución

| Fase | Dependencias | Estado |
|---|---|---|
| F1 — ProgressMonitor (clase OOP) | ninguna | Implementado |
| F2 — _arrancar_worker_y_esperar + ProgressMonitor | F1 | Implementado |
| F3 — _enriquecer_con_proxy_apa (nivel 2) | ninguna | Implementado |
| F4 — _enriquecer_bloques_con_fallback (3 niveles) | F1, F2, F3 | Implementado |
| F5 — Contabilidad por estado físico | F4 | Implementado |
| F6 — Constantes PROGRESS_* | F1 | Implementado (con desviación) |
| F7 — Tests actualizados | F1-F6 | Implementado (30/30) |
| F8 — Validación con datos reales | F7 | Implementado (9 bloques, 96 pendientes) |

**Total estimado:** 1 sesión.

---

## Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| `ProgressMonitor` declara caído al Worker Bun que estaba trabajando legítimamente | Media | Alto | Verificar progreso en intervalos progresivos, no timeout fijo |
| El nivel 2 (proxy APA) satura por rate limit | Alta | Medio | Backoff entre llamadas (no implementado en v6.12 — desviación) |
| La contabilidad física diverge de `_processed_blocks.json` | Media | Bajo | `_bloque_esta_completo` es la fuente de verdad, no el registro |
| `PROGRESS_GROWTH=1.5` no respeta el backoff del Worker Bun | Alta | Medio | **No mitigado en v6.12** — alimenta spec v6.13 |

---

## Entrega

- Archivos modificados en `.zip` con estructura `para-repo-contexto_zai/` + `1-LEER-PRIMERO.txt`.
- Script de entrega `update_czai.ps1` (instanciado de `plantilla_script_entrega_proyecto.ps1`).
- Sentencia de lanzamiento PowerShell (con backticks escapando `$`).
- Commit sugerido: `v6.12: ProgressMonitor + arnes 3 niveles + contabilidad por estado fisico`.

---

## Resultado real (2026-11-02 a 2026-11-03)

- Commit `1f1ba8c` aplicado (tras 4 iteraciones de reempaquetado por problemas de empaquetado).
- Run sobre chat 6a00fcb8: 613 exchanges extraídos, 105 bloques generados.
- ProgressMonitor funcionó: declaró caído al Worker Bun tras 2 intervalos sin progreso.
- Nivel 2 procesó 9 bloques (rate limit del proxy APA tras 9 llamadas).
- 96 bloques quedaron sin RESUMEN.
- Contabilidad honesta: devolvió `pending_tasks=105` (sin falso positivo).
- `_processed_blocks.json` inconsistente con el estado físico (1 completado vs 20 reales).
- `PROGRESS_GROWTH=1.5` no justificado.

---

## Hallazgos para v6.13 (pendiente)

1. Las constantes `PROGRESS_*` deben derivarse del backoff del Worker Bun (factor 2.0), no inventarse (1.5).
2. `_processed_blocks.json` debe reflejar el estado físico, no solo la cola.
3. El nivel 2 necesita backoff cuando el proxy APA satura.
4. El Gauntlet debe ejecutarse contra datos reales (chat con >100 bloques), no solo mocks de <100 chars.
5. El baremo táctico debe derivarse del estratégico con umbrales verificables.

---

**Fin del plan v6.12.**
