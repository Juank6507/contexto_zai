# contexto_zai/spec_recuperacion_contexto_v3.4.md -- Spec v3.4: links externos, clasificacion por capas, estado sin truncado, exportacion/importacion de contexto.
<!-- Destino en el proyecto: /home/z/my-project/spec_recuperacion_contexto_v3.4.md -->

# SPEC — Sistema de Recuperación de Contexto para Agentes Z.ai

**Versión:** 3.4
**Fecha:** 2026-09-05
**Autor:** Director (diseño) + Agente CZAI (especificación)
**Estado:** v3.4 — Cuatro fixes sobre v3.3: (1) links externos como contexto del chat, (2) clasificación temática por capas con subagentes, (3) estado actual con truncamiento lógico, (4) exportación e importación de contexto entre agentes.

**Cambios de v3.3 → v3.4:**
1. **Links externos:** el Director puede escribir un link en el chat y el proceso lo detecta, lo lee y lo procesa como un intercambio más.
2. **Clasificación por capas:** el tema "general" se descompone en temas reales basándose en la intención del usuario, apoyándose en subagentes.
3. **Estado sin truncado:** si el contenido del tema activo supera el límite, se hace truncamiento lógico (resumir la parte excluida y añadirla al final, manteniendo orden cronológico).
4. **Exportación/importación de contexto:** el contexto completo del proyecto se puede empaquetar, guardar y recuperar por otro agente de forma íntegra y automática.

---

## 1-7. (Sin cambios respecto a v3.3)

Las secciones 1 a 7 (problema, solución, definiciones, restricciones, arquitectura, detección, flujo de 13 pasos) se mantienen idénticas a v3.3. Solo cambian las secciones afectadas por los cuatro fixes.

---

## 8. Archivos temáticos — arquitectura

### 8.1-8.5. (Sin cambios respecto a v3.3)

### 8.6. Detección de código y versionado de scripts (Sin cambios respecto a v3.3)

### 8.7. Links externos como contexto (NUEVO en v3.4)

El Director puede entregar un link (URL de un artículo, metodología o documento) escribiéndolo en el chat. El proceso lo detecta, lo lee y lo procesa exactamente igual que como procesa los mensajes de Z.ai.

**Detección de links:**

Durante la extracción (Paso 5), el proceso escanea los mensajes del Director buscando URLs que empiecen con `http://` o `https://`. Cuando encuentra un link, lo procesa:

1. **Lee el contenido del link** (descarga la página y la convierte a texto plano).
2. **Crea un intercambio virtual** con el contenido del link como respuesta del agente.
3. **Clasifica el intercambio** por tema (igual que cualquier otro intercambio).
4. **Lo incluye en los bloques temáticos** para que los subagentes puedan consultarlo.

**El link se procesa como parte del chat, no como contenido externo aparte.** El agente no distingue entre un mensaje de Z.ai y un link externo procesado: ambos son intercambios clasificados y almacenados en bloques.

### 8.8. Clasificación temática por capas (NUEVO en v3.4)

El tema "general" es demasiado grande y vago. Se añade una capa de clasificación que lo descompone en temas reales basándose en la intención del usuario.

**Capa 1 — Clasificación léxica (existente):**

El clasificador actual asigna temas por keywords. Si un mensaje no coincide con ningún tema específico, se asigna a "general".

**Capa 2 — Descomposición de "general" por intención (NUEVA):**

Cuando un intercambio se clasifica como "general", entra en una segunda capa que analiza la intención del usuario para asignarle un tema real:

- **`solicitud_documentacion`**: "describe", "explica", "paso a paso", "dime qué entiendes".
- **`solicitud_implementacion`**: "implementa", "ejecuta", "a ejecutar", "a implementar".
- **`aprobacion`**: "correcto", "aprobado", "ok", "adelante".
- **`rechazo`**: "no estoy de acuerdo", "incorrecto", "no sirve".
- **`correccion`**: "no lo que te pedí", "mejor hacer", "en lugar de".
- **`consulta_estado`**: "cómo vamos", "estado", "qué falta".
- **`handoff`**: "relee el worklog", "perdiste contexto".
- **`priorizacion`**: "entrega primero", "necesito que".
- **`configuracion_proyecto`**: "worklog", "repo", "estrategia".

**Capa 3 — Subagentes discriminadores (NUEVA):**

