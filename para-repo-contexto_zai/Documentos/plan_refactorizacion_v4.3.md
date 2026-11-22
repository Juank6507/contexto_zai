# Plan v4.3 — Implementación del `00_estado_actual.md` como punto de entrada ordenado

**Versión:** 4.3
**Fecha:** 2026-09-15
**Autor:** Agente CZAI (Sesión 18, con consenso del Director)
**Estado:** Pendiente de validación por el Director.
**Continúa de:** plan v4.2 (bibliotecario + unificación + links /s/ + fix Windows).
**Spec asociada:** spec_recuperacion_contexto_v4.3.md.

---

## Estructura del plan

El plan se organiza en 5 fases (F0–F4). Cada fase es independiente y entregable por separado. El orden respeta las dependencias:

0. Primero cerrar los dos huecos detectados por el agente APA (índice stale + deduplicación insuficiente).
1. Luego extender el subagente (nuevo modo `SINTESIS_CONTEXTO`).
2. Luego extender el integrador (handler `_integrar_sintesis_contexto`).
3. Luego intervenir el `EstadoGenerator` para ensamblar las 3 secciones nuevas.
4. Al final, validar con tests E2E.

**Total de archivos nuevos:** 0 (todas las extensiones viven en archivos existentes — `IntercambiosClasificadorSubagent`, `IntegradorRespuestas`, `EstadoGenerator`).
**Total de archivos intervenidos:** 5 (`subagents/intercambios_clasificador_subagent.py`, `coordinador/integrador_respuestas.py`, `generation/estado_generator.py`, `tests/test_v42_e2e.py` y F0 toca `coordinador/integrador_respuestas.py` que ya está en la lista).
**Tests nuevos:** 6 atómicos + 1 E2E + 3 atómicos de F0.

---

## F0 — Cerrar huecos detectados por el agente APA

**Prioridad:** ALTA — son bugs que afectan a bloques nuevos y legacy.
**Dependencias:** ninguna.
**Estimación:** 0.5 sesión.

### F0.1 — Hueco 1: Invocar `IndiceGenerator` después de `_integrar_documento`

Intervenir `coordinador/integrador_respuestas.py`:

- `_integrar_documento()` después de actualizar `_metadata.json`, debe:
  1. Listar los bloques físicos del workspace (`bloque_*.md` + `bloque_externo_*.md`).
  2. Construir objetos `ThematicBlock` a partir de los archivos (o pasar los paths directamente).
  3. Invocar `IndiceGenerator.generate(blocks=..., metadata=metadata)` para regenerar `01_indice_recuperacion.md` con todos los bloques.
  4. Escribir el archivo actualizado en el workspace.
- Si el `IndiceGenerator` falla (por ejemplo, workspace sin bloques físicos), loguear warning y continuar — no rompe el flujo principal.

**Test individual nuevo** en `__main__` de `integrador_respuestas.py`:
- `_integrar_documento` actualiza `01_indice_recuperacion.md` con el bloque externo nuevo y sus temas reales.
- Verifica que el índice regenerado incluye la entrada `tema → bloque_externo_*.md`.

### F0.2 — Hueco 2: Mejorar deduplicación de temas en `_integrar_documento`

Intervenir `coordinador/integrador_respuestas.py`:

- La lógica actual (líneas 440-447):
  ```python
  for tema in temas_reales:
      clave = tema["nombre"]
      if clave in metadata["tema_a_archivo"]:
          clave = f"{filename}_{tema['nombre']}"
      metadata["tema_a_archivo"][clave] = bloque_filename
  ```
  se reemplaza por una función auxiliar `_resolver_clave_tema(tema_nombre, filename, bloque_filename, tema_a_archivo)` que implementa:
  - Si `tema_nombre` existe y apunta a `bloque_filename` → idempotente, devolver `tema_nombre` (no crear entrada nueva).
  - Si `tema_nombre` existe y apunta a otro bloque → intentar `{filename}_{tema_nombre}`.
  - Si `{filename}_{tema_nombre}` existe y apunta a `bloque_filename` → idempotente, devolver esa clave.
  - Si `{filename}_{tema_nombre}` existe y apunta a otro bloque → intentar `{filename}_{tema_nombre}_2`, `_3`, etc. hasta encontrar una libre o una idempotente.
  - Si ninguna existe → usar `tema_nombre` (caso normal, sin colisión).

