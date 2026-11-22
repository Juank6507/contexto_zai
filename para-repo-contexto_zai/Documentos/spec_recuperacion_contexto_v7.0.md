# Spec v7.0 — Modularización + abstracción de plataforma + fixes v6.20

**Versión:** 7.0
**Fecha:** 2026-11-21
**Estado:** Implementación en curso.
**Previa:** v6.20 (implementada sin cierre formal DCEPI).

## 1. Propósito

Cierre formal de v6.20 con dos fixes de bugs detectados, sobre una base arquitectónica nueva: modularización del pipeline en subprocesos separados y restauración de la abstracción de plataforma perdida desde v5.0. La abstracción prepara el proceso para integrarse con MB (app web que provee LLM a múltiples apps) en v7.1.

## 2. Los trece factores

1. **Qué falla:** dos funcionalidades de v6.20 no cumplen su cometido. Bug 1: el daemon no logra avisar al agente cuando la cascada cae a Nivel 3 por rate limit. Bug 2: el subproceso de archivos de recuperación no completa correctamente los cuatro archivos. Fondo: arquitectura mezclada y abstracción de plataforma perdida.
2. **Por qué falla:** los bugs son síntomas. La causa de fondo es arquitectónica: tres subprocesos reusables mezclados en una sola clase (EnriquecimientoOrquestador), abstracción de plataforma v5.0 perdida, fugas de capa en config.py y pipeline.py.
3. **Dónde falla:** pipeline.py (6000+ líneas, 5 clases, 5 literales GLM dispersos), coordinador/recogedor_respuestas.py (limpiar borra auxiliares), coordinador/integrador_respuestas.py (handler faltante), mini-services/subagent-proxy/index.ts (sin circuit breaker), mini-services/pipeline-daemon/index.py (sin invocación explícita), config.py (literales Zai).
4. **Cómo reproducirlo:** workspace actual con 22 bloques + 15 caches. Correr /collect-responses con rate limit: agente nunca lanza subagentes. Observar 02_decisiones_clave.md vacío, 00_estado_actual.md con paths corruptos, 03_objetivo_proyecto.md con placeholders.
5. **Qué debe pasar después:** v7.0 con cuatro subprocesos en módulos separados, interfaces abstractas restauradas, cascada con modelo inyectado, daemon con invocación explícita, subproceso de archivos por pasos con generadores, auxiliares preservados, placeholders reemplazados, tokens reales.
6. **Qué no se toca:** grafo de flujo de cada subproceso (W3 sigue llamando cascada y validando con Crítico, D7 sigue detectando y mandando a pending_task, subproceso archivos sigue generando cuatro archivos). Siete pasos del pipeline en mismo orden. API pública mantiene firma. Cuatro archivos de recuperación mantienen nombre y propósito. Lo que ya funciona (daemon, selección cronológica, bloques, enriquecimiento del resumen) se mantiene, solo cambia dónde vive.
7. **Precondiciones:** workspace con 22 bloques y 15 caches, worklog hasta sesión 14, código v6.20 en sandbox, confirmación del Director de que integración concreta con MB queda para v7.1.
8. **Invariantes:** (a) todo acceso al LLM se hace usando la cascada; (b) el W3 valida con Crítico después de que la cascada devuelve respuesta; (c) los siete pasos del pipeline se ejecutan en orden conciliado (auditar, generar bloques, cascada, pending task, subproceso archivos, auditar final, D7).
9. **Impacto colateral:** los cambios arquitectónicos pueden romper lo que ya funciona si no se hace con cuidado. Cada subproceso se mueve íntegro sin cambiar su grafo de flujo interno. Abstracción se restaura con implementaciones concretas de Zai para que el comportamiento real no cambie. Bugs se rectifican después de refactorización.
10. **Severidad:** alta. Sin estos cambios, cualquier fix futuro es parche sobre código acoplado, y la integración con MB en v7.1 se vuelve impracticable.
11. **Evidencia:** workspace actual con 22 bloques y 15 caches demuestra los dos bugs. Análisis de pipeline.py demuestra mezcla arquitectónica. Ausencia del directorio platforms/ demuestra pérdida de abstracción v5.0.
12. **Antecedentes:** v6.20 implementada sin cierre formal DCEPI. Abstracción de plataforma acordada en v5.0 y perdida en versiones posteriores. Placeholders del objetivo del proyecto nunca implementados pese a estar documentados en código.
13. **Alternativas descartadas:** (a) dejar modularización y abstracción para v7.1 — descartada por orden del Director: todo entra en esta conciliación. (b) hacer solo los fixes sin tocar arquitectura — descartada porque los fixes serían parches sobre arena. (c) mantener criterio 9 de v6.20 de una sola llamada LLM para los archivos — descartada por ahora: separamos por pasos hasta que funcione, después se valora reintegrar.

