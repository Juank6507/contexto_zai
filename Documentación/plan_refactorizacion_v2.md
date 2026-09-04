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
