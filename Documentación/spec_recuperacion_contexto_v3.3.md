# contexto_zai/spec_recuperacion_contexto_v3.3.md -- Spec del sistema de recuperacion de contexto con versionado de scripts.
<!-- Destino en el proyecto: /home/z/my-project/contexto_zai/spec_recuperacion_contexto_v3.3.md -->

# SPEC — Sistema de Recuperación de Contexto para Agentes Z.ai

**Versión:** 3.3
**Fecha:** 2026-09-04
**Autor:** Director (diseño) + Agente CZAI (especificación)
**Estado:** v3.3 — Añade detección de código, versionado de scripts con grafo de cambios reversible, y nombres propios para subtemas de scripts. Reemplaza la fragmentación mecánica de v3.2 por una clasificación basada en artefactos versionables.

**Cambios de v3.2 → v3.3:**
1. **Detección de código:** nuevo detector que identifica scripts y artefactos versionables en el contenido de intercambios.
2. **Versionado con grafo de cambios:** cada script se versiona con un grafo reversible que permite al agente retroceder desde la versión actual hasta cualquier versión anterior aplicando cambios inversos.
3. **Nombres propios para subtemas de scripts:** los scripts se nombran por su nombre propio (con apellido/DNI si hay duplicados), nunca con `parte1`/`parte2`/`frag1`.
4. **Artefactos versionables:** no solo scripts de código; también config, specs, planes — cualquier cosa que si pierde una parte pierde valor.
5. **Bloques accesibles:** los artefactos versionados se guardan en bloques donde los subagentes pueden consultarlos.

---

## 1. Problema

Los agentes Z.ai operan con una ventana de contexto finita (~128K tokens). En sesiones largas, la plataforma comprime el contexto de forma automática y abrupta:

- El agente pierde acceso a los prompts originales.
- Solo conserva un resumen genérico generado por la plataforma.
- El agente no advierte al Director de la pérdida.
- Las decisiones, razonamientos y estado operativo se destruyen.
- **Los scripts y artefactos versionables se pierden**, impidiendo al agente retroceder a versiones anteriores.
- El Director detecta la pérdida cuando el agente da respuestas incoherentes.

**Impacto:** Sesiones de trabajo de días se convierten en experiencias frustrantes donde el agente "olvida" lo acordado, repite errores ya resueltos y pierde el historial de versiones de los scripts.

---

## 2. Solución propuesta

Un **proceso autónomo** que se instala en el workspace del agente y se vincula a la sesión. El agente no lo invoca manualmente con comandos: el proceso queda dormido y se activa cuando el agente detecta pérdida de contexto o cuando el Director se lo indica. El proceso lanza subagentes para hacer el trabajo de recuperación sin consumir la memoria del agente principal.

**Principio fundamental:** Contexto completo, no resúmenes. Los archivos de recuperación contienen la información real necesaria para operar, no resúmenes que introducen pérdida.

**Principio de integridad de artefactos:** Los scripts y artefactos versionables se guardan íntegros, con su historial de versiones y grafo de cambios reversible. Si un artefacto pierde una parte, pierde su valor.

**Objetivo superior:** Con una sola sesión de un agente se puede empezar y culminar un proyecto, porque el sistema de recuperación está vivo desde el primer minuto.

**Intervención del Director:** Una sola vez en la vida del proyecto, para proporcionar el JWT. El protocolo de inyección de cookie + persistencia de estado hace el resto.

---

## 3. Definiciones

| Término | Definición |
|---------|------------|
| **share_id** | UUID visible en la URL del chat compartido (`/s/{share_id}`). Se crea vía POST /api/v1/chats/{chat_id}/share. Es idempotente. |
| **chat_id** | UUID interno del chat, viene en los metadatos del gateway |
| **intercambio (exchange)** | Unidad mínima: un mensaje del Director + las respuesta(s) del agente |
| **tema** | Categoría temática asignada a un intercambio por clasificación léxica |
| **subtema** | Tema derivado único creado cuando un tema crece demasiado y se subdivide |
| **archivo temático (bloque)** | Archivo que contiene intercambios de uno o varios temas, hasta llenar el límite de tokens |
| **script** | Artefacto versionable identificado en el contenido del chat (código, config, spec, plan) |
| **versión de script** | Una versión concreta de un script en un punto del chat |
| **grafo de cambios** | Estructura que registra cómo evolucionó un script de una versión a la siguiente, permitiendo retroceder aplicando cambios inversos |
| **nombre propio** | Identificador único de un script basado en su nombre de archivo (ej: `server`, `router`). Si hay duplicados, se distinguen por su ruta completa (apellido/DNI) |
| **subagente efímero** | Instancia lanzada para leer un archivo temático y devolver una respuesta concreta; se cierra al entregar |
| **estado actual** | Archivo con 8 secciones (D1-D4 + A1-A4) que captura el contexto completo del tema activo |
| **índice de recuperación** | Mapa `tema → archivo` que el proceso consulta antes de lanzar subagentes |
| **decisiones clave** | Registro de decisiones reales (extraídas por LLM, no regex), consultable bajo demanda |
| **compresión** | Evento donde la plataforma reduce el contexto del agente a un resumen |
| **metadata de recuperación** | Archivo JSON auxiliar que trackea último timestamp, mapeo tema → archivo, subtemas derivados, subtemas_derivados |

