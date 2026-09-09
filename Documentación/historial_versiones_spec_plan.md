# Historial de Versiones — Spec y Plan del Sistema CZAI

**Proyecto:** Contexto Z.ai (CZAI)
**Fecha de consolidación:** 2025-01-09
**Total de versiones:** 16 documentos (10 specs + 6 planes)
**Propósito:** Documento único que preserva todas las versiones históricas de la
spec y el plan de CZAI, para permitir eliminar los archivos individuales del
repositorio sin perder información.

---

## Índice de versiones

### Specs (especificación funcional)

| # | Versión | Fecha | Archivo original | Líneas |
|---|---------|-------|------------------|--------|
| 1 | 1.0 | 2026-08-30 | spec_recuperacion_contexto.md | 574 |
| 2 | 2.3 | 2025-08-21 | spec_recuperacion_contexto (1).md | 974 |
| 3 | 2.3 | 2025-08-21 | spec_recuperacion_contexto (2).md | 982 |
| 4 | 3.0 | — | spec_recuperacion_contexto_v3.0.md | 499 |
| 5 | 3.1 | — | spec_recuperacion_contexto_v3.1.md | 526 |
| 6 | 3.2 | — | spec_recuperacion_contexto_v3.2.md | 607 |
| 7 | 3.3 | — | spec_recuperacion_contexto_v3.3.md | 638 |
| 8 | 3.4 | — | spec_recuperacion_contexto_v3.4.md | 246 |
| 9 | 3.5 | 2026-09-05 | spec_recuperacion_contexto_v3.5.md | 269 |
| 10 | 3.6 | 2026-09-06 | spec_recuperacion_contexto_v3.6.md | 293 |

### Planes (plan de implementación)

| # | Versión | Fecha | Archivo original | Líneas |
|---|---------|-------|------------------|--------|
| 1 | — | 2025-08-21 | plan_script_contexto_zai.md | 303 |
| 2 | 2.0 | 2026-09-04 | plan_refactorizacion_v2.md | 230 |
| 3 | 3.0 | — | plan_refactorizacion_v3.md | 196 |
| 4 | 3.4 | — | plan_refactorizacion_v3.4.md | 180 |
| 5 | 3.5 | 2026-09-05 | plan_refactorizacion_v3.5.md | 326 |
| 6 | 3.6 | 2026-09-06 | plan_refactorizacion_v3.6.md | 680 |

> **Nota:** Las versiones 2.3 aparecen dos veces (archivos "(1)" y "(2)") porque
> son duplicados con ligeras variaciones de formato. Se conservan ambas para
> integridad histórica.

---

## Evolución resumida

- **v1.0** — Especificación inicial del sistema de recuperación de contexto
- **v2.3** — Refactorización a CLI con gestión de mensajes
- **v3.0** — Versionado de scripts con grafo de cambios reversible
- **v3.1** — Mejoras de robustez y manejo de errores
- **v3.2** — Refactorización CLI → Proceso Autónomo
- **v3.3** — Versionado de scripts con grafo de cambios reversible
- **v3.4** — Links externos, clasificación por capas, estado sin truncado, exportación/importación
- **v3.5** — Indexación de documentos adjuntos mediante subagentes efímeros
- **v3.6** — JWT automático vía instalador + Subagentes paralelos para documentos grandes (actual)

---

## Contenido completo de cada versión

A continuación se incluye el contenido íntegro de cada documento, separado por
marcadores claros. Cada sección comienza con un encabezado que indica la versión
y el archivo original.



<!-- ============================================================ -->
# SECCIÓN: SPEC v1.0 (spec_recuperacion_contexto.md)
<!-- Archivo original: spec_recuperacion_contexto.md -->
<!-- ============================================================ -->

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

--- fin de SPEC v1.0 (spec_recuperacion_contexto.md) ---


<!-- ============================================================ -->
# SECCIÓN: SPEC v2.3 (spec_recuperacion_contexto (1).md)
<!-- Archivo original: spec_recuperacion_contexto (1).md -->
<!-- ============================================================ -->

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

--- fin de SPEC v2.3 (spec_recuperacion_contexto (1).md) ---


<!-- ============================================================ -->
# SECCIÓN: SPEC v2.3 (spec_recuperacion_contexto (2).md)
<!-- Archivo original: spec_recuperacion_contexto (2).md -->
<!-- ============================================================ -->

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

# 2. Prevenir redirecciones con header Authorization
agent-browser set headers '{"Authorization":"Bearer <JWT_DEL_DIRECTOR>"}'

# 3. Navegar al chat (el header previene redirección a home)
agent-browser open "https://chat.z.ai/c/{chat_id}"

# 4. Inyectar el token del Director como cookie
agent-browser cookies set token "<JWT_DEL_DIRECTOR>"

# 5. Recargar la página — el servidor valida y refresca el token
agent-browser eval "location.reload()"
agent-browser wait 3000

# 6. Guardar el estado autenticado para reutilizarlo
agent-browser state save /home/z/my-project/.browser_auth_state.json
```

> **IMPORTANTE:** El paso 2 (`set headers`) es necesario. Sin él, la navegación en el paso 3 redirige a home y el servidor sobrescribe la cookie con un token de invitado. Con el header, la URL se mantiene en `/c/{chat_id}` y el reload del paso 5 permite al servidor refrescar el token en lugar de reemplazarlo.

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

--- fin de SPEC v2.3 (spec_recuperacion_contexto (2).md) ---


<!-- ============================================================ -->
# SECCIÓN: SPEC v3.0 (spec_recuperacion_contexto_v3.0.md)
<!-- Archivo original: spec_recuperacion_contexto_v3.0.md -->
<!-- ============================================================ -->

<!-- Destino en el proyecto: /home/z/my-project/contexto_zai/spec_recuperacion_contexto_v3.0.md -->

# SPEC — Sistema de Recuperación de Contexto para Agentes Z.ai

**Versión:** 3.0
**Fecha:** 2026-09-02
**Autor:** Director (diseño) + Agente CZAI (especificación)
**Estado:** v3.0 — Reformulación como proceso autónomo. Reemplaza la arquitectura CLI de v2.3 por un proceso que se instala en el workspace del agente y se vincula a la sesión. Añade detección activa de pérdida de contexto, reorganiza los archivos temáticos (varios temas por archivo, subdivisión con nuevos temas, unicidad temática) y confirma el flujo completo en 13 pasos.

**Cambios principales respecto a v2.3:**
1. De aplicación CLI a proceso autónomo vinculado al agente.
2. Detección activa de pérdida de contexto (tres mecanismos combinados: léxico, contador preventivo, auto-preguntas).
3. Archivos temáticos con varios temas por archivo, no un tema por archivo.
4. Subdivisión genera nuevos temas/subtemas únicos, no "parte1/parte2".
5. Unicidad temática: un tema vive en un solo archivo.
6. Actualización de límites a los de v2.3 (estado 20K, carga principal 40K).
7. Referencia a la metodología JWT documentada para la autenticación.

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

**Intervención del Director:** Solo para el setup inicial de autenticación (obtener el JWT de chat.z.ai una vez, siguiendo la metodología documentada en sección 11). Después de eso, el sistema es 100% automático durante toda la vida del proyecto.

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

### 6.5 Mejora futura (no implementar en v3.0)

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
- **Decisiones clave.** Registro de las decisiones importantes que se van tomando. Existe como referencia consultable bajo demanda; no interviene en el ciclo activo de recuperación.

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

**Propósito:** Registro histórico de decisiones importantes tomadas, para que el agente no re-decida lo ya resuelto.
**Tamaño máximo:** 12K tokens (~40KB)
**Lo lee:** El agente principal o un subagente bajo demanda.

**Rol:** Registro histórico consultable. **No interviene en el ciclo activo de recuperación** (no se consulta automáticamente cuando el agente pierde contexto). El agente lo consulta cuando necesita verificar si algo ya fue decidido.

**Cómo se llena:** Mediante un subagente que escanea los intercambios y extrae decisiones con comprensión semántica. El patrón regex no es suficiente para extraer decisiones (validado en v2.1: 0 resultados con patrones estrictos); se necesita comprensión LLM.

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

### 10.3 Subagente de decisiones (bajo demanda)
- Lee `02_decisiones_clave.md` cuando el agente necesita verificar si algo ya fue decidido.
- Responde con la decisión relevante o "no hay decisión registrada".
- Se cierra.

### 10.4 Subagente de mantenimiento (actualización incremental)
- Se lanza en segundo plano cuando se dispara la recuperación.
- Lee la metadata para saber el último timestamp procesado.
- Extrae solo mensajes nuevos.
- Los clasifica y añade a los archivos existentes.
- Actualiza la metadata.

---

## 11. Autenticación con la plataforma Z.ai

La autenticación para acceder a la API de chat.z.ai se resuelve mediante la metodología documentada del JWT. Esta metodología permite que cualquier usuario pueda automatizar el proceso de obtención del Bearer token de forma completa.

**Documento de referencia:** `metodologia_descubrimiento_jwt.md` (incluido en el repositorio del proyecto).

**Resumen del flujo:**

1. El usuario obtiene su JWT del header `Authorization: Bearer` en DevTools de chat.z.ai (una vez).
2. El agente inyecta la cookie `token` con ese JWT en `agent-browser`.
3. Recarga la página (no navega) para que el servidor refresque el token.
4. Guarda el estado autenticado en `.browser_auth_state.json`.
5. En sesiones posteriores, carga el estado y opera sin necesitar el token de nuevo.

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

El código actual está implementado como CLI con `click` y no refleja esta spec v3.0. Los cambios pendientes para alinear el código con esta spec son:

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

---

## 15. Log de validación

[Se llenará después de implementar y probar la v3.0.]

---

## 16. Referencias

- `metodologia_descubrimiento_jwt.md` — Procedimiento reproducible de autenticación.
- Spec v2.3 — Versión anterior, con arquitectura CLI. Reemplazada por esta v3.0.
- Worklog del proyecto — Entradas de sesiones 1 a 4 con la implementación inicial del paquete `contexto_zai/`.

--- fin de SPEC v3.0 (spec_recuperacion_contexto_v3.0.md) ---


<!-- ============================================================ -->
# SECCIÓN: SPEC v3.1 (spec_recuperacion_contexto_v3.1.md)
<!-- Archivo original: spec_recuperacion_contexto_v3.1.md -->
<!-- ============================================================ -->

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

--- fin de SPEC v3.1 (spec_recuperacion_contexto_v3.1.md) ---


<!-- ============================================================ -->
# SECCIÓN: SPEC v3.2 (spec_recuperacion_contexto_v3.2.md)
<!-- Archivo original: spec_recuperacion_contexto_v3.2.md -->
<!-- ============================================================ -->

<!-- Destino en el proyecto: /home/z/my-project/contexto_zai/spec_recuperacion_contexto_v3.2.md -->

# SPEC — Sistema de Recuperación de Contexto para Agentes Z.ai

**Versión:** 3.2
**Fecha:** 2026-09-04
**Autor:** Director (diseño) + Agente CZAI (especificación)
**Estado:** v3.2 — Corrige v3.1 tras la ejecución de prueba del flujo completo en la Sesión 5. Tres hallazgos integrados: (a) el batch endpoint usa `chat_id` y requiere autenticación, no `share_id` como invitado; (b) el navegador del sandbox es invitado, no Director — el fallback de la metodología JWT es el flujo principal; (c) el pipeline actual (CLI v1.0) produce archivos de calidad no operativa que hay que reescribir.

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

**Cambios de v3.1 → v3.2 (tras ejecución de prueba):**
10. **Batch endpoint corregido:** usa `chat_id` con autenticación (cookie `token`), NO `share_id` como invitado. La plataforma cambió desde v2.2.
11. **Flujo principal de autenticación:** el navegador del sandbox es INVITADO por defecto, no Director. El protocolo de inyección de cookie de la metodología JWT es el flujo principal, no un fallback.
12. **Estado actual con 8 secciones obligatorias:** D1-D4 (Director) + A1-A4 (Agente). La versión actual del `estado_generator.py` solo tiene 4 secciones simples, hay que reescribirlo.
13. **Decisiones clave con LLM:** el regex no extrae decisiones reales (validado en la prueba: 20K chars de fragmentos aleatorios). Es obligatorio el subagente con comprensión semántica LLM.
14. **Control estricto de límites por bloque:** ningún bloque puede superar 70K tokens. La subdivisión actual crea `parte2` (prohibido); debe crear subtemas únicos.

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

**Objetivo superior:** Con una sola sesión de un agente se puede empezar y culminar un proyecto, porque el sistema de recuperación está vivo desde el primer minuto.

**Intervención del Director:** Una sola vez en la vida del proyecto, para proporcionar el JWT. El protocolo de inyección de cookie + persistencia de estado hace el resto. El sandbox de Z.ai abre el navegador como invitado por defecto, así que el JWT del Director es necesario para autenticar.

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
| **subagente efímero** | Instancia lanzada para leer un archivo temático y devolver una respuesta concreta; se cierra al entregar |
| **estado actual** | Archivo con 8 secciones (D1-D4 + A1-A4) que captura el contexto completo del tema activo |
| **índice de recuperación** | Mapa `tema → archivo` que el proceso consulta antes de lanzar subagentes |
| **decisiones clave** | Registro de decisiones reales (extraídas por LLM, no regex), consultable bajo demanda |
| **compresión** | Evento donde la plataforma reduce el contexto del agente a un resumen |
| **metadata de recuperación** | Archivo JSON auxiliar que trackea último timestamp, mapeo tema → archivo, subtemas derivados |

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
3. **Resuelve la autenticación:** mediante el protocolo de inyección de cookie de la metodología JWT (sección 11). El sandbox abre como invitado por defecto, así que el JWT del Director es necesario.

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

### 6.5 Mejora futura (no implementar en v3.2)

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

### Construcción del estado actual

**Paso 7.** El proceso genera tres archivos:

- **Estado actual** (el más importante). No es un resumen de los últimos intercambios: es la recuperación del **tema completo** al que pertenece el último intercambio, para que el agente tenga toda la información necesaria para dar una respuesta coherente y de calidad. **Obligatoriamente con 8 secciones D1-D4 + A1-A4** (ver sección 9.1).
- **Índice de recuperación.** Mapa de `tema → archivo`, con el protocolo de uso.
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

Un archivo temático puede contener intercambios de **varios temas diferentes**, siempre que la suma de sus tokens no supere `MAX_TOKENS_BLOQUE` (70K tokens). El archivo se llena hasta su capacidad antes de crear uno nuevo.

**Razón:** Evitar la proliferación de archivos pequeños. Si hay 50 temas pero caben en 5 archivos de tamaño completo, se generan 5 archivos, no 50.

**Hallazgo de Sesión 5:** El pipeline actual creó un `bloque_general.md` de 249K chars (~71K tokens), superando el límite. Esto es inaceptable. El empaquetador por tamaño debe garantizar que ningún archivo supere el límite.

### 8.2 Principio de unicidad temática

Un tema (o subtema) **vive en un solo archivo temático**. No puede haber dos archivos con el mismo tema. Esto garantiza que cuando el proceso consulta el índice y localiza un tema, sabe exactamente a qué archivo preguntar, y que cuando el agente pregunta por un tema, solo se lanza un subagente para el archivo correspondiente, no para todos.

### 8.3 Subdivisión con nuevos temas

Cuando un tema individual crece tanto que no cabe en un archivo, se subdivide. La subdivisión **NO** crea `tema_parte1` y `tema_parte2` (eso fragmentaría el contexto y fue el bug detectado en Sesión 5). En su lugar, el tema se divide en **subtemas derivados** que son nuevos temas únicos en el sistema.

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

**Estructura obligatoria — 8 secciones D1-D4 + A1-A4:**

El `estado_generator.py` actual solo produce 4 secciones simples ("última tarea", "última respuesta", "entregables", "errores"). Esto NO cumple la spec. Hay que reescribirlo para producir las 8 secciones siguientes:

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

**Construcción (paso 8 del flujo):**

1. Localiza el último intercambio del chat.
2. Determina a qué tema pertenece ese intercambio (clasificación léxica sobre el mensaje del Director).
3. Consulta el índice para saber en qué archivo temático está ese tema.
4. Lanza un subagente que lee ese archivo y extrae todo el contexto del tema.
5. El subagente entrega el contexto completo al agente principal.
6. El proceso registra ese contexto como el estado actual con las 8 secciones.

**Anti-patrones detectados en Sesión 5 (a corregir):**

- "Errores abiertos" con falsos positivos: el generador actual detecta cualquier mención de "error" en el texto y la lista como error del proyecto. Hay que usar el subagente con comprensión semántica para distinguir menciones conversacionales de errores reales.
- "Última respuesta del agente" truncada: el generador actual concatena todas las respuestas del agente sin límite. Hay que usar solo la última respuesta relevante del tema activo.

**Versionado:** Archivo puntual. Cada activación lo sobrescribe con el contexto del instante. No guarda historial de estados anteriores.

### 9.2 `01_indice_recuperacion.md`

**Propósito:** Mapa para que el agente sepa qué temas existen y en qué archivo está cada uno.
**Tamaño máximo:** 8K tokens (~25KB)
**Lo lee:** El agente principal durante la recuperación, y el proceso antes de lanzar subagentes.

**Estructura obligatoria — tabla `tema → archivo`:**

El `indice_generator.py` actual solo lista bloques por descripción. NO cumple la spec. Hay que reescribirlo para producir el mapeo `tema → archivo` explícito:

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

**Anti-patrón detectado en Sesión 5 (a corregir):**

El `decisiones_generator.py` actual usa regex. En la prueba de Sesión 5 produjo 20K chars de fragmentos aleatorios que contenían palabras como "decisión" o "decidimos", pero **ninguna era una decisión real**. Esto confirma lo que la spec v2.1 ya documentaba: el regex no funciona para extraer decisiones. Es obligatorio el subagente con comprensión semántica LLM.

**Disparadores de generación/actualización:**

1. **Cada activación del proceso de recuperación** (cuando el agente detecta pérdida de contexto o el Director lo indica). El proceso escanea los intercambios desde la última actualización, extrae las nuevas decisiones y las añade al registro existente.
2. **Cambio de tarea del Director.** Cuando el Director pasa de una tarea a otra, las decisiones de la tarea anterior se consolidan en este archivo antes de que el agente empiece a trabajar en la nueva.
3. **Indicación explícita del Director.** El Director puede solicitar en cualquier momento que se consolide el registro ("actualiza decisiones clave").
4. **Comunicación explícita de una decisión.** Cuando el Director comunica formalmente una decisión ("decidimos X", "a partir de ahora Y", "descartamos Z"), el proceso la registra de inmediato.

**Cómo se llena:** Mediante un subagente con comprensión semántica LLM que escanea los intercambios y extrae decisiones. En cada activación, el subagente solo procesa los intercambios nuevos desde la última actualización (modo incremental), deduplica contra las decisiones ya registradas, y añade solo las nuevas.

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

### 11.3 Por qué esto funciona

- `agent-browser cookies` puede leer y escribir cookies HttpOnly porque opera a nivel del navegador (perfil de Chromium), no a través de JavaScript (que sí tendría la restricción HttpOnly).
- El servidor refresca el JWT en cada request (nueva firma ES256, mismo payload `id` y `email`).
- El JWT no tiene `exp` ni `expires_at` (tokens infinitos por diseño), así que una vez obtenido, sigue siendo válido indefinidamente mientras el servidor no invalide la sesión.
- La cookie se llama `token`. El frontend de chat.z.ai la lee y la envía como `Authorization: Bearer <token>` en cada API call.

### 11.4 Endpoints usados (validados en Sesión 5)

| Endpoint | Método | Autenticación | Propósito |
|---|---|---|---|
| `/api/v1/auths/` | GET | Cookie `token` | Verificar perfil autenticado |
| `/api/v1/chats/{chat_id}/share` | POST | Cookie `token` | Crear o reutilizar share (idempotente) |
| `/api/v1/chats/share/{share_id}` | GET | Cookie `token` | Árbol de mensajes (sin contenido) |
| `/api/v1/chats/{chat_id}/messages/batch` | POST | Cookie `token` | Contenido completo de mensajes |

**⚠️ Cambio crítico respecto a v2.2/v3.0/v3.1:** El batch endpoint usa **`chat_id`** y requiere autenticación. NO usa `share_id` como invitado. La plataforma cambió. La spec v2.2 documentaba incorrectamente el share_id en este endpoint.

### 11.5 Notas técnicas clave

- La cookie se llama `token`, es HttpOnly.
- El servidor refresca el JWT en cada request (nueva firma ES256, mismo payload).
- El JWT no tiene campo `exp` ni `expires_at` (tokens infinitos por diseño).
- La UI de chat no renderiza en agent-browser (React `#app` div permanece vacío), pero todas las API calls funcionan. La extracción es 100% via API, no vía UI.
- El share API es idempotente: devuelve el share_id existente o crea uno nuevo.
- No hay límite de mensajes por request de batch (validado con 30 mensajes en Sesión 5).

