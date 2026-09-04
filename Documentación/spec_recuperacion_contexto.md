# SPEC — Sistema de Recuperación de Contexto para Agentes Z.ai

**Versión:** 1.0
**Fecha:** 2026-08-30
**Autor:** Director (diseño) + Agente (especificación)
**Estado:** Borrador — pendiente consenso

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

Un proceso de cuatro fases que:
1. Extrae la conversación completa desde la plataforma
2. La clasifica y organiza en bloques temáticos de tamaño procesable
3. Genera archivos de recuperación con un protocolo de acceso definido
4. Inyecta instrucciones permanentes en el contrato del agente

**Resultado:** Cuando el agente pierde contexto, existen archivos en disco que le permiten recuperar coherencia operativa sin intervención manual del Director.

---

## 3. Definiciones

| Término | Definición |
|---------|------------|
| **share_id** | UUID visible en la URL del chat compartido (`/s/{share_id}`) |
| **chat_id** | UUID interno del chat, diferente del share_id. Descubierto vía API |
| **bloque temático** | Archivo con mensajes clasificados por materia, de tamaño ≤70K tokens |
| **exchange** | Unidad mínima: un mensaje del Director + la(s) respuesta(s) del agente |
| **subagente efímero** | Instancia de Task lanzada para leer un bloque y devolver una respuesta concisa |
| **snapshot de estado** | Fotografía operativa del último punto de la conversación (~3K tokens) |
| **índice de recuperación** | Mapa de bloques temáticos que el agente lee para saber qué consultar (~8K tokens) |
| **compresión** | Evento donde la plataforma reduce el contexto del agente a un resumen |

---

## 4. Restricciones y constantes

```
VENTANA_AGENTE       = 128K tokens
MARGEN_SEGURIDAD     = 20%  (25.6K tokens reservados para procesamiento)
CAPACIDAD_UTIL       = 102.4K tokens (~350KB de texto)

MAX_TOKENS_BLOQUE    = 70K tokens (~240KB) — deja 58K para leer + procesar + responder
MAX_TOKENS_ESTADO    = 3K tokens  (~10KB)
MAX_TOKENS_INDICE    = 8K tokens  (~25KB)
MAX_TOKENS_DECISIONES= 12K tokens (~40KB)

CARGA_PRINCIPAL_MAX  = 23K tokens (estado + índice + decisiones)
                      → Quedan 105K libres para trabajar

CONVERSION_CHARS_TOKENS = 3.5 (promedio para texto mixto es-código)
```

---

## 5. Fase 1 — Extracción

### 5.1 Objetivo
Obtener el JSON completo de una conversación compartida desde la plataforma z.ai.

### 5.2 Precondiciones
- Chat previamente compartido por el Director (tiene share link)
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
  fetch('/api/v1/chats/' + window._chatData.chat.id + '/messages/batch', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ids: window._allIds})
  })
  .then(r => r.json())
  .then(d => { window._allMsgs = d; })
"
```

Endpoint: `POST /api/v1/chats/{chat_id}/messages/batch`
Body: `{"ids": ["id1", "id2", ...]}`

Respuesta: `{data: {msg_id: {content, content_blocks, role, model, timestamp, ...}}}`

**Paso 5 — Exportar a JSON**
```
agent-browser eval "
  // Construir array secuencial
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
    else if (m.content_blocks) content = m.content_blocks.map(b => b.text || JSON.stringify(b)).join('\n');
    result.push({seq: i+1, role: m.role, timestamp: m.timestamp, model: m.model_name || '', content: content});
  }
  // Descargar
  var a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], {type: 'application/json'}));
  a.download = 'chat_messages.json';
  a.click();
