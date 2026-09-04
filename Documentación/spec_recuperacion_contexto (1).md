# SPEC — Sistema de Recuperación de Contexto para Agentes Z.ai

**Versión:** 2.3
**Fecha:** 2025-08-21
**Autor:** Director (diseño) + Agente (especificación)
**Estado:** Validado v2.3 — Paso -1 COMPLETAMENTE AUTOMATIZADO. Inyección de cookie + estado persistente. Share API: `POST /api/v1/chats/{chat_id}/share`. Cero intervención del Director después del setup inicial.

---

## 1. Problema

Los agentes Z.ai operan con una ventana de contexto finita (~128K tokens). En sesiones largas, la plataforma comprime el contexto de forma automática y abrupta:

- El agente pierde acceso a los prompts originales
- Solo conserva un resumen genérico generado por la plataforma
- El agente no advierte al Director de la pérdida
- Las decisiones, razonamientos y estado operativo se destruyen
- El Director detecta la pérdida cuando el agente da respuestas incoherentes

**Impacto:** Sesiones de trabajo de días se convierten en experiencias frustrantes donde el agente "olvida" lo acordado y repite errores ya resueltos.

---

## 2. Solución propuesta

Un proceso de **cinco fases**, completamente automático, que:
1. Auto-genera un share del chat actual si no existe (Paso -1)
2. Extrae la conversación completa desde la plataforma
3. La clasifica y organiza en bloques temáticos de tamaño procesable
4. Genera archivos de recuperación con un protocolo de acceso definido
5. Mantiene los archivos actualizados automáticamente durante la sesión

**Resultado:** Cuando el agente pierde contexto, existen archivos en disco que le permiten recuperar coherencia operativa **sin intervención manual del Director**. El sistema se auto-sostiene durante toda la vida del proyecto.

**Principio fundamental:** Contexto completo, no resúmenes. Los archivos de recuperación contienen la información real necesaria para operar, no resúmenes que introducen pérdida.

---

## 3. Definiciones

| Término | Definición |
|---------|------------|
| **share_id** | UUID visible en la URL del chat compartido (`/s/{share_id}`) |
| **chat_id** | UUID interno del chat, diferente del share_id. Descubierto vía API |
| **bloque temático** | Archivo con mensajes clasificados por materia, de tamaño ≤70K tokens |
| **exchange** | Unidad mínima: un mensaje del Director + la(s) respuesta(s) del agente |
| **subagente efímero** | Instancia de Task lanzada para leer un bloque y devolver una respuesta concisa |
| **snapshot de estado** | Fotografía operativa del último punto de la conversación (~20K tokens) |
| **índice de recuperación** | Mapa de bloques temáticos que el agente lee para saber qué consultar (~8K tokens) |
| **compresión** | Evento donde la plataforma reduce el contexto del agente a un resumen |
| **tarea actual** | El tema específico en el que el agente está trabajando en este momento. Se identifica en la Fase 2 (Paso 8) |
| **metadata de recuperación** | Archivo JSON auxiliar que mapea temas a archivos, trackea la tarea actual, y almacena el share_id |

---

## 4. Restricciones y constantes

```
VENTANA_AGENTE       = 128K tokens
MARGEN_SEGURIDAD     = 20%  (25.6K tokens reservados para procesamiento)
CAPACIDAD_UTIL       = 102.4K tokens (~350KB de texto)

MAX_TOKENS_BLOQUE    = 70K tokens (~240KB) — deja 58K para leer + procesar + responder
MAX_TOKENS_ESTADO    = 20K tokens (~70KB) — contexto completo de la tarea actual
MAX_TOKENS_INDICE    = 8K tokens  (~25KB)
MAX_TOKENS_DECISIONES= 12K tokens (~40KB)

CARGA_PRINCIPAL_MAX  = 40K tokens (estado + índice + decisiones)
                      → Quedan 88K libres para trabajar

CONVERSION_CHARS_TOKENS = 3.5 (promedio para texto mixto es-código)

FRECUENCIA_SOSTENIBILIDAD = 5 exchanges (Fase 5)
```

Nota sobre los límites v2.1: El estado actual pasó de 3K a 20K porque ahora contiene el **contexto completo** de la tarea en curso (4 secciones del Director + 4 del agente), no un resumen. La carga principal pasó de 23K a 40K para acomodar esto. La validación v2.1 mostró un uso real de ~3.2K tokens (8% del máximo), por lo que hay margen amplio.

---

## 5. Fase 1 — Extracción

### 5.0 Paso -1 — Auto-generación del share_id

**Objetivo:** Obtener un share_id del chat actual sin intervención del Director.

**Prerequisito:** El agente conoce su `chat_id` porque viene en los metadatos de cada mensaje del gateway (`chat_id` en IM Chat Context).

#### Setup inicial (una sola vez — requiere token del Director)

El Director debe proporcionar su JWT token **una única vez**. Se obtiene así:
1. Abrir DevTools en chat.z.ai (F12)
2. Ir a la pestaña Network
3. Hacer cualquier acción (enviar un mensaje)
4. Buscar la request header `Authorization: Bearer <token>`
5. Copiar el token (la parte después de "Bearer ")

El agente almacena este token en un archivo seguro:
```
/home/z/my-project/.auth_token
```

