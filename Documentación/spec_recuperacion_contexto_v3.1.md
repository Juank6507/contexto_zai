<!-- Destino en el proyecto: /home/z/my-project/contexto_zai/spec_recuperacion_contexto_v3.1.md -->

# SPEC — Sistema de Recuperación de Contexto para Agentes Z.ai

**Versión:** 3.1
**Fecha:** 2026-09-02
**Autor:** Director (diseño) + Agente CZAI (especificación)
**Estado:** v3.1 — Afina la v3.0 en dos puntos: (a) la obtención del JWT pasa a ser automática, sin que el Director tenga que ir a DevTools; (b) las decisiones clave dejan de ser un registro pasivo y se generan en cada activación del proceso, disparadas por cambio de tarea, indicación del Director o comunicación explícita.

**Cambios principales respecto a v2.3:**
1. De aplicación CLI a proceso autónomo vinculado al agente.
2. Detección activa de pérdida de contexto (tres mecanismos combinados: léxico, contador preventivo, auto-preguntas).
3. Archivos temáticos con varios temas por archivo, no un tema por archivo.
4. Subdivisión genera nuevos temas/subtemas únicos, no "parte1/parte2".
5. Unicidad temática: un tema vive en un solo archivo.
6. Actualización de límites a los de v2.3 (estado 20K, carga principal 40K).
7. Referencia a la metodología JWT documentada para la autenticación.

**Cambios de v3.0 → v3.1:**
8. **JWT automático:** el proceso obtiene el JWT leyendo la cookie `token` del navegador del sandbox. El Director no va a DevTools.
9. **Decisiones clave activas:** se generan en cada activación del proceso, no son un registro pasivo. Disparadores: cambio de tarea, indicación del Director, comunicación explícita.

---

## 1. Problema

Los agentes Z.ai operan con una ventana de contexto finita (~128K tokens). En sesiones largas, la plataforma comprime el contexto de forma automática y abrupta:

- El agente pierde acceso a los prompts originales.
- Solo conserva un resumen genérico generado por la plataforma.
- El agente no advierte al Director de la pérdida.
- Las decisiones, razonamientos y estado operativo se destruyen.
- El Director detecta la pérdida cuando el agente da respuestas incoherentes.

**Impacto:** Sesiones de trabajo de días se convierten en experiencias frustrantes donde el agente "olvida" lo acordado y repite errores ya resueltos.

---

## 2. Solución propuesta

Un **proceso autónomo** que se instala en el workspace del agente y se vincula a la sesión. El agente no lo invoca manualmente con comandos: el proceso queda dormido y se activa cuando el agente detecta pérdida de contexto o cuando el Director se lo indica. El proceso lanza subagentes para hacer el trabajo de recuperación sin consumir la memoria del agente principal.

**Principio fundamental:** Contexto completo, no resúmenes. Los archivos de recuperación contienen la información real necesaria para operar, no resúmenes que introducen pérdida.

**Objetivo superior:** Con una sola sesión de un agente se puede empezar y culminar un proyecto, porque el sistema de recuperación está vivo desde el primer minuto, no reacciona solo cuando ya se perdió todo.

**Intervención del Director:** Cero para la autenticación. El proceso obtiene el JWT automáticamente de la cookie del navegador del sandbox (ver sección 11). Solo si el navegador del sandbox no está autenticado, el Director debe iniciar sesión en chat.z.ai una vez desde ese navegador. Después de eso, el sistema es 100% automático durante toda la vida del proyecto.

---

## 3. Definiciones

