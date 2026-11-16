# contexto_zai/Documentos/spec_recuperacion_contexto_v6.10.md
# Spec v6.10 — Carga automática del JWT + eliminación de errores silenciados + arnés Worker Bun/subagentes

**Versión:** 6.10
**Fecha:** 2026-10-12
**Estado:** Pendiente de implementación.
**Especifica continuación de:** spec v6.9.

---

## 1. Propósito

La v6.9 dejó tres problemas detectados en sesión real con el Director:

1. El agente tiene que pasar el JWT manualmente al proceso. Si lo pasa vacío, el proceso falla con HTTP 401 sin explicación clara.
2. El proceso oculta errores silenciosamente: cuando el enriquecimiento de bloques falla, el agente no recibe las tareas pendientes que debería ejecutar.
3. Cuando el Worker Bun cae por saturación del servicio de Z.ai, el proceso se queda esperando. El agente no lanza subagentes de fallback y los bloques quedan sin procesar.

Esta spec resuelve los tres problemas y re-aplica fixes de versiones anteriores (v6.8.1, v6.8.3, v6.8.4) que se perdieron del código local tras un reset.

---

## 2. Principio rector: proteger lo existente

**Lo que ya funciona NO se toca:**
- Bloques con contenido literal hasta 70K ✅
- RESUMEN al inicio de cada bloque ✅
- Worker Bun como camino prioritario de enriquecimiento ✅
- Detección de Worker Bun existente por puerto 8090 (v6.8.2 F2) ✅
- Formato lista en tema_a_archivo (v6.8.2 F1) ✅
- Link /s/ procesado como fuente externa (v6.9) ✅

Los cambios son quirúrgicos en tres puntos del proceso.

---

## 3. Los tres problemas a resolver

### Problema 1 — El agente tiene que pasar el JWT manualmente

**Qué pasa hoy:** el proceso principal exige que el agente le pase el JWT del Director como parámetro. Si el agente lo pasa vacío (porque asume que el proceso lo cargará solo), el proceso intenta crear un share con un JWT vacío y falla con HTTP 401.

**Impacto:** el agente tiene que saber que el JWT vive en `~/.czai/credentials.json` y cargarlo manualmente cada vez. Si se olvida, el proceso falla con un error que no explica la causa raíz.

**Causa raíz:** el proceso no carga el JWT automáticamente cuando recibe uno vacío.

### Problema 2 — El proceso oculta errores silenciosamente

**Qué pasa hoy:** hay dos puntos del proceso donde el enriquecimiento de bloques se ejecuta dentro de un bloque `try/except Exception` que captura cualquier error y solo lo registra como advertencia. El agente nunca se entera de que hubo un error. Las tareas pendientes de fallback (que deberían llegarle al agente para que lance subagentes) se pierden.

**Impacto:** cuando el enriquecimiento falla (por ejemplo, el Worker Bun cae por rate limit), el agente recibe `pending_tasks: 0` aunque haya bloques sin procesar. El agente cree que no hay nada que hacer.

**Causa raíz:** el `try/except` silencioso fue introducido en v6.6 como medida defensiva pero oculta errores que el agente debería ver.

### Problema 3 — El proceso se queda esperando al Worker Bun cuando cae

**Qué pasa hoy:** cuando el Worker Bun está procesando bloques y el servicio de Z.ai se satura (HTTP 429), el Worker Bun hace backoff exponencial pero eventualmente muere. El proceso Python queda esperando un timeout (hasta 30 segundos) antes de devolver el control al agente. Recién después de ese timeout, el agente recibe las pending_tasks y puede lanzar subagentes.

**Impacto:** el agente pierde hasta 30 segundos esperando, cuando podría haber lanzado subagentes inmediatamente al detectar la caída del Worker Bun.

**Causa raíz:** el proceso es secuencial: arranca Worker Bun → espera → verifica → construye pending_tasks. No hay un mecanismo que detecte la caída del Worker Bun en tiempo real y lance subagentes mientras lo monitorea.

---

## 4. Soluciones

### F1 — Carga automática del JWT (Problema 1)

