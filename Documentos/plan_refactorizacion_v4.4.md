# contexto_zai/Documentación/plan_refactorizacion_v4.4.md
# Plan v4.4 — Sistema de indexado consistente + multi-chat + subagentes cableados

**Versión:** 4.4
**Fecha:** 2026-09-16
**Autor:** Agente CZAI (Sesión 19, con consenso del Director)
**Estado:** Pendiente de validación por el Director.
**Continúa de:** plan v4.3 (00_estado_actual como punto de entrada ordenado + fixes huecos APA + creación automática de objetivo).
**Spec asociada:** spec_recuperacion_contexto_v4.4.md.

---

## Estructura del plan

El plan se organiza en 5 fases (F1–F5). Cada fase es independiente y entregable por separado. El orden respeta las dependencias:

1. Primero arreglar la lógica de decisión del `Orchestrator` (los 4 casos).
2. Luego ampliar la metadata para soportar múltiples chats.
3. Luego arreglar el `IncrementalCycle` (reempaquetado selectivo + índice + `share_id`).
4. Luego conectar los 3 sistemas de indexado (temas, resúmenes, índice legible).
5. Al final, cablear los subagentes de calidad por defecto.

**Total de archivos nuevos:** 0 (todas las extensiones viven en archivos existentes).
**Total de archivos intervenidos:** 8 (`process/orchestrator.py`, `process/incremental_cycle.py`, `metadata/manager.py`, `models.py`, `pipeline.py`, `generation/indice_generator.py`, `coordinador/integrador_respuestas.py`, `tests/test_v42_e2e.py`).
**Tests nuevos:** 8 atómicos + 2 E2E.

---

## F1 — Lógica de decisión de 4 casos en el Orchestrator

**Prioridad:** ALTA — es el bug del paso 4 (bloqueante).
**Dependencias:** ninguna.
**Estimación:** 0.5 sesión.

### Qué se hace

1. **`Orchestrator.activate()`** (`process/orchestrator.py`):
   - Cambia la lógica de decisión de 1 pregunta a 2 preguntas:
     - Pregunta 1: "¿Existe metadata?"
     - Pregunta 2: "¿El `chat_id` que me llega es el mismo que el de la metadata?"
   - Si llega un `share_id` externo (link `/s/`), descubre el `chat_id` real leyendo el árbol del share antes de decidir.
   - Según las 2 respuestas, decide entre los 4 casos (primera vez, mismo chat sin cambios, mismo chat con novedades, otro chat distinto).

2. **`Orchestrator` pasa `share_id` al `IncrementalCycle`** (consistencia con `RecoveryCycle`):
   - El `IncrementalCycle` se crea con `share_id=self._share_id` si existe.

### Tests individuales

- Test: caso 1 (primera vez) → recuperación completa.
- Test: caso 2 (mismo chat, sin cambios) → no hace nada.
- Test: caso 3 (mismo chat, con novedades) → incremental.
- Test: caso 4 (otro chat distinto) → recuperación completa (no incremental).

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/process/orchestrator.py
```

---

## F2 — Soporte multi-chat en la metadata

**Prioridad:** ALTA — necesario para que el caso 4 funcione.
**Dependencias:** F1.
**Estimación:** 1 sesión.

### Qué se hace

1. **`RecoveryMetadata`** (`models.py`):
   - Se amplía para tener una **lista de chats** en vez de un solo `chat_id` + `ultimo_timestamp`.
   - Cada chat en la lista tiene: `chat_id`, `ultimo_timestamp`, `share_id`.
   - El `tema_a_archivo` sigue siendo un solo mapa (tema → archivo), pero cada archivo sabe de qué chat vino (registrado en `archivo_a_source`).
   - El `archivo_a_source` se amplía para registrar el `chat_id` de cada bloque.
   - **Migración automática**: si el `_metadata.json` tiene el formato viejo (un solo chat), se migra al formato nuevo la primera vez que se lee.

2. **`MetadataManager`** (`metadata/manager.py`):
   - Métodos nuevos: `registrar_chat(chat_id, share_id, ultimo_timestamp)`, `buscar_chat(chat_id) -> Optional[ChatInfo]`, `actualizar_timestamp_chat(chat_id, nuevo_ts)`.
   - El método `read()` detecta el formato viejo y lo migra.

3. **`Orchestrator`** pasa el `chat_id` correcto al `RecoveryCycle` o `IncrementalCycle` según el caso detectado en F1.

### Tests individuales

- Test: metadata con 2 chats distintos → ambos quedan registrados.
- Test: migración automática de formato viejo a nuevo.
- Test: `buscar_chat(chat_id)` encuentra el chat correcto.
- Test: `actualizar_timestamp_chat` solo actualiza el chat correcto, no los demás.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/models.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/metadata/manager.py
```

