# contexto_zai/Documentos/plan_refactorizacion_v6.17.md
# Plan v6.17 — Cascada de acceso + bucle D7 separados + Nivel 3 integrado

**Versión:** 6.17
**Fecha:** 2026-11-10
**Estado:** Pendiente de implementación.
**Spec asociada:** spec_recuperacion_contexto_v6.17.md

---

## Principio: cambios quirúrgicos (NH18), validar antes de entregar (NH19), solo lo pedido (NH23)

Modo de ejecución v1.6 (D6): UN solo Actuador + el agente como Crítico.

---

## Fases

### F1 — Función única de bloques incompletos (criterio 7)

- **Archivos:** `pipeline.py`
- **Cambio:**
  - Unificar `_descubrir_bloques_sin_resumen()` y `_bloque_esta_completo()` en una sola función `_descubrir_bloques_incompletos(workspace_dir)` que:
    - Lee cada `bloque_*.md` del workspace.
    - Verifica los 4 artefactos: RESUMEN al inicio + `_nombre.txt` + `_decisiones.txt` + `_temas.txt` en `_responses/`.
    - Devuelve lista de bloques incompletos (los que faltan al menos 1 artefacto).
    - Para cada bloque incompleto, indica qué artefactos faltan.
  - Sustituir todas las llamadas a `_descubrir_bloques_sin_resumen()` por `_descubrir_bloques_incompletos()`.
- **Estado:** ❌ Pendiente

### F2 — Nivel 3 integrado al proceso (criterio 1)

- **Archivos:** `pipeline.py` (clase `CascadaAccesoLLM`, método `_nivel3_subagentes`)
- **Cambio:**
  - `_nivel3_subagentes()` no solo publica pending_tasks — **procesa los bloques**.
  - Para cada bloque en Nivel 3:
    1. Construir el prompt con `PROMPT_FUSIONADO_W1W2W3`.
    2. Lanzar el subagente (vía Task tool integrado al proceso o vía el mecanismo que el proceso tenga para invocar subagentes).
    3. Verificar si el bloque se completó (4 artefactos).
    4. Si completó → fuera del saco.
    5. Si no completó → pending_task.
  - El subagente se ejecuta dentro del proceso, no es una promesa externa.
- **Estado:** ❌ Pendiente
- **Dependencias:** F1

### F3 — Bucle D7 separado de la cascada (criterio 2)

- **Archivos:** `pipeline.py`
- **Cambio:**
  - El bucle D7 no baja niveles de la cascada.
  - Cuando el D7 no completa tras 5 intentos, la tarea pasa a pending_task.
  - Separar la lógica del D7 de la lógica de la cascada: la cascada decide el nivel, el D7 decide el reintento.
- **Estado:** ❌ Pendiente
- **Dependencias:** F2

### F4 — collect_responses() solo integra (criterio 3)

- **Archivos:** `pipeline.py`
- **Cambio:**
  - `collect_responses()` lee `_responses/`, integra al workspace, devuelve resultado.
  - Eliminar la lógica que verifica bloques incompletos y dispara la cascada desde `collect_responses()`.
  - Esa lógica la asume el proceso (daemon/pipeline) tras llamar `collect_responses()`.
- **Estado:** ❌ Pendiente
- **Dependencias:** F1

### F5 — Daemon en background con reporte de progreso (criterio 4)

- **Archivos:** `mini-services/pipeline-daemon/index.py`, `pipeline.py`
- **Cambio:**
  - El daemon escribe progreso en un archivo `_daemon_status.json` (bloques completados, pendientes, tarea actual, estado: idle/running/done).
  - El agente CZAI lee `_daemon_status.json` antes de responder al Director e incluye el estado en la frase de control.
  - Si el daemon no está haciendo nada, lo dice. Cuando termina, lo dice.
- **Estado:** ❌ Pendiente

### F6 — Detonante usa RecoveryCycle (criterio 5)

- **Archivos:** `pipeline.py`, `mini-services/pipeline-daemon/index.py`
- **Cambio:**
  - Cuando el agente no puede emitir la frase de control, invoca al daemon para que ejecute RecoveryCycle.
  - Si `contexto_recuperacion/` no existe, lo crea desde lo que existe en ese chat.
  - No usa `ampliar_contexto` modo INCREMENTAL.
- **Estado:** ❌ Pendiente
- **Dependencias:** F5

### F7 — Si contexto_recuperacion existe: solo auditar + completar (criterio 6)

- **Archivos:** `pipeline.py`, `mini-services/pipeline-daemon/index.py`
- **Cambio:**
  - Si `contexto_recuperacion/` existe, el daemon:
    1. Audita (con `_descubrir_bloques_incompletos()` de F1).
    2. Completa solo los incompletos (sin re-extraer, sin re-construir, sin borrar caché, sin quitar RESUMENES).
    3. Auditoría final + P17 + P18 + P19.
  - Si no existe, procesa toda la fuente.