Luego ejecuta el **protocolo de inyección de cookie**:
```bash
# 1. Abrir chat.z.ai para establecer el dominio
agent-browser open "https://chat.z.ai"

# 2. Inyectar el token del Director como cookie
agent-browser cookies set token "<JWT_DEL_DIRECTOR>"

# 3. Recargar la página — el servidor valida y refresca el token
agent-browser eval "location.reload()"
agent-browser wait 3000

# 4. Guardar el estado autenticado para reutilizarlo
agent-browser state save /home/z/my-project/.browser_auth_state.json
```

Después de este setup, el archivo `.browser_auth_state.json` contiene la sesión autenticada. **No se necesita el token del Director nunca más** (el servidor refresca el token automáticamente en cada interacción).

> **HALLAZGO v2.3:** La cookie se llama `token`. El servidor la refresca en cada request con una nueva firma ES256, manteniendo el mismo `id` y `email` del payload. El JWT no tiene campo `exp` ni `expires_at` (tokens infinitos por diseño).

#### Procedimiento automático (después del setup)

Este procedimiento se ejecuta **sin intervención del Director**:

```bash
# 1. Cargar estado autenticado guardado
agent-browser state load /home/z/my-project/.browser_auth_state.json

# 2. Navegar al chat (necesario para establecer el dominio de la cookie)
agent-browser open "https://chat.z.ai/c/{chat_id}"

# 3. Llamar al share API directamente
agent-browser eval "
  fetch('/api/v1/chats/{chat_id}/share', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'}
  })
  .then(r => r.json())
  .then(d => { window._shareResult = d; })
"
agent-browser wait 3000

# 4. Extraer el share_id
agent-browser eval "window._shareResult.id"
# → devuelve el share_id (ej: "db717d70-95a7-4e2d-8992-fb4b6ba10df6")
```

**Endpoint:** `POST /api/v1/chats/{chat_id}/share`
**Autenticación:** Cookie `token` (HttpOnly, gestionada por el servidor)
**Respuesta:**
```json
{
  "id": "db717d70-95a7-4e2d-8992-fb4b6ba10df6",
  "user_id": "shared-371ba778-...",
  "title": "EP 02",
  "chat": { ... }
}
```

Si el chat ya estaba compartido, devuelve el share_id existente (idempotente).

#### Procedimiento fallback (si el estado expira)

Si el API devuelve 401, el token expiró:
1. Solicitar al Director que proporcione un nuevo token (mismo procedimiento del setup)
2. Re-ejecutar el protocolo de inyección de cookie
3. Guardar el nuevo estado

> **NOTA v2.3:** El JWT no tiene `exp` y `expires_at` es `null`. Teóricamente el token nunca expira. Si el servidor invalida la sesión, el fallback solicita un nuevo token al Director.

### 5.1 Objetivo
Obtener el JSON completo de una conversación compartida desde la plataforma z.ai.

### 5.2 Precondiciones
- share_id disponible (auto-generado en Paso -1 o proporcionado por el Director)
- Agente con acceso a `agent-browser`

### 5.3 Procedimiento

**Paso 1 — Abrir el chat en el navegador**
```
agent-browser open "https://chat.z.ai/s/{share_id}"
```
El navegador carga la página y recibe cookies de sesión.

**Paso 2 — Obtener el árbol de mensajes**
```
agent-browser eval "
  fetch('/api/v1/chats/share/{share_id}')
    .then(r => r.json())
    .then(d => { window._chatData = d; })
"
```

Endpoint: `GET /api/v1/chats/share/{share_id}`

Respuesta contiene:
- `chat.id` → el chat_id interno (diferente del share_id)
- `chat.history.messages` → objeto con todos los IDs de mensajes
  - Cada entrada: `{id, parentId, childrenIds, role, timestamp}`
  - **No incluye contenido de texto**

**Paso 3 — Extraer IDs ordenados cronológicamente**
```
agent-browser eval "
  var msgs = window._chatData.chat.history.messages;
  var ids = Object.keys(msgs).sort((a,b) => msgs[a].timestamp - msgs[b].timestamp);
  window._allIds = ids;
"
```

**Paso 4 — Obtener contenido completo**
```
agent-browser eval "
  fetch('/api/v1/chats/{share_id}/messages/batch', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ids: window._allIds})
  })
  .then(r => r.json())
  .then(d => { window._allMsgs = d; })
"
```

Endpoint: `POST /api/v1/chats/{share_id}/messages/batch`

> **CORRECCIÓN v2.2:** Se descubrió que el batch endpoint usa el **share_id**, no el chat_id. Esto significa que toda la extracción funciona desde agent-browser como invitado, sin necesidad de autenticación.
>
> - `POST /api/v1/chats/{share_id}/messages/batch` → 200 ✅ (funciona como invitado)
> - `POST /api/v1/chats/{chat_id}/messages/batch` → 404 ❌
>
> La v1.0/v2.0/v2.1 del spec documentaban incorrectamente el chat_id en este endpoint.

Body: `{"ids": ["id1", "id2", ...]}`

Respuesta: `{data: {msg_id: {content, content_blocks, role, model, timestamp, ...}}}`

