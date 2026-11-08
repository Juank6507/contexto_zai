# DOCUMENTO CONSOLIDADO DE RETORNO — contexto_zai v6.14

| Campo | Valor |
|---|---|
| Proyecto | contexto_zai |
| Agente | CZAI |
| Última actualización | 2026-11-08 |
| Origen | Elemento C (Conciliación) del método del proyecto; fichas aprobadas expresamente por el Director |
| Estado | VIGENTE |

## 1. Información general

Este documento consolida el retorno del ciclo DCEPI v6.14 de contexto_zai (sesión CZAI 6a00fcb8, trace 1a1bb155df8d57a1 en adelante). El ciclo corrigió los problemas detectados en la iteración 1 del Gauntlet v6.13 y reorganizó el pipeline a 19 pasos, separando la cascada de acceso al LLM del bucle D7 de completitud, añadiendo el daemon del proceso, y documentando el detonante de falta de contexto (ya asimilado por el agente EP en estrategia v1.6.1).

Estrategia usada por el proyecto: v1.6.1 (commit `20119b4`).

## 2. Lecciones aprendidas (propuestas para agent-learn/lecciones_aprendidas.md)

| # | Lección | Cómo se aplica | Origen (sesión/ciclo) |
|---|---|---|---|
| L018 | Los procesos repetitivos (bucle D7, auditoría, validación W3, backoff 429) deben encapsularse en clases o funciones reutilizables, no dispersarse en funciones procedurales. El criterio del Actuador decide clase vs función según complejidad y estado. | Toda lógica repetitiva del pipeline (cascada de acceso, bucle D7, auditoría) se encapsula en una clase/función con API clara. El código procedural que mezcla niveles y reintentos se sustituye por OOP. | CZAI 6a00fcb8, v6.14, F3+F5 |
| L019 | La cascada de acceso al LLM se aplica **por tarea individual**, no por lote. Cada tarea comienza en Nivel 1 (Worker Bun); si falla, Nivel 2 (proxy); si Nivel 2 cae, **vuelve a probar Nivel 1** antes de caer a Nivel 3 (subagentes del agente CZAI). Pending_tasks se publican solo si Nivel 3 no completa. | Diseñar la cascada como clase con método `procesar_tarea(tarea)` que encapsula los 3 niveles con retry, no como función que procesa todos los bloques a la vez. | CZAI 6a00fcb8, v6.14, P14 |
| L020 | El bucle D7 (reintentos con feedback hasta MAX_ITER=5) y el backoff 429 (espera de cuota) son mecanismos distintos que no deben mezclarse. El bucle D7 pertenece a la garantía de completitud (P17); el backoff 429 pertenece a la cascada de acceso (P14). | El backoff 429 vive en el método `_nivel2_proxy_zai()` de la clase CascadaAccesoLLM. El bucle D7 vive en P17 con su propio MAX_ITER_D7. La función `_enriquecer_con_proxy_zai()` solo hace UN intento por llamada. | CZAI 6a00fcb8, v6.14, F3 |
| L021 | La estructura del contenido (`cronologico` vs `arbitrario`) y el origen (`chat` vs `externo`) son dos dimensiones distintas. La generación de los 4 archivos de recuperación (00_estado_actual, 02_decisiones_clave, 03_objetivo_proyecto) depende de la **estructura**, no del origen. Un archivo externo con estructura cronológica SÍ genera los 4 archivos. | La condición para omitir 00_estado_actual/02_decisiones/03_objetivo es `estructura != "cronologico"`, no `origen == "externo"`. | CZAI 6a00fcb8, v6.14, F8 (corrección) |
| L022 | El Nivel 3 de la cascada no es "publicar pending_tasks y esperar". Es "el agente CZAI lanza subagentes con Task tool PRIMERO; si no se completan correctamente, entonces se publican pending_tasks". | Implementar Nivel 3 como: (1) el proceso devuelve el control al agente CZAI con la tarea; (2) el agente CZAI lanza el subagente con Task tool; (3) el proceso verifica si se completó; (4) solo si no, publica pending_task. | CZAI 6a00fcb8, v6.14, P14 |
| L023 | El daemon del proceso es el único punto de entrada válido para invocar el pipeline. El agente CZAI no escribe scripts `runner_*.py` para invocar el proceso — usa la API pública del daemon (puerto 8088). | Toda invocación de `pipeline.run()` o `ampliar_contexto()` se hace vía `POST /ampliar-contexto` o `POST /pipeline-run` al daemon. El agente CZAI es Crítico, no operador. | CZAI 6a00fcb8, v6.14, F5 |

## 3. Anti-patrones detectados (propuestos para agent-learn/anti_patrones.md)