Cuando el tema "general" (o cualquier subtema derivado de él) sigue siendo demasiado grande, el proceso lanza un subagente que lee todo el contenido del tema y propone una subdivisión en temas más específicos basándose en el contenido real.

El subagente:
1. Lee todos los intercambios del tema "general".
2. Identifica qué se está discutiendo realmente en cada intercambio.
3. Propone temas específicos para cada grupo de intercambios.
4. El proceso reasigna los intercambios a los nuevos temas.

Esto reduce el contexto "general" a temas reales y específicos que el agente puede consultar con precisión.

### 8.9. El índice controla todo (Sin cambios respecto a v3.3)

---

## 9. Los tres archivos de recuperación

### 9.1. `00_estado_actual.md` (MODIFICADO en v3.4)

**Propósito:** Snapshot operativo con contexto completo del tema activo. Cero truncado.
**Tamaño máximo:** 20K tokens (~70KB)
**Lo lee:** El agente principal directamente al recuperar contexto.

**Estructura obligatoria — 8 secciones D1-D4 + A1-A4:**

(Sin cambios respecto a v3.3 en la estructura de las 8 secciones.)

**Truncamiento lógico (NUEVO en v3.4):**

Si el contenido del tema activo supera los 20K tokens, el proceso aplica truncamiento lógico:

1. Identifica la parte del contenido que NO cabe en el límite (la parte más antigua del tema).
2. Resume esa parte sin perder información clave (decisiones, archivos, errores, rutas).
3. Añade el resumen al final del estado actual, después de las 8 secciones, en una sección adicional:

```markdown
## Resumen del contexto excluido (truncamiento lógico)

**Período excluido:** YYYY-MM-DD → YYYY-MM-DD
**Motivo:** El contenido del tema activo supera los 20K tokens.

{Resumen del contenido excluido, manteniendo orden cronológico}
```

4. El orden cronológico del tema siempre se mantiene: primero el contenido más reciente (que cabe en el límite), luego el resumen del contenido más antiguo (que no cabía).

**Principio:** Cero truncado a secas. La información nunca se descarta, se resume y se añade al final. El contexto tiene que ser revelador, exacto y completo.

**Con Fix 2 implementado, será menos probable que esto ocurra** porque el tema "general" se descompondrá en temas más pequeños. Pero si aun así ocurre (un tema específico muy grande), el truncamiento lógico garantiza que no se pierde información.

### 9.2. `01_indice_recuperacion.md` (Sin cambios respecto a v3.3)

### 9.3. `02_decisiones_clave.md` (Sin cambios respecto a v3.3)

---

## 10. Patrones de subagentes

### 10.1-10.4. (Sin cambios respecto a v3.3)

### 10.5. Subagente de retroceso de versiones (Sin cambios respecto a v3.3)

### 10.6. Subagente discriminador de temas (NUEVO en v3.4)

Cuando el tema "general" (o cualquier tema) sigue siendo demasiado grande después de la clasificación por intención, el proceso lanza un subagente discriminador:

1. Lee todos los intercambios del tema.
2. Identifica qué se está discutiendo realmente en cada intercambio.
3. Propone temas específicos para subdividir el tema grande.
4. El proceso reasigna los intercambios a los nuevos temas.

**Ciclo de vida:**
- Se lanza cuando un tema supera el límite de tokens del bloque.
- Lee el contenido del bloque del tema.
- Devuelve una propuesta de subdivisión con nombres de temas reales.
- Se cierra.
- El proceso aplica la subdivisión y reclasifica los intercambios.

---

## 11-16. (Sin cambios respecto a v3.3)

---

## 17. Exportación e importación de contexto (NUEVO en v3.4)

### 17.1. Objetivo

El contexto completo del proyecto (estado, índice, decisiones, bloques, metadata, grafos de cambios) debe poder empaquetarse, guardarse y recuperarse por otro agente de forma íntegra y automática.

Esto permite que la memoria de un proyecto persista entre sesiones, entre agentes y entre chats sin perder información.

### 17.2. Qué se exporta

El paquete de exportación contiene:

1. **Todos los archivos del contexto:**
   - `00_estado_actual.md`
   - `01_indice_recuperacion.md`
   - `02_decisiones_clave.md`
   - `bloque_01.md` a `bloque_NN.md`
   - `_metadata.json`
   - `_grafos_cambios.json` (si existe)

