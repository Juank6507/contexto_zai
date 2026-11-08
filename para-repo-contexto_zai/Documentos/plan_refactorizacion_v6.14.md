# contexto_zai/Documentos/plan_refactorizacion_v6.14.md
# Plan v6.14 — Reorganación a 19 pasos + daemon + detonante

**Versión:** 6.14
**Fecha:** 2026-11-07
**Estado:** Pendiente de implementación.
**Spec asociada:** spec_recuperacion_contexto_v6.14.md
**Sesión origen:** CZAI 6a00fcb8, elemento C del método DCEPI.

---

## Principio: cambios quirúrgicos (NH18), validar antes de entregar (NH19), solo lo pedido (NH23)

Modo de ejecución v1.6 (D6): UN solo Actuador + el agente como Crítico. La doble implementación (dos subagentes en paralelo) queda retirada.

---

## Fases (quirúrgicas, integradas en el flujo del proceso)

### F1 — Commitear cambios v6.13 pendientes (PRE-REQUISITO)

- **Archivos:** `config.py`, `pipeline.py`
- **Cambio:**
  - Commitear `MAX_ITER_W3 = 5` y constantes `RESUMEN_*` en `config.py`.
  - Commitear método `_validar_resumen_w3()` y loop while con MAX_ITER_W3 + backoff 429 en `_enriquecer_con_proxy_zai()` de `pipeline.py`.
  - Commitear `import time` al inicio de `pipeline.py`.
- **Estado:** ❌ Pendiente
- **Dependencias:** ninguna (es pre-requisito para F2-F10)

### F2 — Reposicionar P16 después del enriquecimiento (criterio 17)

- **Archivos:** `process/orchestrator.py`, `pipeline.py`
- **Cambio quirúrgico:**
  - En `Orchestrator.activate()` (`process/orchestrator.py:199-209`): eliminar la auditoría final actual que corre antes del retorno.
  - En `ContextoPipeline.run()` (`pipeline.py:130-158`): mover la auditoría final a DESPUÉS de `_enriquecer_bloques_post_run()` (P14) y ANTES de `_consolidar_decisiones_llm()` (P18).
  - Secuencia final: P14 enriquecimiento → P15 sincronizar → P16 auditoría final → P17 bucle D7 → P18 consolidar decisiones → P19 regenerar índice.
- **Estado:** ❌ Pendiente
- **Dependencias:** F1

### F3 — Implementar bucle D7 en P17 (criterio 18)

- **Archivos:** `pipeline.py`
- **Cambio quirúrgico:**
  - Sustituir `_ejecutar_pending_tasks_obligatorias()` (línea 1859-1920) por un bucle D7 real:
    ```
    bucle_d7_completitud(workspace_dir):
        for intento in 1..MAX_ITER_D7:
            leer _pending_tasks.json (el saco)
            si saco vacío → break (verde)
            para cada bloque incompleto en el saco:
                revisar falla vs spec (W3: ¿longitud? ¿oraciones? ¿etiquetas?)
                modificar prompt corrigiendo esa falla
                re-entregar al Actuador (subagente del Task tool)
                re-valorar como Crítico (W3 validación)
                si pasa → fuera del saco
                si no → próxima iteración
        si MAX_ITER_D7 agotado → generar informe al Director
    ```
  - Añadir constante `MAX_ITER_D7 = 5` en `config.py`.
  - El informe de escalado al Director debe cubrir las 4 preguntas por iteración: qué falló → qué se diagnosticó → cómo se corrigió → qué se implementó.
- **Estado:** ❌ Pendiente
- **Dependencias:** F2

### F4 — Sustituir la llamada incorrecta a `collect_responses()` en `_ejecutar_pending_tasks_obligatorias()` (criterio 19)

- **Archivos:** `pipeline.py`
- **Cambio quirúrgico:**
  - En `_ejecutar_pending_tasks_obligatorias()` (línea 1859-1920): eliminar la llamada a `collect_responses()` como "arregla todo" (líneas 1885-1888). Esa lógica se sustituye por el bucle D7 de F3.
  - **NO eliminar `collect_responses()` del flujo P14-P17** — mantiene su rol correcto como integrador de respuestas de subagentes (cualquier propósito) + disparador de la cascada P14 cuando quedan bloques sin RESUMEN.
  - `collect_responses()` sigue siendo invocado desde:
    - `query_context()` (línea 161 aprox.) para integrar respuestas de búsqueda.
    - El flujo normal de `pipeline.run()` y `ampliar_contexto()` cuando el agente ya ejecutó los subagentes y tiene sus respuestas en `_responses/`.
  - Documentar en docstring de `collect_responses()`: "Esta función es el integrador de respuestas de subagentes (cualquier propósito: estado, intercambios, decisiones, consultas, documentos). Lee `_responses/`, las aplica al workspace según el `purpose` de cada tarea, Y dispara la cascada W1+W2+W3 (P14) cuando quedan bloques sin RESUMEN. NO es un bucle D7 — si tras llamarla quedan bloques incompletos, el bucle D7 de P17 se encarga de los reintentos con feedback."