**Tests individuales nuevos** en `__main__`:
- **Test:** reprocesar el mismo documento dos veces → no crea entradas fantasma (idempotente).
- **Test:** dos documentos distintos con un tema en común → el segundo se prefija con filename correctamente.
- **Test:** tres documentos distintos con el mismo tema → sufijo numérico (`filename_tema_2`, `filename_tema_3`).

### F0.3 — Bug 1 (crítico): Alinear prompts de `ProcesadorDocumento` con el parser

Intervenir `procesadores/procesador_documento.py`:

- `_build_documento_prompt()` y `_build_lote_prompt()` se modifican para pedir los 3 campos (`TEMA:` + `DESCRIPCION:` + `SECCIONES:`), alineándose con el formato del `DocumentoIndexerSubagent._build_prompt_historico()`.
- **Antes** (prompt pide 2 campos):
  ```
  TEMA: <nombre del tema>
  DESCRIPCION: <descripción breve>
  ```
- **Después** (prompt pide 3 campos, alineado con `DocumentoIndexerSubagent`):
  ```
  TEMA: <nombre_snake_case>
  DESCRIPCION: <descripción corta del tema>
  SECCIONES: <sección1, sección2, sección3>
  ```
- El parser `_parse_temas_documento()` del `IntegradorRespuestas` **no se modifica** — ya estaba bien, exige los 3 campos.
- El orden del prompt cambia: primero los bloques `TEMA/DESCRIPCION/SECCIONES`, después el `RESUMEN:`. Esto es para que el parser (que busca `TEMA:...SECCIONES:...`) funcione sin tener que saltar el resumen.

**Test individual nuevo** en `__main__` de `procesador_documento.py`:
- `_build_documento_prompt()` genera un prompt que pide `TEMA:`, `DESCRIPCION:` y `SECCIONES:`.
- `_build_lote_prompt()` idem.
- Verifica que el formato pedido coincide con el que exige `_parse_temas_documento()` del `IntegradorRespuestas`.

### Archivos intervenidos

1. `coordinador/integrador_respuestas.py`:
   - `_integrar_documento()`: +invocación al `IndiceGenerator` después de actualizar metadata (F0.1).
   - `_integrar_documento()`: +nueva función auxiliar `_resolver_clave_tema()` (F0.2).
   - +4 tests individuales en `__main__` (1 del Hueco 1 + 3 del Hueco 2).

2. `procesadores/procesador_documento.py` (F0.3):
   - `_build_documento_prompt()`: prompt actualizado para pedir 3 campos.
   - `_build_lote_prompt()`: idem.
   - +2 tests individuales en `__main__`.

### Detalle

