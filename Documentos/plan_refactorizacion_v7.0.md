# Plan v7.0 — Implementación modular + abstracción + fixes

**Versión:** 7.0
**Fecha:** 2026-11-21
**Estado:** En curso.
**Spec referenciada:** `Documentos/spec_recuperacion_contexto_v7.0.md`.

## Mapeo fases → criterios de aceptación

| Fase | Criterios de la spec que cierra |
|---|---|
| F1 — Modularización arquitectónica | A1, A2, A3, A4, A5 |
| F2 — Restauración de la abstracción de plataforma | B1, B2, B3, B4, B5 |
| F3 — Refactorización de mini-servicios | B6 |
| F4 — Rectificación del bug 1 (comunicación daemon) | C1, C2, C3, C4 |
| F5 — Rectificación del bug 2 (subproceso archivos) | D1, D2, D3, D4, D5 |
| F6 — Cierre formal | E1, E2, E3, E4 |

## Orden de dependencia

F1 → F2 → F3 → F4 → F5 → F6.

- F1 va primero: todo lo demás se apoya en módulos separados.
- F2 depende de F1: las interfaces se inyectan en los módulos nuevos.
- F3 depende de F2: los mini-servicios usan las interfaces abstractas recién creadas.
- F4 depende de F3: el bug 1 toca el Subagent Proxy recién refactorizado.
- F5 depende de F4: el bug 2 necesita que la comunicación daemon-agente funcione.
- F6 cierra todo el ciclo.

## Detalle por fase

### F1 — Modularización arquitectónica

**Objetivo.** Separar los cuatro subprocesos reusables en módulos dedicados, como clases concretas, dentro del paquete `contexto_zai/`. El grafo de flujo interno de cada subproceso no cambia.

**Tareas.**
1. Leer `pipeline.py` completo y mapear boundaries de cada subproceso.
2. Crear `pipeline_cascada.py`: mover `CascadaAccesoLLM` y `_proxy_zai_disponible`, `_arrancar_worker_y_esperar`, `_enriquecer_con_proxy_zai`, `_escribir_artefactos_bloque`, `_post_bloque`, `_persistir_pending_task_en_disco`, `_actualizar_estado_daemon`.
3. Crear `pipeline_w3.py`: mover `_ciclo_w3`, `_validar_resumen_w3`, `_validar_resumen_critico_subagente`, `_llamar_cascada_llm`, `_enriquecer_bloques_con_fallback`, `_enriquecer_bloques_post_run`, `_descubrir_bloques_incompletos`, `_bloque_esta_completo`, `_auditar_y_completar`, `PROMPT_FUSIONADO_W1W2W3`.
4. Crear `pipeline_d7.py`: mover `_bucle_d7_completitud`, `_bucle_d7`, `_construir_pending_task_d7_corregido`, `_ejecutar_pending_tasks_obligatorias`.
5. Crear `pipeline_archivos.py`: mover `_generar_archivos_recuperacion` y `_consolidar_decisiones_llm`, `_regenerar_indice_tras_enriquecimiento`, `_normalizar_bloques_externos`.
6. Crear `pipeline_auditoria.py`: mover `AuditorWorkspace` y `ProgressMonitor`.
7. Reducir `pipeline.py` a: API pública (`ContextoPipeline.run`, `ampliar_contexto`, `collect_responses`, `query_context`, `status`, `export_context`, `import_context`, `find_context_packages`, `index_document`, `index_document_large`, `recuperar_contexto_si_necesario`) + funciones de paso (auditar, generar_bloques, ejecutar_cascada, ejecutar_pending_task, ejecutar_subproceso_archivos, auditar_final, ejecutar_d7).
8. Actualizar imports en todos los archivos que referencian clases movidas.

**Verificación.** A1, A2, A3, A4, A5.

### F2 — Restauración de la abstracción de plataforma

**Objetivo.** Restaurar las interfaces abstractas de v5.0 con sus implementaciones concretas de Zai. Comportamiento real no cambia.