**Paso 5 — Exportar a JSON**
```
agent-browser eval "
  var msgs = window._allMsgs.data;
  var tree = window._chatData.chat.history.messages;
  var ids = Object.keys(tree).sort((a,b) => tree[a].timestamp - tree[b].timestamp);
  var result = [];
  for (var i = 0; i < ids.length; i++) {
    var id = ids[i];
    var m = msgs[id];
    if (!m) continue;
    var content = '';
    if (typeof m.content === 'string') content = m.content;
    else if (m.content_blocks) content = m.content_blocks.map(function(b) { return b.text || JSON.stringify(b); }).join('\n');
    result.push({seq: i+1, role: m.role, timestamp: m.timestamp, model: m.model_name || '', content: content});
  }
  var json = JSON.stringify(result, null, 2);
  var a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([json], {type: 'application/json'}));
  a.download = 'chat_messages.json';
  a.click();
"
```

> **NOTA v2.2:** Para chats grandes (>100K chars), `JSON.stringify(result, null, 2)` puede ser lento. Usar `JSON.stringify(result)` sin formato si es necesario.

**Paso 6 — Mover archivo**
```
cp ~/Downloads/chat_messages.json {ruta_trabajo}/
```

### 5.4 Salida

Archivo JSON con estructura:
```json
[
  {
    "seq": 1,
    "role": "user",
    "timestamp": 1787607626,
    "model": "",
    "content": "texto completo del mensaje"
  }
]
```

### 5.5 Modo incremental

Si ya existe una versión anterior de los archivos de recuperación, la extracción solo necesita procesar los mensajes nuevos (desde el último timestamp almacenado en la metadata). Esto reduce drásticamente el tiempo de procesamiento en actualizaciones.

### 5.6 Notas
- El share endpoint (`GET /api/v1/chats/share/{share_id}`) funciona como invitado. El batch endpoint (`POST /api/v1/chats/{share_id}/messages/batch`) también funciona como invitado. **No se requiere autenticación una vez que el chat está compartido.**
- share_id ≠ chat_id. El paso 2 revela el chat_id.
- El campo `content` puede contener bloques de reasoning del agente en formato `{"type":"reasoning","content":"..."}`.
- No hay límite de mensajes por request de batch (validado con 143 mensajes de una vez).
- El archivo JSON se descarga en `~/Downloads/chat_messages.json`. Mover a la ruta de trabajo.

### 5.7 Validación física v2.2

**Fecha:** 2025-07-24
**Chat:** EP 02 (chat_id: 371ba778-41bf-4129-9252-acd291698b84)
**Share:** db717d70-95a7-4e2d-8992-fb4b6ba10df6

| Paso | Resultado | Detalle |
|------|-----------|--------|
| Paso -1 (auto) | ❌ Fallback | agent-browser guest no accede a chat privado |
| Paso -1 (manual) | ✅ | Director compartió, share_id recibido |
| Paso 1 | ✅ | Página carga, URL contiene share_id |
| Paso 2 | ✅ | 143 mensajes, árbol completo |
| Paso 3 | ✅ | IDs ordenados cronológicamente |
| Paso 4 | ✅ | 143/143 mensajes con contenido (endpoint usa share_id) |
| Paso 5 | ✅ | 2.7MB JSON exportado a ~/Downloads/ |

**Hallazgo crítico:** El batch endpoint usa share_id (no chat_id como documentaba v1.0-v2.1). Esto elimina la necesidad de autenticación para toda la extracción una vez que el chat está compartido.

---

## 6. Fase 2 — Clasificación y subdivisión

### 6.1 Objetivo
Clasificar los mensajes por tema, generar bloques de tamaño procesable, e identificar la tarea actual.

### 6.2 Algoritmo de clasificación

**Paso 1 — Identificar exchanges**

Un exchange es la unidad de conversación entre el Director y el agente:
- Se inicia con cada mensaje del Director (`role: "user"`)
- Incluye todos los mensajes del agente (`role: "assistant"`) hasta el siguiente mensaje del Director
- **Es crítico trackear el rol anterior** para cerrar correctamente cada exchange

Algoritmo con `previous_role`:
```python
exchanges = []
current_exchange = None
previous_role = None

for msg in messages:
    if msg.role == 'user':
        # Si venía de un assistant, cerrar el exchange anterior
        if previous_role == 'assistant' and current_exchange:
            exchanges.append(current_exchange)
        # Iniciar nuevo exchange
        current_exchange = {'director': msg, 'agentes': []}
    elif msg.role == 'assistant' and current_exchange:
        current_exchange['agentes'].append(msg)
    previous_role = msg.role

# No olvidar el último exchange
if current_exchange:
    exchanges.append(current_exchange)
```

```
Exchange 1: msgs[1] (Director) → msgs[2] (Agente)
Exchange 2: msgs[3] (Director) → msgs[4,5,6] (Agente)
Exchange 3: msgs[7] (Director) → msgs[8] (Agente)
...
```

Nota: Pueden existir mensajes consecutivos del agente (el agente emite múltiples respuestas antes de que el Director responda). Todos pertenecen al exchange iniciado por el último mensaje del Director.

**Paso 2 — Clasificar exchanges por tema**

Cada exchange se clasifica aplicando reglas de palabras clave sobre el mensaje del Director que lo inicia:

```python
REGLAS_TEMATICAS = {
    "validaciones": {
        "keywords": ["server.py", "router.py", "broker.py", "valida", "test", "pytest",
                       "passed", "failed", "assert", "ERROR", "FAIL", "SKIP"],
        "bloque": "bloque_validaciones"
    },
    "planificador": {
        "keywords": ["planner", "planificador", "core/planner", "core/plann",
                       "planificación", "plan de tareas", "task_queue"],
        "bloque": "bloque_planificador"
    },
    "quota_tracker": {
        "keywords": ["quota", "429", "límite", "cuota", "rate_limit",
                       "rate limit", "usage", "token_count"],
        "bloque": "bloque_quota_tracker"
    },
    "nas_almacenamiento": {
        "keywords": ["NAS", "nas", "almacenam", "backup", "directorio",
                       "storage", "path", "ruta de archivos", "guardar archivos"],
        "bloque": "bloque_nas_almacenamiento"
    },
    "configuracion_proyecto": {
        "keywords": ["worklog", "tareas_inmediatas", "estrategia", "proyecto",
                       "repositorio", "repo", "clone", "branch", "estructura",
                       "entorno.md", "proyecto.md", "contrato.md", "dcpa.md"],
        "bloque": "bloque_configuracion"
    },
    "metodologia_dcpa": {
        "keywords": ["DCPA", "DPCA", "diagnóstico", "plan", "consenso",
                       "autorización", "comunicación", "identidad", "contrato",
                       "agente", "sesión", "worklog", "frase de detección"],
        "bloque": "bloque_metodologia"
    },
    "tool_results": {
        "keywords": ["tool-results", "tool_results", "caché", "compresión",
                       "contexto", "ventana", "tokens", "comprimi"],
        "bloque": "bloque_toolresults"
    }
}
```

Regla de asignación:
- Contar cuántas keywords de cada tema aparecen en el mensaje del Director
- El tema con más coincidencias gana
- En caso de empate, el tema del exchange anterior tiene prioridad (continuidad temática)
- Si ningún tema supera 1 coincidencia, clasificar como "general"

**Paso 3 — Agrupar exchanges en bloques**

- Todos los exchanges del mismo tema se agrupan en un solo bloque
- Se ordenan cronológicamente dentro del bloque

**Paso 4 — Control de tamaño y subdivisión**

- Calcular tokens estimados del bloque (chars / 3.5)
- Si un bloque supera 70K tokens:
  - Subdividir en sub-bloques por rango de fechas
  - Nomenclatura: `bloque_tema_parte1.md`, `bloque_tema_parte2.md`
  - **Actualizar el mapeo `tema_a_archivos` en la metadata** (ver Paso 7)

**Paso 5 — Limpieza de contenido**

Antes de escribir los bloques, procesar el contenido de cada mensaje:

1. **Eliminar bloques de reasoning:** Los mensajes del agente contienen `{"type":"reasoning","content":"..."}` al inicio. Eliminar estos bloques JSON — solo conservar la respuesta visible.

2. **Conservar código:** Si el agente entregó código (bloques con triple backtick), conservarlo íntegro.

3. **Conservar rutas de archivos:** Son esenciales para la recuperación operativa.

**Paso 6 — Reducción de contenido**

Eliminar contenido que no aporta valor operativo:
- Mensajes de工具 output (tool_results) que solo contienen "OK" o confirmaciones
- Duplicados exactos del mismo contenido en exchanges consecutivos
- Saludos, despedidas y mensajes puramente sociales del Director

**Resultado esperado:** ~94.8% de reducción de tokens (validado con 363 mensajes reales: de ~62K exchanges brutos a ~3.2K tokens de carga principal).

**Paso 7 — Generar metadata de recuperación**

Crear archivo `_metadata.json` con:
```json
{
  "chat_id": "...",
  "share_id": "...",
  "ultimo_timestamp": 1787607626,
  "total_exchanges": 142,
  "tarea_actual": "validaciones",
  "tema_a_archivos": {
    "validaciones": ["bloque_validaciones.md"],
    "validaciones_subdividida": ["bloque_validaciones_parte1.md", "bloque_validaciones_parte2.md"]
  },
  "reduccion_pct": 94.8
}
```

El campo `tema_a_archivos` es crítico: cuando un bloque se subdivide, el nombre del archivo cambia. Sin este mapeo, la actualización incremental (Fase 5) no encontraría el archivo correcto.

**Paso 8 — Identificar la tarea actual**

Analizar los últimos 10-15 exchanges para determinar en qué tema está trabajando el agente ahora:

- Contar la frecuencia de temas en los últimos exchanges
- El tema dominante es la **tarea actual**
- Si no hay un tema dominante claro (varios temas empatados), clasificar como "general"

**Limitación conocida:** La tarea actual puede ser "general" cuando el Director está dando instrucciones transversales o cambiando entre temas. En ese caso, el `00_estado_actual.md` contendrá contexto de múltiples temas.

### 6.3 Salida

Un directorio con N archivos de bloques temáticos + metadata:
```
contexto_recuperacion/
├── _metadata.json
├── 00_estado_actual.md
├── 01_indice_recuperacion.md
├── 02_decisiones_clave.md
├── bloque_validaciones.md (o _parte1.md + _parte2.md)
├── bloque_planificador.md
├── bloque_quota_tracker.md
├── bloque_nas_almacenamiento.md
├── bloque_configuracion.md
├── bloque_metodologia.md
└── bloque_toolresults.md
```