---

## 12. Metadata de recuperación

Archivo `_metadata.json` con:

```json
{
  "chat_id": "13b43432-...",
  "share_id": "1d1196b7-...",
  "ultimo_timestamp": 1788484114,
  "total_exchanges": 15,
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
  "ultima_activacion": "2026-09-04T14:30:00Z"
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
5. **Las decisiones requieren LLM:** El patrón regex no es suficiente para extraer decisiones; se necesita comprensión semántica. Validado en Sesión 5.
6. **La tarea actual puede ser "general":** Cuando el Director da instrucciones transversales, no hay tema dominante. El estado actual contendrá contexto de múltiples temas y será menos preciso.
7. **El sandbox abre como invitado:** El navegador del sandbox no tiene la sesión del Director. El JWT debe proporcionarse una vez y persistirse vía `agent-browser state save`.

---

## 14. Cambios pendientes respecto al código actual (v1.0)

El código actual está implementado como CLI con `click` y no refleja esta spec v3.2. Los cambios pendientes para alinear el código con esta spec son:

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
14. **Batch endpoint con chat_id (v3.2):** Cambiar el `chat_client.py` para que el batch endpoint use `chat_id` con autenticación, no `share_id` como invitado.
15. **Estado actual con 8 secciones (v3.2):** Reescribir `estado_generator.py` para producir las 8 secciones D1-D4 + A1-A4, eliminando los falsos positivos en "errores abiertos" y la truncación en "última respuesta".
16. **Decisiones con LLM (v3.2):** Reemplazar el regex del `decisiones_generator.py` por un subagente con comprensión semántica LLM.
17. **Control estricto de límites por bloque (v3.2):** Garantizar que ningún bloque supere 70K tokens. El `block_manager` actual permitió un bloque de 71K tokens en la prueba de Sesión 5.
18. **Índice con mapeo tema → archivo (v3.2):** Reescribir `indice_generator.py` para producir la tabla `tema → archivo` explícita, no solo lista de bloques por descripción.

---

## 15. Log de validación

### Validación v3.1 → v3.2 (Sesión 5 — ejecución de prueba del flujo completo)

**Fecha:** 2026-09-04
**Chat:** CZAI Sesión 5 (chat_id: 13b43432-36d8-4ed0-8fde-2c17e2f90484)
**Share:** 1d1196b7-18e1-43c7-8869-e59d2dba45f7

| Paso | Resultado | Detalle |
|------|-----------|--------|
| Paso 1 (arranque) | ✅ | Worklog leído, identidad CZAI confirmada |
| Paso 2 (instrucciones worklog) | ✅ | Repo clonado en `/home/z/my-project/contexto_zai/` |
| Paso 3 (autenticación) | ✅ | Sandbox como invitado. Protocolo inyección de cookie aplicado. Servidor refrescó token. Estado guardado. |
| Paso 4 (activación) | ✅ | Disparo explícito del Director |
| Paso 5 (recuperación) | ✅ | share_id creado, 30 mensajes extraídos (598KB, ~158K tokens) |
| Paso 6 (clasificación) | ⚠️ | 6 temas → 9 archivos. `bloque_general.md` desbordado (71K tokens > 70K). Subdividió como `parte2` (prohibido por v3.1) |
| Paso 7 (3 archivos) | ⚠️ | Estado 3K tokens (límite v1.0, no v3.1). Decisiones 6K tokens con falsos positivos. Índice sin mapeo. |
| Pasos 8-9 (subagentes) | ❌ | No implementados en el código actual |
| Pasos 10-13 | — | No verificables (condiciones no dadas) |

**Hallazgos clave integrados en v3.2:**

1. **Batch endpoint cambió:** usa `chat_id` con autenticación, no `share_id` como invitado. Spec v2.2-v3.1 desactualizada. → Cambio 14.
2. **Sandbox es invitado por defecto:** el protocolo de inyección de cookie es el flujo principal, no fallback. → Sección 11 reescrita.
3. **Estado actual sin 8 secciones:** el `estado_generator.py` actual produce 4 secciones simples. → Cambio 15.
4. **Decisiones clave con regex no funcionan:** 20K chars de fragmentos aleatorios, ninguna decisión real. → Cambio 16.
5. **Bloques desbordados:** `block_manager` actual permitió 71K tokens. → Cambio 17.
6. **Índice sin mapeo:** `indice_generator.py` actual solo lista por descripción. → Cambio 18.

---

## 16. Referencias

- `metodologia_descubrimiento_jwt.md` — Procedimiento reproducible de autenticación.
- Spec v3.1 — Versión anterior. Reemplazada por esta v3.2 tras ejecución de prueba.
- Spec v2.3 — Versión con arquitectura CLI. Reemplazada por v3.0.
- Worklog del proyecto — Entradas de sesiones 1 a 5 con la implementación inicial y la ejecución de prueba.

--- fin de SPEC v3.2 (spec_recuperacion_contexto_v3.2.md) ---


<!-- ============================================================ -->
# SECCIÓN: SPEC v3.3 (spec_recuperacion_contexto_v3.3.md)
<!-- Archivo original: spec_recuperacion_contexto_v3.3.md -->
<!-- ============================================================ -->

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

--- fin de SPEC v3.3 (spec_recuperacion_contexto_v3.3.md) ---


<!-- ============================================================ -->
# SECCIÓN: SPEC v3.4 (spec_recuperacion_contexto_v3.4.md)
<!-- Archivo original: spec_recuperacion_contexto_v3.4.md -->
<!-- ============================================================ -->

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

--- fin de SPEC v3.4 (spec_recuperacion_contexto_v3.4.md) ---


<!-- ============================================================ -->
# SECCIÓN: SPEC v3.5 (spec_recuperacion_contexto_v3.5.md)
<!-- Archivo original: spec_recuperacion_contexto_v3.5.md -->
<!-- ============================================================ -->

# Spec v3.5 — Indexación de documentos adjuntos mediante subagentes efímeros

**Versión:** 3.5
**Fecha:** 2026-09-05
**Autor:** Agente CZAI
**Estado:** Pendiente de validación por el Director.
**Especifica continuación de:** spec v3.4 (links externos, clasificación por capas, truncamiento lógico, export/import).

---

## 1. Problema

El Director necesita poder **entregar documentos pesados** (PDFs, DOCX, TXT, etc.) al agente para que este los incorpore al contexto del proyecto. El mecanismo de entrega debe ser el **botón "+" del chat de Z.ai** (adjuntar archivo nativo, no rutas ni links externos).

El problema crítico: **si el agente principal lee el documento directamente, su contexto se llena y se acaba su capacidad de trabajo.** Hoy el proceso hace exactamente esto con los links externos (`WebReader` lee el contenido en el contexto del agente y trunca a 10K chars).

## 2. Solución

Cuando el proceso detecta que un mensaje del Director tiene archivos adjuntos:

1. **No los lee directamente.** El agente principal nunca consume su contexto con el contenido del documento.
2. **Lanza un subagente efímero** para que haga el trabajo pesado: leer, clasificar, resumir.
3. **El subagente devuelve al agente principal** solo un resumen breve + la referencia al índice donde está disponible el detalle.
4. **El índice de materias** (`01_indice_recuperacion.md`) se actualiza con el nuevo documento y sus temas.

### 2.1. Decisión de delegación (regla de 3 niveles)

Por defecto, **el proceso decide automáticamente** si delegar la lectura al subagente. El criterio es:

- **Delegar al subagente** (default): siempre que el documento tenga >5K tokens estimados o el agente principal tenga >80% de su contexto ocupado.
- **Leer directamente** (override del Director): si el Director dice explícitamente "lee este documento completo", el agente lo lee directamente sin subagente.
- **No delegar, no leer**: si el documento es trivialmente pequeño (<1K tokens) y el agente tiene contexto disponible, se incorpora al intercambio directamente.

### 2.2. Cuándo se procesa

**En el momento.** El proceso de contexto está activo desde el inicio de la sesión del agente. En cuanto llega un documento adjunto, el proceso lo detecta y lanza el subagente. No se espera a la activación de la recuperación de contexto completa.

### 2.3. Formatos soportados

**Cualquiera que el subagente de Z.ai pueda leer.** No se imponen límites desde el código. Los formatos típicos que el subagente de Z.ai maneja nativamente: PDF, DOCX, TXT, MD, imágenes, XLSX, PPTX.

## 3. Hallazgos de la investigación de la API

Se investigó a fondo la API de Z.ai para entender cómo expone los attachments. Los hallazgos:

### 3.1. Estructura del campo `files` en `messages/batch`

Cada mensaje del batch endpoint incluye un campo `files` (array de objetos) con la estructura:

```json
{
  "files": [
    {
      "type": "doc",  // o "file", "image"
      "file": {
        "id": "096b178e-a6be-4239-a571-7c15d9229c5f",
        "user_id": "229a58c8-...",
        "filename": "CZAI-01.pdf",
        "meta": {
          "name": "CZAI-01.pdf",
          "content_type": "application/pdf",
          "size": 1652025,
          "cdn_url": "https://z-cdn-media.chatglm.cn/files/...pdf?auth_key=..."
        },
        "created_at": 1788445359
      },
      "id": "096b178e-a6be-4239-a571-7c15d9229c5f",
      "url": "/api/v1/files/096b178e-...",
      "name": "CZAI-01.pdf",
      "status": "uploaded",
      "size": 1652025,
      "media": "doc",  // o "file", "image"
      "ref_user_msg_id": "30354b73-..."
    }
  ]
}
```

### 3.2. Endpoint de descarga de contenido

El endpoint correcto para descargar el contenido del archivo es:

```
GET /api/v1/files/{file_id}/content
```

Requiere autenticación (cookie `token` con JWT del Director). Devuelve el archivo binario directamente con `Content-Type` correcto y header `Content-Disposition: inline; filename*=UTF-8''<nombre>`.

**Verificado:** descarga con `httpx.get(url, cookies={'token': jwt})` funciona correctamente. Un PDF de 1.6 MB y 208 páginas se descarga y lee con `pdfplumber` sin problemas.

### 3.3. Endpoints que NO funcionan

- `/api/v1/files/{id}` devuelve solo metadata (JSON), no el contenido.
- `/api/v1/files/{id}/download`, `/raw`, `/blob` devuelven 404.
- Descarga directa del CDN (`z-cdn-media.chatglm.cn`) falla con 403 desde fuera del navegador (el `auth_key` expira rápido y requiere contexto del navegador).

## 4. Arquitectura OOP reutilizable

### 4.1. Patrón `ContentDelegator` (clase base abstracta)

Define la interfaz para decidir si un contenido debe procesarse en el contexto principal o delegarse a un subagente.

```python
class ContentDelegator(ABC):
    """Decide si un contenido debe delegarse a un subagente."""

    @abstractmethod
    def should_delegate(
        self,
        content_size_tokens: int,
        agent_context_available_pct: float,
        director_override: Optional[str] = None,
    ) -> bool:
        """Devuelve True si el contenido debe delegarse a un subagente."""
        ...
```

### 4.2. Subclases concretas

- `ThemeDelegator` — ya existe como `Subdivider.needs_subdivision`. Se refactoriza para implementar la interfaz `ContentDelegator`.
- `DocumentDelegator` — nueva. Decide si un documento adjunto debe delegarse.

### 4.3. Patrón de subagente (clase base implícita)

Los subagentes existentes siguen el mismo patrón:
- Reciben un contenido (archivo, tema, intercambio).
- Lo leen con su contexto independiente.
- Devuelven al agente principal un resumen o índice, no el contenido completo.

Subagentes existentes que ya implementan este patrón:
- `EstadoSubagent` — lee el archivo del tema activo, devuelve contexto extraído.
- `BarridoSubagent` — busca información puntual en un archivo, devuelve la respuesta.
- `DiscriminatorSubagent` (v3.4 F5) — lee un tema grande, propone subdivisión.

**Nuevo subagente: `DocumentoIndexerSubagent`** — lee un documento completo, lo clasifica por temas, genera un resumen breve y actualiza el índice de materias.

### 4.4. Diagrama de clases

```
ContentDelegator (abstract)
├── ThemeDelegator (= Subdivider.needs_subdivision, refactorizado)
└── DocumentDelegator (nuevo, decide si documento → agente o subagente)

SubagentLauncher (ya existe, genérico)
└── lanza:
    ├── EstadoSubagent (ya existe)
    ├── BarridoSubagent (ya existe)
    ├── DiscriminatorSubagent (ya existe v3.4 F5)
    └── DocumentoIndexerSubagent (nuevo)

AttachmentClient (nuevo, descarga archivos adjuntos desde la API de Z.ai)
├── list_attachments(messages) -> list[Attachment]
└── download(attachment) -> bytes