"
```

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

### 5.5 Notas
- El share endpoint requiere cookies de sesión. `curl` sin autenticación devuelve 403.
- share_id ≠ chat_id. El paso 2 revela el chat_id.
- El campo `content` puede contener bloques de reasoning del agente en formato `"{\"type\":\"reasoning\",\"content\":\"...\"}"`.
- No hay límite de mensajes por request de batch (se enviaron 363 de una vez).

---

## 6. Fase 2 — Clasificación y subdivisión

### 6.1 Objetivo
Clasificar los mensajes por tema y generar bloques de tamaño procesable.

### 6.2 Algoritmo de clasificación

**Paso 1 — Identificar exchanges**

Un exchange es la unidad de conversación entre el Director y el agente:
- Se inicia con cada mensaje del Director (`role: "user"`)
- Incluye todos los mensajes del agente (`role: "assistant"`) hasta el siguiente mensaje del Director
- El tema del exchange lo determina el contenido del mensaje del Director

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

**Paso 4 — Control de tamaño**

- Calcular tokens estimados del bloque (chars / 3.5)
- Si un bloque supera 70K tokens:
  - Subdividir en sub-bloques por rango de fechas
  - Nomenclatura: `bloque_tema_parte1.md`, `bloque_tema_parte2.md`

### 6.3 Limpieza de contenido

Antes de escribir los bloques, procesar el contenido de cada mensaje:

1. **Eliminar bloques de reasoning:** Los mensajes del agente contienen `"{\"type\":\"reasoning\",\"content\":\"...\"}"` al inicio. Eliminar estos bloques JSON — solo conservar la respuesta visible.

2. **Conservar código:** Si el agente entregó código (bloques con triple backtick), conservarlo íntegro.

3. **Conservar rutas de archivos:** Son esenciales para la recuperación operativa.

### 6.4 Salida

Un directorio con N archivos de bloques temáticos:
```
contexto_recuperacion/
├── bloque_validaciones.md
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

**Propósito:** Snapshot operativo del punto exacto donde terminó la conversación.
**Tamaño máximo:** 3K tokens (~10KB)
**Lo lee:** El agente principal directamente.

**Contenido:**

```markdown
# Estado Actual — Agente APA — Sesión 6

## Última tarea en curso
{Texto del último mensaje del Director, literal}

## Última respuesta del agente
{Resumen de 3-5 líneas de lo que el agente estaba haciendo/diciendo}

## Entregables producidos
- {archivo1} — {estado: entregado/pendiente/corregido}
- {archivo2} — ...

## Errores abiertos
- {descripción del error, archivo, línea si aplica}

## Decisiones pendientes del Director
- {decisión que el Director no ha tomado aún}

## Siguiente paso lógico
{Lo que el agente debería hacer al retomar}
```

**Fuente de datos:** Últimos 15-20 mensajes del JSON.

### 7.3 `01_indice_recuperacion.md`

**Propósito:** Mapa para que el agente sepa qué existe y dónde está.
**Tamaño máximo:** 8K tokens (~25KB)
**Lo lee:** El agente principal directamente.

**Contenido:**

```markdown
# Índice de Recuperación — Chat APA 06

## Instrucción
Si detectas que has perdido contexto de esta sesión, este archivo
es tu punto de entrada. Identifica qué tema necesitas y delega
a un subagente para que lea el bloque correspondiente.

## Protocolo de recuperación
1. Lee este archivo (ya lo estás leyendo)
2. Identifica el bloque relevante para tu tarea actual
3. Lanza un subagente: Task(prompt="Lee {ruta_bloque} y responde: {tu pregunta específica}")
4. El subagente devolverá una respuesta concisa (~3-5K tokens)
5. Si necesitas otro bloque, repite desde el paso 3

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
   — Te dice dónde quedaste y qué sigue

2. Lee `/home/z/my-project/contexto_recuperacion/01_indice_recuperacion.md`
   — Te muestra qué información adicional está disponible

3. Si necesitas detalle de un tema específico, delega a un subagente:
   - Task(prompt="Lee /home/z/my-project/contexto_recuperacion/{bloque}.md
     y responde a esta pregunta: {tu pregunta}")

4. No intentes leer los bloques directamente en tu ventana.
   Usa siempre subagentes para no consumir tu contexto.

5. Si el Director te indica explícitamente que perdiste contexto,
   ejecuta los pasos 1-3 sin demora.
```

### 8.4 Ciclo de vida de los archivos

