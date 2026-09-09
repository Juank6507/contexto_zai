# Historial de Planes — Sistema CZAI

**Proyecto:** Contexto Zai (CZAI)
**Fecha de consolidación:** 2025-01-09
**Total de versiones:** 6 planes
**Propósito:** Documento único que preserva todas las versiones históricas del
plan de implementación del sistema CZAI, para permitir eliminar los archivos
individuales del repositorio sin perder información.

---

## Índice de versiones

| # | Versión | Fecha | Archivo original | Líneas |
|---|---------|-------|------------------|--------|
| 1 | — | 2025-08-21 | plan_script_contexto_zai.md | 303 |
| 2 | 2.0 | 2026-09-04 | plan_refactorizacion_v2.md | 230 |
| 3 | 3.0 | — | plan_refactorizacion_v3.md | 196 |
| 4 | 3.4 | — | plan_refactorizacion_v3.4.md | 180 |
| 5 | 3.5 | 2026-09-05 | plan_refactorizacion_v3.5.md | 326 |
| 6 | 3.6 | 2026-09-06 | plan_refactorizacion_v3.6.md | 680 |

---

## Evolución resumida

- **Inicial** — Plan del script Python `contexto_zai.py` (CLI monolítico)
- **v2.0** — Refactorización CLI → Proceso Autónomo v3.2
- **v3.0** — Versionado de scripts con grafo de cambios reversible
- **v3.4** — Links externos, clasificación por capas, estado sin truncado, exportación/importación
- **v3.5** — Implementación de indexación de documentos adjuntos mediante subagentes
- **v3.6** — Implementación: JWT automático + Subagentes paralelos para documentos grandes (actual)

---

## Contenido completo de cada versión

A continuación se incluye el contenido íntegro de cada plan, separado por
marcadores claros. Cada sección comienza con un encabezado que indica la versión
y el archivo original.



<!-- ============================================================ -->
# SECCIÓN: PLAN inicial
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
--- fin de PLAN inicial ---


<!-- ============================================================ -->
# SECCIÓN: PLAN v2.0
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

--- fin de PLAN v2.0 ---


<!-- ============================================================ -->
# SECCIÓN: PLAN v3.0
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

--- fin de PLAN v3.0 ---


<!-- ============================================================ -->
# SECCIÓN: PLAN v3.4
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

--- fin de PLAN v3.4 ---


<!-- ============================================================ -->
# SECCIÓN: PLAN v3.5
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

--- fin de PLAN v3.5 ---


<!-- ============================================================ -->
# SECCIÓN: PLAN v3.6
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

--- fin de PLAN v3.6 ---

<!-- ============================================================ -->
<!-- Fin del documento de historial de planes -->
<!-- ============================================================ -->

## Notas finales

- Este documento fue generado el 2025-01-09 consolidando las 6 versiones
  históricas de plan del proyecto CZAI.
- Cada sección contiene el contenido íntegro del archivo original, sin modificaciones.
- Los archivos originales fueron eliminados del repositorio `contexto_zai` para
  reducir el clutter, pero su contenido se preserva aquí.
- La versión actual y vigente es la **v3.6**.
- Para futuras versiones, se recomienda mantener un único archivo de plan (sin
  versión en el nombre), usando git history para el versionado.