- El `IndiceGenerator` se importa dentro del método para evitar dependencias circulares (igual que ya se hace con `ProcesadorIntercambios` en otros sitios).
- La función `_resolver_clave_tema()` es un método estático — atómico, sin estado, fácil de testear.
- Los tests usan workspaces temporales con bloques físicos simulados.
- **F0.3 es crítico para desbloquear la Vía C del agente APA.** Debe completarse antes de que el agente APA ejecute su reindexación de bloques legacy.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/coordinador/integrador_respuestas.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/procesadores/procesador_documento.py
```

Deben imprimir `[PASS]` con los 6 tests nuevos incluidos (4 de F0.1+F0.2 + 2 de F0.3).

---

## F1 — Extender `IntercambiosClasificadorSubagent` con modo `SINTESIS_CONTEXTO`

**Prioridad:** ALTA — es la base de la sección `G0.B`.
**Dependencias:** ninguna.
**Estimación:** 0.5 sesión.

### Qué se añade

1. **Entrada nueva en el enum `ModoClasificador`** (`subagents/intercambios_clasificador_subagent.py`):
   ```python
   # v4.3: sintetizar el panorama del proyecto a partir del contexto disponible.
   # Devuelve texto plano con un resumen ejecutivo del estado actual del proyecto.
   SINTESIS_CONTEXTO = "sintesis_contexto"
   ```

2. **Dispatch en `build_prompt()`** — añadir rama para `SINTESIS_CONTEXTO` que llama a `_prompt_sintesis_contexto()`.

3. **Dispatch en `parse_response()`** — añadir rama para `SINTESIS_CONTEXTO` que devuelve el texto plano (sin parseo específico, como en `RESUMEN_TRUNCADO`).

4. **Nuevo método `_prompt_sintesis_contexto()`** — construye el prompt que pide al subagente:
   - **Input que recibe el subagente (embebido en el prompt):**
     - La declaración de objetivo del proyecto (`03_objetivo_proyecto.md`) si existe.
     - El contenido actual del `00_estado_actual.md` (secciones operativas: D1, D4, A1, A2, A3, A4) — el agente lo pasa en `context["estado_actual_parcial"]`.
     - El contenido del `01_indice_recuperacion.md` (mapa de bloques) — `context["indice_parcial"]`.
     - El contenido del `02_decisiones_clave.md` (decisiones formales) — `context["decisiones_parcial"]`.
     - El resumen del bloque activo actual (ya disponible en `A1`).
     - Los resúmenes de otros bloques que el agente considere complementarios (los lee del `_metadata.json` y de los `RESUMEN:` en `bloque_externo_*.md`) — `context["resumenes_otros_bloques"]`.
   - **Output que pide al subagente:** un texto de máximo ~1.500 caracteres (≈500 tokens) que responde a: *"Dado todo lo que existe en el contexto del proyecto, ¿cuál es el panorama actual? ¿Qué temas están activos? ¿Qué se está decidiendo? ¿Qué falta por hacer?"*.
   - **Formato:** texto plano, sin headers markdown, sin prefijos como `SINTESIS:`.

5. **Tests individuales nuevos** en `__main__`:
   - **Test:** `SINTESIS_CONTEXTO` devuelve texto plano con un resumen del proyecto.
   - **Test:** `build_prompt` para `SINTESIS_CONTEXTO` incluye el objetivo del proyecto, el índice y las decisiones si se pasan en `context`.
   - **Test:** `build_prompt` para `SINTESIS_CONTEXTO` funciona aunque falten inputs opcionales (objetivo, resúmenes de otros bloques).

### Archivos intervenidos

1. `subagents/intercambios_clasificador_subagent.py`:
   - Enum `ModoClasificador`: +1 entrada.
   - `build_prompt()`: +1 rama en el dispatch.
   - `parse_response()`: +1 rama en el dispatch.
   - +1 método `_prompt_sintesis_contexto()`.
   - +3 tests individuales en `__main__`.

### Detalle

- El subagente NO necesita leer archivos externos — todo el contexto va embebido en el prompt. Esto es consistente con los otros modos del `IntercambiosClasificadorSubagent`.
- Si el agente pasa `context={"objetivo_proyecto": "..."}` vacío, el prompt lo indica claramente para que el subagente sepa que falta la declaración de objetivo.
- El límite de ~1.500 caracteres es una sugerencia en el prompt, no un truncado duro en el parser (la sintesis puede ser algo más larga si el subagente lo considera necesario).

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/subagents/intercambios_clasificador_subagent.py
```

Debe imprimir `[PASS]` con los 3 tests nuevos incluidos.

---

## F2 — Extender `IntegradorRespuestas` con handler `_integrar_sintesis_contexto`

**Prioridad:** ALTA — es donde se aplica la respuesta del subagente.
**Dependencias:** F1.
**Estimación:** 0.5 sesión.

### Qué se añade

1. **Mapeo en `_get_handler()`** (`coordinador/integrador_respuestas.py`):
   ```python
   elif "sintesis_contexto" in task_id:
       return self._integrar_sintesis_contexto
   ```

2. **Nuevo método `_integrar_sintesis_contexto(self, response, ws)`**:
   - Lee el `00_estado_actual.md` existente.
   - Si existe la sección `## G0.B — Síntesis del contexto disponible`, la reemplaza con la nueva síntesis.
   - Si no existe, la inserta después de `## G0.A — Objetivo del proyecto` (o al inicio si `G0.A` tampoco existe todavía).
   - Si el subagente respondió con `SIN_SINTESIS_POSIBLE` (caso de error o contexto insuficiente), deja el placeholder original sin modificar.
   - Devuelve `True` si actualizó, `False` si no.

3. **Tests individuales nuevos** en `__main__`:
   - **Test:** `_integrar_sintesis_contexto` inserta `G0.B` en un `00_estado_actual.md` sin la sección.
   - **Test:** `_integrar_sintesis_contexto` reemplaza `G0.B` existente con la nueva síntesis.
   - **Test:** `_integrar_sintesis_contexto` no modifica nada si el subagente respondió `SIN_SINTESIS_POSIBLE`.