---

## F3 — IncrementalCycle arreglado

**Prioridad:** ALTA — es la causa de la lentitud (36 min por chat) y del índice stale.
**Dependencias:** F2.
**Estimación:** 1 sesión.

### Qué se hace

1. **Reempaquetado selectivo** (`process/incremental_cycle.py`):
   - En vez de reempaquetar TODOS los bloques, solo reempaqueta los temas que recibieron intercambios nuevos.
   - Los demás bloques no se tocan.

2. **Regeneración del índice** (`process/incremental_cycle.py`):
   - Después de añadir mensajes nuevos:
     - Actualiza el `tema_a_archivo` de la metadata (Sistema 1).
     - Regenera el `01_indice_recuperacion.md` llamando al `IndiceGenerator` (Sistema 3).
     - Actualiza el `04_resumenes_bloques.md` si un bloque cambió (Sistema 2, cuando exista en F4).

3. **Acepta `share_id` externo** (`process/incremental_cycle.py`):
   - Igual que `RecoveryCycle`: si llega `share_id`, se salta `create_share()` y lo usa directamente.
   - Si `chat_id` venía vacío, lo descubre del árbol del share.

4. **Verifica que es el mismo chat** (`process/incremental_cycle.py`):
   - Antes de ejecutar, verifica que el `chat_id` de la metadata coincide con el que se está procesando. Si no, devuelve error (debería haber ido por recuperación completa).

### Tests individuales

- Test: 1 mensaje nuevo → solo se reempaqueta el tema afectado, no todos.
- Test: tras incremental, `01_indice_recuperacion.md` está actualizado.
- Test: tras incremental, `tema_a_archivo` está actualizado.
- Test: `IncrementalCycle` acepta `share_id` y se salta `create_share()`.
- Test: si `chat_id` no coincide con metadata, devuelve error.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/process/incremental_cycle.py
```

---

## F4 — 3 sistemas de indexado conectados

**Prioridad:** ALTA — es el núcleo de la v4.4.
**Dependencias:** F2, F3.
**Estimación:** 1.5 sesiones.

### Qué se hace

1. **Sistema 1 — Índice de temas → bloques** (mejorado):
   - `tema_a_archivo` se regenera en cada cambio (ya cubierto por F3 para incremental).
   - Cada bloque sabe de qué chat vino (cubierto por F2 en `archivo_a_source`).
   - Es la fuente única de verdad (ya lo es, se mantiene).

2. **Sistema 2 — Índice de resúmenes** (nuevo archivo `04_resumenes_bloques.md`):
   - Nuevo generador `ResumenesGenerator` (`generation/resumenes_generator.py`) que:
     - Lee todos los bloques del workspace (`bloque_*.md` + `bloque_externo_*.md`).
     - Extrae el `RESUMEN:` de cada uno (para externos, ya existe; para del chat, lo genera el subagente modo `RESUMEN_TRUNCADO`).
     - Escribe `04_resumenes_bloques.md` con la lista: `bloque_filename → resumen`.
   - Se invoca después de cada cambio (recovery, incremental, ampliar_contexto).
   - `query_context()` lo usa como atajo: antes de preparar prompts para subagentes, mira si algún resumen responde la pregunta. Si responde, le entrega el resumen al agente directamente (sin subagente). Si no, procede como hoy.

3. **Sistema 3 — Índice legible** (`01_indice_recuperacion.md` regenerado):
   - Ya se regenera en cada cambio (cubierto por F3 para incremental).
   - Muestra de qué chat es cada bloque (nueva columna en la tabla del índice).

### Tests individuales

- Test: `04_resumenes_bloques.md` se genera con los resúmenes de todos los bloques.
- Test: `query_context` devuelve el resumen directamente si la pregunta es genérica y el resumen responde.
- Test: `query_context` lanza subagente si el resumen no responde.
- Test: `01_indice_recuperacion.md` muestra la columna "chat" con el `chat_id` de cada bloque.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/resumenes_generator.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/pipeline.py
```

---

## F5 — Subagentes de calidad cableados por defecto