| Término | Definición |
|---------|------------|
| **share_id** | UUID visible en la URL del chat compartido (`/s/{share_id}`) |
| **chat_id** | UUID interno del chat, viene en los metadatos del gateway |
| **intercambio (exchange)** | Unidad mínima: un mensaje del Director + las respuesta(s) del agente |
| **tema** | Categoría temática asignada a un intercambio por clasificación léxica |
| **subtema** | Tema derivado único creado cuando un tema crece demasiado y se subdivide |
| **archivo temático (bloque)** | Archivo que contiene intercambios de uno o varios temas, hasta llenar el límite de tokens |
| **subagente efímero** | Instancia lanzada para leer un archivo temático y devolver una respuesta concreta; se cierra al entregar |
| **estado actual** | Archivo con el contexto completo del tema activo al momento de la activación |
| **índice de recuperación** | Mapa tema → archivo que el proceso consulta antes de lanzar subagentes |
| **decisiones clave** | Registro histórico de decisiones importantes tomadas; consultable bajo demanda |
| **compresión** | Evento donde la plataforma reduce el contexto del agente a un resumen |
| **metadata de recuperación** | Archivo JSON auxiliar que trackea último timestamp, tarea actual, mapeo tema → archivo |

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
```

Nota sobre los límites v2.3: El estado actual pasó de 3K (v1.0) a 20K porque ahora contiene el **contexto completo** del tema activo, no un resumen. La carga principal pasó de 23K a 40K para acomodar esto.

---

## 5. Arquitectura del proceso autónomo

El proceso se instala en el workspace del agente en la primera sesión del proyecto, a partir de las instrucciones iniciales del worklog. Una vez instalado:

1. **Toma la información de la sesión:** el `chat_id` (presente en los metadatos del gateway de cada mensaje) y la ruta del workspace.
2. **Se vincula a la sesión:** el proceso queda dormido esperando que el agente lo active.
3. **Resuelve la autenticación:** mediante la metodología JWT documentada (sección 11).

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

### 6.5 Mejora futura (no implementar en v3.1)

Un subagente observador externo que vigila la conversación en paralelo y avisa si detecta incoherencia. Se deja aparcado hasta validar si los tres mecanismos anteriores son suficientes en la práctica.

---

## 7. Flujo del proceso — 13 pasos

### Sesión 1 — Arranque del proyecto

**Paso 1.** El agente comienza con el prompt inicial del Director y el worklog de sesiones anteriores (o el worklog_template si es la primera sesión del proyecto). Desde ese instante, ese worklog pasa a ser el worklog vivo del agente.

**Paso 2.** El agente lee el worklog. Ese worklog, además de la identidad y el contrato, trae instrucciones iniciales explícitas: copiar el proceso de recuperación a su workspace desde el repositorio que se indique, y arrancarlo. El agente obedece: clona o trae el proceso y lo deja instalado y vinculado.

**Paso 3.** Una vez instalado, el proceso toma la información que precisa de la propia sesión (el `chat_id`, que viene en los metadatos del gateway; la ruta del workspace) para configurarse y vincularse a esa sesión. La autenticación para acceder a la plataforma se resuelve con la metodología JWT documentada (sección 11). A partir de aquí el proceso queda dormido, esperando.

### Trabajo normal

**Paso 4.** El agente trabaja con el Director en el proyecto. Su contexto crece. En un momento dado, el agente detecta que le falta contexto (compresión de la plataforma, por cualquiera de los mecanismos de la sección 6), o el Director se lo indica explícitamente. Entonces el agente llama al proceso.

### Recuperación

**Paso 5.** El proceso despierta y recupera, por sus propios mecanismos, el chat completo: todos los intercambios entre el Director y el agente, desde el primer mensaje hasta el momento actual.

**Paso 6.** El proceso clasifica todos los intercambios por tema y los agrupa en archivos temáticos. Los archivos temáticos se llenan por tamaño (número de tokens definido en el spec), no por tema único: un archivo puede contener intercambios de varios temas diferentes siempre que caben dentro del límite. Los archivos se dejan en dos sitios:

- En el workspace del agente (accesibles a subagentes).
- En la carpeta de descarga (para que el Director los pueda bajar si quiere).

### Construcción del estado actual

**Paso 7.** El proceso genera tres archivos:

- **Estado actual** (el más importante). No es un resumen de los últimos intercambios: es la recuperación del **tema completo** al que pertenece el último intercambio, para que el agente tenga toda la información necesaria para dar una respuesta coherente y de calidad.
- **Índice de recuperación.** Mapa de qué tema está en qué archivo, con el protocolo de uso.
- **Decisiones clave.** Registro de las decisiones importantes. Se genera y actualiza en cada activación del proceso (modo incremental: solo procesa intercambios nuevos desde la última actualización, deduplica contra lo ya registrado, y añade las nuevas). También se actualiza cuando el Director cambia de tarea, lo indica explícitamente, o comunica formalmente una decisión.

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

Un archivo temático puede contener intercambios de **varios temas diferentes**, siempre que la suma de sus tokens no supere `MAX_TOKENS_BLOQUE` (70K tokens). El archivo se llena hasta su capacidad antes de crear uno nuevo.

**Razón:** Evitar la proliferación de archivos pequeños. Si hay 50 temas pero caben en 5 archivos de tamaño completo, se generan 5 archivos, no 50.

### 8.2 Principio de unicidad temática

Un tema (o subtema) **vive en un solo archivo temático**. No puede haber dos archivos con el mismo tema. Esto garantiza que cuando el proceso consulta el índice y localiza un tema, sabe exactamente a qué archivo preguntar, y que cuando el agente pregunta por un tema, solo se lanza un subagente para el archivo correspondiente, no para todos.

### 8.3 Subdivisión con nuevos temas

Cuando un tema individual crece tanto que no cabe en un archivo, se subdivide. La subdivisión **NO** crea `tema_parte1` y `tema_parte2` (eso fragmentaría el contexto). En su lugar, el tema se divide en **subtemas derivados** que son nuevos temas únicos en el sistema.

Por ejemplo: si el tema "validaciones" crece demasiado, se subdivide en subtemas como:

- `validaciones_server`
- `validaciones_router`
- `validaciones_broker`

Cada subtema es único, vive en un solo archivo, y se registra en el índice como un tema independiente.

### 8.4 Estructura de archivos resultante

```
contexto_recuperacion/
├── _metadata.json
├── 00_estado_actual.md
├── 01_indice_recuperacion.md
├── 02_decisiones_clave.md
├── bloque_01.md           ← contiene temas A, B, C (si caben)
├── bloque_02.md           ← contiene temas D, E
├── bloque_03.md           ← contiene subtema F1 (derivado de subdivisión)
├── bloque_04.md           ← contiene subtema F2 + tema G
└── ...
```

### 8.5 El índice controla todo

El índice de recuperación mantiene el mapeo `tema → archivo`. Cuando un tema se subdivide en subtemas, el índice se actualiza para reflejar los nuevos temas y sus archivos. El proceso consulta el índice **antes** de lanzar cualquier subagente.

---

## 9. Los tres archivos de recuperación

### 9.1 `00_estado_actual.md`

**Propósito:** Snapshot operativo con **contexto completo del tema activo** al momento de la activación. No es un resumen.
**Tamaño máximo:** 20K tokens (~70KB)
**Lo lee:** El agente principal directamente al recuperar contexto.

**Construcción (paso 8 del flujo):**

1. Localiza el último intercambio del chat.
2. Determina a qué tema pertenece ese intercambio (clasificación léxica sobre el mensaje del Director).
3. Consulta el índice para saber en qué archivo temático está ese tema.
4. Lanza un subagente que lee ese archivo y extrae todo el contexto del tema.
5. El subagente entrega el contexto completo al agente principal.
6. El proceso registra ese contexto como el estado actual.

**Contenido (8 secciones):**

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

**Versionado:** Archivo puntual. Cada activación lo sobrescribe con el contexto del instante. No guarda historial de estados anteriores. Es la fotografía operativa del momento, no una crónica.

### 9.2 `01_indice_recuperacion.md`

**Propósito:** Mapa para que el agente sepa qué temas existen y en qué archivo está cada uno.
**Tamaño máximo:** 8K tokens (~25KB)
**Lo lee:** El agente principal durante la recuperación, y el proceso antes de lanzar subagentes.

**Contenido:**

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
| validaciones_server | bloque_04.md | 22K (subtema derivado) |
| ... | ... | ... |

## Decisiones clave (resumen)
- {decisión 1} — ver detalle en `02_decisiones_clave.md`
- {decisión 2} — ver detalle en `02_decisiones_clave.md`
```

