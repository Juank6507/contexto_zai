# contexto_zai/Documentos/spec_recuperacion_contexto_v6.8.md
# Spec v6.8 — Enriquecimiento confiable + clasificación jerárquica de temas

**Versión:** 6.8
**Fecha:** 2026-10-05
**Estado:** Pendiente de implementación.
**Especifica continuación de:** spec v6.7.

## 1. Propósito

La v6.7 logró que los bloques contengan el contenido literal del documento, pero
el enriquecimiento en cascada nunca se ejecuta en el entorno real. Además, los
nombres de tema son un parche que produce 3 bugs detectados por el agente APA.
Esta spec corrige ambos problemas con un cambio arquitectónico: la clasificación
jerárquica de temas generada por el enriquecimiento.

## 2. Los 4 problemas a resolver

### Problema 1 — El enriquecimiento nunca arranca (import roto + error oculto)

`generation/contexto_generator.py` importa 3 funciones desde `pipeline.py` en
un solo bloque. Una de ellas (`_normalizar_bloques_externos`) no existe — se
perdió en un reset. El `ImportError` tira todo el bloque, las otras dos
funciones (que sí existen) nunca se llaman, y el `try/except Exception` oculta
el error silenciosamente.

**Consecuencia:** el post-procesamiento completo (enriquecer + consolidar
decisiones + normalizar) nunca corre.

### Problema 2 — El enriquecimiento en collect_responses() oculta errores

`pipeline.py` invoca el enriquecimiento dentro de un `try/except Exception`
que se traga cualquier error como `warning`. Si falla, el agente no se entera,
no recibe `pending_tasks` para ejecutar subagentes de fallback, y los bloques
quedan sin RESUMEN.

**Consecuencia:** los bloques no tienen RESUMEN al inicio y `_responses/`
está vacío.

### Problema 3 — Temas provisionales generados de títulos de sección (parche)

Como el enriquecimiento no corría, se añadió un parche que infiere temas de los
títulos de sección del documento. Esto produce 3 bugs detectados por el APA:
- Truncamiento a 50 chars en seco (nombres cortados a mitad de palabra).
- Prefijos contaminados (`grande_ampliar_apa_03_txt_<tema>`).
- Duplicados por prefijo (un tema es prefijo de otro y se ven como distintos).

**Causa raíz:** los nombres de tema NO deberían generarse de los títulos de
sección. Los genera el enriquecimiento después de leer el contenido del bloque.

### Problema 4 — No hay estructura jerárquica de temas

Hoy los temas son planos: una lista de strings en `tema_a_archivo`. Cuando hay
colisión, se resuelve añadiendo prefijos largos. No hay concepto de
tema → subtema → subtema más específico. No hay forma de organizar el contexto
como una biblioteca clasifica libros.

## 3. Los 4 principios rectores (ratificados + nuevos)

### Principio 1 — OOP para lo común
Crear, ampliar y actualizar contexto usan el mismo código vía `ContextoGenerator`.

### Principio 2 — Estructura uniforme del contexto
Un bloque es un bloque, sin importar el origen.

### Principio 3 — Los 4 archivos dependen de la cronología
Se generan cuando la información nueva permite identificar un "último
intercambio" cronológico que sea el más reciente.

### Principio 4 — Bloques secuenciales, índices abarcadores
Los bloques se llenan hasta 70K. El índice cubre cada intercambio.

### Principio 5 (NUEVO) — Los temas los genera el enriquecimiento
Los nombres de tema NO se generan de los títulos de sección ni del nombre del
archivo fuente. Los genera el enriquecimiento (Worker Bun o subagente de
fallback) después de leer el contenido del bloque.

### Principio 6 (NUEVO — CAMBIO ARQUITECTÓNICO) — Clasificación jerárquica
Los temas se estructuran como una biblioteca: tema → subtema → subtema más
específico. La subdivisión la determina el contenido del bloque a criterio del
agente que enriquece, no el tamaño. Antes de crear un tema nuevo, el
enriquecimiento revisa los existentes: si uno cubre el contenido, lo
enriquece; si no, crea uno nuevo.

