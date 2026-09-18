# contexto_zai/Documentación/plan_refactorizacion_v4.5.md
# Plan v4.5 — Índices multi-bloque + 03 ampliado + eliminación de 04_resumenes

**Versión:** 4.5
**Fecha:** 2026-09-18
**Autor:** Agente CZAI (Sesión 19, con consenso del Director)
**Estado:** Pendiente de validación por el Director.
**Continúa de:** plan v4.4 (sistema de indexado consistente + multi-chat + subagentes cableados).
**Spec asociada:** spec_recuperacion_contexto_v4.5.md.

---

## Estructura del plan

El plan se organiza en 4 fases (F1–F4):

1. Cambiar el índice `tema_a_archivo` a multi-bloque y arreglar `registrar_tema()`.
2. Ampliar el `03_objetivo_proyecto.md` con los 3 componentes.
3. Eliminar el `04_resumenes_bloques.md` y cambiar `query_context()` para leer resúmenes de los bloques.
4. Tests E2E y verificación final.

**Total de archivos nuevos:** 0.
**Total de archivos eliminados:** 1 (`generation/resumenes_generator.py`).
**Total de archivos intervenidos:** 5 (`models.py`, `generation/estado_generator.py`, `pipeline.py`, `generation/indice_generator.py`, `tests/test_v42_e2e.py`).
**Tests nuevos:** 5 atómicos + 2 E2E.

---

## F1 — Índice `tema_a_archivo` multi-bloque + `registrar_tema()` arreglado

**Prioridad:** ALTA — es el bug bloqueante que impide procesar varios chats.
**Dependencias:** ninguna.
**Estimación:** 1 sesión.

### Qué se hace

1. **`RecoveryMetadata.tema_a_archivo`** (`models.py`):
   - Pasa de `dict[str, str]` (tema → un archivo) a `dict[str, list[str]]` (tema → varios archivos).
   - **Migración automática**: si el `_metadata.json` tiene el formato viejo, se migra al leer (cada valor `str` se convierte en `[str]`).

2. **`registrar_tema()`** (`models.py`):
   - Si el tema no existe → crear entrada con `[archivo]`.
   - Si el tema existe y el archivo ya está en la lista → no hacer nada (idempotente).
   - Si el tema existe y el archivo no está → añadir a la lista.
   - **No revienta nunca.**

3. **`archivo_para_tema()`** (`models.py`):
   - Devuelve `list[str]` (lista de archivos) en vez de `str | None`.

4. **`tiene_tema()`** (`models.py`):
   - Sin cambios (sigue comprobando si la clave existe).

5. **`IndiceGenerator._build_tema_a_archivo()`** (`generation/indice_generator.py`):
   - Devuelve `dict[str, list[str]]` en vez de `dict[str, str]`.
   - El formato del `01_indice_recuperacion.md` se actualiza para mostrar cada tema con todos sus bloques.

6. **Sitios que usan `tema_a_archivo`** (verificar y ajustar):
   - `pipeline.py` (`query_context`): busca candidatos — ahora puede encontrar varios bloques por tema.
   - `process/incremental_cycle.py`: actualiza metadata tras reempaquetar.
   - `coordinador/integrador_respuestas.py`: registra temas de bloques externos.
   - `process/recovery_cycle.py`: registra temas tras clasificar.
   - `generation/indice_generator.py`: genera el índice legible.

### Tests individuales

- Test: `registrar_tema()` con tema nuevo → crea `[archivo]`.
- Test: `registrar_tema()` con tema existente en mismo archivo → idempotente.
- Test: `registrar_tema()` con tema existente en OTRO archivo → añade a la lista (no revienta).
- Test: `archivo_para_tema()` devuelve lista de varios archivos.
- Test: migración automática de formato viejo (`dict[str, str]` → `dict[str, list[str]]`).

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/models.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/indice_generator.py
```

---

## F2 — `03_objetivo_proyecto.md` ampliado

**Prioridad:** ALTA — el agente necesita saber quién es antes de recuperar.
**Dependencias:** ninguna.
**Estimación:** 0.5 sesión.

### Qué se hace

1. **`EstadoGenerator._asegurar_objetivo_proyecto()`** (`generation/estado_generator.py`):
   - El contenido que crea pasa de ser solo "el objetivo" a tener 3 componentes:
     - **Quién eres**: derivado de `estrategia/agent-context/identidad.md` o de los bloques.
     - **Cuál es tu norte**: derivado de `estrategia/agent-context/proyecto.md` o de la cascada (lo que ya estaba en v4.3 F5).
     - **Qué te pasó y cómo recuperarte**: template fijo con el camino del proceso.
   - Si el archivo ya existe, no se sobrescribe.

2. **El template del Componente 3** (qué te pasó y cómo recuperarte) es fijo:
   ```markdown
   ## Qué te pasó y cómo recuperarte

   Has perdido contexto. Esto es normal y tienes un proceso que te ayuda.

   1. Estás leyendo este archivo — ya empezaste a recuperarte.
   2. Lee `00_estado_actual.md` para saber qué estaba pasando.
   3. Consulta `01_indice_recuperacion.md` para saber dónde está cada tema.
   4. Revisa `02_decisiones_clave.md` para no repetir lo ya decidido.
   5. Si necesitas detalle de un tema, usa `query_context("tu pregunta")`.
   6. Si el proceso te dejó tareas pendientes, lánzalas y llama `collect_responses()`.
   7. Si el Director te pasa información nueva, usa `ampliar_contexto()`.
   ```

3. **El orden de lectura** de los 4 archivos se documenta en el `G1` (guía de uso) del `00_estado_actual.md`:
   - `03` primero, después `00`, después `01`, después `02`.

### Tests individuales

- Test: `03_objetivo_proyecto.md` creado automáticamente tiene los 3 componentes.
- Test: el Componente 3 (template fijo) está siempre presente.
- Test: si el archivo ya existe, no se sobrescribe.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/estado_generator.py
```