## 3. Tabla de alcance

### Archivos nuevos
- `contexto_zai/pipeline_cascada.py` — cascada de acceso al LLM como clase concreta con modelo inyectado por constructor.
- `contexto_zai/pipeline_w3.py` — ciclo W3 como clase concreta.
- `contexto_zai/pipeline_d7.py` — ciclo D7 como clase concreta.
- `contexto_zai/pipeline_archivos.py` — subproceso de archivos de recuperación como clase concreta.
- `contexto_zai/pipeline_auditoria.py` — AuditorWorkspace y ProgressMonitor en su propio módulo.
- `contexto_zai/platforms/__init__.py` — paquete de abstracción de plataforma.
- `contexto_zai/platforms/interfaces.py` — las cuatro interfaces abstractas (PlatformAuth, PlatformChat, PlatformLinks, PlatformLLM).
- `contexto_zai/platforms/zai/__init__.py` — paquete de implementación concreta Zai.
- `contexto_zai/platforms/zai/zai_auth.py` — implementación de PlatformAuth.
- `contexto_zai/platforms/zai/zai_chat.py` — implementación de PlatformChat.
- `contexto_zai/platforms/zai/zai_links.py` — implementación de PlatformLinks.
- `contexto_zai/platforms/zai/zai_llm.py` — implementación de PlatformLLM.
- `contexto_zai/platforms/zai/zai_config.py` — configuración concreta Zai (URL, modelos default).

### Archivos modificados
- `contexto_zai/pipeline.py` — se reduce a API pública + orquestación de los siete pasos. Clases EnriquecimientoOrquestador, CascadaAccesoLLM, AuditorWorkspace y ProgressMonitor se mueven a sus módulos dedicados.
- `contexto_zai/config.py` — constantes Zai renombradas a genéricas (PROXY_LLM_URL en vez de PROXY_ZAI_URL, etc.). Valores concretos Zai se mueven a `platforms/zai/zai_config.py`.
- `contexto_zai/coordinador/recogedor_respuestas.py` — método `limpiar` preserva auxiliares y directorio cache.
- `contexto_zai/coordinador/integrador_respuestas.py` — se añade handler para patrón `enriquecer_bloque_NN`.
- `contexto_zai/processing/message_extractor.py` — refactorizado para usar interfaces abstractas.
- `contexto_zai/generation/estado_generator.py` — arreglos en extracción de paths, errores, tool_calls, bash_blocks, revalidación de síntesis.
- `contexto_zai/generation/indice_generator.py` — tokens calculados del tamaño real de los bloques.
- `contexto_zai/generation/recovery_generator.py` — orquestación de generadores al nuevo subproceso por pasos.
- `mini-services/pipeline-daemon/index.py` — `/collect-responses` devuelve campo explícito con pending_tasks cuando hay tareas esperando; `/status` valida estado físico.
- `mini-services/subagent-proxy/index.ts` — circuit breaker + clasificación de errores; refactorizado para usar interfaz abstracta.
- `contexto_zai/mini-services/worker-cascade/index.ts` — refactorizado para usar interfaz abstracta.

### Archivos de cierre
- `/home/z/my-project/worklog.md` — entrada sesión 15 con cierre formal v7.0.
- `/home/z/my-project/contexto_zai/Documentos/spec_recuperacion_contexto_v7.0.md` — esta especificación.
- `/home/z/my-project/contexto_zai/Documentos/plan_refactorizacion_v7.0.md` — el plan.