AttachmentDetector (nuevo, detecta attachments en mensajes extraídos)
├── detect_in_messages(messages) -> list[Attachment]
└── get_messages_with_attachments(messages) -> dict[msg_id, list[Attachment]]
```

## 5. Flujo completo del proceso

### Paso 1: Extracción de mensajes (sin cambios)

`ChatClient.extract_all()` extrae los mensajes del chat como hasta ahora. Los mensajes devueltos incluyen el campo `files` en el JSON crudo, pero `ChatClient._extract_content()` no lo procesa (solo extrae texto).

### Paso 2: Detección de attachments (NUEVO)

`AttachmentDetector.detect_in_messages(messages)` recorre los mensajes y devuelve la lista de attachments con su metadata (file_id, filename, content_type, size, ref_user_msg_id).

### Paso 3: Para cada attachment detectado, decidir delegación (NUEVO)

`DocumentDelegator.should_delegate(content_size, context_available, override)` decide:

- Si el Director dijo "lee completo" → `False` (agente principal lee).
- Si el documento es trivial (<1K tokens) y hay contexto → `False`.
- Si no → `True` (delegar a subagente).

### Paso 4a: Si delega (default), lanzar subagente (NUEVO)

`DocumentoIndexerSubagent.run(attachment)`:

1. Descarga el archivo con `AttachmentClient.download(attachment)`.
2. Lo guarda temporalmente en `download/uploads/temp/`.
3. Lanza el subagente efímero con el prompt: "Lee este archivo, clasifica por temas, genera resumen".
4. El subagente lee el archivo (con `Read` de Z.ai o `pdfplumber` si es PDF).
5. El subagente devuelve:
   - `resumen_breve` (≤500 chars).
   - `temas_detectados` (lista de `{tema, descripcion, secciones}`).
   - `archivo_indexado_path` (dónde quedó guardado el archivo para consultas futuras).
6. El proceso mueve el archivo de `temp/` a `download/uploads/indexed/`.
7. El proceso actualiza el `01_indice_recuperacion.md` con la nueva materia.

### Paso 4b: Si no delega, el agente principal lee (excepcional)

El proceso descarga el archivo con `AttachmentClient.download(attachment)`, lo lee directamente (con `pdfplumber` o el extractor adecuado), y crea un intercambio virtual con el contenido completo (sin truncar).

### Paso 5: Integración al contexto

El intercambio virtual (sea del subagente o directo) se clasifica con tema `documento_adjunto` y entra al pipeline normal: `BlockPacker` lo empaqueta, `EstadoGenerator` lo referencia en el estado actual, `IndiceGenerator` lo mapea en el índice.

## 6. Refactorización pendiente (fix de deuda técnica)

### 6.1. Fix del `WebReader` actual (links externos)

Hoy `ExchangeBuilder._process_external_links()` llama a `WebReader.read()` directamente en el contexto del agente principal y trunca a 10K chars. **Eso viola el consenso.**

**Fix:** refactorizar para que `_process_external_links()` use el mismo patrón:
1. Detectar URLs.
2. Decidir delegación con `DocumentDelegator.should_delegate()` (mismo criterio que attachments).
3. Si delega: lanzar `DocumentoIndexerSubagent` con la URL en vez de file_id.
4. Si no delega (default para links pequeños): leer con `WebReader` directamente.

Esto unifica los dos mecanismos (links externos + archivos adjuntos) bajo el mismo patrón OOP.

### 6.2. Quitar truncado a 10K chars

El `content.content[:10000]` en `exchange_builder.py:195` se elimina. El `Subdivider` y `DiscriminatorSubagent` se encargan de partir contenido grande en subtemas automáticamente.

## 7. Archivos nuevos

| Archivo | Responsabilidad |
|---|---|
| `client/attachment_client.py` | Descarga archivos adjuntos desde la API de Z.ai (`/api/v1/files/{id}/content`). |
| `processing/attachment_detector.py` | Detecta attachments en mensajes extraídos. |
| `processing/content_delegator.py` | Clase base abstracta + `DocumentDelegator` concreto. |
| `subagents/documento_indexer_subagent.py` | Subagente que lee, clasifica y resume documentos. |

## 8. Archivos a modificar

| Archivo | Cambio |
|---|---|
| `models.py` | Añadir modelo `Attachment` (file_id, filename, content_type, size, url, ref_msg_id). |
| `config.py` | Añadir `DELEGATION_THRESHOLD_TOKENS=5000`, `DELEGATION_CONTEXT_LIMIT_PCT=80`, `TRIVIAL_SIZE_TOKENS=1000`, `DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS=500`. |
| `chat_client.py` | `extract_all()` debe devolver también los attachments detectados. Nuevo método `extract_attachments(messages_raw)`. |
| `exchange_builder.py` | Refactor `_process_external_links()`: usar `DocumentDelegator` + `DocumentoIndexerSubagent` en vez de leer directamente. Quitar truncado 10K. |
| `subdivider.py` | `needs_subdivision()` refactorizado para implementar interfaz `ContentDelegator` (sin romper API existente). |
| `subagents/__init__.py` | Exportar `DocumentoIndexerSubagent`. |
| `pipeline.py` | Añadir `index_document(attachment)` para procesar un documento en tiempo real. |
| `recovery_cycle.py` | Integrar `AttachmentDetector` después de extracción. Lanzar `DocumentoIndexerSubagent` para cada attachment. |
| `generation/indice_generator.py` | Incluir sección "Documentos indexados" en el índice de materias. |
| `tests/run_all_tests.py` | Añadir 4 nuevos módulos atómicos a la Fase 1. |
| `tests/test_e2e_pipeline.py` | Añadir tests E2E para attachments. |

## 9. Compatibilidad con versiones anteriores

- El flujo existente (sin attachments) sigue funcionando igual.
- Los links externos pequeños (<5K tokens) se leen directamente con `WebReader` como antes.
- Los links externos grandes se delegan al subagente (nuevo comportamiento, mejora la v3.4).
- La exportación/importación de contexto (v3.4 F10/F11) incluye los documentos indexados en el ZIP.

## 10. Validación

### 10.1. Auto-tests atómicos (Fase 1, 4 nuevos módulos)

- `client/attachment_client.py`: descarga con mock, manejo de errores, casos edge.
- `processing/attachment_detector.py`: detección en mensajes, filtrado, deduplicación.
- `processing/content_delegator.py`: criterios de delegación, override del Director.
- `subagents/documento_indexer_subagent.py`: leer+clasificar+resumir con mock invoker.

### 10.2. Tests E2E

- Adjuntar PDF real en un chat de prueba y verificar que se indexa.
- Verificar que el agente principal no consume tokens del PDF en su contexto.
- Verificar que el índice de materias se actualiza con el documento.
- Verificar que el override del Director ("lee completo") funciona.

## 11. Pendiente de validación

Espero tu validación para pasar a la fase de EJECUCIÓN del plan v3.5.

--- fin de SPEC v3.5 (spec_recuperacion_contexto_v3.5.md) ---


<!-- ============================================================ -->
# SECCIÓN: SPEC v3.6 (spec_recuperacion_contexto_v3.6.md)
<!-- Archivo original: spec_recuperacion_contexto_v3.6.md -->
<!-- ============================================================ -->

# Spec v3.6 — JWT automático vía .bat + Subagentes paralelos para documentos grandes

**Versión:** 3.6
**Fecha:** 2026-09-06
**Autor:** Agente CZAI
**Estado:** Pendiente de validación por el Director.
**Especifica continuación de:** spec v3.5 (indexación de documentos adjuntos).

---

## 1. Problema

La spec v3.5 introdujo la indexación de documentos adjuntos mediante subagentes efímeros. Quedaron 2 problemas sin resolver:

### Problema 1 — Obtención del JWT (fricción para el Director)

El agente necesita el JWT del Director para acceder a la API de Z.ai. Hoy el Director tiene que:
1. Abrir DevTools (F12).
2. Ir a Application → Cookies.
3. Buscar la cookie `token`.
4. Copiar el valor.
5. Pegarlo en el chat o pasarlo al proceso.

Esto no es natural y dificulta la adopción por usuarios no técnicos.

### Problema 2 — Documentos muy grandes llenan el contexto del subagente

La spec v3.5 delega la lectura de documentos adjuntos a un **único** `DocumentoIndexerSubagent`. Si el documento es muy grande (ej: 1.000 páginas = ~1M tokens), el subagente puede:
- Llenar su contexto y no poder procesar todo el documento.
- Truncar la lectura (el `Read` tool tiene límite de líneas).
- Devolver un resumen incompleto porque no vio todo el contenido.

## 2. Solución

### Solución 1 — JWT automático vía `.bat` con PowerShell + Edge + DevTools Protocol

**Mecanismo:**

1. El agente (sandbox) detecta que no tiene JWT disponible.
2. Expone 3 endpoints HTTP temporales:
   - `GET /jwt-status` → `{"needs_jwt": true|false}`
   - `POST /recibir-jwt` → recibe el JWT y lo persiste
   - `GET /czai-jwt-bridge.bat` → sirve el script descargable
3. El agente le dice al Director: "Descarga este archivo y haz doble click".
4. El Director descarga `czai-jwt-bridge.bat` (3 KB) y hace doble click.
5. El `.bat` ejecuta PowerShell silenciosamente, que:
   - Lanza Edge con `--remote-debugging-port=9222`.
   - Edge abre `chat.z.ai` (donde el Director ya tiene sesión).
   - PowerShell se conecta a Edge vía DevTools Protocol (WebSocket).
   - PowerShell ejecuta `fetch('/api/v1/auths/')` dentro de la página de `chat.z.ai`.
   - El navegador envía las cookies automáticamente (sesión del Director).
   - Z.ai responde con `{token: "eyJhbG...", role: "user"}`.
   - PowerShell captura el JWT de la respuesta.
   - PowerShell envía el JWT al sandbox: `POST /recibir-jwt`.
   - PowerShell cierra Edge.
   - Muestra "JWT enviado correctamente" y se cierra.
6. El sandbox persiste el JWT en `.browser_auth_state.json`.
7. El agente sigue trabajando automáticamente.

**Pre-instalado en todos los Windows 10/11:**
- PowerShell (viene con Windows desde Windows 7).
- Microsoft Edge (viene con Windows 10/11, basado en Chromium).
- DevTools Protocol (integrado en Edge y Chrome).

**No requiere instalar:**
- Python.
- Extensiones del navegador.
- DevTools manuales.
- Copiar/pegar cookies.

**Interacción del Director:**
- Descargar `czai-jwt-bridge.bat` (3 KB).
- Doble click.
- Una vez en la vida (el JWT no expira).

### Solución 2 — Subagentes paralelos en 3 niveles para documentos grandes

**Arquitectura:**

```
Documento muy grande (>50K tokens)
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  NIVEL 1 (Divisor)                                            │
│                                                               │
│  - Recibe el documento grande                                 │
│  - Calcula N bloques matemáticamente:                         │
│      N = ceil(total_tokens / MAX_TOKENS_POR_SUBAGENTE_N2)     │
│  - Lanza N subagentes de Nivel 2 EN PARALELO                  │
│  - Si N > MAX_SUBAGENTES_N2_PARALELOS (3):                    │
│      Lanza en lotes de 3                                      │
│  - Espera a que todos terminen                                │
│  - Acumula los N índices parciales                            │
│  - Se cierra                                                  │
└──────────────────────┬────────────────────────────────────────┘
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
  [N2-1]           [N2-2]           [N2-3]      (lote 1, máx 3)
  Lee bloque 1     Lee bloque 2     Lee bloque 3
  Clasifica        Clasifica        Clasifica
  Devuelve índice  Devuelve índice  Devuelve índice
       │               │               │
       └───────────────┼───────────────┘
                       │
                       ▼
                   [N2-4, N2-5, ...]            (lote 2, si hay más)
                       │
                       ▼
                   ... (hasta completar N bloques)
                       │
                       ▼ (el proceso pasa los N índices al N3)
┌──────────────────────────────────────────────────────────────┐
│  NIVEL 3 (Conciliador)                                        │
│                                                               │
│  - Recibe los N índices parciales de los N2                   │
│  - Reubica temas para evitar duplicados                       │
│  - Rehace 01_indice_recuperacion.md con todo organizado       │
│  - Genera resumen final para el agente principal              │
│  - Se cierra                                                  │
└──────────────────────────────────────────────────────────────┘
```

**Decisiones clave:**

| Aspecto | Decisión |
|---|---|
| Quién decide la cantidad de bloques | Nivel 1, con cálculo matemático |
| Quién lanza los N2 | Nivel 1 (no el proceso principal) |
| Cómo se lanzan los N2 | En paralelo real (siempre) |
| Límite paralelo para clasificación profunda | 3 subagentes a la vez |
| Si N > 3 | Se procesan en lotes de 3 |
| Comunicación entre niveles | N2 devuelven índices al N1, el proceso los pasa al N3 |
| Umbral de activación | Documentos >50K tokens van al flujo de 3 niveles |

**3 niveles de delegación:**

```
Documento adjunto
    │
    ▼
DocumentDelegator.should_delegate(size, context, override)
    │
    ├── size < 1000 tokens → LECTURA DIRECTA (agente principal lee)
    │
    ├── 1000 ≤ size ≤ 50000 tokens → SUBAGENTE ÚNICO (DocumentoIndexerSubagent actual)
    │
    └── size > 50000 tokens → FLUJO DE 3 NIVELES (N1 → N2×N → N3)
```

**Límites por tipo de tarea (conocimiento del agente):**

| Tipo de tarea | Límite paralelo | Aplicación |
|---|---|---|
| Lectura simple de archivos | 5 | Futuras tareas |
| Búsqueda puntual | 8 | Futuras tareas |
| Clasificación profunda + indexación | 3 | **Nivel 2** |

## 3. Arquitectura OOP

### Patrón reutilizable: Divisor + Conciliador

```
ContentDelegator (clase base abstracta, ya existe v3.5)
├── DocumentDelegator (ya existe)
└── Subdivider (ya existe, refactor v3.5)

SubagentLauncher (ya existe)
├── launch()              → 1 subagente (ya existe)
├── launch_many()         → N subagentes secuencial (ya existe)
└── launch_parallel()     → N subagentes en paralelo (NUEVO, genérico)
    │
    └── usa: concurrent.futures.ThreadPoolExecutor
         con max_workers = límite según tipo de tarea

Divisor (NUEVO, clase base abstracta)
├── particionar(contenido) → list[Porcion]
├── lanzar_subagentes(porciones, max_paralelos) → list[Respuesta]
└── implementaciones:
    └── DocumentoDivisor : Divisor
        └── particiona documento por páginas/tokens

Conciliador (NUEVO, clase base abstracta)
├── conciliar(respuestas) → RespuestaConsolidada
├── producir_resumen_final() → str
└── implementaciones:
    └── DocumentoConciliador : Conciliador
        └── combina índices parciales en índice consolidado
```

### Diagrama de clases

```
Divisor (abstract)
├── particionar() → list[Porcion]           (abstract)
├── lanzar_subagentes(porciones, max) → list[Respuesta]  (concreto, usa launch_parallel)
└── DocumentoDivisor : Divisor
    └── particionar(documento) → list[PorcionDocumento]

Conciliador (abstract)
├── conciliar(respuestas) → Consolidado     (abstract)
├── producir_resumen_final() → str          (abstract)
└── DocumentoConciliador : Conciliador
    ├── conciliar(indices_parciales) → IndiceConsolidado
    └── producir_resumen_final() → str

SubagentLauncher (modificado)
└── launch_parallel(requests, max_workers) → list[SubagentResponse]
    └── usa ThreadPoolExecutor

DocumentoIndexerSubagent (modificado)
├── run(attachment) → DocumentoIndexResult                    (ya existe, para docs <50K)
└── run_3_levels(attachment) → DocumentoIndexResult           (NUEVO, para docs >50K)
    ├── Lanza DivisorSubagent (N1)
    ├── N1 lanza N2×N en paralelo
    ├── Proceso pasa índices al ConciliadorSubagent (N3)
    └── N3 devuelve resultado consolidado
```

## 4. Archivos nuevos

| Archivo | Responsabilidad |
|---|---|
| `scripts/czai-jwt-bridge.bat` | Script .bat que el Director ejecuta con doble click |
| `scripts/jwt_bridge.ps1` | Script PowerShell que el .bat invoca (lógica real) |
| `client/credential_manager.py` | Gestiona el JWT: lo pide si falta, lo valida, lo persiste |
| `client/jwt_bridge_server.py` | Mini HTTP server temporal en el sandbox (3 endpoints) |
| `processing/divisor.py` | Clase base abstracta `Divisor` + `DocumentoDivisor` concreto |
| `processing/conciliador.py` | Clase base abstracta `Conciliador` + `DocumentoConciliador` concreto |
| `subagents/divisor_subagent.py` | Subagente N1 (divide + lanza N2) |
| `subagents/conciliador_subagent.py` | Subagente N3 (consolida índices) |

## 5. Archivos a modificar

| Archivo | Cambio |
|---|---|
| `models.py` | Añadir modelos `Porcion`, `IndiceParcial`, `IndiceConsolidado` |
| `config.py` | Añadir constantes de particionado y límites paralelos |
| `subagents/launcher.py` | Añadir `launch_parallel()` con ThreadPoolExecutor |
| `subagents/documento_indexer_subagent.py` | Añadir `run_3_levels()` para flujo de 3 niveles |
| `subagents/__init__.py` | Exportar nuevas clases |
| `pipeline.py` | Añadir `index_document_large()` para docs >50K |
| `recovery_cycle.py` | Detectar tamaño de attachment y elegir entre subagente único o 3 niveles |
| `estrategia/worklog_template.md` | Actualizar Paso 2c con instrucciones del .bat |

## 6. Constantes nuevas en config.py

```python
# v3.6: Particionado de documentos grandes
PARTITION_THRESHOLD_TOKENS = 50000          # docs >50K van a 3 niveles
MAX_TOKENS_POR_SUBAGENTE_N2 = 30000         # cada N2 lee ~30K tokens

# v3.6: Límites de subagentes paralelos por tipo de tarea
MAX_SUBAGENTES_LECTURA_ARCHIVOS = 5
MAX_SUBAGENTES_BUSQUEDA_PUNTUAL = 8
MAX_SUBAGENTES_CLASIFICACION_PROFUNDA = 3   # N2 usa este límite
MAX_SUBAGENTES_N2_PARALELOS = MAX_SUBAGENTES_CLASIFICACION_PROFUNDA  # = 3