---

## 4. Restricciones y constantes

```
VENTANA_AGENTE          = 128K tokens
MARGEN_SEGURIDAD        = 20%  (25.6K tokens reservados para procesamiento)
CAPACIDAD_UTIL          = 102.4K tokens (~350KB de texto)

MAX_TOKENS_BLOQUE        = 70K tokens (~240KB) — archivo temático
MAX_TOKENS_ESTADO        = 20K tokens (~70KB) — contexto completo del tema activo
MAX_TOKENS_INDICE        = 8K tokens  (~25KB)
MAX_TOKENS_DECISIONES    = 12K tokens (~40KB)

CARGA_PRINCIPAL_MAX      = 40K tokens (estado + índice + decisiones)
                          → Quedan ~88K libres para trabajar

CONVERSION_CHARS_TOKENS  = 3.5 (promedio para texto mixto es-código)

UMBRAL_COMPRESION_PCT    = 90%  (disparador del contador preventivo)

# Margen de seguridad para cabecera del bloque (v3.2)
SAFETY_MARGIN_TOKENS     = 3000 (limitado al 10% del máximo)
EFFECTIVE_MAX_TOKENS     = MAX_TOKENS_BLOQUE - SAFETY_MARGIN_TOKENS
                          → 67000 tokens efectivos
```

Nota sobre los límites v3.2: El estado actual pasó de 3K (v1.0) a 20K porque ahora contiene el **contexto completo** del tema activo, no un resumen. La carga principal pasó de 23K a 40K para acomodar esto.

El margen de seguridad de 3000 tokens garantiza que ningún archivo formateado (con cabecera del BloqueGenerator) supere el límite nominal de 70K.

---

## 5. Arquitectura del proceso autónomo

El proceso se instala en el workspace del agente en la primera sesión del proyecto, a partir de las instrucciones iniciales del worklog. Una vez instalado:

1. **Toma la información de la sesión:** el `chat_id` (presente en los metadatos del gateway de cada mensaje) y la ruta del workspace.
2. **Se vincula a la sesión:** el proceso queda dormido esperando que el agente lo active.
3. **Resuelve la autenticación:** mediante el protocolo de inyección de cookie de la metodología JWT (sección 11). El navegador del sandbox abre como invitado por defecto, así que el JWT del Director es necesario.

El proceso **no es una aplicación de línea de comandos**. Nadie lo invoca manualmente. El agente lo activa internamente cuando detecta pérdida de contexto, o el Director lo activa explícitamente con "relee el worklog" o cualquier reclamo de incoherencia.

---

## 6. Detección de pérdida de contexto

El agente puede perder contexto por compresión de la plataforma. Esta pérdida no se puede evitar, pero sí detectar. Tres mecanismos combinados, más la activación manual del Director.

### 6.1 Disparador léxico

El agente vigila el lenguaje del Director en cada mensaje. Si detecta frases como:

- "ya te dije", "lo hablamos", "no repitas", "otra vez lo mismo"
- "estás olvidando", "ya no recuerdas"
- "por qué respondes eso si ya acordamos X"

Dispara recuperación. Cubre el caso en que el Director reclama.

### 6.2 Contador preventivo por consumo estimado

El agente lleva la cuenta aproximada de tokens consumidos desde la última recuperación. Cuando se acerca al umbral de compresión (`UMBRAL_COMPRESION_PCT` = 90% de la capacidad útil), dispara recuperación **antes** de que la plataforma lo provoque. Esto evita que el Director tenga que reclamar.

### 6.3 Auto-preguntas tras entregas relevantes

Después de cada entrega importante, el agente se hace tres preguntas internas:

- ¿Sé en qué archivo estoy trabajando?
- ¿Sé qué decidimos sobre esto?
- ¿Sé qué sigue?