**Tareas.**
1. Crear `platforms/__init__.py` y `platforms/zai/__init__.py`.
2. Crear `platforms/interfaces.py` con `PlatformAuth`, `PlatformChat`, `PlatformLinks`, `PlatformLLM` (ABCs).
3. Crear `platforms/zai/zai_config.py` con valores concretos (URL, modelos GLM defaults).
4. Crear `platforms/zai/zai_auth.py` (hereda de `PlatformAuth`, envuelve `AuthClient`).
5. Crear `platforms/zai/zai_chat.py` (hereda de `PlatformChat`, envuelve `ChatClient`).
6. Crear `platforms/zai/zai_links.py` (hereda de `PlatformLinks`, envuelve `AttachmentClient`).
7. Crear `platforms/zai/zai_llm.py` (hereda de `PlatformLLM`, envuelve el proxy Zai actual).
8. Renombrar en `config.py`: `PROXY_ZAI_URL` → `PROXY_LLM_URL`, `PROXY_ZAI_TIMEOUT` → `PROXY_LLM_TIMEOUT`. Mantener valores apuntando a la implementación Zai.
9. Modificar `pipeline_cascada.py` (la cascada) para recibir `PlatformLLM` por constructor en vez de tener modelo hardcoded.
10. Refactorizar `processing/message_extractor.py` para recibir `PlatformAuth` y `PlatformChat` en vez de importar `AuthClient` y `ChatClient` directos.
11. Actualizar llamadores: `ContextoPipeline.run` construye la implementación Zai por defecto y la inyecta.

**Verificación.** B1, B2, B3, B4, B5.

### F3 — Refactorización de mini-servicios

**Objetivo.** Worker Bun y Subagent Proxy usan la interfaz abstracta. Siguen trabajando como niveles de la cascada hasta que MB funcione.

**Tareas.**
1. Modificar `worker-cascade/index.ts`: leer URL y modelos desde env vars que apuntan a la implementación Zai por defecto. Documentar que cuando MB exista, esos env vars apuntan a la URL de MB.
2. Modificar `subagent-proxy/index.ts`: abstraer la llamada al SDK Zai detrás una interfaz `LLMProvider` interna en TypeScript. Por defecto usa `z-ai-web-dev-sdk` pero la interfaz permite inyectar otra implementación.
3. Los defaults siguen siendo Zai (URL `/api/zai-proxy/v1/chat/completions`, modelos `glm-4-plus` y `glm-4-flash`).
4. El Subagent Proxy también recibe en esta fase el circuit breaker y la clasificación de errores (tareas de F4 que conviene hacer acá para no tocar el archivo dos veces).

**Verificación.** B6 (más C2, C3 como bonus).

### F4 — Rectificación del bug 1 (comunicación daemon)

**Objetivo.** El daemon le avisa explícitamente al agente cuando hay tareas esperando, para que el agente lance los subagentes del Nivel 3.

**Tareas.**
1. Modificar `_handle_collect_responses` en `mini-services/pipeline-daemon/index.py`: cuando `_collect_responses_and_finalize` detecte bloques incompletos y publique pending_tasks, el handler devuelve en la respuesta HTTP un campo `needs_agent_action: true` con la lista completa de pending_tasks (cada una con `task_id`, `purpose`, `prompt`).
2. Garantizar que el contrato daemon → agente sea explícito: el campo `needs_agent_action` y la lista `pending_tasks` son la única fuente de verdad. Si el agente recibe `needs_agent_action: true`, tiene que lanzar las tareas y luego llamar `/collect-responses` de nuevo.
3. En `subagent-proxy/index.ts`: añadir `circuitBreaker` con contador global. Si llega a 5 fallos consecutivos, breaker abre, espera 60s antes de probar. Si la próxima llamada tiene éxito, breaker cierra.
4. Añadir `isRecoverable(error)` en TypeScript: 401, 403, `missing X-Token`, `Unauthorized` → no recuperable, mover a `_failed_tasks.json` sin reintentar. 429, 5xx, ETIMEDOUT, ECONNRESET, fetch failed → recuperable, reintentar.
5. En `processTask` del proxy Bun, siempre eliminar la tarea de `_pending_tasks.json` después de procesarla (éxito o fallo), para evitar el bucle infinito.