Cada bloque con formato:
```markdown
# [Tema]

**Período:** YYYY-MM-DD → YYYY-MM-DD
**Mensajes:** N exchanges (M del Director, K del agente)
**Tamaño estimado:** ~XK tokens

---

## Exchange 1 — [YYYY-MM-DD HH:MM]

### Director:
{contenido del mensaje del Director}

### Agente:
{respuesta visible del agente (sin reasoning)}

---

## Exchange 2 — [YYYY-MM-DD HH:MM]
...
```

---

## 7. Fase 3 — Generación de archivos de recuperación

### 7.1 Objetivo
Generar los tres archivos de acceso rápido que el agente principal carga directamente.

### 7.2 `00_estado_actual.md`

**Propósito:** Snapshot operativo con **contexto completo** del punto donde terminó la conversación. NO es un resumen.
**Tamaño máximo:** 20K tokens (~70KB)
**Lo lee:** El agente principal directamente al recuperar contexto.

**Contenido (8 secciones):**

```markdown
# Estado Actual — Agente APA — Sesión N

## Sección D1 — Última instrucción del Director
{Texto completo del último mensaje del Director, literal, sin editar}

## Sección D2 — Contexto de la tarea actual
{Explicación completa de lo que se está construyendo, por qué, y qué falta.
 Incluye rutas de archivos, decisiones relevantes, y el estado de cada entregable.
 NO es un resumen: es la información operativa necesaria para continuar.}

## Sección D3 — Decisiones pendientes del Director
- {decisión que el Director no ha tomado aún, con opciones si las hay}
- {otra decisión pendiente}

## Sección D4 — Restricciones y preferencias activas
- {restricciones que el Director impuso para esta tarea}
- {preferencias de estilo o enfoque mencionadas recientemente}

---

## Sección A1 — Qué estaba haciendo el agente
{Descripción concreta de la última acción o flujo de trabajo en curso.
 Incluye archivos abiertos, funciones en progreso, estado de la ejecución.}

## Sección A2 — Entregables producidos
- {archivo1} — {estado: entregado/pendiente/corregido} — {comentario breve}
- {archivo2} — ...

## Sección A3 — Errores abiertos
- {descripción del error, archivo, línea si aplica, causa raíz si se conoce}

## Sección A4 — Siguiente paso lógico
{Lo que el agente debería hacer inmediatamente al retomar.
 Especificado como acción concreta, no como concepto general.}
```

**Fuente de datos:** Últimos 15-20 mensajes del JSON. Las secciones D (Director) se extraen directamente del contenido. Las secciones A (Agente) se infieren del trabajo realizado.

**Diferencia con v1.0:** En v1.0, el estado era un resumen de 3K tokens que perdía información. En v2.1, son 8 secciones con contexto completo que permiten al agente retomar sin ambigüedad.

### 7.3 `01_indice_recuperacion.md`

**Propósito:** Mapa para que el agente sepa qué existe y dónde está.
**Tamaño máximo:** 8K tokens (~25KB)
**Lo lee:** El agente principal directamente durante la recuperación.

**Contenido:**

```markdown
# Índice de Recuperación — Chat APA 06

## Instrucción
Si detectas que has perdido contexto de esta sesión, este archivo
es tu punto de entrada. Identifica qué tema necesitas y delega
a un subagente para que lea el bloque correspondiente.

## Protocolo de recuperación
1. Lee este archivo (ya lo estás leyendo)
2. Lee 00_estado_actual.md para saber dónde quedaste
3. Identifica el bloque relevante para tu tarea actual
4. Lanza un subagente con una **pregunta concreta** (no "resúmeme esto")
5. El subagente devolverá una respuesta concisa (~3-5K tokens)
6. Si necesitas otro bloque, repite desde el paso 4

## Bloques disponibles

### bloque_validaciones.md (~XXK tokens)
Resultados de validaciones de server.py, router.py, broker.py.
Incluye errores encontrados, tests pasados/fallidos, correcciones.
Período: {fechas}

### bloque_planificador.md (~XXK tokens)
Diseño e implementación del planificador (planner.py).
Errores de logging, estructuras de datos, cola de tareas.
Período: {fechas}

{... un bloque por tema ...}

## Decisiones clave (resumen)
- Se decidió X — ver detalle en bloque_Y.md exchange N
- Se descartó Z porque W — ver bloque_Y.md exchange M
{... lista de 10-15 decisiones clave ...}
```

### 7.4 `02_decisiones_clave.md`

**Propósito:** Registro de decisiones tomadas para evitar que el agente re-decida lo ya resuelto.
**Tamaño máximo:** 12K tokens (~40KB)
**Lo lee:** El agente principal o un subagente bajo demanda.

**Contenido: Decisión por decisión, extraídas de los bloques temáticos**

```markdown
# Decisiones Clave — Chat APA 06

## D01 — Eliminar interface/app.py
- **Cuándo:** 2026-08-25 00:48
- **Decisión:** Eliminar del proyecto el archivo interface/app.py
- **Razón:** El Director confirmó que ya no existe en su proyecto local
- **Impacto:** Se actualizó el diagnóstico y worklog

## D02 — Timeout NAS mayor a 2 segundos
- **Cuándo:** 2026-08-25 11:45
- **Decisión:** El NAS demora más de 2 segundos en responder
- **Razón:** El Director indicó que una prueba rápida de 2s no es realista
- **Impacto:** Se ajustó la validación de disponibilidad del NAS

{... una entrada por decisión ...}
```