Si alguna falla, dispara recuperación. Es ligero, no requiere subagente externo.

### 6.4 Activación explícita del Director

El Director puede activar la recuperación explícitamente con:

- "relee el worklog"
- "perdiste contexto"
- Cualquier reclamo de incoherencia

Esta activación es directa y no requiere los mecanismos automáticos.

### 6.5 Mejora futura (no implementar en v3.3)

Un subagente observador externo que vigila la conversación en paralelo y avisa si detecta incoherencia. Se deja aparcado hasta validar si los tres mecanismos anteriores son suficientes en la práctica.

---

## 7. Flujo del proceso — 13 pasos

### Sesión 1 — Arranque del proyecto

**Paso 1.** El agente comienza con el prompt inicial del Director y el worklog de sesiones anteriores (o el worklog_template si es la primera sesión del proyecto). Desde ese instante, ese worklog pasa a ser el worklog vivo del agente.

**Paso 2.** El agente lee el worklog. Ese worklog, además de la identidad y el contrato, trae instrucciones iniciales explícitas: copiar el proceso de recuperación a su workspace desde el repositorio que se indique, y arrancarlo. El agente obedece: clona o trae el proceso y lo deja instalado y vinculado.

**Paso 3.** Una vez instalado, el proceso toma la información que precisa de la propia sesión (el `chat_id`, que viene en los metadatos del gateway; la ruta del workspace) para configurarse y vincularse a esa sesión. La autenticación para acceder a la plataforma se resuelve con el protocolo de inyección de cookie de la metodología JWT (sección 11), porque el navegador del sandbox abre como invitado por defecto. A partir de aquí el proceso queda dormido, esperando.

### Trabajo normal

**Paso 4.** El agente trabaja con el Director en el proyecto. Su contexto crece. En un momento dado, el agente detecta que le falta contexto (compresión de la plataforma, por cualquiera de los mecanismos de la sección 6), o el Director se lo indica explícitamente. Entonces el agente llama al proceso.

### Recuperación

**Paso 5.** El proceso despierta y recupera, por sus propios mecanismos, el chat completo: todos los intercambios entre el Director y el agente, desde el primer mensaje hasta el momento actual.

**Mecánica (validada en Sesión 5):**

1. Cargar estado autenticado del navegador (`.browser_auth_state.json`), o aplicar el protocolo de inyección de cookie si no existe.
2. `POST /api/v1/chats/{chat_id}/share` → crear o reutilizar share. Respuesta idempotente.
3. `GET /api/v1/chats/share/{share_id}` → árbol de mensajes (sin contenido, solo metadata).
4. Ordenar IDs por timestamp.
5. `POST /api/v1/chats/{chat_id}/messages/batch` con body `{"ids": [...]}` → contenido completo de todos los mensajes. **Requiere autenticación (cookie `token`).**
6. Construir JSON exportable y guardarlo en disco.

**Paso 6.** El proceso clasifica todos los intercambios por tema y los agrupa en archivos temáticos. Los archivos temáticos se llenan por tamaño (número de tokens definido en el spec), no por tema único: un archivo puede contener intercambios de varios temas diferentes siempre que caben dentro del límite. Los archivos se dejan en dos sitios:

- En el workspace del agente (accesibles a subagentes).
- En la carpeta de descarga (para que el Director los pueda bajar si quiere).

**Paso 6b — Detección de código (NUEVO en v3.3).** Durante la clasificación, el proceso detecta scripts y artefactos versionables en el contenido de los intercambios. Los scripts identificados se extraen, se versionan con grafo de cambios reversible, y se asignan a subtemas con nombres propios (basados en el nombre del archivo de código, con apellido/DNI si hay duplicados). Ver sección 8.6.

### Construcción del estado actual

**Paso 7.** El proceso genera tres archivos:

- **Estado actual** (el más importante). No es un resumen de los últimos intercambios: es la recuperación del **tema completo** al que pertenece el último intercambio, para que el agente tenga toda la información necesaria para dar una respuesta coherente y de calidad. **Obligatoriamente con 8 secciones D1-D4 + A1-A4** (ver sección 9.1).
- **Índice de recuperación.** Mapa de `tema → archivo`, con el protocolo de uso. Incluye los scripts versionados.
- **Decisiones clave.** Registro de las decisiones importantes. Se genera y actualiza en cada activación del proceso (modo incremental: solo procesa intercambios nuevos desde la última actualización, deduplica contra lo ya registrado, y añade las nuevas). También se actualiza cuando el Director cambia de tarea, lo indica explícitamente, o comunica formalmente una decisión. **Obligatoriamente con LLM**, no regex.