# v3.6: JWT Bridge Server
JWT_BRIDGE_SERVER_PORT = 8086                # puerto del mini HTTP server
JWT_BRIDGE_SERVER_HOST = "0.0.0.0"           # accesible desde fuera del sandbox
```

## 7. Compatibilidad con versiones anteriores

- El flujo existente (sin documentos grandes) sigue funcionando igual.
- Los documentos <50K tokens siguen usando `DocumentoIndexerSubagent.run()` (subagente único).
- Los documentos >50K tokens usan `DocumentoIndexerSubagent.run_3_levels()` (3 niveles).
- El JWT manual (pasado explícitamente) sigue funcionando como fallback.
- El `.bat` es opcional: si el Director prefiere pasar el JWT manualmente, puede hacerlo.

## 8. Validación

### 8.1. Auto-tests atómicos

- `client/credential_manager.py`: validación de JWT, persistencia, detección de expiración.
- `client/jwt_bridge_server.py`: 3 endpoints responden correctamente.
- `processing/divisor.py`: particionado matemático, casos edge (doc vacío, 1 bloque, N bloques).
- `processing/conciliador.py`: consolidación de índices, deduplicación de temas.
- `subagents/divisor_subagent.py`: lanza N2 en paralelo, acumula resultados.
- `subagents/conciliador_subagent.py`: recibe índices, genera resumen final.

### 8.2. Tests E2E

- `test_e2e_v36_jwt_bridge`: simula el flujo completo del .bat (mock de DevTools Protocol).
- `test_e2e_v36_3_levels_small_doc`: doc <50K → subagente único (no 3 niveles).
- `test_e2e_v36_3_levels_large_doc`: doc >50K → 3 niveles con mock invoker.
- `test_e2e_v36_parallel_launch`: `launch_parallel()` lanza N subagentes en paralelo real.

## 9. Pendiente de validación

Espero tu validación para pasar a la fase de EJECUCIÓN del plan v3.6.

--- fin de SPEC v3.6 (spec_recuperacion_contexto_v3.6.md) ---


<!-- ============================================================ -->
# SECCIÓN: PLAN inicial (plan_script_contexto_zai.md)
<!-- Archivo original: plan_script_contexto_zai.md -->
<!-- ============================================================ -->

# Plan — Script Python: `contexto_zai.py`

**Proyecto:** Contexto Z.ai
**Fecha:** 2025-08-21
**Estado:** Plan arquitectónico

---

## 1. Visión

Un script Python que cualquier agente Z.ai puede invocar para recuperar su contexto perdido. El script:
- Extrae mensajes de cualquier chat (via agent-browser)
- Los clasifica automáticamente (sin keywords hardcodeadas)
- Genera archivos de recuperación autoexpandibles
- Se actualiza incrementalmente conforme el chat crece
- Funciona como herramienta CLI o como módulo importable

---

## 2. Arquitectura

```
contexto_zai.py
├── class ContextRecovery
│   ├── __init__(chat_id, work_dir)
│   ├── 
│   ├── # --- Paso -1: Autenticación ---
│   ├── setup_auth(jwt_token)          # Inyección de cookie + state save
│   ├── load_auth()                     # Cargar estado guardado
│   ├── get_share_id() → str           # POST /api/v1/chats/{chat_id}/share
│   │
│   ├── # --- Fase 1: Extracción ---
│   ├── extract_messages(since=None)   # Extraer todos o desde timestamp
│   ├── _get_message_tree() → dict     # GET /api/v1/chats/share/{share_id}
│   ├── _get_batch_content(ids) → list # POST .../messages/batch
│   │
│   ├── # --- Fase 2: Clasificación ---
│   ├── _build_exchanges(messages) → list
│   ├── _classify_dynamic(exchanges) → dict  # Agrupación temporal + TF-IDF
│   ├── _subdivide_if_needed(bloque) → list
│   │
│   ├── # --- Fase 3: Generación ---
│   ├── generate_all()                  # Orquesta Fase 2 + Fase 3
│   ├── _gen_estado_actual(exchanges) → str
│   ├── _gen_indice(bloques) → str
│   ├── _gen_decisiones(bloques) → str
│   ├── _gen_bloque(tema, exchanges) → str
│   │
│   ├── # --- Fase 5: Sostenibilidad ---
│   ├── check_updates() → bool         # ¿Hay mensajes nuevos?
│   ├── update_incremental()           # Extraer + reclasificar + regenerar
│   │
│   └── # --- Utilidades ---
│       ├── load_metadata() → dict
│       ├── save_metadata(data)
│       └── get_recovery_files() → list
│
├── def cli()                          # Click/argparse CLI
└── def main()
```

---

## 3. Clasificación Dinámica (solución al Gap #3 de la validación)

### Problema

Las reglas hardcodeadas del spec v2.3 solo funcionan para el proyecto APA. Necesitamos clasificación que funcione para CUALQUIER chat.

### Solución: Agrupación Temporal con Detección de Cambios de Tema

```
1. Dividir exchanges en ventanas temporales (ej: 30 min de inactividad = separación)
2. Para cada ventana, extraer las 10 palabras más frecuentes (excluyendo stopwords)
3. Dos ventanas consecutivas con < 30% de palabras en común = temas diferentes
4. Fusionar ventanas con > 70% de palabras en común = mismo tema
5. Nombre del tema = las 3-5 palabras más representativas de la ventana
```

### Ventajas
- Cero keywords hardcodeadas
- Funciona para cualquier proyecto/idioma
- Se adapta automáticamente al contenido del chat
- Los nombres de tema son descriptivos (ej: "recuperación contexto jwt", "planner OOP refactor")

### Alternativa: LLM-assisted (opcional, más lenta)

Si el agente tiene acceso a un LLM, puede clasificar un lote de exchanges con un prompt:
```
"Dado estos N exchanges de una conversación, clasifícalos en 2-5 temas.
 Devuelve JSON: {tema: [exchange_indices]}"
```
Esto se activaría solo si la clasificación automática produce temas demasiado genéricos (>50% clasificados como "general").

---

## 4. Generación de 00_estado_actual.md

### Secciones D (Director) — Fáciles de automatizar

| Sección | Fuente | Automatización |
|---------|--------|----------------|
| D1 — Última instrucción | Último mensaje role="user" | Copia literal del contenido |
| D2 — Contexto de tarea | Últimos 10 mensajes | Heurística: concatenar mensajes del Director de los últimos N exchanges, mantener < 10K tokens |
| D3 — Decisiones pendientes | Buscar patrones | Regex: "¿X o Y?", "decidir", "cuál prefieres", preguntas sin respuesta del agente |
| D4 — Restricciones | Buscar patrones | Regex: "no uses", "nunca", "siempre", "preferiblemente", instrucciones imperativas |

### Secciones A (Agente) — Parcialmente automatizables

| Sección | Fuente | Automatización |
|---------|--------|----------------|
| A1 — Qué estaba haciendo | Último mensaje role="assistant" | Primeros 500 chars del último mensaje del agente |
| A2 — Entregables | Todos los mensajes | Regex: rutas de archivo (`/path/to/file.ext`), menciones de "archivo", "guardado", "creado" |
| A3 — Errores | Todos los mensajes | Regex: "ERROR", "FAIL", "failed", "Traceback", "Exception" en los últimos 20 exchanges |
| A4 — Siguiente paso | Inferencia del contexto | Última instrucción del Director + lo que el agente estaba haciendo → síntesis simple |

### Estrategia

El script genera una **versión cruda** de las 8 secciones. Es suficiente para que un agente recupere el contexto operativo. Si necesita más detalle, delega a un subagente para que lea el bloque temático relevante.

---

## 5. Autoexpansión

### Cómo crece el sistema

```
Estado inicial (N mensajes):
  contexto_recuperacion/
  ├── _metadata.json          (share_id, ultimo_timestamp, tema_a_archivos)
  ├── 00_estado_actual.md     (8 secciones, ~5-20K tokens)
  ├── 01_indice_recuperacion.md
  ├── 02_decisiones_clave.md
  └── bloque_tema1.md         (N exchanges, < 70K tokens)

Después de M mensajes nuevos:
  contexto_recuperacion/
  ├── _metadata.json          (actualizado: nuevo ultimo_timestamp)
  ├── 00_estado_actual.md     (regenerado completamente)
  ├── 01_indice_recuperacion.md (actualizado con nuevos bloques)
  ├── 02_decisiones_clave.md   (actualizado con nuevas decisiones)
  ├── bloque_tema1.md          (ampliado con nuevos exchanges)
  └── bloque_tema2.md          (NUEVO: tema detectado en mensajes nuevos)

Si bloque_tema1.md supera 70K tokens:
  contexto_recuperacion/
  ├── ...
  ├── bloque_tema1_parte1.md  (exchanges antiguos)
  ├── bloque_tema1_parte2.md  (exchanges recientes)
  └── ...
  (tema_a_archivos actualizado en metadata)
```

### Trigger de actualización

No usa un contador en memoria (se pierde con compresión). Usa:

```python
def check_updates(self):
    """Compara ultimo_timestamp con el timestamp del último mensaje del chat."""
    tree = self._get_message_tree()
    latest_ts = max(m['timestamp'] for m in tree['chat']['history']['messages'].values())
    saved_ts = self.load_metadata().get('ultimo_timestamp', 0)
    return latest_ts > saved_ts
```

El agente (o un cron) llama `check_updates()` periódicamente. Si devuelve True, ejecuta `update_incremental()`.

---

## 6. Interfaz CLI

```bash
# Setup inicial (una vez)
python contexto_zai.py setup --token "<JWT>" --chat-id "<chat_id>"

# Extracción completa
python contexto_zai.py extract --chat-id "<chat_id>"

# Generar archivos de recuperación
python contexto_zai.py generate --chat-id "<chat_id>"

# Verificar si hay actualizaciones
python contexto_zai.py check --chat-id "<chat_id>"

# Actualización incremental
python contexto_zai.py update --chat-id "<chat_id>"

# Pipeline completo (extract + generate)
python contexto_zai.py run --chat-id "<chat_id>"

# Modo automático: extraer, generar, y dejar listo para que el agente lea
python contexto_zai.py auto --chat-id "<chat_id>" --work-dir ./contexto_recuperacion/
```

---

## 7. Dependencias

```
# Ninguna dependencia externa para la lógica core
# Solo usa:
# - subprocess (para llamar agent-browser)
# - json, os, re, datetime, math (stdlib)
# - collections.Counter (para TF de palabras)

# Opcional (para LLM-assisted classification):
# - openai / z-ai-web-dev-sdk
```

El script es **autosuficiente**. No requiere numpy, scikit-learn, ni ninguna librería de ML. La clasificación es por heurísticas estadísticas simples.

---

## 8. Estructura de archivos de salida

```
{work_dir}/
├── _metadata.json
├── 00_estado_actual.md
├── 01_indice_recuperacion.md
├── 02_decisiones_clave.md
├── bloque_{tema_sanitizado}.md
├── bloque_{tema_sanitizado}_parte{N}.md  (si se subdividió)
└── _extraction_raw.json  (opcional, para debug)
```

Los nombres de tema se sanitizan: minúsculas, espacios → guiones bajos, máximo 40 chars.
Ejemplo: "Recuperación de Contexto JWT" → `bloque_recuperacion_contexto_jwt.md`

---

## 9. Manejo de Errores

| Error | Acción |
|-------|--------|
| agent-browser no encontrado | Mensaje claro + instrucciones de instalación |
| 401 en share API | Intentar reload del estado. Si falla, pedir nuevo token al Director |
| 404 en batch endpoint | Verificar share_id. Si expiró, re-ejecutar Paso -1 |
| Chat vacío (0 mensajes) | Log warning, generar metadata vacía, no fallar |
| JSON malformado en mensajes | Skip mensaje, log warning, continuar con los demás |
| Bloque > 70K tokens | Subdividir automáticamente |
| _metadata.json corrupto | Regenerar desde cero (extracción completa) |

---

## 10. Plan de Implementación (fases de codificación)

### Fase A — Core (extracción)
1. `__init__` con chat_id y work_dir
2. `setup_auth()` — protocolo de inyección de cookie
3. `load_auth()` — cargar estado guardado
4. `get_share_id()` — llamar share API
5. `extract_messages()` — Fase 1 completa
6. `_get_message_tree()` + `_get_batch_content()` — helpers de API

### Fase B — Clasificación
1. `_build_exchanges()` — algoritmo con previous_role
2. `_classify_dynamic()` — agrupación temporal + TF
3. `_subdivide_if_needed()` — control de tamaño

### Fase C — Generación
1. `_gen_estado_actual()` — 8 secciones
2. `_gen_indice()` — mapa de bloques
3. `_gen_decisiones()` — extracción de decisiones
4. `_gen_bloque()` — formato markdown de un bloque
5. `generate_all()` — orquestador

### Fase D — Sostenibilidad
1. `check_updates()` — delta de timestamps
2. `update_incremental()` — pipeline incremental
3. Metadata management (load/save)

### Fase E — CLI y pulido
1. argparse CLI con los comandos de la sección 6
2. Logging estructurado
3. Manejo de errores robusto
4. Tests básicos

---

## 11. Cómo el agente lo usa

### Cuando pierde contexto:

```
1. El agente lee 00_estado_actual.md
   → Sabe qué estaba haciendo, qué falta, qué sigue

2. Si necesita más detalle:
   → Lanza subagente con pregunta concreta sobre un bloque

3. Para actualizar los archivos:
   → Ejecuta: python contexto_zai.py update --chat-id <id>