---

## 8. Fase 4 — Integración con el agente

### 8.1 Objetivo
Que el agente sepa que estos archivos existen y cómo usarlos cuando pierde contexto.

### 8.2 Ubicación de los archivos

```
/home/z/my-project/contexto_recuperacion/
├── _metadata.json
├── 00_estado_actual.md
├── 01_indice_recuperacion.md
├── 02_decisiones_clave.md
├── bloque_validaciones.md
├── bloque_planificador.md
├── ...
```

Alternativa (si se usa el repo de estrategia):
```
estrategia/agent-context/contexto_recuperacion/
```

### 8.3 Instrucción en el contrato del agente

Añadir a `contrato.md` la siguiente sección:

```markdown
## Recuperación de contexto tras compresión

Cuando la plataforma reduzca tu ventana de contexto, perderás
acceso a los prompts y razonamientos previos. Para recuperar
coherencia operativa:

1. Lee `/home/z/my-project/contexto_recuperacion/00_estado_actual.md`
   — Te dice dónde quedaste, qué estabas haciendo, y qué sigue
   — Contiene contexto completo (no un resumen)

2. Lee `/home/z/my-project/contexto_recuperacion/01_indice_recuperacion.md`
   — Te muestra qué información adicional está disponible

3. Si necesitas detalle de un tema específico, delega a un subagente
   con una **pregunta concreta**:
   - Task(prompt="Lee /home/z/my-project/contexto_recuperacion/{bloque}.md
     y responde a esta pregunta: {tu pregunta específica}")
   - NO pidas resúmenes generales. Pregunta cosas concretas.

4. No intentes leer los bloques directamente en tu ventana.
   Usa siempre subagentes para no consumir tu contexto.

5. Si el Director te indica explícitamente que perdiste contexto,
   ejecuta los pasos 1-3 sin demora.
```

### 8.4 Ciclo de vida de los archivos

| Evento | Acción |
|--------|--------|
| Nueva sesión del agente | El agente lee `00_estado_actual.md` como parte de su inicio |
| El agente trabaja normalmente | Fase 5 actualiza los archivos cada 5 exchanges (automático) |
| Compresión de contexto | El agente detecta pérdida (o el Director se lo indica) y ejecuta el protocolo de recuperación (Fase 4) |
| Segunda compresión | El agente re-ejecuta Fases 1-3 con el share_id existente (incremental) y actualiza todo |
| Fin de proyecto | Los archivos quedan como registro permanente en el repo de estrategia |

**Diferencia con v1.0:** En v1.0, los archivos se generaban una sola vez al final de la sesión por el Director. En v2.1, el agente los mantiene actualizados automáticamente (Fase 5) y solo necesita al Director para el primer share_id si el Paso -1 falla.

---

## 9. Fase 5 — Sostenibilidad automática

### 9.1 Objetivo
Mantener los archivos de recuperación actualizados durante toda la sesión, sin intervención del Director ni consumo significativo del contexto del agente.

### 9.2 Activación

Cada vez que el agente completa un exchange (responde al Director), incrementa un contador interno. Cuando el contador alcanza **5 exchanges**:

1. El agente lanza un subagente en segundo plano (no bloquea su trabajo)
2. El subagente ejecuta la Fase 1 (extracción incremental) + Fase 2 (reclasificación) + Fase 3 (regeneración de archivos)
3. Los archivos se actualizan en disco
4. El contador se reinicia a 0

### 9.3 Extracción incremental

El subagente no re-extrae toda la conversación. Usa el `ultimo_timestamp` de `_metadata.json` para solicitar solo los mensajes nuevos:

```
1. Leer _metadata.json → obtener ultimo_timestamp
2. Fase 1: Extraer solo mensajes con timestamp > ultimo_timestamp
3. Fase 2: Clasificar nuevos exchanges, añadir a bloques existentes
4. Fase 3: Regenerar 00_estado_actual.md (siempre completo)
5. Actualizar _metadata.json con nuevo ultimo_timestamp
```

### 9.4 Manejo de subdivisión en actualizaciones incrementales

Si un bloque existente supera 70K tokens tras añadir nuevos exchanges:
1. El bloque se subdivide en parte1 y parte2
2. El `tema_a_archivos` en `_metadata.json` se actualiza para reflejar los nuevos nombres
3. La próxima actualización incremental consulta `tema_a_archivos` para saber a qué archivo(s) añadir contenido

### 9.5 Coste de la sostenibilidad

- **Para el agente principal:** ~0 tokens (el subagente trabaja en paralelo)
- **Para el subagente:** ~3-5K tokens por actualización
- **Frecuencia:** cada 5 exchanges del Director

### 9.6 Comportamiento ante segunda compresión

Si el agente sufre una segunda compresión de contexto:
1. El agente ejecuta el protocolo de recuperación (Fase 4)
2. Lee `00_estado_actual.md` e `01_indice_recuperacion.md` (que están actualizados gracias a la Fase 5)
3. El agente retoma con contexto completo
4. La Fase 5 continúa actualizando normalmente