**Paso 8.** Para construir el estado actual, el proceso hace dos cosas: localiza cuál fue el último intercambio, determina a qué tema pertenece, y lanza un subagente que lee el archivo temático que contiene ese tema y extrae de ahí el contexto completo. El subagente entrega el contexto al agente principal y desaparece.

### Barrido por temas cuando sigue faltando

**Paso 9.** Si después de recuperar el estado actual el agente sigue necesitando más (otro tema, o algo que ya se valoró antes), el proceso consulta el índice para identificar qué archivo(s) contienen temas relevantes, y lanza un subagente por cada archivo identificado. A cada subagente le pasa una pregunta concreta sobre el tema. Los subagentes que encuentran información responden; los que no, no. Cuando todos han respondido, se cierran hasta el próximo intercambio.

### Actualización incremental

**Paso 10.** El agente sigue trabajando, su contexto se va llenando de nuevo. Llega un punto en que vuelve a faltar contexto (segunda compresión, o nueva necesidad). Esta vez el proceso **no descarga todo el chat de nuevo**: lee hasta dónde llegó la vez anterior (el último intercambio procesado, registrado en la metadata) y descarga solo desde ese punto hasta ahora. Clasifica esos nuevos intercambios y los **añade** a los archivos temáticos que ya existen. Así los archivos temáticos siempre están al día sin repetir trabajo.

### Subagentes siempre

**Paso 11.** El agente nunca consulta los archivos temáticos directamente. Siempre crea subagentes que van, responden la pregunta concreta, llenan el contexto del agente y se cierran.

### Reconstrucción del estado actual en cada activación

**Paso 12.** Cada vez que el proceso se activa por pérdida de contexto, construye un **nuevo** archivo de estado actual, basado en el tema del último intercambio de ese momento. El estado actual es un archivo puntual: refleja el contexto del instante, no guarda historial de estados anteriores.

### Cierre de sesión

**Paso 13.** Cuando la sesión cierra, el agente hace una última actualización completa de los archivos de recuperación (para que queden al día como handoff para la próxima sesión), añade su entrada al worklog, y si detectó aprendizajes reusables los persiste en el repo de estrategia. Los archivos de recuperación quedan en disco como registro permanente.

---

## 8. Archivos temáticos — arquitectura

### 8.1 Principio de agrupación por tamaño

Un archivo temático puede contener intercambios de **varios temas diferentes**, siempre que la suma de sus tokens no supere `EFFECTIVE_MAX_TOKENS` (67000 tokens efectivos, con margen de seguridad para cabecera). El archivo se llena hasta su capacidad efectiva antes de crear uno nuevo.

**Razón:** Evitar la proliferación de archivos pequeños. Si hay 50 temas pero caben en 5 archivos de tamaño completo, se generan 5 archivos, no 50.

### 8.2 Principio de unicidad temática

Un tema (o subtema) **vive en un solo archivo temático**. No puede haber dos archivos con el mismo tema. Esto garantiza que cuando el proceso consulta el índice y localiza un tema, sabe exactamente a qué archivo preguntar, y que cuando el agente pregunta por un tema, solo se lanza un subagente para el archivo correspondiente, no para todos.

### 8.3 Subdivisión con nuevos temas

Cuando un tema individual crece tanto que no cabe en un archivo, se subdivide. La subdivisión **NO** crea `tema_parte1` y `tema_parte2` (eso fragmentaría el contexto y fue el bug detectado en Sesión 5). En su lugar, el tema se divide en **subtemas derivados** que son nuevos temas únicos en el sistema.

Por ejemplo: si el tema "validaciones" crece demasiado, se subdivide en subtemas como:

- `validaciones_server`
- `validaciones_router`
- `validaciones_broker`

Cada subtema es único, vive en un solo archivo, y se registra en el índice como un tema independiente.

### 8.4 Subdivisión temporal por fechas

Cuando un tema no tiene sub-palabras léxicas conocidas y crece demasiado, se subdivide por **rangos temporales con nombres basados en fechas** (ej: `general_2026sep03`, `metodologia_2026sep04`), nunca con `parte1`/`parte2`.

### 8.5 Estructura de archivos resultante

```
contexto_recuperacion/
├── _metadata.json
├── _grafos_cambios.json          (NUEVO v3.3)
├── 00_estado_actual.md
├── 01_indice_recuperacion.md
├── 02_decisiones_clave.md
├── bloque_01.md           ← contiene temas A, B, C (si caben)
├── bloque_02.md           ← contiene temas D, E
├── bloque_03.md           ← contiene subtema F1 (derivado de subdivisión)
├── bloque_04.md           ← contiene subtema F2 + tema G
└── ...
```