| # | Anti-patrón | Señal de alerta | Corrección acordada | Origen |
|---|---|---|---|---|
| AP24 | Cambiar la firma de una función sin actualizar los callers | La función acepta un parámetro nuevo pero los puntos de invocación no lo pasan; los bloques generados tienen la cabecera vieja | Cuando se añade un parámetro a una firma, auditar todos los callers y actualizarlos. Verificar con test que el parámetro se propaga. | CZAI 6a00fcb8, v6.14, F7 (bug `origen` no propagado a BloqueGenerator) |
| AP25 | Mezclar dos dimensiones conceptuales en una sola condición | `if origen == "externo"` decide omisión de archivos, pero "externo" mezcla "viene de ampliar_contexto" con "no cronológico" — un archivo externo puede ser cronológico | Separar dimensiones: `origen` (dónde) y `estructura` (qué). Decidir por la dimensión correcta. | CZAI 6a00fcb8, v6.14, F8 (bug de diseño origen vs estructura) |
| AP26 | Mezclar backoff 429 con bucle D7 en la misma función | `_enriquecer_con_proxy_zai()` tiene un bucle while con MAX_ITER_W3 que mezcla validación W3 (feedback al LLM) con backoff 429 (espera de cuota) | El backoff 429 vive en la cascada de acceso (método `_nivel2_proxy_zai` de la clase). El bucle D7 con feedback vive en P17. La función de enriquecimiento hace un solo intento. | CZAI 6a00fcb8, v6.14, P14 |
| AP27 | Detener procesos manualmente en vez de dejar que la cascada complete | `pkill -9` sobre el proceso de enriquecimiento cuando el proxy da 429, en vez de dejar que la cascada caiga a Nivel 3 | Dejar que la cascada complete su flujo. Cuando el proceso devuelve `result.pending_tasks`, el agente CZAI las procesa vía Nivel 3 (subagentes del Task tool). | CZAI 6a00fcb8, v6.14, F10 |
| AP28 | Confundir `collect_responses()` con bucle D7 | Llamar `collect_responses()` dentro de `_ejecutar_pending_tasks_obligatorias()` como si fuera un mecanismo de completitud | `collect_responses()` es el integrador de respuestas de subagentes + disparador de la cascada P14. El bucle D7 de completitud es P17, separado. | CZAI 6a00fcb8, v6.14, F4 (corrección) |
| AP29 | Escribir informes escalados sin que el Director los pida | Generar `informe_escalado_d7_v614.md` en `download/` sin orden expresa del Director | Los informes solo se producen a petición expresa del Director. Lo general (aplicable a la estrategia) viaja en el documento consolidado de retorno; lo particular queda en el worklog. | CZAI 6a00fcb8, v6.14, cierre elemento I |

## 4. Patrones recurrentes (propuestos para agent-learn/patrones_recurrentes.md)

| # | Patrón | Descripción | Aplica cuando |
|---|---|---|---|
| P12 | **Cascada de acceso al LLM por tarea individual con retry entre niveles** | Para cada tarea o grupo de tareas, la cascada comienza en Nivel 1 (Worker Bun). Si 2 intervalos consecutivos (16-32s) no progresa o hay 429, cae a Nivel 2 (proxy directo). Si Nivel 2 cae, **vuelve a probar Nivel 1**. Si Nivel 1 también falla, cae a Nivel 3 (subagentes del agente CZAI). Pending_tasks se publican solo si Nivel 3 no completa. Implementado como clase `CascadaAccesoLLM` con método `procesar_tarea(tarea)`. | Cualquier acceso al LLM para enriquecer bloques, extraer decisiones, generar índices, etc. |
| P13 | **Encapsulamiento de procesos repetitivos** | Bucle D7, auditoría (AuditorWorkspace), validación W3, backoff 429: cada uno se encapsula en clase o función con API clara. El criterio del Actuador decide clase (si hay estado que preservar) vs función (si es stateless). Reutilización: una instancia por sesión, no una nueva por tarea. | Cualquier lógica repetitiva del pipeline (auditoría, reintentos, validación, backoff). |
| P14 | **Separación cascada de acceso vs bucle D7** | La cascada de acceso (cómo se llega al LLM: Nivel 1→2→3 con retry) es distinta del bucle D7 (qué hacer cuando la cascada no completó: revisar falla → modificar prompt → re-entregar al Actuador → re-valorar como Crítico → re-probar, hasta MAX_ITER=5). No mezclar: el backoff 429 no es bucle D7; el bucle D7 no es backoff 429. | Diseño de cualquier pipeline con acceso a LLM externo + garantía de completitud. |
| P15 | **Daemon del proceso como único punto de entrada** | El proceso contexto_zai corre como mini-servicio daemon (puerto 8088) siempre activo. El agente CZAI no escribe scripts runner_*.py ni invoca la API directamente — hace POST al daemon. El daemon ejecuta la API pública del proceso y devuelve el resultado. | Cualquier proceso que el agente CZAI necesite invocar repetidamente. |

## 5. Decisiones generales aprobadas (aplicables a la estrategia)

| # | Decisión | Alimenta qué archivo de estrategia | Origen |
|---|---|---|---|
| D8 | El detonante de falta de contexto se documenta en `premisa_respuesta.md` §3 y `herramientas.md` §8 con espejo NH20 capa 1: cuando el agente no puede emitir la frase de control → recuperación espontánea → invocar al daemon del proceso → `ampliar_contexto(chat_id_actual)` modo INCREMENTAL → leer los 4 archivos de recuperación → reemitir frase de control. La invocación al daemon es USO de la API pública, no reparación (la reparación sigue siendo del Director/proyecto propietario). | `agent-context/premisa_respuesta.md` §3 + `agent-context/herramientas.md` §8 (ya implementado por EP en v1.6.1) | CZAI 6a00fcb8, v6.14, elemento C |

## 6. Pendientes de cosecha

- El agente EP ya cosechó D8 (detonante de falta de contexto) en estrategia v1.6.1 (commit `20119b4`). Sin pendientes de cosecha para esa decisión.
- Las lecciones L018-L023, anti-patrones AP24-AP29 y patrones P12-P15 están propuestos en este documento para que el agente EP los coseche en el siguiente ciclo de la estrategia (M2, dcepi.md I.3.c).

---

Reglas del documento (NH26): (1) solo entra aquí información aprobada expresamente por el Director en el elemento C del proyecto; (2) lo general (aplicable a la estrategia) viaja en este documento; lo particular y específico queda en el worklog del proyecto; (3) el agente EP lo cosecha en M2 (dcepi.md I.3.c) citando proyecto y documento de origen; (4) la vía de retorno es única: repositorios. No existe push directo ni vía lateral.