---

## F3 — Eliminar `04_resumenes_bloques.md` + `query_context()` lee de bloques

**Prioridad:** ALTA — eliminar lo que no debía existir.
**Dependencias:** F1.
**Estimación:** 0.5 sesión.

### Qué se hace

1. **Eliminar** `generation/resumenes_generator.py`.

2. **Eliminar** `_buscar_en_resumenes()` de `pipeline.py`.

3. **Eliminar** el modo `resumen_atajo` de `query_context()` en `pipeline.py`.

4. **Añadir** a `query_context()` la lectura directa de `RESUMEN:` de los bloques candidatos:
   - Después de identificar los bloques candidatos (por `tema_a_archivo`), antes de preparar prompts para subagentes:
   - Lee cada bloque candidato físicamente.
   - Busca el campo `RESUMEN:` al inicio de línea.
   - Si un resumen contiene las palabras de la pregunta → se lo entrega al agente como parte de la respuesta (atajo, sin subagente).
   - Si ningún resumen responde → prepara prompts para subagentes como antes.

5. **El `01_indice_recuperacion.md`** ya no referencia `04_resumenes_bloques.md` en su guía.

### Tests individuales

- Test: `query_context()` lee `RESUMEN:` directamente de un bloque físico y lo entrega como atajo.
- Test: si el bloque no tiene `RESUMEN:`, `query_context()` prepara prompts para subagente.
- Test: si varios bloques candidatos tienen `RESUMEN:` que responde, se entregan todos.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/pipeline.py
```

---

## F4 — Tests E2E y verificación final

**Prioridad:** ALTA — valida que todo encaja.
**Dependencias:** F1, F2, F3.
**Estimación:** 0.5 sesión.

### Qué se hace

1. **Test E2E multi-chat con temas comunes** en `tests/test_v42_e2e.py`:
   - Simular 2 chats con un tema común (`configuracion_proyecto`).
   - Registrar el tema en bloques de ambos chats.
   - Verificar que `tema_a_archivo` apunta a los 2 bloques.
   - Verificar que `registrar_tema()` no revienta.
   - Verificar que `query_context()` encuentra ambos bloques.

2. **Test E2E `03` ampliado** en `tests/test_v42_e2e.py`:
   - Crear `03_objetivo_proyecto.md` automáticamente.
   - Verificar que tiene los 3 componentes.
   - Verificar que el Componente 3 (template fijo) está siempre presente.

3. **Verificación final**:
   ```bash
   cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/tests/run_all_tests.py
   cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/tests/test_v42_e2e.py
   cd /home/z/my-project && bun run lint
   ```
   Todos deben pasar.

### Archivos intervenidos

1. `tests/test_v42_e2e.py`:
   - +2 tests E2E (multi-chat con temas comunes + `03` ampliado).
   - Actualizar tests anteriores que asumían `tema_a_archivo` como `dict[str, str]`.

---

## Orden de ejecución

| Fase | Sesión estimada | Dependencias |
|---|---|---|
| F1 — Índice multi-bloque + `registrar_tema()` | Sesión 19 (1.0) | ninguna |
| F2 — `03_objetivo_proyecto.md` ampliado | Sesión 19 (0.5) | ninguna |
| F3 — Eliminar `04_resumenes` + `query_context()` lee de bloques | Sesión 19 (0.5) | F1 |
| F4 — Tests E2E + verificación final | Sesión 19 (0.5) | F1, F2, F3 |

**Total estimado:** 2.5 sesiones.

## Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| Cambiar `tema_a_archivo` de `str` a `list[str]` rompe sitios que lo usan | Alta | Alto | Auditar todos los sitios que lo usan antes de tocar. Tests individuales por cada sitio. |
| El `03` ampliado no encuentra la documentación del proyecto | Media | Bajo | Cascada documentación → bloques → contenido mínimo (ya implementado en v4.3 F5). |
| `query_context()` lee bloques físicos y es lento | Baja | Medio | Solo lee el `RESUMEN:` (primeras líneas), no el bloque completo. |
| Los tests existentes asumen `dict[str, str]` | Alta | Medio | Actualizar los tests afectados en F4. |

---

**Fin del plan v4.5.**