### 8.6 Detección de código y versionado de scripts (NUEVO en v3.3)

#### 8.6.1 Detector de código

El proceso incluye un **detector de código** que identifica scripts y artefactos versionables en el contenido de los intercambios. El detector busca:

1. **Bloques de código entre triple backtick** con identificador de lenguaje (```` ```python ... ``` ````).
2. **Comentarios `# Destino: ruta/al/archivo.py`** en la primera línea de un bloque de código.
3. **Rutas de archivo** mencionadas en el texto del intercambio (ej: `contexto_zai/config.py`).
4. **Bloques de código sin lenguaje explícito** que contienen patrones de código (imports, def, class, function).

El detector extrae cada script identificado y le asigna un **nombre propio** basado en el nombre del archivo (sin extensión). Si dos scripts tienen el mismo nombre pero diferente ruta, se distinguen por su **apellido/DNI**: la ruta completa o un identificador único.

#### 8.6.2 Tipos de artefactos versionables

No solo scripts de código. También se versionan:

- **Scripts de código** (`.py`, `.ts`, `.js`, etc.)
- **Archivos de configuración** (`.json`, `.yaml`, `.toml`, `.env`)
- **Specs y planes** (`.md` con estructura de spec o plan)
- **Cualquier artefacto que si pierde una parte pierde valor**

#### 8.6.3 Versionado con grafo de cambios

Cada script identificado se **versiona** a lo largo del chat. Cuando el agente muestra una versión nueva de un script que ya había aparecido, se calcula el **grafo de cambios** entre la versión anterior y la nueva:

- **Diff forward:** los cambios necesarios para llegar de la versión anterior a la nueva.
- **Diff reverse:** los cambios necesarios para volver de la nueva a la anterior.

El grafo de cambios es **reversible**: el agente puede tomar la versión actual del script y, aplicando los cambios inversos del grafo, reconstruir cualquier versión anterior.

#### 8.6.4 Estructura del grafo

El grafo se guarda en `_grafos_cambios.json` (archivo separado en el directorio de recuperación). Estructura:

```json
{
  "server": {
    "versions": [
      {
        "version_id": "v1",
        "timestamp": 1788482829,
        "exchange_id": 5,
        "parent_version": null,
        "forward_diff": null,
        "reverse_diff": null
      },
      {
        "version_id": "v2",
        "timestamp": 1788483000,
        "exchange_id": 8,
        "parent_version": "v1",
        "forward_diff": "+ def new_function():\n+     pass",
        "reverse_diff": "- def new_function():\n-     pass"
      },
      {
        "version_id": "v3",
        "timestamp": 1788483100,
        "exchange_id": 12,
        "parent_version": "v2",
        "forward_diff": "- def old_function():\n-     pass",
        "reverse_diff": "+ def old_function():\n+     pass"
      }
    ],
    "current_version": "v3"
  }
}
```

#### 8.6.5 Retroceso a versiones anteriores

El agente puede retroceder desde la versión actual hasta cualquier versión anterior siguiendo el grafo de cambios:

1. Identificar la versión destino (ej: `v1`).
2. Desde la versión actual (`v3`), aplicar `reverse_diff` de `v3` para llegar a `v2`.
3. Aplicar `reverse_diff` de `v2` para llegar a `v1`.
4. El resultado es el contenido del script en `v1`.

#### 8.6.6 Nombres propios para subtemas de scripts

Cuando un intercambio contiene scripts, se subdividen por **nombre del script** (no por keywords léxicas del tema padre). Cada subtema = nombre del script:

- `almacenamiento_server` (script server.py del tema almacenamiento)
- `almacenamiento_router` (script router.py del tema almacenamiento)
- `validaciones_auth` (script auth.py del tema validaciones)

Si dos scripts tienen el mismo nombre pero diferente ruta, se distinguen por su apellido/DNI:

- `almacenamiento_config_client` (config.py de la carpeta client/)
- `almacenamiento_config_server` (config.py de la carpeta server/)

### 8.7 El índice controla todo

El índice de recuperación mantiene el mapeo `tema → archivo`. Cuando un tema se subdivide en subtemas (léxicos, temporales o por script), el índice se actualiza para reflejar los nuevos temas y sus archivos. El proceso consulta el índice **antes** de lanzar cualquier subagente.

---

## 9. Los tres archivos de recuperación

### 9.1 `00_estado_actual.md`