### 9.3 `02_decisiones_clave.md`

**Propósito:** Registro de decisiones importantes tomadas, para que el agente no re-decida lo ya resuelto y para que el Director tenga visibilidad del acumulado de decisiones del proyecto.
**Tamaño máximo:** 12K tokens (~40KB)
**Lo lee:** El agente principal o un subagente bajo demanda.

**Rol:** Activo. Se genera y actualiza en **cada activación del proceso de recuperación de contexto**, no es un registro pasivo. Forma parte del ciclo activo de recuperación.

**Disparadores de generación/actualización:**

1. **Cada activación del proceso de recuperación** (cuando el agente detecta pérdida de contexto o el Director lo indica). El proceso escanea los intercambios desde la última actualización, extrae las nuevas decisiones y las añade al registro existente.
2. **Cambio de tarea del Director.** Cuando el Director pasa de una tarea a otra, las decisiones de la tarea anterior se consolidan en este archivo antes de que el agente empiece a trabajar en la nueva.
3. **Indicación explícita del Director.** El Director puede solicitar en cualquier momento que se consolide el registro ("actualiza decisiones clave").
4. **Comunicación explícita de una decisión.** Cuando el Director comunica formalmente una decisión ("decidimos X", "a partir de ahora Y", "descartamos Z"), el proceso la registra de inmediato.