**Verificación.** C1, C2, C3, C4.

### F5 — Rectificación del bug 2 (subproceso archivos)

**Objetivo.** El subproceso de archivos completa los cuatro archivos correctamente, usando los generadores existentes por separado, sin bypassar la cascada.

**Tareas.**
1. Reescribir `pipeline_archivos.py` (subproceso de archivos) para usar los generadores existentes en vez de una sola llamada LLM:
   - `EstadoGenerator.generate()` para `00_estado_actual.md`.
   - `DecisionesGenerator.generate()` para `02_decisiones_clave.md`.
   - `IndiceGenerator.generate()` para `01_indice_recuperacion.md`.
   - `PlaceholderReplacer.reemplazar()` para `03_objetivo_proyecto.md`.
   - Cuando algún generador necesite LLM, delegar al W3 (que a su vez usa la cascada), no bypassar.
2. Modificar `RecogedorRespuestas.limpiar()` en `coordinador/recogedor_respuestas.py`: añadir filtro de exclusión para `_nombre.txt`, `_decisiones.txt`, `_temas.txt`, `_resumen.txt` y directorio `cache/`. Solo borrar respuestas de tasks (archivos `{task_id}.txt`).
3. Añadir fallback en el consolidador de decisiones (`_consolidar_decisiones_llm` ahora en `pipeline_archivos.py`): si los `_decisiones.txt` no existen, leer los `_responses/cache/*.json` que tengan campo `decisiones`.
4. Arreglar `estado_generator.py`:
   - `_FILE_PATH_PATTERN`: sacar backticks opcionales, no capturar comillas ni llaves.
   - `_ERROR_REGEX`: exigir contexto sintáctico (dos puntos seguidos de palabra, código de salida no cero).
   - `_strip_tool_calls`: cubrir JSON compacto sin espacios.
   - `_strip_bash_blocks`: cubrir texto natural con paths embebidos sin cercar.
   - `_build_g0_b`: revalidar síntesis tras enriquecimiento (llamar de nuevo después de P14).
5. Arreglar `indice_generator.py`: `_find_tokens_for_tema` calcula del tamaño real del bloque físico (`len(content) / 3500`), no devuelve `~67.0K` hardcoded.
6. Crear `generation/placeholder_replacer.py`: clase `PlaceholderReplacer` con método `reemplazar(workspace_dir)`. Lee `03_objetivo_proyecto.md`, lee el primer exchange del chat (del metadata o del primer bloque), decodifica el JWT del Director para obtener email, y reemplaza los cuatro placeholders.
7. Añadir handler en `coordinador/integrador_respuestas.py` para el patrón `enriquecer_bloque_NN`: cuando el task_id empiece con `enriquecer_`, despachar a `_integrar_enriquecer_bloque` que aplica el JSON de respuesta al bloque (resumen + nombre + decisiones + temas).
8. Ampliar `_FILE_PATH_PATTERN` en `estado_generator.py`: excluir caracteres especiales (`--`, `>`, `+`, `=`, `!`, `?`, `;`, `:`) de los paths capturados. (D6)
9. Modificar `PROMPT_FUSIONADO_W1W2W3` en `pipeline_w3.py`: añadir instrucción al LLM de que solo extraiga decisiones importantes del Director, no descripciones de actividades técnicas del agente. (D8)
10. Modificar `_consolidar_decisiones_llm` en `pipeline_archivos.py`: añadir paso de deduplicación que revise las decisiones anteriores para no duplicarlas entre bloques. (D7)
11. Modificar `EstadoGenerator._build_g0_a` en `estado_generator.py`: NO llamar a `_asegurar_objetivo_proyecto()` si el `03_objetivo_proyecto.md` no existe. Devolver string vacío o placeholder. El paso 4 del subproceso de archivos lo crea. (D9)
12. Modificar `_find_tokens_for_tema` en `indice_generator.py`: cuando un tema aparece en varios bloques, sumar los tamaños de todos los bloques donde aparece, no solo del primero. (D10)