**Propósito:** Snapshot operativo con **contexto completo del tema activo** al momento de la activación. No es un resumen.
**Tamaño máximo:** 20K tokens (~70KB)
**Lo lee:** El agente principal directamente al recuperar contexto.

**Estructura obligatoria — 8 secciones D1-D4 + A1-A4:**

```markdown
# Estado Actual — Agente — Sesión N

## Sección D1 — Última instrucción del Director
{Texto completo del último mensaje del Director, literal, sin editar}

## Sección D2 — Contexto del tema activo
{Información completa del tema al que pertenece el último intercambio.
 Incluye rutas de archivos, decisiones relevantes, estado de entregables.
 NO es un resumen: es la información operativa necesaria para continuar.}

## Sección D3 — Decisiones pendientes del Director
- {decisión que el Director no ha tomado aún, con opciones si las hay}

## Sección D4 — Restricciones y preferencias activas
- {restricciones que el Director impuso para esta tarea}

---

## Sección A1 — Qué estaba haciendo el agente
{Descripción concreta de la última acción o flujo en curso.}

## Sección A2 — Entregables producidos
- {archivo1} — {estado} — {comentario breve}

## Sección A3 — Errores abiertos
- {descripción del error, archivo, causa raíz si se conoce}

## Sección A4 — Siguiente paso lógico
{Lo que el agente debería hacer al retomar.}
```

**Versionado:** Archivo puntual. Cada activación lo sobrescribe con el contexto del instante. No guarda historial de estados anteriores.

### 9.2 `01_indice_recuperacion.md`

**Propósito:** Mapa para que el agente sepa qué temas existen y en qué archivo está cada uno.
**Tamaño máximo:** 8K tokens (~25KB)
**Lo lee:** El agente principal durante la recuperación, y el proceso antes de lanzar subagentes.

**Estructura obligatoria — tabla `tema → archivo`:**

```markdown
# Índice de Recuperación

## Instrucción
Si detectas que has perdido contexto, este archivo es tu punto de entrada.
Identifica qué tema necesitas y delega a un subagente para que lea el archivo
correspondiente.

## Protocolo de recuperación
1. Lee este archivo (ya lo estás leyendo).
2. Lee `00_estado_actual.md` para saber dónde quedaste (contexto del tema activo).
3. Si necesitas otro tema, identifica aquí en qué archivo está.
4. Lanza un subagente con una **pregunta concreta** sobre ese tema.
5. El subagente devolverá una respuesta concisa.
6. Si necesitas otro tema, repite desde el paso 3.

## Mapeo tema → archivo

| Tema | Archivo | Tokens aprox. |
|------|---------|---------------|
| validaciones | bloque_01.md | 18K |
| planificador | bloque_02.md | 12K |
| configuracion | bloque_01.md | (comparte archivo con validaciones) |
| metodologia | bloque_03.md | 9K |
| almacenamiento_server | bloque_04.md | 22K (script versionado, ver _grafos_cambios.json) |
| ... | ... | ... |

## Decisiones clave (resumen)
- {decisión 1} — ver detalle en `02_decisiones_clave.md`
- {decisión 2} — ver detalle en `02_decisiones_clave.md`

## Scripts versionados (NUEVO v3.3)
- `server.py` — 3 versiones (v1→v2→v3), ver grafo en `_grafos_cambios.json`
- `router.py` — 1 versión (v1), ver grafo en `_grafos_cambios.json`
```

### 9.3 `02_decisiones_clave.md`

**Propósito:** Registro de decisiones importantes tomadas, para que el agente no re-decida lo ya resuelto y para que el Director tenga visibilidad del acumulado de decisiones del proyecto.
**Tamaño máximo:** 12K tokens (~40KB)
**Lo lee:** El agente principal o un subagente bajo demanda.

**Rol:** Activo. Se genera y actualiza en **cada activación del proceso de recuperación de contexto**, no es un registro pasivo. Forma parte del ciclo activo de recuperación.

**Disparadores de generación/actualización:**

1. **Cada activación del proceso de recuperación.**
2. **Cambio de tarea del Director.**
3. **Indicación explícita del Director.**
4. **Comunicación explícita de una decisión.**

**Cómo se llena:** Mediante un subagente con comprensión semántica LLM. En cada activación, el subagente solo procesa los intercambios nuevos desde la última actualización (modo incremental), deduplica contra las decisiones ya registradas, y añade solo las nuevas.

---

## 10. Patrones de subagentes

El agente principal nunca lee los archivos temáticos directamente. Siempre opera vía subagentes:

### 10.1 Subagente de estado actual
- Lee el archivo temático que contiene el tema del último intercambio.
- Extrae todo el contexto del tema.
- Entrega al agente principal.
- Se cierra.