**Cómo se llena:** Mediante un subagente que escanea los intercambios y extrae decisiones con comprensión semántica. El patrón regex no es suficiente para extraer decisiones (validado en v2.1: 0 resultados con patrones estrictos); se necesita comprensión LLM. En cada activación, el subagente solo procesa los intercambios nuevos desde la última actualización (modo incremental), deduplica contra las decisiones ya registradas, y añade solo las nuevas.

**Contenido:**

```markdown
# Decisiones Clave

## D01 — {título breve}
- **Cuándo:** YYYY-MM-DD HH:MM
- **Decisión:** {qué se decidió}
- **Razón:** {por qué}
- **Impacto:** {qué afecta}

## D02 — {título breve}
...
```

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
- Se lanza en cada activación del proceso (no es bajo demanda, es parte del ciclo activo).
- Escanea los intercambios nuevos desde la última actualización (modo incremental).
- Extrae decisiones con comprensión semántica LLM (regex no es suficiente).
- Deduplica contra el registro existente en `02_decisiones_clave.md`.
- Añade solo las decisiones nuevas.
- También se activa cuando el Director cambia de tarea, lo indica explícitamente, o comunica formalmente una decisión.
- Se cierra al terminar.

### 10.4 Subagente de mantenimiento (actualización incremental)
- Se lanza en segundo plano cuando se dispara la recuperación.
- Lee la metadata para saber el último timestamp procesado.
- Extrae solo mensajes nuevos.
- Los clasifica y añade a los archivos existentes.
- Actualiza la metadata.

---

## 11. Autenticación con la plataforma Z.ai

La autenticación para acceder a la API de chat.z.ai se obtiene **automáticamente**. El proceso extrae el JWT de la cookie del navegador del sandbox, sin que el Director tenga que ir a DevTools ni proporcionar el token manualmente.

**Documento de referencia:** `metodologia_descubrimiento_jwt.md` (incluido en el repositorio del proyecto). Documenta la cadena de descubrimiento que permite esta automatización.

**Flujo automático (cero intervención del Director):**

1. El proceso abre chat.z.ai con `agent-browser`. El navegador del sandbox ya tiene la sesión del Director cargada (es el navegador con el que el Director accede al propio sandbox).
2. El proceso ejecuta `agent-browser cookies` y localiza la cookie `token` (HttpOnly, pero accesible vía el CLI de agent-browser que opera a nivel interno del navegador, no vía `document.cookie`).
3. El proceso lee el valor de esa cookie: es el JWT del Director autenticado.
4. El proceso guarda el estado autenticado en `.browser_auth_state.json` para no repetir la lectura en cada activación.
5. En activaciones posteriores, el proceso carga el estado guardado y opera directamente.

**Por qué esto funciona sin intervención manual:**

- El navegador del sandbox es el mismo con el que el Director accede a la plataforma Z.ai. La sesión ya está autenticada como él.
- `agent-browser cookies` puede leer cookies HttpOnly porque opera a nivel del navegador (perfil de Chromium), no a través de JavaScript (que sí tendría la restricción HttpOnly).
- El JWT no tiene `exp` ni `expires_at` (tokens infinitos por diseño), así que una vez obtenido, sigue siendo válido indefinidamente mientras el servidor no invalide la sesión.

**Fallback (solo si la sesión del sandbox no está autenticada):**

Si el proceso detecta que la cookie `token` contiene un JWT de invitado (email `guest-*@guest.com`), significa que el navegador del sandbox no está autenticado. En ese caso, el proceso le pide al Director que inicie sesión en chat.z.ai desde el propio navegador del sandbox (abriendo la URL y haciendo login una vez). Después de eso, el proceso recupera el JWT automáticamente y no vuelve a pedir nada.

**Notas técnicas clave:**

- La cookie se llama `token`, es HttpOnly.
- El servidor refresca el JWT en cada request (nueva firma ES256, mismo payload).
- El JWT no tiene campo `exp` ni `expires_at` (tokens infinitos por diseño).
- La UI de chat no renderiza en agent-browser, pero todas las API calls funcionan.
- El share API es idempotente: devuelve el share_id existente o crea uno nuevo.

**Endpoints usados:**

- `POST /api/v1/chats/{chat_id}/share` → crear o reutilizar share.
- `GET /api/v1/chats/share/{share_id}` → árbol de mensajes (sin contenido).
- `POST /api/v1/chats/{share_id}/messages/batch` → contenido completo de mensajes (funciona como invitado).

---

## 12. Metadata de recuperación