## 4. Criterios de aceptación

### Arquitectura
- A1. `EnriquecimientoOrquestador` no existe más en `pipeline.py` (grep devuelve 0 coincidencias).
- A2. Cuatro módulos nuevos (`pipeline_cascada.py`, `pipeline_w3.py`, `pipeline_d7.py`, `pipeline_archivos.py`) existen en `contexto_zai/`.
- A3. Cada módulo expone una clase concreta con constructor que recibe `workspace_dir` y configuración.
- A4. Los siete pasos del pipeline están separados en funciones que `run` orquesta.
- A5. El subproceso de archivos no bypassa la cascada: llama al W3 que llama a la cascada (grep de llamadas `urllib` directas en `pipeline_archivos.py` devuelve 0).

### Abstracción
- B1. Las cuatro interfaces abstractas (`PlatformAuth`, `PlatformChat`, `PlatformLinks`, `PlatformLLM`) existen en `platforms/interfaces.py`.
- B2. Las cuatro implementaciones concretas de Zai existen en `platforms/zai/`.
- B3. Ningún módulo fuera de `platforms/zai/` importa directamente clientes de `client/`.
- B4. `config.py` no tiene literales `ZAI` en los nombres de constantes (grep devuelve 0).
- B5. La cascada recibe el modelo por constructor, no hardcoded.
- B6. `Worker Bun` y `Subagent Proxy` usan la interfaz abstracta para acceder al LLM.

### Bug 1 (comunicación daemon)
- C1. El daemon devuelve en la respuesta HTTP de `/collect-responses` un campo explícito que dice que hay tareas esperando y cuáles son, cuando la cascada cae al Nivel 3.
- C2. El `Subagent Proxy` tiene circuit breaker: si cinco tareas fallan consecutivas, entra en modo espera.
- C3. El `Subagent Proxy` clasifica errores: 401 y 403 van a dead letter queue, no se reintentan.
- C4. El archivo `_processed_tasks.json` no crece indefinidamente con reintentos fallidos tras ejecución de prueba.

### Bug 2 (subproceso archivos)
- D1. El subproceso de archivos usa los generadores existentes (`EstadoGenerator`, `DecisionesGenerator`, `IndiceGenerator`) por separado en vez de una sola llamada LLM.
- D2. El método `limpiar` del `RecogedorRespuestas` no borra los archivos auxiliares (`_nombre.txt`, `_decisiones.txt`, `_temas.txt`) ni el directorio `cache/`.
- D3. El consolidador de decisiones tiene fallback a caches cuando los auxiliares no existen.
- D4. El archivo `03_objetivo_proyecto.md` no tiene placeholders sin reemplazar tras la primera generación (grep de `MODELO_AGENTE`, `DIRECTOR`, `EMAIL`, `ACTA_NACIMIENTO` devuelve 0).
- D5. El índice muestra tokens calculados del tamaño real de los bloques, no hardcoded.

### Cierre
- E1. Existe entrada en el worklog para la sesión 15 con el cierre formal v7.0.
- E2. Existen spec v7.0 y plan v7.0 en `Documentos/`.
- E3. El diff entre el repositorio actualizado y la entrega es cero.
- E4. El veredicto JSON del Gauntlet no tiene items fallados.

## 5. Principios conciliados que se respetan

- **P1.** Todo acceso al LLM se hace usando la cascada.
- **P2.** El W3 valida con Crítico después de que la cascada devuelve respuesta.
- **P3.** Los siete pasos del pipeline se ejecutan en orden conciliado.
- **P4.** La cascada es acceso al LLM. El subproceso de archivos es otro módulo que usa el W3, que a su vez usa la cascada. No son lo mismo.
- **P5.** Cambiamos arquitectura pero el grafo de flujo de cada subproceso se mantiene.
- **P6.** Worklog se actualiza al cierre de cada elemento del DCEPI, no todo al final.

## 6. Lo que se mantiene fuera del alcance (va a v7.1)

- Integración concreta con MB (la app web que provee LLM).
- Eliminación efectiva de los defaults Zai en mini-servicios (cuando MB funcione).

**Fin de la spec v7.0.**