```

### Cuando inicia una nueva sesión:

```
1. El agente verifica si contexto_recuperacion/ existe
2. Si existe y tiene metadata → ejecuta check_updates()
3. Si hay mensajes nuevos → update_incremental()
4. Lee 00_estado_actual.md como parte de su carga inicial
```
--- fin de PLAN inicial (plan_script_contexto_zai.md) ---


<!-- ============================================================ -->
# SECCIÓN: PLAN v2.0 (plan_refactorizacion_v2.md)
<!-- Archivo original: plan_refactorizacion_v2.md -->
<!-- ============================================================ -->

<!-- Destino en el proyecto: /home/z/my-project/contexto_zai/plan_refactorizacion_v2.md -->

# PLAN DE IMPLEMENTACIÓN v2 — Refactorización CLI → Proceso Autónomo v3.2

**Versión:** 2.0
**Fecha:** 2026-09-04
**Autor:** Agente CZAI
**Estado:** Pendiente de validación por el Director.
**Spec objetivo:** v3.2 (entregada en paralelo).

---

## Principios de implementación

1. **OOP estricto:** Todos los componentes son clases con responsabilidad única, interfaces claras, type hints, docstrings. Sin funciones sueltas en módulos.
2. **Scripts atómicos standalone:** Cada módulo independiente se autocontiene, no depende de otros módulos del proyecto, e incluye su propia validación interna (bloque `if __name__ == "__main__"` con batería de pruebas sobre sus funcionalidades).
3. **Scripts de dependencia con tests:** Los módulos que orquestan varios atómicos se validan mediante tests independientes en la carpeta `tests/` del proyecto, que ejecutan la integración de cada módulo atómico en el flujo completo.
4. **Cambios quirúrgicos:** Sobre el código existente, se reescribe solo lo que cambia. Lo reutilizable se conserva (exchange_builder, content_cleaner, chat_client base).

---

## Arquitectura de archivos propuesta

### Archivos atómicos standalone (auto-validables)

Cada uno incluye un bloque `if __name__ == "__main__"` con pruebas de sus funcionalidades.

| Archivo | Responsabilidad | Origen |
|---|---|---|
| `config.py` | Constantes y límites v3.2 (20K estado, 40K carga principal, UMBRAL_COMPRESION_PCT) | **Actualizar** existente |
| `models.py` | Modelos Pydantic (añadir Metadata, TemaMapping, SubtemaDerivado, DetectionEvent, Decision) | **Actualizar** existente |
| `client/browser_session.py` | Wrapper sobre agent-browser: lee/escribe cookie `token`, detecta sesión invitada, guarda/carga estado | **Nuevo** |
| `client/auth_client.py` | Aplica protocolo de inyección de cookie (set headers + navegar + set cookie + reload), valida perfil, crea share | **Refactorizar** existente |
| `client/chat_client.py` | Extrae árbol de mensajes y contenido vía batch (con `chat_id` autenticado, NO `share_id` invitado) | **Refactorizar** existente |
| `processing/exchange_builder.py` | Agrupa mensajes en intercambios | **Conservar** existente |
| `processing/classifier.py` | Clasifica cada intercambio en un tema (devuelve tema, no bloque) | **Reescribir** |
| `processing/content_cleaner.py` | Elimina reasoning, conserva código y rutas | **Conservar** existente |
| `processing/block_packer.py` | Empaqueta varios temas en un archivo hasta llenar el límite de tokens (garantiza que NINGÚN archivo supere 70K) | **Nuevo** (reemplaza block_manager) |
| `processing/subdivider.py` | Subdivide un tema grande en subtemas derivados únicos (NO parte1/parte2) | **Nuevo** |
| `metadata/manager.py` | Lee/escribe `_metadata.json`: tema_a_archivo, subtemas_derivados, ultimo_timestamp | **Nuevo** |
| `generation/estado_generator.py` | Genera estado actual con 8 secciones D1-D4 + A1-A4 (NO 4 secciones simples) | **Reescribir** |
| `generation/indice_generator.py` | Genera índice con tabla `tema → archivo` explícita (NO lista de descripciones) | **Reescribir** |
| `generation/decisiones_generator.py` | Delegador al subagente LLM (NO regex) | **Reescribir** |
| `generation/bloque_generator.py` | Formatea intercambios dentro de un bloque | **Conservar** existente |
| `detection/lexic_trigger.py` | Detecta frases del Director que indican pérdida ("ya te dije", "no repitas") | **Nuevo** |
| `detection/token_counter.py` | Estima tokens consumidos, dispara al 90% de capacidad útil | **Nuevo** |
| `detection/self_questions.py` | Auto-preguntas tras entregas relevantes (archivo, decisión, siguiente paso) | **Nuevo** |
| `subagents/launcher.py` | Wrapper sobre la herramienta Task para lanzar subagentes efímeros | **Nuevo** |
| `subagents/estado_subagent.py` | Lee archivo del tema del último intercambio, extrae contexto completo para las 8 secciones | **Nuevo** |
| `subagents/barrido_subagent.py` | Un subagente por archivo relevante, pregunta concreta | **Nuevo** |
| `subagents/decisiones_subagent.py` | Escanea intercambios nuevos, extrae decisiones con LLM, deduplica | **Nuevo** |
| `subagents/mantenimiento_subagent.py` | Actualización incremental: lee metadata, extrae nuevos, reclasifica | **Nuevo** |
| `verification/verifier.py` | Verifica límites con nuevos valores (20K estado, 40K carga principal, 70K bloques estricto) | **Actualizar** existente |

### Scripts de dependencia (orquestadores, con tests de integración)

| Archivo | Responsabilidad | Origen |
|---|---|---|
| `process/orchestrator.py` | Punto de entrada que el agente activa. Recibe señal de detección, coordina el ciclo completo | **Nuevo** |
| `process/recovery_cycle.py` | Coordina pasos 5-9 del flujo (extracción → clasificación → packing → subagentes → archivos) | **Nuevo** |
| `process/incremental_cycle.py` | Coordina paso 10 (actualización incremental: lee metadata, extrae nuevos, añade a existentes) | **Nuevo** |
| `pipeline.py` | Refactorizado: de CLI pipeline a entry point del proceso | **Reescribir** |

### Archivos a eliminar

| Archivo | Motivo |
|---|---|
| `cli.py` | Reemplazado por `process/orchestrator.py` |
| `__main__.py` | Si solo es entry point del CLI, se reemplaza |

### Tests de integración (carpeta `tests/`)

Un test por cada script de dependencia, validando que los atómicos se integran correctamente:

| Test | Valida |
|---|---|
| `tests/test_orchestrator.py` | Orchestrator recibe señal y activa el ciclo correcto (recovery vs incremental) |
| `tests/test_recovery_cycle.py` | Pasos 5-9: extracción → clasificación → packing → subagentes → archivos |
| `tests/test_incremental_cycle.py` | Paso 10: lee metadata, extrae solo nuevos, añade a existentes, actualiza metadata |
| `tests/test_pipeline.py` | Entry point end-to-end con datos simulados |

### Fixtures de prueba

| Archivo | Contenido |
|---|---|
| `tests/fixtures/chat_simulado.json` | 30 mensajes simulados con 4-5 temas diferentes para validar packing, unicidad y subdivisión |
| `tests/fixtures/chat_simulado_grande.json` | 100+ mensajes en un solo tema para validar subdivisión con subtemas únicos |

---

## Fases de ejecución (milestones)

Cada milestone produce un entregable verificable de forma independiente. Si la sesión se interrumpe, el siguiente agente puede retomar desde el último milestone completado.

### Milestone 0 — Foundation (base para todo lo demás)
- Actualizar `config.py` con límites v3.2 (20K estado, 40K carga principal, UMBRAL_COMPRESION_PCT=90)
- Actualizar `models.py` con nuevos modelos (Metadata, TemaMapping, SubtemaDerivado, DetectionEvent, Decision)
- Eliminar `cli.py` y `__main__.py`
- **Validación:** los atómicos existentes (exchange_builder, content_cleaner, chat_client) siguen pasando sus auto-tests
- **Prueba:** ejecutar `python3 contexto_zai/processing/exchange_builder.py` y los demás atómicos

### Milestone 1 — Autenticación automática
- Crear `client/browser_session.py` (atómico): `open_chat()`, `read_token_cookie()`, `is_guest_session()`, `inject_jwt(jwt)`, `save_state(path)`, `load_state(path)`
- Refactorizar `client/auth_client.py` (atómico): `validate_session()`, `create_share(chat_id)`
- Refactorizar `client/chat_client.py` (atómico): `extract_messages(chat_id)` con batch autenticado por `chat_id` (NO `share_id`)
- **Tests:** `tests/test_browser_session.py`, `tests/test_auth_client.py`, `tests/test_chat_client.py` (validan lectura de cookie, detección de invitado, save/load de estado, extracción completa)
- **Prueba de humo:** ejecutar contra el chat real de Sesión 5 y verificar que extrae los 30 mensajes

### Milestone 2 — Procesamiento multi-tema
- Reescribir `processing/classifier.py` (atómico): `classify(exchange) -> Tema` (devuelve tema, no bloque)
- Crear `processing/block_packer.py` (atómico): `pack(exchanges_by_topic, max_tokens) -> List[Bloque]` agrupando varios temas por archivo, garantizando que NINGÚN archivo supere 70K tokens
- Crear `processing/subdivider.py` (atómico): `subdivide(tema, exchanges) -> List[Subtema]` generando subtemas derivados únicos (NO parte1/parte2)
- **Tests:** auto-tests de cada atómico + `tests/test_block_packer.py` (valida unicidad temática, packing por tamaño, subdivisión con subtemas únicos)
- **Prueba de humo:** ejecutar sobre los 30 mensajes reales de Sesión 5 y verificar que ningún bloque supera 70K tokens

### Milestone 3 — Metadata
- Crear `metadata/manager.py` (atómico): `read(path)`, `write(metadata)`, `update_tema_a_archivo(tema, archivo)`, `update_subtemas_derivados(tema, subtemas)`, `get_ultimo_timestamp()`, `set_ultimo_timestamp()`
- **Tests:** auto-tests (CRUD de metadata, tema_a_archivo, subtemas_derivados, ultimo_timestamp)
- **Prueba de humo:** escribir y leer metadata con casos de prueba

### Milestone 4 — Generación v3.2
- Reescribir `generation/estado_generator.py` (atómico): generar 8 secciones D1-D4 + A1-A4, eliminando falsos positivos en errores y truncación en última respuesta. Tamaño máximo 20K tokens.
- Reescribir `generation/indice_generator.py` (atómico): tabla `tema → archivo` explícita
- Reescribir `generation/decisiones_generator.py` (atómico): delegador al subagente LLM, no regex. Modo incremental + deduplicación.
- **Tests:** auto-tests de cada generador
- **Prueba de humo:** ejecutar sobre los 30 mensajes reales de Sesión 5 y verificar: estado con 8 secciones, índice con tabla mapeo, decisiones sin falsos positivos

### Milestone 5 — Detección
- Crear `detection/lexic_trigger.py` (atómico): `detect(text_director) -> bool`
- Crear `detection/token_counter.py` (atómico): `estimate_tokens(messages) -> int`, `should_trigger(counter, threshold) -> bool`
- Crear `detection/self_questions.py` (atómico): `ask(exchange) -> List[Answer]`, `should_trigger(answers) -> bool`
- **Tests:** auto-tests de cada mecanismo

### Milestone 6 — Subagentes
- Crear `subagents/launcher.py` (atómico): `launch(prompt, files_to_read) -> Response`
- Crear `subagents/estado_subagent.py` (atómico): `run(exchange, indice, tema_a_archivo) -> EstadoContext`
- Crear `subagents/barrido_subagent.py` (atómico): `run(archivo, pregunta) -> Response`
- Crear `subagents/decisiones_subagent.py` (atómico): `run(exchanges_nuevos, decisiones_existentes) -> List[Decision]`
- Crear `subagents/mantenimiento_subagent.py` (atómico): `run(metadata_path) -> Metadata`
- **Tests:** auto-tests de cada subagente (con datos simulados)

### Milestone 7 — Orquestación (scripts de dependencia)
- Crear `process/orchestrator.py`: punto de entrada del proceso. `activate(trigger, chat_id, jwt=None)`
- Crear `process/recovery_cycle.py`: coordina pasos 5-9
- Crear `process/incremental_cycle.py`: coordina paso 10
- Refactorizar `pipeline.py` como entry point del proceso
- **Tests de integración:** `tests/test_orchestrator.py`, `tests/test_recovery_cycle.py`, `tests/test_incremental_cycle.py`

### Milestone 8 — Verificación y contrato
- Actualizar `verification/verifier.py` con nuevos límites (20K estado, 40K carga principal, 70K bloques estricto con reject si supera)
- **Requiere autorización separada:** añadir sección de recuperación a `estrategia/agent-context/contrato.md` (es archivo del repo de estrategia)

### Milestone 9 — Validación end-to-end
- `tests/test_pipeline.py` con un chat real o simulado
- Prueba completa del flujo de 13 pasos
- **Criterio de aceptación:** el pipeline ejecuta los 13 pasos contra el chat real de Sesión 5 y produce archivos operativos (estado con 8 secciones reales, índice con mapeo, decisiones sin falsos positivos, bloques sin desbordar)

---

## Decisiones de arquitectura relevantes

**1. Subagentes como clases, no como funciones.** Cada subagente es una clase con método `run()` que encapsula su prompt, su lógica de lectura y su formato de respuesta. Esto permite testearlos con datos simulados sin lanzar el Task real.

**2. El orquestador es el único punto de entrada.** El agente principal solo llama a `Orchestrator.activate(trigger=...)`. El orquestador decide si ejecuta recovery_cycle o incremental_cycle según el estado de la metadata.

**3. La metadata es la fuente de verdad.** Todo el estado del proceso vive en `_metadata.json`. Si el proceso se reinicia, lee la metadata y sabe dónde quedó. Esto permite que múltiples sesiones del agente compartan el mismo estado.

**4. Los atómicos no se importan entre sí.** Cada atómico recibe sus dependencias por inyección en el constructor. Esto permite testearlos aislados y reutilizarlos en otros contextos.

**5. Los tests de integración usan datos simulados, no chats reales.** Un fixture `tests/fixtures/chat_simulado.json` con intercambios de prueba permite validar el flujo completo sin depender de la API de Z.ai. Para la validación final (Milestone 9) sí se usa el chat real.

**6. El block_packer garantiza el límite estricto.** Es el componente crítico para evitar el bug de Sesión 5 (bloque de 71K tokens). Si un tema individual excede 70K tokens, el subdivider lo subdivide en subtemas únicos ANTES de que el packer lo empaquete. El packer nunca recibe un tema que supere el límite.

---

## Dependencias externas necesarias

| Paquete | Uso |
|---|---|
| `pydantic` | Modelos (ya instalado) |
| `rich` | Output en consola (ya instalado) |
| `httpx` | HTTP client (ya instalado) |
| `agent-browser` (CLI) | Manipulación del navegador (ya instalado) |

No se añaden dependencias nuevas.

---

## Cobertura de los cambios pendientes de la spec v3.2

| Cambio spec v3.2 | Milestone que lo cubre |
|---|---|
| 1. De CLI a proceso autónomo | M7 |
| 2. Mecanismos de detección | M5 |
| 3. Reescribir clasificador | M2 |
| 4. Subdivisión con nuevos temas | M2 |
| 5. Mecanismo de unicidad temática | M2 |
| 6. Actualización incremental | M7 |
| 7. Subagente de estado actual | M6 + M7 |
| 8. Límites actualizados | M0 |
| 9. Sección de recuperación en contrato.md | M8 (requiere autorización separada) |
| 10. Archivos accesibles desde workspace y download | M7 |
| 11. Metadata _metadata.json | M3 |
| 12. JWT automático | M1 |
| 13. Decisiones clave activas | M4 + M6 |
| 14. Batch endpoint con chat_id | M1 |
| 15. Estado actual con 8 secciones | M4 |
| 16. Decisiones con LLM | M4 + M6 |
| 17. Control estricto de límites por bloque | M2 |
| 18. Índice con mapeo tema → archivo | M4 |

**Cobertura total:** 18/18 cambios cubiertos.

---

## Cómo se valida este plan

Tras tu validación en el próximo prompt, el agente de la próxima sesión (o yo mismo si continúo) leerá:

1. `worklog.md` — estado actual y handoff de Sesión 5.
2. `download/spec_recuperacion_contexto_v3.2.md` — spec objetivo.
3. `download/plan_refactorizacion_v2.md` — este plan.

Y comenzará la ejecución por el Milestone 0, avanzando secuencialmente hasta donde la sesión permita, dejando handoff claro en el worklog al cierre.

---

## Pendiente de validación

Espero tu validación en el próximo prompt para pasar a la fase de EJECUCIÓN. Si hay algo que ajustar del plan (orden de milestones, alcance, decisiones de arquitectura), indícamelo y lo corrijo antes de empezar.

--- fin de PLAN v2.0 (plan_refactorizacion_v2.md) ---


<!-- ============================================================ -->
# SECCIÓN: PLAN v3.0 (plan_refactorizacion_v3.md)
<!-- Archivo original: plan_refactorizacion_v3.md -->
<!-- ============================================================ -->

# contexto_zai/plan_refactorizacion_v3.md -- Plan v3: versionado de scripts con grafo de cambios reversible.
<!-- Destino en el proyecto: /home/z/my-project/contexto_zai/plan_refactorizacion_v3.md -->

# PLAN DE IMPLEMENTACIÓN v3 — Versionado de scripts con grafo de cambios reversible

**Versión:** 3.0
**Fecha:** 2026-09-04
**Autor:** Agente CZAI
**Estado:** Pendiente de validación por el Director.
**Spec objetivo:** v3.3 (entregada en paralelo).

---

## Principios de implementación

1. **OOP estricto:** Todos los componentes son clases con responsabilidad única, interfaces claras, type hints, docstrings. Sin funciones sueltas en módulos.
2. **Scripts atómicos standalone:** Cada módulo independiente se autocontiene, no depende de otros módulos del proyecto, e incluye su propia validación interna (bloque `if __name__ == "__main__"` con batería de pruebas sobre sus funcionalidades).
3. **Scripts de dependencia con tests:** Los módulos que orquestan varios atómicos se validan mediante tests independientes en la carpeta `tests/` del proyecto, que ejecutan la integración de cada módulo atómico en el flujo completo.
4. **Cambios quirúrgicos:** Sobre el código existente, se reescribe solo lo que cambia. Lo reutilizable se conserva.
5. **Compatibilidad Windows:** Todos los scripts son auto-ejecutables en Windows sin configuración previa (stub de `sys.path` + UTF-8 inline + cabeceras de documentación).

---

## Arquitectura de archivos

### Archivos atómicos nuevos

| Archivo | Responsabilidad |
|---|---|
| `processing/code_detector.py` | Detector de código: identifica scripts y artefactos versionables en el contenido de intercambios. Extrae bloques de código, identifica el nombre del script (por ruta de archivo, comentario `# Destino:`, o bloque de código con nombre). Asigna nombre propio (con apellido/DNI si hay duplicados). |
| `processing/version_graph.py` | Grafo de cambios: calcula diffs entre versiones consecutivas de un script (forward y reverse). Permite retroceder desde la versión actual aplicando cambios inversos. |

### Archivos atómicos a modificar

| Archivo | Cambio |
|---|---|
| `models.py` | Añadir modelos: `Script`, `ScriptVersion`, `ChangeGraph`, `ChangeNode`. |
| `processing/subdivider.py` | Integrar `code_detector`: cuando un intercambio contiene scripts, se subdividen por nombre de script (no por keywords léxicas). Cada subtema = nombre del script. |
| `generation/bloque_generator.py` | Incluir el grafo de cambios en el formato del bloque cuando contenga scripts versionados. |
| `generation/indice_generator.py` | Mostrar scripts versionados en el índice. |
| `generation/recovery_generator.py` | Orquestar la generación del archivo `_grafos_cambios.json`. |
| `process/recovery_cycle.py` | Invocar el detector de código durante la clasificación. |
| `config.py` | Patrones de detección de código (triple backtick, comentarios `# Destino:`, rutas de archivo). |

### Archivos de tests nuevos

| Archivo | Qué valida |
|---|---|
| `tests/test_code_detector.py` | Detección de scripts, extracción de bloques, identificación de duplicados. |
| `tests/test_version_graph.py` | Cálculo de diffs, retroceso a versiones anteriores, casos edge. |

### Archivos de tests a modificar

| Archivo | Cambio |
|---|---|
| `tests/test_classifier_packer_subdivider.py` | Añadir tests de subdivisión por nombre de script. |
| `tests/test_e2e_pipeline.py` | Añadir tests de detección de código y versionado en el flujo E2E. |

---

## Nuevos modelos

```python
class Script(BaseModel):
    """Un script o artefacto versionable identificado en el chat."""
    name: str           # Nombre propio (ej: "server", "router")
    full_path: str       # Ruta completa (DNI/apellido si hay duplicados)
    versions: list[ScriptVersion]

class ScriptVersion(BaseModel):
    """Una versión de un script en un punto del chat."""
    version_id: str     # Identificador único (ej: "v1", "v2")
    timestamp: float    # Cuándo apareció en el chat
    exchange_id: int     # En qué intercambio apareció
    content: str        # Contenido del script en esta versión
    parent_version: Optional[str]  # Versión padre en el grafo

class ChangeGraph(BaseModel):
    """Grafo de cambios reversible de un script."""
    script_name: str
    nodes: list[ChangeNode]  # Nodos del grafo (uno por versión)
    current_version: str

class ChangeNode(BaseModel):
    """Nodo del grafo de cambios."""
    version_id: str
    parent_version_id: Optional[str]
    forward_diff: str   # Diff para llegar a esta versión desde el padre
    reverse_diff: str   # Diff para volver al padre desde esta versión
```

---

## Fases de ejecución (milestones)

Cada milestone produce un entregable verificable de forma independiente.

### Milestone V1 — Code Detector
- Crear `processing/code_detector.py` (atómico standalone con auto-tests).
- **Responsabilidad:** identificar scripts y artefactos versionables en el contenido de intercambios.
- **Patrones de detección:**
  1. Bloques de código entre triple backtick con identificador de lenguaje.
  2. Comentarios `# Destino: ruta/al/archivo.py` en la primera línea.
  3. Rutas de archivo mencionadas en el texto.
  4. Bloques de código sin lenguaje explícito que contienen patrones de código (imports, def, class, function).
- **Nombres propios:** el nombre del script se extrae del nombre del archivo (sin extensión). Si hay duplicados, se distingue por ruta completa (apellido/DNI).
- **Tests auto:** detección de scripts, extracción de bloques, identificación de duplicados, casos edge (sin código, código sin nombre, código con ruta relativa).
- **Tests integración:** `tests/test_code_detector.py`.

### Milestone V2 — Version Graph
- Crear `processing/version_graph.py` (atómico standalone con auto-tests).
- **Responsabilidad:** calcular diffs entre versiones consecutivas de un script (forward y reverse), y permitir retroceder desde la versión actual aplicando cambios inversos.
- **Diff forward:** cambios necesarios para llegar de la versión anterior a la nueva.
- **Diff reverse:** cambios necesarios para volver de la nueva a la anterior.
- **Retroceso:** desde la versión actual, aplicar `reverse_diff` sucesivamente hasta llegar a la versión destino.
- **Casos edge:** sin versiones, una sola versión, ramificaciones (si el agente probó enfoques diferentes).
- **Tests auto:** cálculo de diffs, retroceso a versiones anteriores, casos edge.
- **Tests integración:** `tests/test_version_graph.py`.

### Milestone V3 — Modelos
- Actualizar `models.py` con `Script`, `ScriptVersion`, `ChangeGraph`, `ChangeNode`.
- Auto-tests de los nuevos modelos.

### Milestone V4 — Integración en Subdivider
- Modificar `processing/subdivider.py` para integrar `code_detector`.
- Cuando un intercambio contiene scripts, se subdividen por nombre de script (no por keywords léxicas).
- Cada subtema = nombre del script (con apellido/DNI si hay duplicados).
- El `_split_exchange_content` usa el detector de código para identificar scripts y crear subtemas con nombres propios.
- **Tests:** subdivisión por nombre de script, unicidad, integridad de versiones.

### Milestone V5 — Integración en Bloque Generator
- Modificar `generation/bloque_generator.py` para incluir el grafo de cambios en el formato del bloque.
- Cuando un bloque contiene scripts versionados, se incluye una sección con el resumen del grafo (versiones, cambios principales).
- **Tests:** formato con grafo de cambios.

### Milestone V6 — Integración en Índice y Recovery Generator
- Modificar `generation/indice_generator.py` para mostrar scripts versionados.
- Modificar `generation/recovery_generator.py` para orquestar la generación del archivo `_grafos_cambios.json`.
- **Tests:** índice con scripts, generación de `_grafos_cambios.json`.

### Milestone V7 — Integración en Recovery Cycle
- Modificar `process/recovery_cycle.py` para invocar el detector de código durante la clasificación.
- El flujo completo: extracción → clasificación → detección de código → subdivisión por script → empaquetado → generación con grafo de cambios.
- **Tests:** flujo completo con detección de código.

### Milestone V8 — Config y patrones
- Actualizar `config.py` con patrones de detección de código.
- **Tests:** patrones cargados correctamente.