Archivo `_metadata.json` con:

```json
{
  "chat_id": "371ba778-...",
  "share_id": "db717d70-...",
  "ultimo_timestamp": 1787607626,
  "total_exchanges": 142,
  "tema_a_archivo": {
    "validaciones": "bloque_01.md",
    "planificador": "bloque_02.md",
    "configuracion": "bloque_01.md",
    "metodologia": "bloque_03.md",
    "validaciones_server": "bloque_04.md",
    "validaciones_router": "bloque_05.md"
  },
  "subtemas_derivados": {
    "validaciones": ["validaciones_server", "validaciones_router"]
  },
  "ultima_activacion": "2026-09-02T14:30:00Z"
}
```

**Campos críticos:**

- `tema_a_archivo`: mapeo que garantiza la unicidad. Un tema aparece una sola vez aquí, apuntando a un solo archivo.
- `subtemas_derivados`: registro de qué subtemas se crearon al subdividir un tema grande.
- `ultimo_timestamp`: marca el punto hasta donde se ha procesado, para la actualización incremental.
- `ultima_activacion`: timestamp de la última vez que el proceso se activó.

---

## 13. Limitaciones conocidas

1. **El sistema no previene la compresión:** Solo mitiga sus efectos detectándola y recuperando.
2. **Requiere agent-browser:** La API no es accesible por curl directamente; se necesita un navegador con cookies de sesión.
3. **La detección no es perfecta:** Los tres mecanismos combinados (léxico, contador, auto-preguntas) pueden perder casos. El subagente observador queda como mejora futura.
4. **El estado actual es puntual:** No guarda historial de estados anteriores. Si se necesita saber el estado en un momento pasado, no es posible.
5. **Las decisiones requieren LLM:** El patrón regex no es suficiente para extraer decisiones; se necesita comprensión semántica.
6. **La tarea actual puede ser "general":** Cuando el Director da instrucciones transversales, no hay tema dominante. El estado actual contendrá contexto de múltiples temas y será menos preciso.

---

## 14. Cambios pendientes respecto al código actual (v1.0)

El código actual está implementado como CLI con `click` y no refleja esta spec v3.1. Los cambios pendientes para alinear el código con esta spec son:

1. **De CLI a proceso autónomo:** Eliminar la interfaz `click`, crear un proceso que el agente activa internamente.
2. **Mecanismos de detección:** Implementar los tres (léxico, contador preventivo, auto-preguntas).
3. **Reescribir el clasificador:** Cambiar de "un tema por archivo" a "varios temas por archivo hasta llenar el límite".
4. **Subdivisión con nuevos temas:** Cambiar de "parte1/parte2" a subtemas derivados únicos.
5. **Mecanismo de unicidad temática:** Garantizar que un tema no aparezca en dos archivos.
6. **Actualización incremental:** Implementar la lectura de `ultimo_timestamp` y la descarga solo de mensajes nuevos.
7. **Subagente de estado actual:** Implementar la lógica de localizar último intercambio, determinar tema, consultar índice, lanzar subagente.
8. **Límites actualizados:** `max_tokens_estado` de 3K a 20K, `carga_principal_max` de 23K a 40K.
9. **Sección de recuperación en `contrato.md`:** Añadir las instrucciones que el agente sigue cuando pierde contexto.
10. **Archivos accesibles desde el workspace y la carpeta de descarga.**
11. **Metadata `_metadata.json`:** Implementar con los campos `tema_a_archivo`, `subtemas_derivados`, `ultimo_timestamp`.
12. **JWT automático (v3.1):** Implementar la lectura automática de la cookie `token` del navegador del sandbox con `agent-browser cookies`. Eliminar la dependencia del token proporcionado manualmente por el Director. Incluir fallback para el caso de sesión no autenticada.
13. **Decisiones clave activas (v3.1):** Cambiar el subagente de decisiones de "bajo demanda" a "en cada activación del proceso". Implementar modo incremental (solo intercambios nuevos desde la última actualización). Implementar deduplicación. Implementar disparadores adicionales: cambio de tarea, indicación del Director, comunicación explícita de una decisión.

---

## 15. Log de validación

[Se llenará después de implementar y probar la v3.0.]

---

## 16. Referencias

- `metodologia_descubrimiento_jwt.md` — Procedimiento reproducible de autenticación.
- Spec v2.3 — Versión anterior, con arquitectura CLI. Reemplazada por esta v3.0.
- Worklog del proyecto — Entradas de sesiones 1 a 4 con la implementación inicial del paquete `contexto_zai/`.