### Archivos intervenidos

1. `coordinador/integrador_respuestas.py`:
   - `_get_handler()`: +1 rama en el mapeo.
   - +1 método `_integrar_sintesis_contexto()`.
   - +3 tests individuales en `__main__`.

### Detalle

- La sección `G0.B` en el archivo se identifica con el header `## G0.B — Síntesis del contexto disponible`. El handler usa regex para localizarla y reemplazarla.
- Si la respuesta del subagente excede los ~2.000 caracteres, el handler la trunca con un aviso `... (síntesis truncada por longitud)`.
- El handler es idempotente: llamarlo dos veces con la misma respuesta produce el mismo resultado.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/coordinador/integrador_respuestas.py
```

Debe imprimir `[PASS]` con los 3 tests nuevos incluidos.

---

## F3 — Intervenir `EstadoGenerator` para ensamblar las 3 secciones nuevas

**Prioridad:** ALTA — es donde se ensambla el archivo completo.
**Dependencias:** F1 (modo `SINTESIS_CONTEXTO` existe), F2 (handler existe, aunque el `EstadoGenerator` no lo llame — lo llama el `IntegradorRespuestas` después de `collect_responses()`).
**Estimación:** 1 sesión.

### Qué se añade

1. **Nuevo método `_build_g0_a(self, workspace_dir)`** en `EstadoGenerator`:
   - Lee `workspace_dir / "03_objetivo_proyecto.md"` si existe.
   - Devuelve el contenido como sección `## G0.A — Objetivo del proyecto`.
   - Si no existe, devuelve el placeholder: *"Objetivo del proyecto no declarado. Crea `03_objetivo_proyecto.md` en el workspace para que aparezca aquí."*

2. **Nuevo método `_build_g0_b(self, workspace_dir)`** en `EstadoGenerator`:
   - Devuelve la sección `## G0.B — Síntesis del contexto disponible` con el placeholder inicial: *"Síntesis del contexto no disponible. Ejecuta `pipeline.collect_responses()` para generarla."*
   - El contenido real lo inserta el `IntegradorRespuestas._integrar_sintesis_contexto()` después de `collect_responses()`.

3. **Nuevo método `_build_g1(self)`** en `EstadoGenerator`:
   - Devuelve la sección `## G1 — Cómo usar este contexto` con el texto fijo especificado en la spec v4.3 (sección 3.2).
   - Es un template hardcodeado, no depende del workspace.

4. **Nuevo método `_build_sintesis_contexto_task(self, recent, tema_actual, workspace_dir)`** en `EstadoGenerator`:
   - Prepara el contexto que el subagente necesita: lee `03_objetivo_proyecto.md`, `01_indice_recuperacion.md`, `02_decisiones_clave.md`, y los resúmenes de otros bloques del `_metadata.json`.
   - Llama a `ProcesadorIntercambios.procesar(modo="SINTESIS_CONTEXTO", intercambios=recent, context={...})` que publica la tarea vía el `Orquestador`.
   - El resultado se aplica después con `collect_responses()`.

5. **Intervención en `EstadoGenerator.generate()`**:
   - Antes de ensamblar el contenido final, llamar a `_build_g0_a()`, `_build_g0_b()` (placeholder) y `_build_g1()`.
   - Ensamblar el archivo en este orden:
     ```
     # Estado Actual del Proyecto
     
     ## G0.A — Objetivo del proyecto
     <contenido o placeholder>
     
     ## G0.B — Síntesis del contexto disponible
     <placeholder inicial>
     
     ## G1 — Cómo usar este contexto
     <texto fijo>
     
     ## D1 — Última instrucción del Director
     <contenido existente>
     
     ## D4 — Restricciones activas
     <contenido existente>
     
     ## A1 — Qué estaba haciendo el agente
     <contenido existente>
     
     ## A2 — Entregables producidos
     <contenido existente>
     
     ## A3 — Errores abiertos
     <contenido existente>
     
     ## A4 — Siguiente paso
     <contenido existente>
     ```
   - Preparar y publicar la tarea `SINTESIS_CONTEXTO` (igual que ya se preparan D4, A1, decisiones, nombres).