| Evento | Acción |
|--------|--------|
| Nueva sesión del agente | El agente lee `00_estado_actual.md` como parte de su inicio |
| El agente trabaja normalmente | No toca los archivos de recuperación |
| Compresión de contexto | El agente detecta pérdida (o el Director se lo indica) y ejecuta el protocolo de recuperación |
| Fin de sesión | El Director extrae el chat y genera nueva versión de los archivos de recuperación para la próxima sesión |

---

## 9. Protocolo de acceso del agente

### 9.1 Carga inicial (sesión nueva)

```
Agente lee al iniciar:
  ├── Archivos de estrategia (entorno.md, proyecto.md, contrato.md, etc.)  ~15K tokens
  ├── 00_estado_actual.md                                               ~3K tokens
  └── Total carga:                                                       ~18K tokens
  └── Contexto libre para trabajar:                                     ~110K tokens
```

El agente NO carga el índice ni las decisiones al inicio. Solo las lee si necesita recuperar contexto.

### 9.2 Recuperación tras compresión

```
Agente detecta pérdida de contexto:
  ├── Lee 00_estado_actual.md                                          ~3K tokens
  ├── Lee 01_indice_recuperacion.md                                     ~8K tokens
  ├── Identifica bloque relevante
  ├── Lanza subagente con pregunta específica
  └── Recibe respuesta concisa del subagente                              ~3-5K tokens
  └── Total para recuperación:                                          ~14-16K tokens
```

### 9.3 Consulta bajo demanda (trabajando normalmente)

```
Agente necesita detalle de un tema histórico:
  ├── Lanza subagente: "Lee bloque_X.md y dime Y"
  └── Recibe respuesta                                                 ~3-5K tokens
  └── Coste para el agente principal:                                   ~3-5K tokens
```

---

## 10. Verificación

Al finalizar la generación de todos los archivos, ejecutar:

```python
# Para cada archivo generado
for archivo in lista_archivos:
    tokens_estimados = len(contenido) / 3.5
    assert tokens_estimados <= LIMITE_CORRESPONDIENTE
    print(f"{archivo}: ~{tokens_estimados:.0f}K tokens — OK")

# Verificación global
tokens_carga_principal = estado + indice + decisiones
assert tokens_carga_principal <= 23000
print(f"Carga principal: ~{tokens_carga_principal/1000:.0f}K tokens — OK")

# Verificación de que ningún bloque necesita subdivisión
for bloque in bloques:
    if bloque.tokens > 70000:
        print(f"ALERTA: {bloque.nombre} supera 70K tokens — requiere subdivisión")
```

---

## 11. Limitaciones conocidas

1. **Solo chats compartidos:** El proceso requiere que el chat tenga share link. Chats no compartidos no son accesibles vía API.

2. **Requiere agent-browser:** La API no es accesible por curl. Se necesita un navegador con cookies de sesión.

3. **No previene la compresión:** El sistema no evita que la plataforma comprima el contexto. Solo mitiga sus efectos.

4. **El agente no sabe cuándo se comprimió:** No existe un API para consultar tokens restantes. El agente detecta la pérdida por comportamiento (no recuerda cosas) o porque el Director se lo indica.

5. **Los archivos de recuperación son estáticos:** Se generan al final de una sesión. No reflejan cambios en tiempo real durante la sesión actual.

6. **El contenido incluye reasoning:** El JSON extraído incluye los bloques de razonamiento interno del agente. La fase de limpieza los elimina, pero si un bloque de reasoning contiene información operativa útil, se pierde.

---

## 12. Mejoras futuras

- **Actualización incremental:** Que el agente actualice `00_estado_actual.md` periódicamente durante la sesión (no solo al final).
- **Detección automática de compresión:** Contar exchanges y estimar cuándo se aproxima la compresión.
- **Extracción automatizada:** Que el proceso de Fase 1 se ejecute automáticamente al final de cada sesión sin intervención del Director.
- **Repositorio de recuperación:** Versionar los archivos en el repo de estrategia para acceso inmediato al clonar.