### Milestone V9 — Validación E2E
- Ejecutar el proceso completo contra el chat real.
- Verificar que los scripts se identifican, versionan y guardan correctamente.
- Verificar que el grafo de cambios permite retroceder a versiones anteriores.
- **Tests:** `tests/test_e2e_pipeline.py` actualizado con tests de detección de código y versionado.

---

## Orden de ejecución

V1 → V2 → V3 → V4 → V5 → V6 → V7 → V8 → V9

---

## Cobertura de los cambios pendientes de la spec v3.3

| Cambio spec v3.3 | Milestone que lo cubre |
|---|---|
| 1. Crear `processing/code_detector.py` | V1 |
| 2. Crear `processing/version_graph.py` | V2 |
| 3. Actualizar `models.py` | V3 |
| 4. Actualizar `processing/subdivider.py` | V4 |
| 5. Actualizar `generation/bloque_generator.py` | V5 |
| 6. Actualizar `generation/indice_generator.py` | V6 |
| 7. Actualizar `generation/recovery_generator.py` | V6 |
| 8. Actualizar `process/recovery_cycle.py` | V7 |
| 9. Actualizar `config.py` | V8 |

**Cobertura total:** 9/9 cambios cubiertos.

---

## Cómo se valida este plan

Tras tu validación, el agente leerá:

1. `worklog.md` — estado actual y handoff de Sesión 5.
2. `download/spec_recuperacion_contexto_v3.3.md` — spec objetivo.
3. `download/plan_refactorizacion_v3.md` — este plan.

Y comenzará la ejecución por el Milestone V1, avanzando secuencialmente hasta donde la sesión permita, dejando handoff claro en el worklog al cierre.

---

## Pendiente de validación

Espero tu validación para pasar a la fase de EJECUCIÓN del plan v3. Si hay algo que ajustar del plan (orden de milestones, alcance, decisiones de arquitectura), indícamelo y lo corrijo antes de empezar.

--- fin de PLAN v3.0 (plan_refactorizacion_v3.md) ---


<!-- ============================================================ -->
# SECCIÓN: PLAN v3.4 (plan_refactorizacion_v3.4.md)
<!-- Archivo original: plan_refactorizacion_v3.4.md -->
<!-- ============================================================ -->

# contexto_zai/plan_refactorizacion_v3.4.md -- Plan v3.4: links externos, clasificacion por capas, estado sin truncado, exportacion/importacion de contexto.
<!-- Destino en el proyecto: /home/z/my-project/plan_refactorizacion_v3.4.md -->

# PLAN DE IMPLEMENTACIÓN v3.4 — Links externos, clasificación por capas, estado sin truncado, exportación/importación

**Versión:** 3.4
**Fecha:** 2026-09-05
**Autor:** Agente CZAI
**Estado:** Pendiente de validación por el Director.
**Spec objetivo:** v3.4 (entregada en paralelo).

---

## Principios de implementación

1. **OOP estricto:** Clases con responsabilidad única, interfaces claras, type hints, docstrings.
2. **Scripts atómicos standalone:** Autocontenidos con bloque `if __name__ == "__main__"` con auto-tests.
3. **Scripts de dependencia con tests:** Tests de integración en `tests/`.
4. **Cambios quirúrgicos:** Sobre el código existente del repo, solo se modifica lo que cambia.
5. **Compatibilidad Windows:** Auto-ejecutables sin configuración previa.

---

## Archivos nuevos

| Archivo | Responsabilidad |
|---|---|
| `client/web_reader.py` | Lee contenido de una URL y lo convierte en texto plano. Detecta URLs en mensajes del Director. |
| `subagents/discriminator_subagent.py` | Subagente que lee un tema grande y propone subdivisión en temas específicos basándose en el contenido real. |
| `processing/intention_classifier.py` | Capa 2 de clasificación: analiza la intención del usuario para descomponer el tema "general" en temas reales. |
| `context/exporter.py` | Empaqueta todos los archivos del contexto en un `.zip` con instrucciones de recuperación y metadata del paquete. |
| `context/importer.py` | Descomprime un paquete de contexto exportado y lo carga en el workspace del agente. |
| `context/__init__.py` | Paquete de exportación/importación de contexto. |

## Archivos a modificar

| Archivo | Cambio |
|---|---|
| `processing/exchange_builder.py` | Cuando detecta un link en un mensaje del Director, usa `web_reader` para leerlo y crea un intercambio virtual con el contenido. |
| `processing/classifier.py` | Después de la clasificación léxica (Capa 1), si un intercambio va a "general", pasa por `intention_classifier` (Capa 2) para asignarle un tema real. |
| `generation/estado_generator.py` | Reemplazar el truncado actual por truncamiento lógico: resumir la parte excluida y añadirla al final, manteniendo orden cronológico. |
| `config.py` | Añadir patrones de detección de URLs y temas de intención (solicitud_documentacion, aprobacion, rechazo, etc.). |
| `process/recovery_cycle.py` | Invocar el subagente discriminador cuando un tema sigue siendo demasiado grande después de la Capa 2. |
| `pipeline.py` | Añadir funciones `export_context()` y `import_context()`. |
| `worklog_template.md` (repo estrategia) | Documentar exportación/importación de contexto en el Paso 2b. |

---

## Fases de ejecución (milestones)

### Milestone F1 — Web Reader (links externos)
- Crear `client/web_reader.py` (atómico standalone con auto-tests).
- Detecta URLs (`http://`, `https://`) en texto.
- Descarga el contenido de la URL con httpx.
- Convierte HTML a texto plano (elimina scripts, estilos, etiquetas).
- Extrae el título de la página.
- Devuelve `ExternalContent` con url, title, content, source.
- **Tests auto:** detección de URLs, lectura de HTML, limpieza de scripts/estilos, extracción de título, casos edge (URL vacía, URL inválida, sin conexión).

### Milestone F2 — Integración de links en exchange_builder
- Modificar `processing/exchange_builder.py`.
- Cuando construye intercambios, escanea los mensajes del Director buscando URLs.
- Si encuentra un link, usa `web_reader` para leerlo.
- Crea un intercambio virtual con el contenido del link como respuesta del agente.
- El intercambio se clasifica y se mete en un bloque temático como cualquier otro.
- **Tests:** detección de links en mensajes, creación de intercambios virtuales, integración con el pipeline.

### Milestone F3 — Clasificación por intención (Capa 2)
- Crear `processing/intention_classifier.py` (atómico standalone con auto-tests).
- Recibe un intercambio clasificado como "general".
- Analiza la intención del usuario basándose en patrones:
  - `solicitud_documentacion`: "describe", "explica", "paso a paso".
  - `solicitud_implementacion`: "implementa", "ejecuta", "a ejecutar".
  - `aprobacion`: "correcto", "aprobado", "ok".
  - `rechazo`: "no estoy de acuerdo", "incorrecto".
  - `correccion`: "no lo que te pedí", "mejor hacer".
  - `consulta_estado`: "cómo vamos", "estado", "qué falta".
  - `handoff`: "relee el worklog", "perdiste contexto".
  - `priorizacion`: "entrega primero", "necesito que".
- Devuelve el tema real (no "general").
- **Tests auto:** detección de cada intención, casos edge (mensaje neutro, mensaje ambiguo).

### Milestone F4 — Integración de Capa 2 en classifier
- Modificar `processing/classifier.py`.
- Después de la clasificación léxica (Capa 1), si un intercambio se asigna a "general", pasa por `intention_classifier` (Capa 2).
- Si la Capa 2 asigna un tema real, se usa ese.
- Si la Capa 2 no encuentra intención, se mantiene "general".
- **Tests:** clasificación de dos capas en secuencia, temas reales asignados correctamente.

### Milestone F5 — Subagente discriminador (Capa 3)
- Crear `subagents/discriminator_subagent.py` (atómico standalone con auto-tests).
- Se lanza cuando un tema (después de Capa 1 y Capa 2) sigue siendo demasiado grande.
- Lee todos los intercambios del tema.
- Identifica qué se está discutiendo realmente.
- Propone temas específicos para subdividir.
- Devuelve una propuesta de subdivisión (tema → intercambios).
- **Tests auto:** discriminación de temas, propuesta de subdivisión.

### Milestone F6 — Integración de Capa 3 en recovery_cycle
- Modificar `process/recovery_cycle.py`.
- Después de la clasificación (Capa 1 + Capa 2), si un tema sigue superando el límite, lanza el subagente discriminador (Capa 3).
- Aplica la subdivisión propuesta por el subagente.
- Reclasifica los intercambios a los nuevos temas.
- **Tests:** integración de tres capas, reducción del tema "general".

### Milestone F7 — Estado actual con truncamiento lógico
- Modificar `generation/estado_generator.py`.
- Reemplazar el `_truncate` actual (que corta con "(truncado por límite de espacio)") por truncamiento lógico:
  1. Identifica la parte del contenido que no cabe (la más antigua del tema).
  2. Resume esa parte sin perder información clave.
  3. Añade el resumen al final en una sección "Resumen del contexto excluido".
  4. Mantiene el orden cronológico.
- **Tests:** truncamiento lógico, preservación de información, orden cronológico.

### Milestone F8 — Config y patrones
- Modificar `config.py`.
- Añadir patrones de detección de URLs (`URL_PATTERN`).
- Añadir temas de intención (`INTENTION_THEMES` con keywords por intención).
- **Tests:** patrones cargados correctamente.

### Milestone F9 — Validación E2E (fixes 1-3)
- Ejecutar el proceso completo contra el chat real.
- Verificar que los links externos se procesan como intercambios.
- Verificar que el tema "general" se descompone en temas reales.
- Verificar que el estado actual no se trunca a secas (o usa truncamiento lógico).
- **Tests:** `tests/test_e2e_pipeline.py` actualizado.

### Milestone F10 — Exportador de contexto
- Crear `context/exporter.py` (atómico standalone con auto-tests).
- Empaqueta todos los archivos del contexto (`00_estado_actual.md`, `01_indice_recuperacion.md`, `02_decisiones_clave.md`, `bloque_*.md`, `_metadata.json`, `_grafos_cambios.json`) en un `.zip`.
- Genera `_instrucciones_recuperacion.md` con el protocolo de recuperación paso a paso.
- Genera `_paquete.json` con metadata del paquete (chat_id, fecha, totales).
- Guarda el `.zip` en `download/` o en la carpeta indicada.
- **Tests auto:** empaquetado, generación de instrucciones, generación de metadata, casos edge (sin archivos, sin metadata).

### Milestone F11 — Importador de contexto
- Crear `context/importer.py` (atómico standalone con auto-tests).
- Busca archivos `contexto_exportado_*.zip` en `download/` o carpeta indicada.
- Descomprime el paquete en `/home/z/my-project/contexto_recuperacion/`.
- Lee `_instrucciones_recuperacion.md` y devuelve el protocolo de recuperación.
- Verifica que los archivos están completos.
- **Tests auto:** descompresión, verificación de integridad, casos edge (paquete corrupto, sin paquete).

### Milestone F12 — Integración en pipeline y worklog
- Modificar `pipeline.py`: añadir `export_context()` y `import_context()`.
- Modificar `worklog_template.md` (repo estrategia): documentar exportación/importación en el Paso 2b.
- **Tests:** integración de exportación/importación en el flujo E2E.

---

## Orden de ejecución

F1 → F2 → F3 → F4 → F5 → F6 → F7 → F8 → F9 → F10 → F11 → F12

---

## Cobertura de los cambios de la spec v3.4

| Cambio spec v3.4 | Milestone |
|---|---|
| 1. Crear `client/web_reader.py` | F1 |
| 2. Modificar `processing/exchange_builder.py` | F2 |
| 3. Crear `processing/intention_classifier.py` | F3 |
| 4. Modificar `processing/classifier.py` (Capa 2) | F4 |
| 5. Crear `subagents/discriminator_subagent.py` | F5 |
| 6. Modificar `process/recovery_cycle.py` (Capa 3) | F6 |
| 7. Modificar `generation/estado_generator.py` | F7 |
| 8. Modificar `config.py` | F8 |
| 9. Crear `context/exporter.py` | F10 |
| 10. Crear `context/importer.py` | F11 |
| 11. Modificar `pipeline.py` | F12 |
| 12. Modificar `worklog_template.md` | F12 |

**Cobertura total:** 12/12 cambios cubiertos.

---

## Pendiente de validación

Espero tu validación para pasar a la fase de EJECUCIÓN del plan v3.4.

--- fin de PLAN v3.4 (plan_refactorizacion_v3.4.md) ---


<!-- ============================================================ -->
# SECCIÓN: PLAN v3.5 (plan_refactorizacion_v3.5.md)
<!-- Archivo original: plan_refactorizacion_v3.5.md -->
<!-- ============================================================ -->

# Plan v3.5 — Implementación de indexación de documentos adjuntos mediante subagentes

**Versión:** 3.5
**Fecha:** 2026-09-05
**Autor:** Agente CZAI
**Estado:** Pendiente de validación por el Director.
**Spec objetivo:** v3.5 (entregada en `/home/z/my-project/download/spec_recuperacion_contexto_v3.5.md`).

---

## Principios de implementación

1. **OOP estricto:** clases con responsabilidad única, interfaces claras, type hints, docstrings.
2. **Reutilización antes que duplicación:** si una clase existente hace algo similar, se refactoriza para compartir interfaz, no se crea nueva.
3. **Scripts atómicos standalone:** autocontenidos con bloque `if __name__ == "__main__"` con auto-tests.
4. **Cambios quirúrgicos:** sobre el código existente del repo, solo se modifica lo que cambia.
5. **Compatibilidad Windows:** auto-ejecutables sin configuración previa (stub `sys.path` ya corregido en v3.4).

---

## Archivos nuevos

| Archivo | Responsabilidad |
|---|---|
| `client/attachment_client.py` | Cliente de descarga de attachments desde la API de Z.ai. |
| `processing/attachment_detector.py` | Detector de attachments en mensajes extraídos. |
| `processing/content_delegator.py` | Clase base `ContentDelegator` + `DocumentDelegator`. |
| `subagents/documento_indexer_subagent.py` | Subagente que lee, clasifica y resume documentos. |

## Archivos a modificar

| Archivo | Cambio |
|---|---|
| `models.py` | Añadir modelo `Attachment`. |
| `config.py` | Añadir constantes de delegación (`DELEGATION_THRESHOLD_TOKENS`, `DELEGATION_CONTEXT_LIMIT_PCT`, `TRIVIAL_SIZE_TOKENS`, `DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS`). |
| `chat_client.py` | Nuevo método `extract_attachments()` para extraer attachments crudos del batch. |
| `exchange_builder.py` | Refactor `_process_external_links()` para usar `DocumentDelegator`. Quitar truncado 10K. |
| `subdivider.py` | Refactor `needs_subdivision()` para implementar interfaz `ContentDelegator`. |
| `subagents/__init__.py` | Exportar `DocumentoIndexerSubagent`. |
| `pipeline.py` | Añadir `index_document()`. |
| `recovery_cycle.py` | Integrar `AttachmentDetector` + `DocumentoIndexerSubagent`. |
| `generation/indice_generator.py` | Incluir sección "Documentos indexados". |
| `tests/run_all_tests.py` | Añadir 4 nuevos módulos atómicos a la Fase 1. |
| `tests/test_e2e_pipeline.py` | Añadir tests E2E para attachments. |

---

## Fases de ejecución (milestones)

### Milestone G1 — Modelo `Attachment` y constantes de configuración

**Modificar `models.py`:**
- Añadir clase `Attachment` (Pydantic BaseModel) con campos:
  - `file_id: str`
  - `filename: str`
  - `content_type: str`
  - `size: int` (bytes)
  - `url: str` (endpoint `/api/v1/files/{id}/content`)
  - `cdn_url: str` (URL del CDN, opcional)
  - `ref_msg_id: str` (ID del mensaje del Director que adjuntó el archivo)
  - `media: str` (tipo: "doc", "file", "image")
  - `status: str` (estado: "uploaded", "indexed", "error")
  - `created_at: float` (timestamp)
- Propiedades calculadas:
  - `estimated_tokens` (size / 3.5 aproximado, o None si no es texto)
  - `is_pdf`, `is_docx`, `is_text`, `is_image` (basado en content_type)
  - `is_trivially_small` (tokens < `TRIVIAL_SIZE_TOKENS`)

**Modificar `config.py`:**
- `DELEGATION_THRESHOLD_TOKENS = 5000` (documentos >5K tokens se delegan)
- `DELEGATION_CONTEXT_LIMIT_PCT = 80` (si agente >80% ocupado, delega)
- `TRIVIAL_SIZE_TOKENS = 1000` (documentos <1K tokens se incorporan directo)
- `DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS = 500` (resumen breve que devuelve el subagente)
- `ATTACHMENTS_TEMP_DIR = WORKSPACE_ROOT / "download" / "uploads" / "temp"`
- `ATTACHMENTS_INDEXED_DIR = WORKSPACE_ROOT / "download" / "uploads" / "indexed"`

**Tests auto:** validar modelo `Attachment`, propiedades calculadas, constantes cargadas.

### Milestone G2 — `AttachmentClient` (descarga de archivos)

**Crear `client/attachment_client.py`:**
- Clase `AttachmentClient`:
  - `__init__(token: str, timeout: float = 60.0)`: cliente httpx con cookie JWT.
  - `download(attachment: Attachment) -> bytes`: descarga el contenido binario desde `/api/v1/files/{id}/content`.
  - `download_to_file(attachment: Attachment, dest_path: Path) -> Path`: descarga y guarda en disco.
  - `download_many(attachments: list[Attachment]) -> dict[str, bytes]`: descarga en lote.
- Manejo de errores: `AttachmentDownloadError` (404, 401, timeout, tamaño >límite).
- Detección de tipo por magic number (no confiar solo en content_type del server).

**Tests auto:**
- Mock de httpx para simular descarga exitosa.
- Casos edge: file_id inválido (404), token expirado (401), timeout, archivo corrupto.
- Detección de magic number: PDF (`%PDF`), DOCX (ZIP con `word/`), texto plano.
- `download_to_file` escribe en disco correctamente.

### Milestone G3 — `AttachmentDetector` (detección en mensajes)