**Qué se hace:**
1. Cuando el proceso principal recibe un JWT vacío, lo carga automáticamente del `CredentialManager` (que es donde vive el JWT del Director persistido por el bookmarklet).
2. Si después de intentar cargarlo sigue vacío, el proceso devuelve un error claro: "No hay JWT disponible. Pedí al Director que reconecte CZAI desde el sandbox."
3. El agente ya no necesita cargar el JWT manualmente. Solo lo pasa si quiere usar uno distinto al persistido.

**Lo que NO se toca:**
- El `CredentialManager` (no se modifica).
- El bookmarklet ni el flujo de conexión del Director.
- El parámetro `jwt` del proceso principal (sigue existiendo, ahora con valor por defecto vacío).

### F2 — Eliminar los dos `try/except` silenciosos (Problema 2)

**Qué se hace:**
1. En la función que enriquece bloques después de la activación principal (`_enriquecer_bloques_post_run`), eliminar el `try/except` que envuelve todo el bloque. Si el enriquecimiento falla, el error se propaga y se registra claramente.
2. En la función que recoge respuestas de subagentes (`collect_responses`), eliminar el `try/except` similar. Capturar el valor de retorno del enriquecimiento directamente, sin re-leer del Orquestador.
3. Re-aplicar el fix de v6.8.1: el enriquecimiento devuelve las pending_tasks en su valor de retorno. El agente las recibe directamente, sin intermediarios.

**Lo que NO se toca:**
- La lógica del enriquecimiento (sigue siendo la misma, ahora sin envoltorio silencioso).
- El Worker Bun (no se modifica).
- Los tests existentes (se actualizan para reflejar que los errores ya no se silencian).

### F3 — Arnés Worker Bun / subagentes (Problema 3)

**Modelo de funcionamiento:**

El proceso de enriquecimiento funciona con un "arnés" que prioriza el Worker Bun y recurre a subagentes solo cuando el Worker Bun cae. El flujo es:

1. **Worker Bun trabajando solo:** cuando el proceso necesita enriquecer bloques y el servicio de Z.ai está sano, el Worker Bun procesa los bloques. El agente no hace nada. No lanza subagentes. Solo espera a que el Worker Bun termine.

2. **Worker Bun cae → subagentes entran:** si el Worker Bun falla (HTTP 429, timeout, muerte del proceso), la tarea que estaba procesando se devuelve a la lista de pendientes. En ese momento, el proceso le entrega al agente las pending_tasks y el agente lanza un lote de subagentes para procesar lo pendiente.

3. **Monitor en segundo plano:** mientras los subagentes trabajan, el proceso monitorea al Worker Bun en segundo plano. Si el Worker Bun se recupera (el rate limit cedió), se deja que el lote de subagentes termine la tarea que está procesando (no se interrumpe a mitad) y se vuelve al Worker Bun como camino prioritario.

4. **Ciclo:** Worker Bun solo → cae → subagentes solo → monitor → Worker Bun se recupera → lote termina → Worker Bun solo → ...

**Regla de oro:** el Worker Bun y los subagentes nunca procesan la misma tarea al mismo tiempo. El Worker Bun es el camino prioritario. Los subagentes son el sustituto temporal cuando el Worker Bun cae. Cuando el Worker Bun se recupera, los subagentes terminan lo que están haciendo y se retiran.

**Lo que se implementa:**
1. Detectar la caída del Worker Bun sin esperar al timeout completo.
2. Cuando cae: devolver la tarea en proceso a la lista de pendientes y construir pending_tasks para el agente inmediatamente.
3. Lanzar el Worker Bun en segundo plano (no bloqueante) mientras los subagentes trabajan, para detectar cuándo se recupera.
4. Cuando el Worker Bun se recupera: dejar que el lote actual de subagentes termine, luego volver al Worker Bun.

**Lo que NO se toca:**
- El Worker Bun en sí (su código TypeScript no se modifica).
- El backoff exponencial interno del Worker Bun (sigue igual).
- Los prompts de enriquecimiento (Worker Bun y subagentes usan el mismo prompt riguroso).
- La idempotencia (Worker Bun y subagentes verifican si el bloque ya tiene RESUMEN antes de procesarlo).