- **Estado:** ❌ Pendiente
- **Dependencias:** F1, F5

### F8 — Manejo del 429 entre tareas (criterio 8)

- **Archivos:** `pipeline.py` (clase `CascadaAccesoLLM`)
- **Cambio:**
  - Una tarea o grupo recibe 429 en Nivel 1 o Nivel 2 → cae a Nivel 3 para esa tarea.
  - Antes de la siguiente tarea: ping para comprobar si el 429 persiste.
  - Si persiste → la siguiente tarea va directo a Nivel 3.
  - Si no persiste → la siguiente tarea empieza en Nivel 1.
  - Si Nivel 1 cae por causa que NO es 429 → Nivel 2 SÍ se prueba.
- **Estado:** ❌ Pendiente
- **Dependencias:** F2

### F9 — Enriquecimiento atómico (criterio 9)

- **Archivos:** `pipeline.py` (función `_enriquecer_con_proxy_zai`)
- **Cambio:**
  - Escribir los 4 artefactos atómicamente: escribir a archivo temporal y renombrar, o escribir todos o ninguno.
  - Si falla entre medio, el bloque queda en su estado anterior.
- **Estado:** ❌ Pendiente

### F10 — ampliar_contexto() propaga estructura (criterio 10)

- **Archivos:** `pipeline.py`, `coordinador/integrador_respuestas.py`, `generation/recovery_generator.py`
- **Cambio:**
  - `ampliar_contexto()` propaga `estructura` desde la detección (P4.2) hasta `RecoveryGenerator.generate_all()`.
  - Los bloques externos con estructura cronológica generan los 4 archivos de recuperación.
- **Estado:** ❌ Pendiente

### F11 — Pending_tasks persistente en ambos lugares (criterio 11)

- **Archivos:** `pipeline.py`
- **Cambio:**
  - Persistir pending_tasks en disco en: (a) el bucle D7, (b) `_post_bloque()`.
  - Reusando el mismo código (función `_persistir_pending_task()`).
  - Las pending_tasks pueden caer desde cualquier nivel de la cascada.
- **Estado:** ❌ Pendiente
- **Dependencias:** F3

### F12 — Bucle D7 encapsulado (criterio 12)

- **Archivos:** `pipeline.py`
- **Cambio:**
  - Encapsular el bucle D7 en clase o función.
  - Procedimiento: revisar falla → corregir prompt → reintentar → verificar → si cumple, fuera; si no, próxima iteración; si 5 agotados, se mantiene en pending_task.
  - No disperso. No baja niveles.
- **Estado:** ❌ Pendiente
- **Dependencias:** F3

### F13 — Reconstruir contexto desde exchanges_czai_consolidados.md

- **Qué se hace:**
  1. Borrar workspace `contexto_recuperacion/`.
  2. Invocar al daemon con la fuente.
  3. El daemon ejecuta el pipeline con las correcciones F1-F12.
  4. F7: si contexto_recuperacion existe (de una ejecución parcial), solo auditar y completar.
  5. F1: detectar bloques incompletos con la función unificada.
  6. F2: Nivel 3 procesa automáticamente.
  7. F8: manejo del 429 entre tareas.
  8. F9: enriquecimiento atómico.
- **Estado:** ❌ Pendiente
- **Dependencias:** F1-F12

### F14 — Gauntlet de terminación

- **Qué se hace:**
  1. Ejecutar los 7 pasos del Gauntlet.
  2. Verificar los 12 criterios de aceptación.
  3. Si no pasa → bucle D7.
  4. Si pasa → empaquetado.
- **Estado:** ❌ Pendiente
- **Dependencias:** F13

---

## Orden de ejecución

| Fase | Descripción | Deps |
|---|---|---|
| F1 | Función única de bloques incompletos | ninguna |
| F2 | Nivel 3 integrado al proceso | F1 |
| F3 | Bucle D7 separado de la cascada | F2 |
| F4 | collect_responses() solo integra | F1 |
| F5 | Daemon con reporte de progreso | ninguna |
| F6 | Detonante usa RecoveryCycle | F5 |
| F7 | Si contexto existe: solo auditar + completar | F1, F5 |
| F8 | Manejo del 429 entre tareas | F2 |
| F9 | Enriquecimiento atómico | ninguna |
| F10 | ampliar_contexto propaga estructura | ninguna |
| F11 | Pending_tasks persistente en ambos lugares | F3 |
| F12 | Bucle D7 encapsulado | F3 |
| F13 | Reconstruir contexto | F1-F12 |
| F14 | Gauntlet de terminación | F13 |

---

**Fin del plan v6.17.**
