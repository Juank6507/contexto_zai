# contexto_zai/Documentos/plan_refactorizacion_v6.8.md
# Plan v6.8 — Enriquecimiento confiable + clasificación jerárquica de temas

**Versión:** 6.8
**Fecha:** 2026-10-05
**Estado:** Pendiente.
**Continuación de:** plan v6.7.
**Spec asociada:** spec_recuperacion_contexto_v6.8.md

## Objetivo

Implementar la spec v6.8: 4 cambios para que el enriquecimiento en cascada
finalmente funcione (o falle con error visible), elimine el parche de temas
provisionales, y lo reemplace por clasificación jerárquica generada por el
enriquecimiento.

## Fases

### F1 — Restaurar `_normalizar_bloques_externos` + separar imports + no ocultar errores

**Archivos:** `pipeline.py`, `generation/contexto_generator.py`.

**Qué se hace:**
1. Definir `_normalizar_bloques_externos(workspace_dir)` en `pipeline.py`:
   - Limpia nombres de tema en `_metadata.json`: aplica codificación jerárquica,
     elimina prefijos contaminados de versiones anteriores.
2. En `contexto_generator.py._post_procesar()`:
   - Importar cada función por separado (no en un solo `import`).
   - Si una falla, loguear ERROR y continuar con las demás.
   - Eliminar el `try/except Exception` que envuelve todo el bloque.

**Tests:** `__main__` de `contexto_generator.py`. Verificar que el
post-procesamiento no falla aunque una función no exista, y que los errores
son visibles (no ocultos).

### F2 — Eliminar try/except silencioso en collect_responses()

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. En `collect_responses()`, eliminar el `try/except Exception` que se traga
   errores del enriquecimiento.
2. Si el enriquecimiento falla, el error se propaga al resultado.
3. Si el Worker Bun falla, generar `pending_tasks` para subagentes de fallback
   (eso ya está implementado, pero el try/except lo ocultaba).

**Tests:** `__main__` de `pipeline.py`. Verificar que `collect_responses()`
propaga el error cuando el enriquecimiento falla (no lo oculta).

### F3 — Eliminar temas provisionales de títulos de sección

**Archivos:** `coordinador/integrador_respuestas.py`.

**Qué se hace:**
1. Eliminar el bloque de código que infiere temas tentativos de los títulos
   de sección (`## Sección N — <título>`).
2. El bloque se crea con tema provisional genérico (`documento_externo_NN`).
3. El enriquecimiento (F4) generará los temas definitivos.
4. Esto elimina de raíz los 3 bugs del APA (truncamiento, prefijos
   contaminados, duplicados por prefijo).

**Tests:** `__main__` de `integrador_respuestas.py`. Verificar que el bloque
se crea con tema genérico, no con temas inferidos de títulos.

### F4 — Enriquecimiento genera temas jerárquicos (CAMBIO ARQUITECTÓNICO)

**Archivos:** `pipeline.py`, `mini-services/worker-cascade/index.ts`,
`coordinador/integrador_respuestas.py`, `models.py`.

**Qué se hace:**

1. **Cambiar el prompt de extracción de temas:**
   - Worker 4 en `mini-services/worker-cascade/index.ts`.
   - Subagente fallback en `pipeline.py` (función `_construir_pending_task_para_bloque`).
   - Ambos prompts piden:
     * Leer el RESUMEN del bloque.
     * Revisar los temas existentes en `_metadata.json`.
     * Si un tema existente cubre el contenido → añadir el bloque a ese tema.
     * Si no → crear un tema nuevo con nombre corto y significativo.
     * Si el contenido abarca ideas distintas → generar subtemas.
     * La subdivisión la determina el contenido, no el tamaño.
   - Ambos caminos usan el mismo prompt.

2. **Codificación jerárquica de temas:**
   - Un tema tiene un nombre corto y significativo (`autenticacion_jwt`).
   - Un subtema indica su padre con notación jerárquica
     (`autenticacion_jwt.firma_token`), no con prefijos largos.
   - El `tema_a_archivo` mapea cada tema/subtema a su bloque.
   - No se usan prefijos como `grande_ampliar_apa_03_txt_<tema>`.

3. **El integrador aplica los temas generados:**
   - Lee los resultados del enriquecimiento (de `_responses/` o de las
     `pending_tasks` resueltas).
   - Actualiza `tema_a_archivo` reemplazando los temas provisionales por
     los definitivos con estructura jerárquica.