- **Estado:** ❌ Pendiente
- **Dependencias:** F3

### F5 — Crear el daemon del proceso contexto_zai (criterios 20, 21)

- **Archivos:** `mini-services/pipeline-daemon/index.py` (NUEVO), `mini-services/pipeline-daemon/package.json` (NUEVO), `mini-services/_launch.sh` (modificar para levantar el daemon)
- **Cambio:**
  - Crear mini-servicio Python siempre corriendo en puerto 8088.
  - Endpoints:
    - `POST /ampliar-contexto` → invoca `ampliar_contexto(source_type, source_path, jwt, metadata)`.
    - `POST /pipeline-run` → invoca `pipeline.run(chat_id, jwt, ...)`.
    - `GET /pending-tasks` → devuelve `_pending_tasks.json` actual.
    - `GET /status` → devuelve estado del workspace.
  - El daemon se lanza con doble setsid (patrón `_launch.sh`) para sobrevivir entre llamadas del Bash tool.
  - Eliminar `runner_ampliar.py`, `runner_collect.py`, `runner_6a00fcb8.py`, `enrich_nivel2.py` — ya no se necesitan.
- **Estado:** ❌ Pendiente
- **Dependencias:** F1

### F6 — Determinar estructura del contenido en ampliar_contexto (criterio 22)

- **Archivos:** `pipeline.py` (función `ampliar_contexto`)
- **Cambio quirúrgico:**
  - Añadir función `_detectar_estructura_contenido(content_bytes)` que devuelva:
    - `"cronologico"` si el contenido tiene marcadores `## Exchange N -- [timestamp]` o `### 📅 YYYY-MM-DD`.
    - `"arbitrario"` en caso contrario.
  - Si `cronologico` → procesar como P4.1 (extraer intercambios y construirlos en P5).
  - Si `arbitrario` → saltar directamente a P6 (clasificar por tema a nivel de bloque, no de intercambio).
- **Estado:** ❌ Pendiente
- **Dependencias:** F1

### F7 — Cabecera de bloques: cronológico vs externo (criterio 23)

- **Archivos:** `generation/bloque_generator.py`
- **Cambio quirúrgico:**
  - Añadir parámetro `origen: str = "cronologico"` al método `generate()`.
  - Si `origen == "cronologico"` → cabecera `# Bloque cronológico N` (sin cambios).
  - Si `origen == "externo"` → cabecera `# Bloque externo N` + `**Source:** ampliar_contexto (documento externo)`.
- **Estado:** ❌ Pendiente
- **Dependencias:** F6

### F8 — P9 (00_estado_actual) solo para cronológico (criterio 24)

- **Archivos:** `process/recovery_cycle.py`, `process/incremental_cycle.py`, `coordinador/orquestador.py`
- **Cambio quirúrgico:**
  - Pasar el parámetro `origen` desde P4.2 hasta el `RecoveryGenerator` que orquesta los generadores.
  - Si `origen == "externo"` → saltar la generación de `00_estado_actual.md` (EstadoGenerator no se invoca).
  - Los otros 3 archivos (01_indice, 02_decisiones, 03_objetivo) sí se generan.
- **Estado:** ❌ Pendiente
- **Dependencias:** F6

### F9 — Ordenamiento: bloques externos al final en orden de entrada (criterio 25)

- **Archivos:** `processing/block_packer.py`
- **Cambio quirúrgico:**
  - Modificar `pack()` para aceptar parámetro `origen` por bloque.
  - Si `origen == "cronologico"` → ordenar por timestamp descendente (comportamiento actual).
  - Si `origen == "externo"` → añadir al final del workspace, después de los cronológicos, en el orden de entrada (no por timestamp).
  - Numeración: bloque_01..bloque_N para cronológicos; bloque_N+1..bloque_M para externos.
- **Estado:** ❌ Pendiente
- **Dependencias:** F6, F7

### F10 — Reconstruir contexto desde exchanges_czai_consolidados.md (criterio 16, post-Gauntlet)