Los temas se codifican jerárquicamente, no con prefijos largos. Un tema tiene
un nombre corto y significativo. Un subtema indica su padre en la jerarquía.
No se usan prefijos como `grande_ampliar_apa_03_txt_autenticacion_jwt`.

### Principio 7 (NUEVO) — El enriquecimiento puede ser Worker Bun o subagente
No siempre son Workers. Si el Worker Bun no está disponible o falla, el proceso
genera `pending_tasks` y el agente lanza subagentes de fallback. Ambos caminos
usan el mismo prompt y producen la misma estructura.

### Principio 8 (NUEVO) — No se tapa ni enmascara nada
Si algo falla, el error es visible. No hay `try/except` que se traga errores
silenciosamente. El agente tiene que saber qué falló para poder corregirlo.

## 4. Soluciones

### F1 — Restaurar `_normalizar_bloques_externos` + separar imports + no ocultar errores

**Archivos:** `pipeline.py`, `generation/contexto_generator.py`.

**Qué se hace:**
1. Definir `_normalizar_bloques_externos(workspace_dir)` en `pipeline.py`.
   Esta función limpia nombres de tema en `_metadata.json`: normaliza la
   estructura jerárquica, elimina prefijos contaminados que hayan quedado de
   versiones anteriores, y aplica la codificación jerárquica.
2. En `contexto_generator.py._post_procesar()`, importar cada función por
   separado (no en un solo `import`). Si una falla, loguear ERROR y continuar
   con las demás, pero no ocultar el error.
3. Eliminar el `try/except Exception` que envuelve todo el post-procesamiento.
   Si el enriquecimiento falla, el error sube.

### F2 — Eliminar try/except silencioso en collect_responses()

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. En `collect_responses()`, eliminar el `try/except Exception` que se traga
   errores del enriquecimiento. Si el enriquecimiento falla, el error se
   propaga al resultado para que el agente sepa que falló.
2. Si el Worker Bun falla, generar `pending_tasks` para subagentes de fallback
   (eso ya está implementado, pero el try/except lo oculta).
3. El agente recibe las `pending_tasks` y puede lanzar subagentes.

### F3 — Eliminar temas provisionales de títulos de sección

**Archivos:** `coordinador/integrador_respuestas.py`.

**Qué se hace:**
1. Eliminar el bloque de código que infiere temas tentativos de los títulos
   de sección (`## Sección N — <título>`).
2. El bloque se crea con un tema provisional genérico (`documento_externo_NN`).
3. El enriquecimiento (F4) generará los temas definitivos.
4. Esto elimina de raíz los 3 bugs del APA: truncamiento, prefijos
   contaminados, y duplicados por prefijo. Ya no se generan temas de los
   títulos de sección, así que no hay nada que truncar ni contaminar.

### F4 — Enriquecimiento genera temas jerárquicos (CAMBIO ARQUITECTÓNICO)

**Archivos:** `pipeline.py`, `mini-services/worker-cascade/index.ts`,
`coordinador/integrador_respuestas.py`, `models.py`.

**Qué se hace:**

1. **Cambiar el prompt de extracción de temas** (Worker 4 en index.ts y
   subagente fallback en pipeline.py) para que:
   - Lea el RESUMEN del bloque.
   - Revise los temas existentes en `_metadata.json` antes de crear nuevos.
   - Si un tema existente cubre el contenido → añada el bloque a ese tema.
   - Si no → cree un tema nuevo con nombre corto y significativo.
   - Si el contenido abarca ideas distintas → genere subtemas.
   - La subdivisión la determina el contenido, no el tamaño del bloque.
   - Ambos caminos (Worker Bun y subagente fallback) usan el mismo prompt.

2. **Codificación jerárquica de temas en el metadata:**
   - Un tema tiene un nombre corto y significativo (`autenticacion_jwt`).
   - Un subtema indica su padre con notación jerárquica
     (`autenticacion_jwt.firma_token`), no con prefijos largos.
   - El `tema_a_archivo` mapea cada tema/subtema a su bloque.
   - No se usan prefijos como `grande_ampliar_apa_03_txt_<tema>`.

3. **El integrador aplica los temas generados al metadata**, reemplazando los
   provisionales. Lee los resultados del enriquecimiento (de `_responses/` o
   de las `pending_tasks` resueltas) y actualiza `tema_a_archivo` con la
   estructura jerárquica.