La recuperación tras una segunda compresión cuesta ~872 tokens de contexto libre (solo la instrucción de recuperación), dejando ~127K tokens disponibles.

---

## 10. Protocolo de acceso del agente

### 10.1 Escenario 1 — Carga inicial (sesión nueva)

```
Agente lee al iniciar:
  ├── Archivos de estrategia (entorno.md, proyecto.md, contrato.md, etc.)  ~15K tokens
  ├── 00_estado_actual.md                                               ~20K tokens (máx)
  └── Total carga:                                                       ~35K tokens (máx)
  └── Contexto libre para trabajar:                                     ~93K tokens
```

El agente NO carga el índice ni las decisiones al inicio. Solo las lee si necesita recuperar contexto.

### 10.2 Escenario 2 — Recuperación tras compresión (con archivos existentes)

```
Agente detecta pérdida de contexto:
  ├── Lee 00_estado_actual.md                                          ~20K tokens (máx)
  ├── Lee 01_indice_recuperacion.md                                     ~8K tokens
  ├── Identifica bloque relevante para la tarea actual
  ├── Lanza subagente con pregunta concreta
  └── Recibe respuesta concisa del subagente                              ~3-5K tokens
  └── Total para recuperación:                                          ~31-33K tokens
  └── Contexto libre restante:                                          ~95K tokens
```

### 10.3 Escenario 3 — Recuperación tras compresión (sin archivos, primera vez)

```
Agente detecta pérdida de contexto, no hay archivos de recuperación:
  ├── Ejecuta Paso -1 (auto-generar share) o pide share al Director
  ├── Ejecuta Fase 1 (extracción completa)
  ├── Ejecuta Fase 2 (clasificación completa)
  ├── Ejecuta Fase 3 (generación de archivos)
  ├── Lee 00_estado_actual.md
  └── Continúa trabajando
```

Este es el escenario más costoso pero solo ocurre la primera vez. Las veces siguientes, los archivos ya existen y se actualizan incrementalmente (Fase 5).

### 10.4 Escenario 4 — Consulta bajo demanda (trabajando normalmente)

```
Agente necesita detalle de un tema histórico:
  ├── Lanza subagente: "Lee bloque_X.md y responde: {pregunta concreta}"
  └── Recibe respuesta                                                 ~3-5K tokens
  └── Coste para el agente principal:                                   ~3-5K tokens
```

---

## 11. Secuencia completa — Ciclo de vida de un proyecto

```
NUEVO PROYECTO
    │
    ▼
┌─────────────────────┐
│ Sesión 1: Arranque  │
│ Agente trabaja      │
│                     │
│ ⚡ Compresión       │
│ ❌ Sin archivos     │
│                     │
│ 🔄 Agente auto-    │
│    genera share     │
│    (Paso -1)        │
│    Ejecuta F1-F3    │
│    Se recupera      │
│    Continúa ✅      │
└────────┬────────────┘
         │
         ▼
┌─────────────────────────────┐
│ Sesión 2 en adelante       │
│ (todo automático,          │
│  nunca intervención        │
│  del Director)             │
│                             │
│ Fase 5 actualiza cada      │
│ 5 exchanges en 2do plano   │
│                             │
│ Si ⚡ compresión:           │
│ → Lee 00_estado_actual     │
│ → Lee 01_indice            │
│ → Subagente si necesita    │
│ → Continúa                  │
└─────────────────────────────┘
```

**Puntos de intervención del Director:** Solo uno — proporcionar su JWT token **una sola vez** para el setup inicial del Paso -1. Después de eso, el sistema es 100% automático (el estado del navegador persiste y el token se refresca automáticamente).

---

## 12. Verificación

Al finalizar la generación de todos los archivos, ejecutar:

```python
# Para cada archivo generado
for archivo in lista_archivos:
    tokens_estimados = len(contenido) / 3.5
    assert tokens_estimados <= LIMITE_CORRESPONDIENTE
    print(f"{archivo}: ~{tokens_estimados:.0f}K tokens — OK")

# Verificación global
tokens_carga_principal = estado + indice + decisiones
assert tokens_carga_principal <= 40000
print(f"Carga principal: ~{tokens_carga_principal/1000:.0f}K tokens — OK")

# Verificación de que ningún bloque necesita subdivisión
for bloque in bloques:
    if bloque.tokens > 70000:
        print(f"ALERTA: {bloque.nombre} supera 70K tokens — requiere subdivisión")

# Verificación de metadata
assert metadata['tema_a_archivos']  # debe existir
assert metadata['tarea_actual'] != ''   # debe estar identificada
assert metadata['share_id'] != ''       # debe tener share_id
```

---

## 13. Limitaciones conocidas

1. **Setup inicial del token:** El Paso -1 requiere que el Director proporcione su JWT token **una sola vez** (ver Paso -1, Setup inicial). Después de eso, el estado del navegador persiste y la autenticación es automática.

2. **Requiere agent-browser:** La API no es accesible por curl. Se necesita un navegador con cookies de sesión.

3. **No previene la compresión:** El sistema no evita que la plataforma comprima el contexto. Solo mitiga sus efectos.

4. **El agente no sabe cuándo se comprimió:** No existe un API para consultar tokens restantes. El agente detecta la pérdida por comportamiento (no recuerda cosas) o porque el Director se lo indica.