**Crear `processing/attachment_detector.py`:**
- Clase `AttachmentDetector`:
  - `detect_in_raw_messages(raw_messages: dict) -> list[Attachment]`: recorre el JSON crudo del batch endpoint y extrae attachments del campo `files`.
  - `detect_in_messages(messages: list[Message]) -> dict[int, list[Attachment]]`: mapea cada mensaje procesado a sus attachments (por `ref_user_msg_id`).
  - `filter_by_type(attachments, media_type: str) -> list[Attachment]`: filtra por tipo (doc, file, image).
  - `deduplicate(attachments) -> list[Attachment]`: elimina duplicados por `file_id`.
- Mapeo `file.raw` → `Attachment` (Pydantic).

**Tests auto:**
- Mensaje sin attachments → lista vacía.
- Mensaje con 1 attachment → detecta correctamente.
- Mensaje con múltiples attachments → detecta todos.
- Deduplicación por `file_id`.
- Filtrado por tipo (`media` field).

### Milestone G4 — `ContentDelegator` (clase base + `DocumentDelegator`)

**Crear `processing/content_delegator.py`:**
- Clase abstracta `ContentDelegator`:
  - `should_delegate(content_size_tokens: int, agent_context_available_pct: float, director_override: Optional[str] = None) -> bool`
  - Método `_parse_override(director_override: str) -> Optional[bool]` que interpreta frases del Director ("lee completo", "no leas", etc.).
- Clase concreta `DocumentDelegator(ContentDelegator)`:
  - Usa constantes de `config.py` (`DELEGATION_THRESHOLD_TOKENS`, etc.).
  - Devuelve `True` (delegar) si: tamaño > umbral Y no hay override.
  - Devuelve `False` (leer directo) si: override del Director dice "lee completo" O tamaño < trivial.
  - Devuelve `False` si: contexto del agente > 80% Y no override.

**Refactorizar `subdivider.py`:**
- `Subdivider.needs_subdivision()` refactorizado para implementar `ContentDelegator` (sin romper API existente).
- Añadir método `should_delegate()` que llama a `needs_subdivision()` internamente.

**Tests auto:**
- Delegación automática: documento grande → True, pequeño → False.
- Override del Director: "lee completo" → False siempre.
- Override del Director: "no leas" → True siempre (pero marca como ignorado).
- Contexto del agente: 90% ocupado → True aunque el documento sea pequeño.
- `Subdivider` refactorizado sigue pasando sus tests existentes.

### Milestone G5 — `DocumentoIndexerSubagent` (subagente efímero)

**Crear `subagents/documento_indexer_subagent.py`:**
- Dataclass `DocumentoIndexResult`:
  - `attachment_id: str`
  - `filename: str`
  - `resumen_breve: str` (≤500 chars)
  - `temas_detectados: list[ThemeSection]`
  - `archivo_indexado_path: Path` (dónde quedó guardado para futuras consultas)
  - `success: bool`
  - `error: str = ""`
- Dataclass `ThemeSection`:
  - `tema: str`
  - `descripcion: str`
  - `secciones: list[str]` (referencias a secciones del documento)
- Clase `DocumentoIndexerSubagent`:
  - `__init__(launcher: SubagentLauncher, attachment_client: AttachmentClient, max_resumen_chars: int = 500)`.
  - `run(attachment: Attachment) -> DocumentoIndexResult`:
    1. Descarga el archivo con `AttachmentClient`.
    2. Lo guarda en `ATTACHMENTS_TEMP_DIR`.
    3. Construye prompt para el subagente: "Lee este archivo en {ruta}, clasifica por temas, genera un resumen de {max_resumen_chars} chars".
    4. Lanza subagente con `SubagentLauncher.launch()`.
    5. Parsea respuesta del subagente (formato estructurado similar a `DiscriminatorSubagent`).
    6. Mueve archivo de `temp/` a `indexed/`.
    7. Devuelve `DocumentoIndexResult`.

**Tests auto:**
- Mock invoker que devuelve clasificación estructurada → parsea correctamente.
- Casos edge: archivo no descargable, subagente que falla, respuesta mal formada.
- Validación: resumen ≤ max_chars, todos los temas tienen descripción.
- Archivo movido correctamente de `temp/` a `indexed/`.

### Milestone G6 — Refactor de `exchange_builder.py` (links externos + attachments unificados)

**Modificar `exchange_builder.py`:**
- Refactor `_process_external_links()` → `_process_external_content()` que maneja tanto URLs como attachments.
- Para cada URL o attachment detectado:
  1. Estimar tokens del contenido.
  2. Llamar `DocumentDelegator.should_delegate()`.
  3. Si delega: lanzar `DocumentoIndexerSubagent` (para attachments) o `WebReader+Subagente` (para URLs).
  4. Si no delega: leer directamente con `WebReader` (URLs) o `AttachmentClient` (attachments).
- **Quitar el truncado a 10K chars** (`content.content[:10000]`). El `Subdivider` se encarga de partir contenido grande.

**Tests auto:**
- URL pequeña → leída directamente (sin subagente).
- URL grande → delegada al subagente.
- Attachment pequeño → leído directamente.
- Attachment grande → delegado al subagente.
- Override del Director "lee completo" → siempre lee directo.
- Sin truncado a 10K (contenido completo en el intercambio).

### Milestone G7 — Integración en `recovery_cycle.py`

**Modificar `recovery_cycle.py`:**
- En `run()`, después de `extract_all()`:
  1. Extraer attachments crudos del batch endpoint con `ChatClient.extract_attachments()`.
  2. Detectar attachments con `AttachmentDetector`.
  3. Para cada attachment, decidir delegación con `DocumentDelegator`.
  4. Lanzar `DocumentoIndexerSubagent` para los delegados.
  5. Crear intercambios virtuales con los resúmenes (no con el contenido completo).
- Añadir campo `attachments_indexados: list[DocumentoIndexResult]` a `RecoveryCycleResult`.

**Modificar `chat_client.py`:**
- Nuevo método `extract_attachments(chat_id, message_ids) -> list[Attachment]`:
  - Llama al batch endpoint.
  - Recorre el JSON crudo buscando campo `files`.
  - Construye objetos `Attachment`.

**Tests auto:**
- RecoveryCycle con attachments → se indexan correctamente.
- `attachments_indexados` en `RecoveryCycleResult` se llena.
- El agente principal no consume tokens del PDF en su contexto.

### Milestone G8 — `IndiceGenerator` con sección de documentos indexados

**Modificar `generation/indice_generator.py`:**
- `generate()` acepta parámetro nuevo `attachments_indexados: list[DocumentoIndexResult]`.
- Añade sección "## Documentos indexados" al `01_indice_recuperacion.md`:
  - Tabla: `| Documento | Temas | Resumen | Ruta |`
  - Cada documento indexado se lista con sus temas y la ruta donde está guardado.

**Tests auto:**
- Índice generado con 0 documentos → sección omitida.
- Índice generado con 3 documentos → tabla con 3 filas.
- Formato markdown correcto.

### Milestone G9 — `pipeline.py` con `index_document()`

**Modificar `pipeline.py`:**
- Añadir función `index_document(chat_id, file_id, jwt, force_direct: bool = False) -> DocumentoIndexResult`:
  - Construye un `Attachment` a partir de `file_id` (consulta metadata con `AttachmentClient`).
  - Llama a `DocumentoIndexerSubagent.run()`.
  - Devuelve el resultado.
- Usable en tiempo real (sin necesidad de activar la recuperación completa).

**Tests auto:**
- `index_document` disponible y con firma correcta.
- `force_direct=True` omite la delegación.

### Milestone G10 — Tests E2E

**Modificar `tests/test_e2e_pipeline.py`:**
- `test_e2e_v35_attachment_detection`: simula batch endpoint con attachments, verifica que `AttachmentDetector` los encuentra.
- `test_e2e_v35_attachment_delegation_large`: documento >5K tokens → se delega al subagente.
- `test_e2e_v35_attachment_direct_small`: documento <1K tokens → se lee directamente.
- `test_e2e_v35_attachment_override`: "lee completo" → se lee directamente sin subagente.
- `test_e2e_v35_indice_with_documents`: índice generado incluye sección de documentos indexados.
- `test_e2e_v35_pipeline_real_pdf`: usa el PDF real `CZAI-01.pdf` del chat de prueba para validar el flujo completo.

**Tests de integración:**
- `tests/test_attachment_flow.py` (nuevo): test aislado del flujo completo de un attachment desde detección hasta indexación.

### Milestone G11 — Actualizar `run_all_tests.py` y documentación

**Modificar `tests/run_all_tests.py`:**
- Añadir 4 nuevos módulos atómicos a la Fase 1:
  - `client/attachment_client.py`
  - `processing/attachment_detector.py`
  - `processing/content_delegator.py`
  - `subagents/documento_indexer_subagent.py`

**Documentación:**
- Actualizar `estrategia/worklog_template.md` con el Paso 2c: "Indexación de documentos adjuntos".
- Actualizar `download/LEEME_INSTALACION.md` con las nuevas funciones.

### Milestone G12 — Refactor de `Subdivider` para implementar `ContentDelegator`

**Modificar `processing/subdivider.py`:**
- `Subdivider` hereda de `ContentDelegator`.
- `needs_subdivision()` se mantiene (compatibilidad hacia atrás) pero internamente llama a `should_delegate()`.
- Nuevo método `should_delegate()` que implementa la interfaz común.

**Tests auto:**
- `Subdivider.should_delegate()` funciona igual que `needs_subdivision()` para los casos existentes.
- Tests existentes siguen pasando sin cambios.

---

## Orden de ejecución

```
G1 (models + config)
    ↓
G2 (AttachmentClient)  ←── G3 (AttachmentDetector)  [paralelizables]
    ↓                          ↓
G4 (ContentDelegator) ────────┘
    ↓
G5 (DocumentoIndexerSubagent)
    ↓
G6 (refactor exchange_builder)
    ↓
G7 (recovery_cycle + chat_client)
    ↓
G8 (IndiceGenerator)
    ↓
G9 (pipeline.index_document)
    ↓
G10 (tests E2E)
    ↓
G11 (run_all_tests + docs)
    ↓
G12 (refactor Subdivider, último para no romper nada)
```

---

## Cobertura de los cambios de la spec v3.5

| Cambio spec v3.5 | Milestone |
|---|---|
| Modelo `Attachment` | G1 |
| Constantes de delegación en `config.py` | G1 |
| `AttachmentClient` (descarga) | G2 |
| `AttachmentDetector` (detección) | G3 |
| `ContentDelegator` + `DocumentDelegator` | G4 |
| `DocumentoIndexerSubagent` (subagente) | G5 |
| Refactor `exchange_builder` (links + attachments unificados) | G6 |
| Integración en `recovery_cycle` + `chat_client` | G7 |
| `IndiceGenerator` con documentos indexados | G8 |
| `pipeline.index_document()` | G9 |
| Tests E2E | G10 |
| `run_all_tests` + docs | G11 |
| Refactor `Subdivider` para implementar `ContentDelegator` | G12 |

**Cobertura total:** 12/12 cambios cubiertos.

---

## Pendiente de validación

Espero tu validación para pasar a la fase de EJECUCIÓN del plan v3.5.

--- fin de PLAN v3.5 (plan_refactorizacion_v3.5.md) ---


<!-- ============================================================ -->
# SECCIÓN: PLAN v3.6 (plan_refactorizacion_v3.6.md)
<!-- Archivo original: plan_refactorizacion_v3.6.md -->
<!-- ============================================================ -->

# Plan v3.6 — Implementación: JWT automático + Subagentes paralelos para documentos grandes

**Versión:** 3.6
**Fecha:** 2026-09-06
**Autor:** Agente CZAI
**Estado:** Pendiente de validación por el Director.
**Spec objetivo:** v3.6 (entregada en `/home/z/my-project/download/spec_recuperacion_contexto_v3.6.md`).

---

## Principios de implementación

1. **OOP estricto:** clases con responsabilidad única, interfaces claras, type hints, docstrings.
2. **Reutilización antes que duplicación:** refactorizar `SubagentLauncher` para soportar paralelismo genérico.
3. **Scripts atómicos standalone:** autocontenibles con auto-tests en `__main__`.
4. **Cambios quirúrgicos:** solo se modifica lo que cambia.
5. **Compatibilidad Windows/Linux:** todos los paths usan `pathlib.Path`.

---

## Archivos nuevos

| Archivo | Responsabilidad |
|---|---|
| `scripts/czai-jwt-bridge.bat` | Script .bat que el Director ejecuta con doble click |
| `scripts/jwt_bridge.ps1` | Script PowerShell que el .bat invoca |
| `client/credential_manager.py` | Gestiona el JWT: pide si falta, valida, persiste |
| `client/jwt_bridge_server.py` | Mini HTTP server temporal (3 endpoints) |
| `processing/divisor.py` | Clase base `Divisor` + `DocumentoDivisor` |
| `processing/conciliador.py` | Clase base `Conciliador` + `DocumentoConciliador` |
| `subagents/divisor_subagent.py` | Subagente N1 (divide + lanza N2) |
| `subagents/conciliador_subagent.py` | Subagente N3 (consolida índices) |

## Archivos a modificar

| Archivo | Cambio |
|---|---|
| `models.py` | Añadir `Porcion`, `IndiceParcial`, `IndiceConsolidado` |
| `config.py` | Añadir constantes de particionado y límites paralelos |
| `subagents/launcher.py` | Añadir `launch_parallel()` con ThreadPoolExecutor |
| `subagents/documento_indexer_subagent.py` | Añadir `run_3_levels()` |
| `subagents/__init__.py` | Exportar nuevas clases |
| `pipeline.py` | Añadir `index_document_large()` |
| `recovery_cycle.py` | Elegir entre subagente único o 3 niveles según tamaño |
| `estrategia/worklog_template.md` | Actualizar Paso 2c |
| `tests/run_all_tests.py` | Añadir nuevos módulos atómicos |
| `tests/test_v36_e2e.py` | Tests E2E nuevos |

---

## Fases de ejecución (milestones)

### Milestone H1 — Modelos y constantes

**Modificar `models.py`:**
- Clase `Porcion` (Pydantic BaseModel):
  - `id: int` (índice de la porción, 1-based)
  - `contenido_path: Path` (ruta del archivo temporal con la porción)
  - `tokens_estimados: int`
  - `paginas: tuple[int, int]` (página inicio, página fin) — solo para PDFs
- Clase `IndiceParcial` (Pydantic BaseModel):
  - `porcion_id: int`
  - `temas: list[ThemeSection]`
  - `resumen_parcial: str`
- Clase `IndiceConsolidado` (Pydantic BaseModel):
  - `temas_consolidados: list[ThemeSection]`
  - `resumen_final: str`
  - `indices_parciales: list[IndiceParcial]`

**Modificar `config.py`:**
```python
PARTITION_THRESHOLD_TOKENS = 50000
MAX_TOKENS_POR_SUBAGENTE_N2 = 30000
MAX_SUBAGENTES_LECTURA_ARCHIVOS = 5
MAX_SUBAGENTES_BUSQUEDA_PUNTUAL = 8
MAX_SUBAGENTES_CLASIFICACION_PROFUNDA = 3
MAX_SUBAGENTES_N2_PARALELOS = 3
JWT_BRIDGE_SERVER_PORT = 8086
JWT_BRIDGE_SERVER_HOST = "0.0.0.0"
```

**Tests auto:** validar modelos, constantes cargadas.

---

### Milestone H2 — `SubagentLauncher.launch_parallel()` (genérico)

**Modificar `subagents/launcher.py`:**
- Añadir método `launch_parallel(requests: list[SubagentRequest], max_workers: int = 3) -> list[SubagentResponse]`.
- Usa `concurrent.futures.ThreadPoolExecutor` para invocar el Task en paralelo.
- Cada Task se ejecuta en un thread independiente.
- `max_workers` limita cuántos Tasks corren simultáneamente.
- Devuelve las respuestas en el mismo orden que las requests.

**Tests auto:**
- 3 requests en paralelo con mock invoker → 3 respuestas.
- 5 requests con max_workers=3 → se procesan en 2 lotes (3 + 2).
- Invoker que falla → error capturado en esa response, otras responses OK.
- Orden de respuestas preservado.

---

### Milestone H3 — `Divisor` (clase base + `DocumentoDivisor`)

**Crear `processing/divisor.py`:**

```python
class Divisor(ABC):
    @abstractmethod
    def particionar(self, contenido, max_tokens_por_porcion) -> list[Porcion]:
        ...

    def lanzar_subagentes(
        self,
        porciones: list[Porcion],
        launcher: SubagentLauncher,
        max_paralelos: int,
        prompt_builder: callable,
    ) -> list[SubagentResponse]:
        """Lanza un subagente por cada porción, en paralelo."""
        requests = [
            SubagentRequest(
                prompt=prompt_builder(p),
                files_to_read=[str(p.contenido_path)],
                description=f"Procesar porción {p.id}",
            )
            for p in porciones
        ]
        return launcher.launch_parallel(requests, max_workers=max_paralelos)

class DocumentoDivisor(Divisor):
    def particionar(self, documento_path: Path, max_tokens: int) -> list[Porcion]:
        """Particiona un PDF por páginas hasta alcanzar max_tokens por porción."""
        # Usa pdfplumber para contar páginas y estimar tokens
        # Agrupa páginas en porciones que no superen max_tokens
```

**Tests auto:**
- Particionar PDF de 200 páginas con max_tokens=30K → ~5-7 porciones.
- Particionar PDF de 1 página → 1 porción.
- Particionar archivo vacío → lista vacía.
- Particionar por tamaño exacto → sin desbordamiento.

---

### Milestone H4 — `Conciliador` (clase base + `DocumentoConciliador`)

**Crear `processing/conciliador.py`:**