- **Qué se hace:**
  1. Borrar workspace `contexto_recuperacion/` actual (50 bloques sin RESUMEN de la iteración 1).
  2. Invocar al daemon (F5) con `ampliar_contexto("file", "exchanges_czai_consolidados.md")`.
  3. El daemon ejecuta el pipeline de 19 pasos sobre el archivo.
  4. P4.2 detecta que el contenido es cronológico (marcadores `## Exchange N`) → procesa como P4.1.
  5. El enriquecimiento (P14) dispara la cascada W1+W2+W3 con bucle D7.
  6. P17 garantiza la completitud con bucle D7.
  7. Auditoría final P16 verifica que todos los bloques están completos.
- **Estado:** ❌ Pendiente (post-F1..F9)
- **Dependencias:** F1, F2, F3, F4, F5, F6, F7, F8, F9

### F11 — Gauntlet de terminación (criterio 14, NH27)

- **Qué se hace:**
  1. Tras F10, ejecutar los 7 pasos del Gauntlet sobre el workspace reconstruido.
  2. Verificar los 26 criterios de aceptación (16 heredados de v6.13 + 10 nuevos de v6.14).
  3. Si no pasa → bucle D7 (P17) con MAX_ITER=5.
  4. Si MAX_ITER=5 agotado → informe al Director con las 4 preguntas por iteración.
  5. Si pasa → empaquetado (I.3.a) desbloqueado.
- **Estado:** ❌ Pendiente (post-F10)
- **Dependencias:** F10

---

## Orden de ejecución

| Fase | Descripción | Estado | Dependencias |
|---|---|---|---|
| F1 | Commitear cambios v6.13 pendientes | ❌ | ninguna |
| F2 | Reposicionar P16 después del enriquecimiento | ❌ | F1 |
| F3 | Implementar bucle D7 en P17 | ❌ | F2 |
| F4 | Sustituir llamada incorrecta a `collect_responses()` en `_ejecutar_pending_tasks_obligatorias()` | ❌ | F3 |
| F5 | Crear el daemon del proceso contexto_zai | ❌ | F1 |
| F6 | Determinar estructura del contenido en `ampliar_contexto` | ❌ | F1 |
| F7 | Cabecera de bloques: cronológico vs externo | ❌ | F6 |
| F8 | P9 (00_estado_actual) solo para cronológico | ❌ | F6 |
| F9 | Ordenamiento: bloques externos al final en orden de entrada | ❌ | F6, F7 |
| F10 | Reconstruir contexto desde `exchanges_czai_consolidados.md` | ❌ | F1-F9 |
| F11 | Gauntlet de terminación (7 pasos + 26 criterios) | ❌ | F10 |

**Total:** 11 fases quirúrgicas.

**Falta después de F11:** empaquetado (I.3.a) y entrega al Director para validación en Windows (I.3.b) — esto ya es parte del elemento I del DCEPI, no del plan de refactorización.

---

## Consideraciones para la implementación

### Modo de ejecución (estrategia v1.6, D6)

- Cada fase se ejecuta con UN solo subagente (Actuador) lanzado por el agente CZAI con el Task tool.
- El agente CZAI valora la respuesta del Actuador como Crítico contra el baremo.
- Si la respuesta no cumple → bucle D7 (modificar prompt → re-entregar al Actuador → re-valorar) hasta MAX_ITER=5.
- Nada se selecciona sin el Director; si existe algo mejor que lo conciliado, se explica y SE RE-CONCILIA antes de implementar.

### Trazabilidad

- Cada fase debe registrar en el worklog CZAI: qué se pidió, qué se hizo, qué archivos se modificaron, qué pendientes quedan.
- Los cambios se commitean al final de cada fase (no al final de toda la implementación) para preservar trazabilidad.

### Validación con datos reales (NH25)

- F10 usa el archivo real `exchanges_czai_consolidados.md` (5.2 MB, 649 exchanges).
- F11 ejecuta el Gauntlet sobre el workspace real generado por F10.
- No se aceptan mocks ni simulaciones como evidencia de veredicto (salvo que no existan datos reales, lo cual no aplica aquí).

### Pendientes que requieren conciliación con el Director

- El puerto del daemon (F5) — propongo 8088, pero requiere confirmación.
- Si el daemon se lanza automáticamente al iniciar el sandbox o si requiere orden explícita del Director.
- Si el informe al Director (cuando MAX_ITER=5 se agota en F11) se entrega en `download/` o por chat directo.

---

**Fin del plan v6.14.**