4. **El índice refleja la jerarquía:**
   - Muestra temas agrupados con sus subtemas, como un catálogo de biblioteca.

**Tests:** `__main__` de `pipeline.py` e `index.ts`. Verificar que el
prompt pide clasificación jerárquica y revisión de temas existentes.

### F5 — Tests con datos reales para cada intervención

**Archivos:** `tests/test_v42_e2e.py`, `__main__` de cada script intervenido.

**Qué se hace:**
Los tests y validaciones de cada script intervenido deben reflejar y validar
cada una de las intervenciones con datos reales (no mocks que ocultan los
bugs). Cada test reproduce las condiciones reales que produjeron los bugs
detectados por el agente APA.

1. **Test F1 (import roto + error oculto):** verificar con datos reales que:
   - El post-procesamiento de `ContextoGenerator` no falla aunque una función
     no exista.
   - Si una función falla, el error es visible (log ERROR, no WARNING oculto).
   - Las funciones que sí existen se ejecutan aunque una falle.
   - Datos reales: workspace con bloques sin RESUMEN, invocar
     `ContextoGenerator.ejecutar()` y verificar que el enriquecimiento corre
     (o falla con error visible).

2. **Test F2 (try/except silencioso en collect_responses):** verificar con
   datos reales que:
   - `collect_responses()` propaga el error cuando el enriquecimiento falla.
   - Si el Worker Bun no está disponible, genera `pending_tasks` para
     subagentes de fallback.
   - Datos reales: documento APA procesado, `collect_responses()` invocado
     con proxy no disponible, verificar que el resultado contiene
     `pending_tasks` y no oculta el error.

3. **Test F3 (eliminar temas tentativos):** verificar con datos reales que:
   - El bloque se crea con tema genérico, no con temas inferidos de títulos.
   - No hay truncamiento a 50 chars.
   - No hay prefijos `grande_ampliar_`.
   - Datos reales: documento con secciones de título largas (como las del
     APA 01), verificar que el bloque no tiene temas truncados ni
     contaminados.

4. **Test F4 (clasificación jerárquica):** verificar con datos reales que:
   - El enriquecimiento genera temas con nombres cortos y significativos.
   - El enriquecimiento revisa temas existentes antes de crear nuevos.
   - Si un tema existente cubre el contenido, añade el bloque a ese tema.
   - Si el contenido abarca ideas distintas, genera subtemas jerárquicos.
   - No hay duplicados por prefijo.
   - Datos reales: dos documentos que tratan el mismo tema (como APA 01 y
     APA 03 que ambos hablan de autenticación), verificar que el segundo
     enriquece el tema existente en vez de crear uno duplicado.

5. **Test de regresión (bugs del APA):** verificar con datos reales que los
   3 bugs + Bug 7 no se reproducen:
   - Bug 1: no hay nombres cortados a mitad de palabra.
   - Bug 2: no hay `grande_ampliar_apa_03_txt_` en los temas.
   - Bug 3: dos temas donde uno es prefijo del otro se tratan como el mismo
     tema o se renombran distintivamente.
   - Bug 7: los bloques tienen RESUMEN al inicio tras el enriquecimiento.
   - Datos reales: reproducir exactamente las condiciones del agente APA
     (filename `APA 01.txt`, `APA 03.txt`, `APA 04.txt` con contenido real).

**Tests:** ejecución de `test_v42_e2e.py` y de los `__main__` de cada script
intervenido. Todos deben pasar con datos reales.

### F6 — Validación end-to-end

**Qué se hace:**
1. Ejecutar todos los `__main__` atómicos.
2. Ejecutar los 30+ tests E2E de `test_v42_e2e.py`.
3. Validar con el agente APA procesando APA 01/03/04.txt:
   - Bloques con RESUMEN al inicio.
   - `_responses/` con los 4 archivos por bloque.
   - Temas con nombres cortos y significativos (no truncados, no
     contaminados, no duplicados).
   - Estructura jerárquica de temas y subtemas en el índice.
   - Si el Worker Bun no está disponible, el agente recibe `pending_tasks`
     y puede lanzar subagentes de fallback.
   - Si algo falla, el error es visible (no oculto).

---

**Fin del plan v6.8.**
