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