6. **Tests individuales nuevos** en `__main__`:
   - **Test:** el `00_estado_actual.md` generado incluye las 3 secciones nuevas (`G0.A`, `G0.B`, `G1`) en el orden correcto, antes de las secciones operativas.
   - **Test:** `G0.A` muestra el contenido de `03_objetivo_proyecto.md` cuando existe.
   - **Test:** `G0.A` muestra el placeholder cuando `03_objetivo_proyecto.md` no existe.
   - **Test:** `G0.B` muestra el placeholder inicial (la síntesis real la pone `collect_responses()`).
   - **Test:** `G1` contiene el texto fijo de la guía.
   - **Test:** las secciones operativas existentes (D1, D4, A1, A2, A3, A4) siguen funcionando sin cambios.

### Archivos intervenidos

1. `generation/estado_generator.py`:
   - +4 métodos nuevos (`_build_g0_a`, `_build_g0_b`, `_build_g1`, `_build_sintesis_contexto_task`).
   - `generate()`: ensamblaje en orden nuevo.
   - +6 tests individuales en `__main__`.

### Detalle

- El `EstadoGenerator` recibe el `workspace_dir` (ya lo tiene en `__init__` indirectamente vía los paths de output). Si no, se le pasa explícito.
- Los tests usan un workspace temporal con `03_objetivo_proyecto.md` presente y ausente, para cubrir ambos casos.
- Los tests verifican que las secciones operativas existentes no se rompen.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/estado_generator.py
```

Debe imprimir `[PASS]` con los 6 tests nuevos incluidos.

---

## F4 — Test E2E y verificación final

**Prioridad:** ALTA — valida que todo encaja.
**Dependencias:** F1, F2, F3.
**Estimación:** 0.5 sesión.

### Qué se hace

1. **Nuevo test E2E** en `tests/test_v42_e2e.py`:
   - **`test_sintesis_contexto_e2e()`** — valida el flujo completo:
     1. Crea un workspace temporal con `03_objetivo_proyecto.md` (objetivo ficticio).
     2. Llama a `ProcesadorIntercambios.procesar(modo="SINTESIS_CONTEXTO", ...)` con los contextos necesarios.
     3. Verifica que la tarea se publicó en `_pending_tasks.json`.
     4. Simula: el agente lanza el subagente y escribe una respuesta de síntesis en `_responses/`.
     5. Llama a `pipeline.collect_responses()`.
     6. Verifica que el `00_estado_actual.md` (creado antes con un `EstadoGenerator.generate()`) tiene la sección `G0.B` actualizada con la síntesis del subagente.
     7. Verifica que las secciones `G0.A` (objetivo), `G1` (guía) y las operativas (D1, D4, A1, etc.) siguen presentes y sin cambios.

2. **Verificación final:**
   ```bash
   # Tests atómicos
   cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/tests/run_all_tests.py
   
   # Test E2E v4.2 (ampliado con el nuevo test de síntesis)
   cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/tests/test_v42_e2e.py
   
   # Lint
   cd /home/z/my-project && bun run lint
   ```
   Todos deben pasar.

### Archivos intervenidos

1. `tests/test_v42_e2e.py`:
   - +1 test E2E `test_sintesis_contexto_e2e`.
   - Actualizar el contador de tests en `main()`.

### Detalle

- El test E2E no lanza subagentes reales — simula la respuesta del subagente escribiendo directamente en `_responses/`.
- El test verifica específicamente que la sección `G0.B` pasa del placeholder inicial al contenido de la síntesis.

---

## Orden de ejecución

| Fase | Sesión estimada | Dependencias |
|---|---|---|
| F0 — Cerrar huecos del agente APA (índice stale + deduplicación + bug prompt) | Sesión 18 (0.5) | ninguna |
| F1 — Extender `IntercambiosClasificadorSubagent` con `SINTESIS_CONTEXTO` | Sesión 18 (0.5) | ninguna |
| F2 — Extender `IntegradorRespuestas` con `_integrar_sintesis_contexto` | Sesión 19 (0.5) | F1 |
| F3 — Intervenir `EstadoGenerator` para ensamblar G0.A + G0.B + G1 | Sesión 19 (1.0) | F1, F2 |
| F4 — Test E2E y verificación final | Sesión 19 (0.5) | F1, F2, F3 |
| F5 — Creación automática de `03_objetivo_proyecto.md` (cascada doc→bloques) | Sesión 19 (0.5) | F3 |

**Total estimado:** 3.5 sesiones.

---

## F5 — Creación automática de `03_objetivo_proyecto.md`

**Prioridad:** ALTA — el Director establece que el proceso no debe dejar placeholders pidiendo al agente que cree archivos; si detecta que falta, lo crea.
**Dependencias:** F3 (EstadoGenerator tiene `workspace_dir`).
**Estimación:** 0.5 sesión.

### Qué se añade

1. **Nuevo método `_asegurar_objetivo_proyecto(self) -> None`** en `EstadoGenerator`:
   - Se ejecuta al inicio de `_build_g0_a()` si `03_objetivo_proyecto.md` no existe.
   - Aplica la cascada:
     - **Caso A (documentación):** lee en orden `estrategia/agent-context/proyecto.md`, `identidad.md`, `entorno.md`, y `upload/worklog_*.md` (relativos al workspace raíz). Extrae el objetivo declarado y lo escribe en `03_objetivo_proyecto.md`.
     - **Caso B (bloques):** si la documentación no aporta suficiente, lee `_metadata.json["tema_a_archivo"]`, los temas, y el primer párrafo de los bloques. Construye un objetivo tentativo con los 3-5 temas más representativos. Lo escribe con comentario de "derivado automáticamente".
     - **Caso C (sin fuentes):** si no hay ni documentación ni bloques, escribe `"Proyecto sin objetivo declarado. Edita este archivo para declararlo."`.
   - Si el archivo ya existe, **no lo sobrescribe** (la cascada solo se ejecuta la primera vez).

2. **Intervención en `_build_g0_a()`**:
   - Antes de leer el archivo, llama a `_asegurar_objetivo_proyecto()`.
   - Elimina el placeholder anterior *"Objetivo del proyecto no declarado..."* — ya no se usa, el archivo siempre existe después de la cascada.

3. **Tests individuales nuevos** en `__main__`:
   - **Test:** si `03_objetivo_proyecto.md` no existe, se crea automáticamente tras `generate()`.
   - **Test:** Caso A — si existe `estrategia/agent-context/proyecto.md`, el objetivo se deriva de ahí.
   - **Test:** Caso B — si no hay documentación pero hay bloques en `_metadata.json`, el objetivo se deriva de los temas.
   - **Test:** Caso C — si no hay ni documentación ni bloques, se escribe el contenido mínimo.
   - **Test:** si el archivo ya existe, no se sobrescribe.

### Archivos intervenidos

1. `generation/estado_generator.py`:
   - +1 método `_asegurar_objetivo_proyecto()`.
   - `_build_g0_a()`: +1 llamada al nuevo método al inicio.
   - +5 tests individuales en `__main__`.

### Detalle

- Las rutas de documentación son relativas al workspace raíz del proyecto (no al `workspace_dir` del proceso). El proceso busca en `WORKSPACE_ROOT/estrategia/agent-context/` y `WORKSPACE_ROOT/upload/`.
- `WORKSPACE_ROOT` ya existe en `config.py` — se reutiliza.
- Las regex de extracción del objetivo de la documentación son simples: primer párrafo no vacío que mencione "proyecto" o "objetivo".
- El Caso B no lanza subagentes — usa lectura directa de bloques para mantenerlo simple y rápido.
- Los tests usan workspaces temporales con documentación simulada y bloques simulados.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/estado_generator.py
```

Debe imprimir `[PASS]` con los 5 tests nuevos incluidos.

## Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| El `EstadoGenerator.generate()` queda en estado inconsistente tras añadir las secciones nuevas | Baja | Alto | Los tests individuales validan el ensamblaje antes de cerrar F3. |
| El subagente de síntesis devuelve texto demasiado largo (>2K chars) | Media | Bajo | El handler trunca con aviso visible. |
| El subagente no tiene suficiente contexto para generar una síntesis útil | Media | Medio | El prompt pide explícitamente que, si no hay suficiente contexto, responda `SIN_SINTESIS_POSIBLE`. El handler deja el placeholder sin modificar. |
| El `03_objetivo_proyecto.md` no existe en workspaces legacy | Alta | Bajo | El `EstadoGenerator._build_g0_a()` muestra un placeholder visible — no rompe nada. |
| Los tests existentes de `EstadoGenerator` fallan por el cambio de orden en el archivo | Media | Medio | Los tests de `EstadoGenerator` se actualizan en F3 para reflejar el nuevo orden. |

---

**Fin del plan v4.3.**