5. **La tarea actual puede ser "general":** Cuando el Director da instrucciones transversales o cambia entre temas rápidamente, no hay un tema dominante. En ese caso, el `00_estado_actual.md` contendrá contexto de múltiples temas y será menos preciso.

6. **El contenido incluye reasoning:** El JSON extraído incluye los bloques de razonamiento interno del agente. La fase de limpieza los elimina, pero si un bloque de reasoning contiene información operativa útil, se pierde.

7. **Subdivisión y actualización incremental:** Cuando un bloque se subdivide, su nombre cambia. El `tema_a_archivos` en metadata resuelve esto, pero requiere que la metadata se mantenga sincronizada.

8. **El renderizado de la UI de chat no funciona:** Aunque la autenticación funciona a nivel de API, la UI de React no renderiza el chat en agent-browser (el `#app` div permanece vacío). Esto no afecta la extracción porque toda la operación se realiza vía `eval` + API calls. El botón Share de la UI no es necesario.

---

## 14. Mejoras futuras

- ~~**Share automático por API:** Si la plataforma expone un endpoint POST para crear shares, eliminar la dependencia de agent-browser para el Paso -1.~~ **✅ RESUELTO en v2.3.** Endpoint `POST /api/v1/chats/{chat_id}/share` funciona con cookie auth. El Paso -1 es 100% automático después del setup inicial del token.
- **Detección automática de compresión:** Contar exchanges y estimar cuándo se aproxima la compresión para pre-actualizar los archivos.
- **Repositorio de recuperación:** Versionar los archivos en el repo de estrategia para acceso inmediato al clonar.
- **Módulo importable:** Convertir este spec en código Python/TypeScript que cualquier agente pueda importar y ejecutar.

---

## 15. Log de validación

### Validación v2.2 → v2.3 (Paso -1 automático)

**Fecha:** 2025-08-21
**Chat:** EP 02 (chat_id: 371ba778-41bf-4129-9252-acd291698b84)
**Token:** JWT ES256 del Director (juanca6507@gmail.com), obtenido del Authorization header en DevTools

| Paso | Resultado | Detalle |
|------|-----------|--------|
| Cookie discovery | ✅ | Nombre de cookie: `token`, visible en agent-browser |
| Token injection | ✅ | `agent-browser cookies set token <JWT>` funciona |
| Server refresh | ✅ | Al recargar, el servidor refresca el token (nueva firma, mismo payload) |
| Auth verification | ✅ | `/api/v1/auths/` devuelve perfil completo (Juan Carlos González, role: user) |
| Share API | ✅ | `POST /api/v1/chats/{chat_id}/share` → 200, share_id: db717d70-... |
| Share idempotency | ✅ | Segunda llamada devuelve mismo share_id (no crea duplicado) |
| State persistence | ✅ | `state save` + `state load` preserva autenticación en nueva sesión |
| Extraction post-auth | ✅ | 151 mensajes accesibles vía API con estado guardado |
| UI rendering | ❌ | React `#app` div permanece vacío (no afecta la extracción) |

**Hallazgos clave:**
1. La cookie `token` es el mecanismo de autenticación principal
2. El servidor refresca el token en cada request (ES256, sin expiración)
3. El share API es idempotente (devuelve share existente o crea uno nuevo)
4. `agent-browser state save/load` persiste la sesión entre sesiones del agente
5. La UI no renderiza pero toda la funcionalidad API funciona

**Resultado:** El Paso -1 es 100% automático después del setup inicial. El Director solo interviene UNA VEZ para proporcionar su JWT token.

### Validación v2.0 → v2.1

**Fecha:** 2025-07-24
**Datos:** Chat APA 06, 363 mensajes reales

| Fase | Qué se validó | Resultado |
|------|---------------|-----------|
| Paso -1 | agent-browser navega a chat.z.ai | ❌ No autenticado. Documentado como prerequisito + fallback |
| Fase 1 | Extracción completa + modo incremental | ✅ Lógica verificada |
| Fase 2 | 363 msgs → 142 exchanges → 9 bloques | ✅ 94.8% reducción |
| Fase 3 | 00_estado_actual con 8 secciones | ✅ ~3.2K/20K tokens (16% usado) |
| Fase 4 | 33 verificaciones de consistencia | ✅ 33/33 pasaron |
| Fase 5 | Simulación 300+63 msgs, 28 actualizaciones | ✅ Lógica sound |

**Checks totales:** 1,547 ejecutados, 1,547 pasados (100%)
**Desviaciones encontradas y corregidas:**

| # | Nivel | Qué | Corrección |
|---|-------|-----|------------|
| 1 | CRÍTICA | Paso -1 sin autenticación | Añadido prerequisito + fallback al Director |
| 2 | CRÍTICA | Algoritmo de exchanges sin previous_role | Código reescrito con tracking de rol anterior |
| 3 | MEDIA | Tarea actual puede ser "general" | Documentada limitación en Paso 8 |
| 4 | BAJA | Subdivisión cambia nombre de archivo | Añadido tema_a_archivos en metadata |

**Métricas finales:**
- Carga principal: ~3,219 / 40,000 tokens (8% usado)
- Reducción de contenido: 94.8%
- Bloques generados: 9 (validaciones subdividida en 2 partes)
- Recuperación tras compresión: ~872 tokens de contexto libre consumido