**Prioridad:** MEDIA — mejora la calidad pero no es bloqueante.
**Dependencias:** F1 (Orchestrator arreglado).
**Estimación:** 0.5 sesión.

### Qué se hace

1. **`Orchestrator.activate()`** (`process/orchestrator.py`):
   - Cambia `enable_capa3=False` por `enable_capa3=True`.
   - Pasa el `ProcesadorIntercambios` (launcher) a los generadores y al `Subdivider` (igual que ya se hace en el `RecoveryCycle` del flujo de recuperación).

2. **Verificar que los subagentes se lanzan en modo diferido**:
   - Los generadores (`EstadoGenerator`, `DecisionesGenerator`) llaman a `ProcesadorIntercambios.procesar(modo=...)` que publica la tarea.
   - El `Subdivider` usa `ProcesadorIntercambios` para el namer.
   - El `DiscriminatorSubagent` usa `ProcesadorIntercambios` para `CLASIFICACION_TEMAS`.
   - Todo vía `EntregadorTareas` + `_pending_tasks.json` + `collect_responses()`.

### Tests individuales

- Test: el `RecoveryCycle` se crea con `enable_capa3=True`.
- Test: el launcher se pasa a `EstadoGenerator` y `DecisionesGenerator`.
- Test: el launcher se pasa al `Subdivider`.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/process/orchestrator.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/tests/run_all_tests.py
```

---

## F6 — Tests E2E y verificación final

**Prioridad:** ALTA — valida que todo encaja.
**Dependencias:** F1, F2, F3, F4, F5.
**Estimación:** 0.5 sesión.

### Qué se hace

1. **Test E2E multi-chat** en `tests/test_v42_e2e.py`:
   - Procesar chat A (recovery completo) → bloques de A + metadata con A.
   - Procesar chat B (recovery completo, caso 4) → bloques de B + metadata con A y B.
   - `query_context` encuentra info de ambos chats.
   - Los 4 archivos de recuperación reflejan el último chat procesado.

2. **Test E2E atajo de resúmenes** en `tests/test_v42_e2e.py`:
   - Procesar un chat con bloques que tienen `RESUMEN:`.
   - `query_context` con pregunta genérica → devuelve el resumen directamente (sin subagente).
   - `query_context` con pregunta específica → lanza subagente.

3. **Verificación final**:
   ```bash
   # Tests atómicos
   cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/tests/run_all_tests.py
   
   # Test E2E v4.2 (ampliado con los nuevos tests)
   cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/tests/test_v42_e2e.py
   
   # Lint
   cd /home/z/my-project && bun run lint
   ```
   Todos deben pasar.

### Archivos intervenidos

1. `tests/test_v42_e2e.py`:
   - +2 tests E2E (multi-chat + atajo de resúmenes).
   - Actualizar el contador de tests en `main()`.

---

## Orden de ejecución

| Fase | Sesión estimada | Dependencias |
|---|---|---|
| F1 — Lógica de decisión de 4 casos en Orchestrator | Sesión 19 (0.5) | ninguna |
| F2 — Soporte multi-chat en metadata | Sesión 20 (1.0) | F1 |
| F3 — IncrementalCycle arreglado | Sesión 20 (1.0) | F2 |
| F4 — 3 sistemas de indexado conectados | Sesión 21 (1.5) | F2, F3 |
| F5 — Subagentes cableados por defecto | Sesión 21 (0.5) | F1 |
| F6 — Tests E2E y verificación final | Sesión 21 (0.5) | F1, F2, F3, F4, F5 |

**Total estimado:** 5 sesiones.

## Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| La migración automática de metadata vieja a nueva rompe workspaces existentes | Media | Alto | Los tests de F2 verifican la migración. Se hace backup del `_metadata.json` antes de migrar. |
| El reempaquetado selectivo del IncrementalCycle no cubre todos los casos | Media | Medio | Los tests de F3 verifican que solo se reempaquetan los temas afectados. |
| El atajo de resúmenes en query_context devuelve respuestas incompletas | Media | Medio | El test de F4 verifica que solo se usa el atajo para preguntas genéricas; para específicas se lanza subagente. |
| Cablear los subagentes por defecto hace más lento el recovery (más tareas pendientes) | Baja | Bajo | Las tareas son diferidas (vía `_pending_tasks.json`), no bloquean el flujo principal. |
| El soporte multi-chat en metadata complica el export/import de contexto | Baja | Medio | El exporter/importer se actualiza para soportar el formato nuevo. |

---

**Fin del plan v4.4.**