### F4 — Re-aplicación de fixes perdidos (v6.8.1, v6.8.3, v6.8.4)

Los siguientes fixes se perdieron del código local tras un reset. Se re-aplican como parte de v6.10:

- **v6.8.1:** capturar `fallback_tasks` del valor de retorno del enriquecimiento (parte de F2).
- **v6.8.3:** verificar que el Worker Bun realmente procesó bloques tras esperar (parte de F3).
- **v6.8.4:** no registrar temas provisionales en `tema_a_archivo` al integrar documentos externos; definir `_regenerar_indice_tras_enriquecimiento` y `_normalizar_bloques_externos`.

**Lo que NO se toca:**
- Las specs y planes de v6.8.1, v6.8.3, v6.8.4 (ya existen en el historial, no se regeneran).
- El comportamiento documentado en esas specs (se respetan íntegramente).

---

## 5. Archivos intervenidos

| Archivo | Cambio |
|---|---|
| `pipeline.py` | F1: carga automática del JWT. F2: eliminar `try/except` silencioso en `_enriquecer_bloques_post_run` y `collect_responses`. F3: arnés Worker Bun/subagentes. F4: re-aplicar v6.8.1, v6.8.3, v6.8.4. |
| `coordinador/integrador_respuestas.py` | F4: re-aplicar v6.8.4 (sin temas provisionales). |
| `tests/test_v42_e2e.py` | Actualizar tests que asumían el comportamiento viejo (try/except silencioso, temas provisionales). |

---

## 6. Lo que NO se toca

- Worker Bun (código TypeScript, prompts, backoff).
- `CredentialManager` (no se modifica).
- Bookmarklet ni el flujo de conexión del Director.
- Bloques físicos (nombre, contenido, RESUMEN).
- Especificaciones y planes de versiones anteriores (ya en el historial).
- La estructura de archivos de recuperación (`00_estado_actual.md`, `01_indice_recuperacion.md`, etc.).

---

## 7. Criterios de aceptación

1. El agente puede llamar al proceso principal sin pasar el JWT (vacío) y el proceso lo carga automáticamente del `CredentialManager`.
2. Si no hay JWT disponible, el proceso devuelve un error claro que explica qué hacer.
3. Cuando el enriquecimiento falla, el agente recibe las `pending_tasks` correspondientes (no se silencian).
4. Cuando el Worker Bun cae por rate limit, el agente recibe las `pending_tasks` en menos de 5 segundos (no espera 30 segundos de timeout).
5. Cuando el Worker Bun se recupera mientras los subagentes trabajan, los subagentes terminan su lote actual y el Worker Bun retoma el control.
6. El Worker Bun y los subagentes nunca procesan la misma tarea al mismo tiempo.
7. Tests atómicos y E2E pasan.
8. Importación de las funciones críticas (`_enriquecer_bloques_con_fallback`, `_consolidar_decisiones_llm`, `_normalizar_bloques_externos`, `_regenerar_indice_tras_enriquecimiento`) funciona sin error.

---

## 8. Validación con datos reales

1. **Test F1 (JWT automático):** llamar al proceso principal sin pasar JWT. El proceso debe cargarlo automáticamente y funcionar. Si se elimina el JWT del `CredentialManager`, el proceso debe devolver el error claro.

2. **Test F2 (sin errores silenciados):** simular una falla en el enriquecimiento (por ejemplo, Workspace sin bloques). El proceso debe devolver las `pending_tasks` correspondientes, no `0`.

3. **Test F3 (arnés):** con el servicio de Z.ai saturado (429), verificar que:
   - El agente recibe las `pending_tasks` en menos de 5 segundos.
   - Los subagentes procesan los bloques mientras el Worker Bun intenta recuperarse.
   - Cuando el servicio se recupera, el Worker Bun retoma el control.

4. **Test F4 (fixes re-aplicados):** verificar que las funciones `_regenerar_indice_tras_enriquecimiento` y `_normalizar_bloques_externos` existen y se importan correctamente. Verificar que `_integrar_documento` no registra temas provisionales.

---

**Fin de la spec v6.10.**