```python
class Conciliador(ABC):
    @abstractmethod
    def conciliar(self, respuestas: list[SubagentResponse]) -> IndiceConsolidado:
        ...

    @abstractmethod
    def producir_resumen_final(self, consolidado: IndiceConsolidado) -> str:
        ...

class DocumentoConciliador(Conciliador):
    def conciliar(self, respuestas: list[SubagentResponse]) -> IndiceConsolidado:
        """Combina índices parciales de N2 en un índice consolidado."""
        # Parsea cada respuesta (formato TEMA/DESCRIPCION/SECCIONES)
        # Deduplica temas similares (ej: "auth_jwt" y "autenticacion_jwt" → fusiona)
        # Reubica temas en categorías coherentes
        # Genera IndiceConsolidado

    def producir_resumen_final(self, consolidado: IndiceConsolidado) -> str:
        """Genera resumen breve (≤500 chars) del documento completo."""
        # Sintetiza los temas consolidados en un resumen coherente
```

**Tests auto:**
- 3 respuestas con 2 temas cada una → consolidado con temas únicos.
- Deduplicación: "auth_jwt" y "autenticacion_jwt" → 1 tema fusionado.
- Resumen final ≤500 chars.
- Caso edge: 1 sola respuesta (sin consolidación real).

---

### Milestone H5 — `DivisorSubagent` (Nivel 1)

**Crear `subagents/divisor_subagent.py`:**

```python
class DivisorSubagent:
    """Subagente Nivel 1: divide documento + lanza N2 en paralelo."""

    def __init__(self, launcher, divisor: DocumentoDivisor, max_paralelos: int):
        self._launcher = launcher
        self._divisor = divisor
        self._max_paralelos = max_paralelos

    def run(self, attachment: Attachment, documento_path: Path) -> list[IndiceParcial]:
        # 1. Particionar documento
        porciones = self._divisor.particionar(documento_path, MAX_TOKENS_POR_SUBAGENTE_N2)

        # 2. Construir prompt para cada N2
        prompt_builder = self._build_prompt_n2(attachment)

        # 3. Lanzar N2 en paralelo (lotes de max_paralelos)
        responses = self._divisor.lanzar_subagentes(
            porciones, self._launcher, self._max_paralelos, prompt_builder
        )

        # 4. Parsear respuestas en IndiceParcial
        indices_parciales = [self._parse_response(r, p) for r, p in zip(responses, porciones)]

        return indices_parciales
```

**Tests auto:**
- 3 porciones, mock invoker devuelve 3 respuestas → 3 índices parciales.
- 5 porciones con max_paralelos=3 → se procesan en 2 lotes (3+2).
- Error en 1 N2 → esa respuesta es error, otras OK.

---

### Milestone H6 — `ConciliadorSubagent` (Nivel 3)

**Crear `subagents/conciliador_subagent.py`:**

```python
class ConciliadorSubagent:
    """Subagente Nivel 3: consolida índices parciales de N2."""

    def __init__(self, launcher, conciliador: DocumentoConciliador):
        self._launcher = launcher
        self._conciliador = conciliador

    def run(self, indices_parciales: list[IndiceParcial], attachment: Attachment) -> DocumentoIndexResult:
        # 1. Construir prompt con todos los índices parciales
        prompt = self._build_prompt_n3(indices_parciales, attachment)

        # 2. Lanzar subagente N3
        response = self._launcher.launch(
            prompt=prompt,
            files_to_read=[],
            description="Consolidar índices de documento grande",
        )

        # 3. Parsear respuesta consolidada
        consolidado = self._conciliador.conciliar([response])

        # 4. Generar resumen final
        resumen_final = self._conciliador.producir_resumen_final(consolidado)

        return DocumentoIndexResult(
            attachment_id=attachment.file_id,
            filename=attachment.filename,
            resumen_breve=resumen_final,
            temas_detectados=consolidado.temas_consolidados,
            archivo_indexado_path=...,
            success=True,
        )
```

**Tests auto:**
- 3 índices parciales → N3 consolida en 1 índice.
- Deduplicación de temas entre porciones.
- Resumen final coherente (≤500 chars).
- Error en N3 → DocumentoIndexResult con success=False.

---

### Milestone H7 — `DocumentoIndexerSubagent.run_3_levels()`

**Modificar `subagents/documento_indexer_subagent.py`:**

```python
class DocumentoIndexerSubagent:
    # ... métodos existentes ...

    def run_3_levels(self, attachment: Attachment) -> DocumentoIndexResult:
        """Flujo de 3 niveles para documentos >50K tokens."""
        # 1. Descargar y guardar documento
        documento_path = self._download_and_save(attachment)

        # 2. Lanzar N1 (DivisorSubagent)
        divisor = DocumentoDivisor()
        n1 = DivisorSubagent(
            launcher=self._launcher,
            divisor=divisor,
            max_paralelos=MAX_SUBAGENTES_N2_PARALELOS,
        )
        indices_parciales = n1.run(attachment, documento_path)

        # 3. Lanzar N3 (ConciliadorSubagent)
        conciliador = DocumentoConciliador()
        n3 = ConciliadorSubagent(
            launcher=self._launcher,
            conciliador=conciliador,
        )
        result = n3.run(indices_parciales, attachment)

        # 4. Mover documento a indexed/
        self._move_to_indexed(documento_path)

        return result
```

**Tests auto:**
- Documento de 200 páginas → run_3_levels() procesa en lotes.
- Documento de 1 página → run() (subagente único, no 3 niveles).
- Error en N1 → DocumentoIndexResult con success=False.
- Error en N3 → DocumentoIndexResult con success=False.

---

### Milestone H8 — `RecoveryCycle` elige entre subagente único o 3 niveles

**Modificar `recovery_cycle.py`:**

```python
def _index_attachments(self, raw_messages):
    # ... detección existente ...

    for att in attachments:
        estimated_tokens = int(att.estimated_tokens)

        # Decidir flujo según tamaño
        if estimated_tokens > PARTITION_THRESHOLD_TOKENS:
            # Documento grande → 3 niveles
            result = indexer.run_3_levels(att)
        else:
            # Documento mediano → subagente único (flujo actual)
            result = indexer.run(att)

        results.append(result)
```

**Tests auto:**
- Attachment de 165K tokens → usa run_3_levels().
- Attachment de 5K tokens → usa run().
- Attachment de 500 tokens → lectura directa (sin subagente).

---

### Milestone H9 — `pipeline.index_document_large()`

**Modificar `pipeline.py`:**

```python
def index_document_large(
    file_id: str,
    jwt: str,
    filename: str = "",
    content_type: str = "application/pdf",
    size: int = 0,
) -> Optional[DocumentoIndexResult]:
    """Indexa un documento grande (>50K tokens) usando 3 niveles de subagentes."""
    # Construye attachment
    # Si estimated_tokens > PARTITION_THRESHOLD_TOKENS:
    #   Usa run_3_levels()
    # Else:
    #   Fallback a index_document() (subagente único)
```

**Tests auto:**
- Documento >50K → usa 3 niveles.
- Documento <50K → fallback a subagente único.
- force_direct=True → lectura directa sin subagente.

---

### Milestone H10 — `CredentialManager` + `JwtBridgeServer`

**Crear `client/credential_manager.py`:**

```python
class CredentialManager:
    """Gestiona el JWT del Director."""

    def __init__(self, credentials_path: Path = None):
        self._path = credentials_path or Path.home() / ".czai" / "credentials.json"

    def get_jwt(self) -> Optional[str]:
        """Lee el JWT persistido. Devuelve None si no existe."""
        if not self._path.exists():
            return None
        data = json.loads(self._path.read_text())
        return data.get("token")

    def save_jwt(self, jwt: str, email: str = "") -> None:
        """Persiste el JWT con permisos 0600."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"token": jwt, "email": email}))
        self._path.chmod(0o600)

    def is_valid(self, jwt: str) -> bool:
        """Verifica el JWT contra /api/v1/auths/."""
        # Hace GET /api/v1/auths/ con cookie token=jwt
        # Si responde role=user → válido
        # Si responde role=guest o 401 → inválido

    def needs_jwt(self) -> bool:
        """True si no hay JWT o el existente es inválido."""
        jwt = self.get_jwt()
        if not jwt:
            return True
        return not self.is_valid(jwt)
```

**Crear `client/jwt_bridge_server.py`:**

```python
class JwtBridgeServer:
    """Mini HTTP server temporal para recibir JWT del .bat."""

    def __init__(self, port: int = JWT_BRIDGE_SERVER_PORT, credential_manager: CredentialManager = None):
        self._port = port
        self._cm = credential_manager or CredentialManager()
        self._server = None
        self._thread = None

    def start(self) -> None:
        """Levanta el server en un thread daemon."""
        from http.server import HTTPServer, BaseHTTPRequestHandler

        class Handler(BaseHTTPRequestHandler):
            def do_GET(s):
                if s.path == "/jwt-status":
                    needs = self._cm.needs_jwt()
                    s.send_json({"needs_jwt": needs})
                elif s.path == "/czai-jwt-bridge.bat":
                    s.serve_file("scripts/czai-jwt-bridge.bat")
                else:
                    s.send_404()

            def do_POST(s):
                if s.path == "/recibir-jwt":
                    body = json.loads(s.read_body())
                    self._cm.save_jwt(body["token"], body.get("email", ""))
                    s.send_json({"success": True})
                    # Apagar server después de recibir
                    threading.Thread(target=self.stop, daemon=True).start()

        self._server = HTTPServer((JWT_BRIDGE_SERVER_HOST, self._port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
```

**Tests auto:**
- `CredentialManager.get_jwt()` sin archivo → None.
- `CredentialManager.save_jwt()` + `get_jwt()` → recupera correctamente.
- `CredentialManager.is_valid()` con mock httpx → valida correctamente.
- `JwtBridgeServer.start()` + GET /jwt-status → responde JSON.
- `JwtBridgeServer` + POST /recibir-jwt → persiste y apaga.

---

### Milestone H11 — Script `.bat` + PowerShell

**Crear `scripts/czai-jwt-bridge.bat`:**

```batch
@echo off
REM CZAI JWT Bridge - Obtiene el JWT del Director y lo envía al sandbox
REM Uso: doble click. Se cierra solo.

REM Configuración (el agente reemplaza estas variables al servir el archivo)
set SANDBOX_URL=%1
if "%SANDBOX_URL%"=="" set SANDBOX_URL=https://DEFAULT_SANDBOX_URL

REM Ejecutar script PowerShell
powershell -ExecutionPolicy Bypass -File "%~dp0jwt_bridge.ps1" -SandboxUrl "%SANDBOX_URL%"
```

**Crear `scripts/jwt_bridge.ps1`:**

```powershell
param(
    [string]$SandboxUrl = "https://DEFAULT_SANDBOX_URL"
)

# 1. Verificar que el agente necesita JWT
$status = Invoke-RestMethod -Uri "$SandboxUrl/jwt-status" -Method GET
if (-not $status.needs_jwt) {
    Write-Host "El agente ya tiene JWT. No es necesario enviarlo."
    exit 0
}

# 2. Lanzar Edge con DevTools Protocol
$edgeProcess = Start-Process -FilePath "msedge.exe" -ArgumentList @(
    "--remote-debugging-port=9222",
    "https://chat.z.ai"
) -PassThru

Start-Sleep -Seconds 5

# 3. Conectarse al DevTools Protocol
$devtoolsUrl = "http://localhost:9222/json"
$tabs = Invoke-RestMethod -Uri $devtoolsUrl -Method GET
$chatTab = $tabs | Where-Object { $_.url -like "*chat.z.ai*" } | Select-Object -First 1

if (-not $chatTab) {
    Write-Host "Error: no se encontró pestaña de chat.z.ai"
    Stop-Process -Id $edgeProcess.Id -Force
    exit 1
}

# 4. Ejecutar fetch('/api/v1/auths/') vía WebSocket
$wsUrl = $chatTab.webSocketDebuggerUrl
# (conexión WebSocket y ejecución de JS - requiere módulo o implementación nativa)

# 5. Capturar JWT de la respuesta
$jwt = $response.token
$email = $response.email

# 6. Enviar JWT al sandbox
$body = @{ token = $jwt; email = $email } | ConvertTo-Json
$result = Invoke-RestMethod -Uri "$SandboxUrl/recibir-jwt" -Method POST -Body $body -ContentType "application/json"

if ($result.success) {
    Write-Host "JWT enviado al agente correctamente."
} else {
    Write-Host "Error enviando JWT."
}

# 7. Cerrar Edge
Stop-Process -Id $edgeProcess.Id -Force
```

**Tests:**
- El `.bat` se ejecuta sin errores (con mock de sandbox).
- El PowerShell detecta pestaña de chat.z.ai.
- El flujo completo envía el JWT correctamente.

---

### Milestone H12 — Integración en `recovery_cycle` + `pipeline`

**Modificar `recovery_cycle.py`:**

```python
def _ensure_jwt(self) -> str:
    """Obtiene el JWT del Director, pidiéndolo si no está disponible."""
    cm = CredentialManager()
    jwt = cm.get_jwt()

    if jwt and cm.is_valid(jwt):
        return jwt

    # JWT no disponible → iniciar JwtBridgeServer y pedir al Director
    server = JwtBridgeServer(credential_manager=cm)
    server.start()

    sandbox_url = f"https://[sandbox-host]:{JWT_BRIDGE_SERVER_PORT}"
    print(f"Descarga y ejecuta: {sandbox_url}/czai-jwt-bridge.bat")

    # Esperar a que el Director ejecute el .bat
    # (el server se apaga solo al recibir el JWT)
    # ... loop de espera con timeout ...

    jwt = cm.get_jwt()
    server.stop()
    return jwt
```

**Modificar `pipeline.py`:**
- `run()` y `index_document()` usan `_ensure_jwt()` si no se pasa JWT explícito.

**Tests auto:**
- `_ensure_jwt()` con JWT válido existente → lo devuelve sin pedir.
- `_ensure_jwt()` sin JWT → inicia server, simula recepción, devuelve JWT.

---

### Milestone H13 — Tests E2E

**Crear `tests/test_v36_e2e.py`:**

```python
def test_e2e_v36_jwt_bridge_flow():
    """Flujo completo del JWT bridge con mock."""
    # 1. CredentialManager sin JWT → needs_jwt=True
    # 2. JwtBridgeServer.start()
    # 3. Simular POST /recibir-jwt con JWT mock
    # 4. CredentialManager ahora tiene JWT
    # 5. needs_jwt=False

def test_e2e_v36_3_levels_small_doc():
    """Doc <50K → subagente único (no 3 niveles)."""

def test_e2e_v36_3_levels_large_doc():
    """Doc >50K → 3 niveles con mock invoker."""
    # 1. Crear PDF mock de 200 páginas
    # 2. DocumentoIndexerSubagent.run_3_levels()
    # 3. N1 divide en ~7 porciones
    # 4. N2×7 procesan en paralelo (lotes de 3)
    # 5. N3 consolida
    # 6. Resultado tiene resumen + temas

def test_e2e_v36_parallel_launch():
    """launch_parallel() lanza N subagentes en paralelo real."""
    # Verificar que el tiempo total es menor que secuencial
```

---

### Milestone H14 — Actualizar `run_all_tests.py` + documentación

**Modificar `tests/run_all_tests.py`:**
- Añadir 6 nuevos módulos atómicos a la Fase 1:
  - `client/credential_manager.py`
  - `client/jwt_bridge_server.py`
  - `processing/divisor.py`
  - `processing/conciliador.py`
  - `subagents/divisor_subagent.py`
  - `subagents/conciliador_subagent.py`

**Modificar `estrategia/worklog_template.md`:**
- Actualizar Paso 2c con instrucciones del `.bat`.

**Actualizar `download/MANUAL_CZAI_v3.5.md` → MANUAL_CZAI_v3.6.md`**

---

## Orden de ejecución

```
H1 (modelos + constantes)
    ↓
H2 (launch_parallel, genérico)  ←── H3 (Divisor)  ←── H4 (Conciliador)  [paralelizables]
    ↓                                   ↓                    ↓
H5 (DivisorSubagent N1) ────────────────┘                    │
    ↓                                                        │
H6 (ConciliadorSubagent N3) ─────────────────────────────────┘
    ↓
H7 (run_3_levels en DocumentoIndexerSubagent)
    ↓
H8 (recovery_cycle elige flujo según tamaño)
    ↓
H9 (pipeline.index_document_large)
    ↓
H10 (CredentialManager + JwtBridgeServer)
    ↓
H11 (scripts .bat + .ps1)
    ↓
H12 (integración _ensure_jwt en recovery_cycle + pipeline)
    ↓
H13 (tests E2E)
    ↓
H14 (run_all_tests + docs)
```

---

## Cobertura de los cambios de la spec v3.6

| Cambio spec v3.6 | Milestone |
|---|---|
| Modelo `Porcion`, `IndiceParcial`, `IndiceConsolidado` | H1 |
| Constantes de particionado y límites paralelos | H1 |
| `SubagentLauncher.launch_parallel()` | H2 |
| Clase base `Divisor` + `DocumentoDivisor` | H3 |
| Clase base `Conciliador` + `DocumentoConciliador` | H4 |
| `DivisorSubagent` (N1) | H5 |
| `ConciliadorSubagent` (N3) | H6 |
| `DocumentoIndexerSubagent.run_3_levels()` | H7 |
| `RecoveryCycle` elige flujo | H8 |
| `pipeline.index_document_large()` | H9 |
| `CredentialManager` | H10 |
| `JwtBridgeServer` | H10 |
| Script `.bat` + `.ps1` | H11 |
| Integración `_ensure_jwt` | H12 |
| Tests E2E | H13 |
| `run_all_tests` + docs | H14 |

**Cobertura total:** 14/14 cambios cubiertos.

---

## Pendiente de validación

Espero tu validación para pasar a la fase de EJECUCIÓN del plan v3.6.

--- fin de PLAN v3.6 (plan_refactorizacion_v3.6.md) ---

<!-- ============================================================ -->
<!-- Fin del documento consolidado -->
<!-- ============================================================ -->

## Notas finales

- Este documento fue generado automáticamente el 2025-01-09 consolidando las
  16 versiones históricas de spec y plan del proyecto CZAI.
- Cada sección contiene el contenido íntegro del archivo original, sin modificaciones.
- Los archivos originales fueron eliminados del repositorio `contexto_zai` para
  reducir el clutter, pero su contenido se preserva aquí.
- La versión actual y vigente es la **v3.6** (spec y plan).
- Para futuras versiones, se recomienda mantener un único archivo de spec y un
  único archivo de plan (sin versiones en el nombre), usando git history para
  el versionado.