4. **El índice refleja la jerarquía:** muestra temas agrupados con sus
   subtemas, como un catálogo de biblioteca.

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
   - `collect_responses()` propaga el error cuando el enriquecimiento falla
     (no lo oculta como WARNING).
   - Si el Worker Bun no está disponible, genera `pending_tasks` para
     subagentes de fallback (no se cuelga ni se oculta).
   - Datos reales: documento APA procesado, `collect_responses()` invocado
     con proxy mockeado como no disponible, verificar que el resultado
     contiene `pending_tasks` y no oculta el error.

3. **Test F3 (eliminar temas tentativos):** verificar con datos reales que:
   - El bloque se crea con tema genérico `documento_externo_NN`, no con
     temas inferidos de títulos de sección.
   - No hay truncamiento a 50 chars (porque no se generan temas de títulos).
   - No hay prefijos `grande_ampliar_` (porque no se generan temas de
     filenames).
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
   3 bugs detectados por el agente APA no se reproducen:
   - Bug 1 (truncamiento): no hay nombres cortados a mitad de palabra.
   - Bug 2 (prefijos contaminados): no hay `grande_ampliar_apa_03_txt_` en
     los temas.
   - Bug 3 (duplicados por prefijo): dos temas donde uno es prefijo del otro
     se tratan como el mismo tema o se renombran distintivamente.
   - Bug 7 (RESUMEN al inicio): los bloques tienen RESUMEN al inicio tras el
     enriquecimiento.
   - Datos reales: reproducir exactamente las condiciones del agente APA
     (filename `APA 01.txt`, `APA 03.txt`, `APA 04.txt` con contenido real
     de cada uno).

## 5. Archivos intervenidos

| Archivo | Cambio |
|---|---|
| `pipeline.py` | F1: definir `_normalizar_bloques_externos`. F2: eliminar try/except silencioso. F4: prompt del subagente fallback con clasificación jerárquica. |
| `generation/contexto_generator.py` | F1: separar imports + no ocultar errores. |
| `coordinador/integrador_respuestas.py` | F3: eliminar temas tentativos. F4: aplicar temas jerárquicos del enriquecimiento. |
| `mini-services/worker-cascade/index.ts` | F4: prompt de Worker 4 con clasificación jerárquica. |
| `models.py` | F4: posible soporte para estructura jerárquica en tema_a_archivo. |
| `tests/test_v42_e2e.py` | F5: tests para los 4 cambios. |

## 6. Flujo correcto tras v6.8

```
ampliar_contexto(fuente_externa)
│
├─ 1. Dividir documento en lotes de 70K tokens
├─ 2. Para cada lote:
│    └─ Subagente extrae contenido literal → escribe bloque_NN.md (70K)
│       con tema provisional genérico (documento_externo_NN)
│
├─ 3. collect_responses() integra las respuestas (sin ocultar errores)
│    └─ _integrar_documento() escribe bloque con contenido literal
│
└─ 4. collect_responses() invoca enriquecimiento (sin try/except silencioso):
     ├─ Worker 1 (o subagente fallback) lee bloque (70K) → RESUMEN → escribe al inicio
     ├─ Worker 4 (o subagente fallback) lee RESUMEN → genera temas jerárquicos:
     │    ├─ Revisa temas existentes en _metadata.json
     │    ├─ Si un tema cubre el contenido → añade bloque a ese tema
     │    ├─ Si no → crea tema nuevo con nombre corto y significativo
     │    └─ Si el contenido abarca ideas distintas → subtemas jerárquicos
     ├─ Workers 2-3 (o subagente fallback) leen RESUMEN → nombre + decisiones
     └─ Integrador aplica resultados a _metadata.json e índice
         (reemplaza temas provisionales por definitivos)
```

**Si el Worker Bun falla:** el error es visible. El proceso genera
`pending_tasks`. El agente lanza subagentes de fallback con el mismo prompt.
Los subagentes producen el mismo resultado que el Worker Bun.

**Si algo más falla:** el error sube. El agente se entera. No hay errores
ocultos.

---

**Fin de la spec v6.8.**