### 10.2 Subagente de barrido por tema
- Un subagente por cada archivo relevante (identificado vía índice).
- Recibe una pregunta concreta sobre el tema.
- Si encuentra información, responde.
- Se cierra al terminar.

### 10.3 Subagente de decisiones
- Se lanza en cada activación del proceso.
- Escanea los intercambios nuevos desde la última actualización (modo incremental).
- Extrae decisiones con comprensión semántica LLM (regex no es suficiente).
- Deduplica contra el registro existente.
- Añade solo las decisiones nuevas.
- También se activa cuando el Director cambia de tarea, lo indica explícitamente, o comunica formalmente una decisión.
- Se cierra al terminar.

### 10.4 Subagente de mantenimiento (actualización incremental)
- Se lanza en segundo plano cuando se dispara la recuperación.
- Lee la metadata para saber el último timestamp procesado.
- Extrae solo mensajes nuevos.
- Los clasifica y añade a los archivos existentes.
- Actualiza la metadata.

### 10.5 Subagente de retroceso de versiones (NUEVO v3.3)
- Cuando el agente necesita retroceder a una versión anterior de un script.
- Lee el grafo de cambios del script en `_grafos_cambios.json`.
- Aplica los `reverse_diff` necesarios desde la versión actual hasta la versión destino.
- Entrega al agente principal el contenido del script en la versión solicitada.
- Se cierra.

---

## 11. Autenticación con la plataforma Z.ai

La autenticación para acceder a la API de chat.z.ai se obtiene mediante el **protocolo de inyección de cookie** de la metodología JWT. Es el flujo principal, no un fallback: el navegador del sandbox de Z.ai abre chat.z.ai como **INVITADO** por defecto, así que el JWT del Director es necesario para autenticar.

**Documento de referencia:** `metodologia_descubrimiento_jwt.md` (incluido en el repositorio del proyecto). Documenta la cadena de descubrimiento que permite esta automatización.

### 11.1 Por qué el navegador del sandbox es invitado

Verificado en Sesión 5: al abrir `https://chat.z.ai` con `agent-browser`, la cookie `token` contiene un JWT con payload `{"id":"...","email":"guest-*@guest.com"}`. El navegador del sandbox no tiene la sesión de Google del Director cargada. Es un navegador limpio.

### 11.2 Protocolo de inyección de cookie (flujo principal)

**Setup inicial (una vez en la vida del proyecto):**

1. El Director obtiene su JWT del header `Authorization: Bearer` en DevTools de chat.z.ai (en su navegador habitual, no el del sandbox).
2. El Director proporciona ese JWT al agente (por chat, como en Sesión 5).
3. El agente abre chat.z.ai con `agent-browser` para establecer el dominio.
4. El agente establece el header Authorization en todas las requests: `agent-browser set headers '{"Authorization":"Bearer <JWT>"}'`. Esto previene que el servidor redirija a home.
5. El agente navega al chat: `agent-browser open "https://chat.z.ai/c/{chat_id}"`. La URL se mantiene gracias al header.
6. El agente inyecta la cookie: `agent-browser cookies set token "<JWT>"`.
7. El agente recarga: `agent-browser eval "location.reload()"`. El servidor valida el token, lo refresca (nueva firma ES256, mismo payload) y responde con `Set-Cookie` con el nuevo token.
8. El agente guarda el estado autenticado: `agent-browser state save /home/z/my-project/.browser_auth_state.json`.

**Uso recurrente (cero intervención del Director):**

1. `agent-browser state load /home/z/my-project/.browser_auth_state.json`
2. `agent-browser open "https://chat.z.ai/c/{chat_id}"`
3. Proceder con el paso 5 del flujo (extracción).

### 11.3 Endpoints usados (validados en Sesión 5)

| Endpoint | Método | Autenticación | Propósito |
|---|---|---|---|
| `/api/v1/auths/` | GET | Cookie `token` | Verificar perfil autenticado |
| `/api/v1/chats/{chat_id}/share` | POST | Cookie `token` | Crear o reutilizar share (idempotente) |
| `/api/v1/chats/share/{share_id}` | GET | Cookie `token` | Árbol de mensajes (sin contenido) |
| `/api/v1/chats/{chat_id}/messages/batch` | POST | Cookie `token` | Contenido completo de mensajes |

**Cambio crítico respecto a v2.2:** El batch endpoint usa **`chat_id`** y requiere autenticación. NO usa `share_id` como invitado. La plataforma cambió.

### 11.4 Notas técnicas clave