2. **Instrucciones de recuperación** (`_instrucciones_recuperacion.md`):
   - Indicaciones precisas para el agente nuevo de cómo cargar y usar el contexto.
   - Qué leer primero, qué leer después, cómo lanzar subagentes.
   - El protocolo de recuperación paso a paso.

3. **Metadata del paquete** (`_paquete.json`):
   - `chat_id` origen
   - `fecha_exportacion`
   - `total_intercambios`
   - `total_temas`
   - `total_archivos`
   - `version_spec` (versión de la spec con la que se generó)

### 17.3. Formato de exportación

Un único archivo empaquetado `.zip` que contiene todos los archivos en un directorio raíz:

```
contexto_exportado_<chat_id>_<fecha>.zip
├── _paquete.json
├── _instrucciones_recuperacion.md
├── 00_estado_actual.md
├── 01_indice_recuperacion.md
├── 02_decisiones_clave.md
├── _metadata.json
├── _grafos_cambios.json (si existe)
├── bloque_01.md
├── bloque_02.md
└── ...
```

### 17.4. Dónde se guarda

- Por defecto en `/home/z/my-project/download/`.
- El Director puede indicar otra carpeta.
- No requiere ir a un repositorio. El agente nuevo puede extraerlo de la carpeta donde se encuentre.

### 17.5. Importación automática

Cuando un agente nuevo lee el worklog y encuentra el Paso 2b, busca automáticamente si existe un paquete de contexto exportado:

1. Busca archivos `contexto_exportado_*.zip` en `download/` o en la carpeta indicada.
2. Si encuentra un paquete, lo descomprime en `/home/z/my-project/contexto_recuperacion/`.
3. Lee `_instrucciones_recuperacion.md` para saber cómo usar el contexto.
4. Lee `00_estado_actual.md` para saber dónde quedó el proyecto.
5. Lee `01_indice_recuperacion.md` para saber qué temas hay y en qué bloque están.
6. Si necesita detalle, lanza subagentes con `Task` que lean los bloques.

### 17.6. Versionado

No hay versionado. Cada exportación reemplaza la anterior. Se exporta la memoria del proyecto completo hasta ese instante. Si se necesita conservar una exportación anterior, el Director la guarda manualmente antes de hacer una nueva.

### 17.7. Cuándo se exporta

- **Cierre de sesión:** el agente exporta el contexto antes de cerrar la sesión (Paso 13 del flujo).
- **Indicación explícita del Director:** "exporta el contexto" o "guarda el contexto".
- **Antes de una activación del proceso:** para tener un punto de recuperación.

---

## 14. Cambios pendientes respecto al código actual (v3.3)

1. **Crear `client/web_reader.py`** (nuevo atómico): lee contenido de una URL y lo convierte en texto plano. Detecta URLs en mensajes del Director.
2. **Modificar `processing/exchange_builder.py`**: cuando detecta un link en un mensaje del Director, usa `web_reader` para leerlo y crea un intercambio virtual con el contenido del link.
3. **Crear `processing/intention_classifier.py`** (nuevo atómico): Capa 2 de clasificación por intención.
4. **Modificar `processing/classifier.py`**: integrar Capa 2 de clasificación por intención.
5. **Crear `subagents/discriminator_subagent.py`** (nuevo atómico): subagente que lee un tema grande y propone subdivisión en temas específicos.
6. **Modificar `process/recovery_cycle.py`**: invocar el subagente discriminador (Capa 3) cuando un tema sigue siendo demasiado grande.
7. **Modificar `generation/estado_generator.py`**: reemplazar el truncado actual por truncamiento lógico (resumir la parte excluida y añadirla al final).
8. **Modificar `config.py`**: añadir patrones de detección de URLs y temas de intención.
9. **Crear `context/exporter.py`** (nuevo atómico): empaqueta todos los archivos del contexto en un `.zip` con instrucciones de recuperación.
10. **Crear `context/importer.py`** (nuevo atómico): descomprime un paquete de contexto exportado y lo carga en el workspace.
11. **Modificar `pipeline.py`**: añadir funciones `export_context()` y `import_context()`.
12. **Modificar `worklog_template.md`**: documentar exportación/importación de contexto en el Paso 2b.