**Verificación.** D1, D2, D3, D4, D5, D6, D7, D8, D9, D10.

### F5b — Auditoría de calidad de los archivos de recuperación

**Objetivo.** El `AuditorWorkspace` audita no solo completitud sino también calidad del contenido de los 4 archivos de recuperación.

**Tareas.**
1. Añadir método `auditar_calidad` a `AuditorWorkspace` en `pipeline_auditoria.py`. Este método lee los 4 archivos de recuperación y verifica:
   - `00_estado_actual.md`: sin placeholders `__*__` embebidos, sin G0.A duplicada, sin paths con caracteres especiales en A2, sin "Traceback" sin stack trace en A3, sin `\*` (caracteres escapados) en G0.B. (F2)
   - `03_objetivo_proyecto.md`: sin `__PLACEHOLDER__`, sin "Proyecto sobre:" (objetivo automático), contenido real presente. (F3)
   - `01_indice_recuperacion.md`: tokens no hardcodeados (no todos los temas transversales con el mismo valor). (F4)
   - `02_decisiones_clave.md`: decisiones deduplicadas (no hay duplicadas por texto), no excede un rango razonable (no 175 decisiones para 649 intercambios). (F5)
2. Modificar `auditar_completitud` para que también llame a `auditar_calidad` y devuelva las deficiencias en el resultado. (F1)
3. El paso 6 del pipeline (auditar final) ya llama a `auditar_completitud`. Como ahora incluye calidad, las deficiencias se reportan automáticamente. (F6)
4. Si `auditar_calidad` detecta deficiencias, las devuelve en `resultado["deficiencias_calidad"]` para que el D7 las reintente. (F7)

**Verificación.** F1, F2, F3, F4, F5, F6, F7.

### F6 — Cierre formal

**Objetivo.** Cerrar el ciclo DCEPI con veredicto, empaquetado y diff cero.

**Tareas.**
1. Actualizar `worklog.md` con entrada de sesión 15 que registra:
   - Cierre de D, C, E, P con checklists íntegras.
   - Implementación de las 6 fases con evidencias.
   - Veredicto JSON del Gauntlet.
2. Ejecutar Gauntlet determinista: regresión vs golden master, perímetro archivos, perímetro líneas, estática, dinámica, lógica con fuzzing.
3. Generar veredicto JSON con schema fijo del DCEPI.
4. Empaquetar entrega completa en `/home/z/my-project/download/contexto_zai_v7.0.zip`.
5. Generar `update_czai.ps1` desde la plantilla v1.1 con los 12 pasos del script de entrega.
6. Generar sentencias de validación para Windows.
7. Ejecutar diff cero entre repositorio local y entrega. Archivar DIFF en `/home/z/my-project/upload/DIFF_ENTREGA_contexto_zai_v7.0.txt`.
8. Generar veredicto final asentado.

**Verificación.** E1, E2, E3, E4.

## Reglas de implementación

- **R1.** Cada fase cierra con su verificación contra los criterios de la spec. Si una fase no cumple, no se pasa a la siguiente.
- **R2.** El grafo de flujo interno de cada subproceso se mantiene. No se cambia qué hace el W3, el D7, la cascada o el subproceso de archivos. Solo cambia dónde viven y con qué interfaz.
- **R3.** Lo que ya funciona (invocación al daemon, selección cronológica, creación de bloques, enriquecimiento del resumen) no se toca más allá de moverlo al módulo que le corresponde.
- **R4.** El worklog se actualiza al cierre de cada fase, no todo al final.
- **R5.** Cuando una fase cierra, su checklist con evidencias se copia al worklog.

**Fin del plan v7.0.**