- La cookie se llama `token`, es HttpOnly.
- El servidor refresca el JWT en cada request (nueva firma ES256, mismo payload).
- El JWT no tiene campo `exp` ni `expires_at` (tokens infinitos por diseño).
- La UI de chat no renderiza en agent-browser, pero todas las API calls funcionan.
- El share API es idempotente: devuelve el share_id existente o crea uno nuevo.
- No hay límite de mensajes por request de batch.

---

## 12. Metadata de recuperación

Archivo `_metadata.json` con:

```json
{
  "chat_id": "13b43432-...",
  "share_id": "1d1196b7-...",
  "ultimo_timestamp": 1788607626,
  "total_exchanges": 32,
  "tema_a_archivo": {
    "validaciones": "bloque_01.md",
    "planificador": "bloque_02.md",
    "almacenamiento_server": "bloque_04.md",
    "almacenamiento_router": "bloque_05.md"
  },
  "subtemas_derivados": {
    "validaciones": ["validaciones_server", "validaciones_router"],
    "almacenamiento": ["almacenamiento_server", "almacenamiento_router"]
  },
  "scripts_versionados": {
    "server": {"versions": 3, "current": "v3", "archivo": "bloque_04.md"},
    "router": {"versions": 1, "current": "v1", "archivo": "bloque_05.md"}
  },
  "ultima_activacion": "2026-09-04T23:24:51Z"
}
```

**Campos nuevos (v3.3):**

- `scripts_versionados`: registro de qué scripts se versionaron, cuántas versiones tienen, cuál es la actual, y en qué archivo están.

---

## 13. Limitaciones conocidas

1. **El sistema no previene la compresión:** Solo mitiga sus efectos detectándola y recuperando.
2. **Requiere agent-browser:** La API no es accesible por curl directamente; se necesita un navegador con cookies de sesión.
3. **La detección no es perfecta:** Los tres mecanismos combinados (léxico, contador, auto-preguntas) pueden perder casos. El subagente observador queda como mejora futura.
4. **El estado actual es puntual:** No guarda historial de estados anteriores.
5. **Las decisiones requieren LLM:** El patrón regex no es suficiente para extraer decisiones; se necesita comprensión semántica.
6. **La tarea actual puede ser "general":** Cuando el Director da instrucciones transversales, no hay tema dominante.
7. **El sandbox abre como invitado:** El navegador del sandbox no tiene la sesión del Director. El JWT debe proporcionarse una vez y persistirse.
8. **El detector de código puede no detectar todos los scripts:** Si un script no tiene bloque de código, comentario `# Destino:`, ni ruta de archivo, puede no ser detectado. El detector se actualiza con nuevos patrones según se descubran casos edge.
9. **El grafo de cambios es lineal por defecto:** Si el agente prueba enfoques alternativos y vuelve a uno anterior, el grafo puede tener ramificaciones. El retroceso sigue el camino principal (current → parent → parent → ...). Ramificaciones laterales se documentan pero el retroceso automático sigue el camino principal.

---

## 14. Cambios pendientes respecto al código actual (v3.2)

1. **Crear `processing/code_detector.py`** (nuevo atómico): detector de scripts y artefactos versionables.
2. **Crear `processing/version_graph.py`** (nuevo atómico): grafo de cambios reversible con diffs forward y reverse.
3. **Actualizar `models.py`**: añadir `Script`, `ScriptVersion`, `ChangeGraph`, `ChangeNode`.
4. **Actualizar `processing/subdivider.py`**: integrar `code_detector` para subdividir por nombre de script cuando un intercambio contiene código.
5. **Actualizar `generation/bloque_generator.py`**: incluir el grafo de cambios en el formato del bloque cuando contenga scripts versionados.
6. **Actualizar `generation/indice_generator.py`**: mostrar scripts versionados en el índice.
7. **Actualizar `generation/recovery_generator.py`**: orquestar la generación del archivo `_grafos_cambios.json`.
8. **Actualizar `process/recovery_cycle.py`**: invocar el detector de código durante la clasificación.
9. **Actualizar `config.py`**: patrones de detección de código.

---

## 15. Log de validación

[Se llenará después de implementar y probar la v3.3.]

---

## 16. Referencias

- `metodologia_descubrimiento_jwt.md` — Procedimiento reproducible de autenticación.
- Spec v3.2 — Versión anterior. Reemplazada por esta v3.3.
- Spec v2.3 — Versión con arquitectura CLI. Reemplazada por v3.0.
- Worklog del proyecto — Entradas de sesiones 1 a 5 con la implementación inicial y los fixes.
