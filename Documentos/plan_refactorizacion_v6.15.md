# contexto_zai/Documentos/plan_refactorizacion_v6.15.md
# Plan v6.15 — Corrección de bugs F7/F8 + refactor cascada de acceso

**Versión:** 6.15
**Fecha:** 2026-11-08
**Estado:** Pendiente de implementación.
**Spec asociada:** spec_recuperacion_contexto_v6.15.md
**Sesión origen:** CZAI 6a00fcb8, elementos E+P del método DCEPI.

---

## Principio: cambios quirúrgicos (NH18), validar antes de entregar (NH19), solo lo pedido (NH23)

Modo de ejecución v1.6 (D6): UN solo Actuador + el agente como Crítico.

---

## Fases (quirúrgicas)

### F1 — Corregir bug F7: propagar `estructura` a `BloqueGenerator.generate()` (criterio 27)

- **Archivos:** `coordinador/integrador_respuestas.py`, `generation/bloque_generator.py`
- **Cambio quirúrgico:**
  - En `IntegradorRespuestas._integrar_documento()`: cuando se invoca `BloqueGenerator().generate(block, cleaner)`, añadir el parámetro `origen="externo"` (o `estructura=self._estructura` si se propaga).
  - Verificar que los bloques externos se generan con cabecera `# Bloque externo N` + `**Source:** ampliar_contexto (documento externo)`.
  - Test: crear un bloque externo de prueba y verificar la cabecera generada.
- **Estado:** ❌ Pendiente
- **Dependencias:** ninguna

### F2 — Corregir bug F8: omisión de archivos por `estructura`, no por `origen` (criterio 28)

- **Archivos:** `generation/recovery_generator.py`, `process/recovery_cycle.py`
- **Cambio quirúrgico:**
  - En `RecoveryGenerator.generate_all()`: cambiar la condición `if origen == "externo":` por `if estructura != "cronologico":`.
  - Propagar el parámetro `estructura` (detectado por P4.2 en `ampliar_contexto`) desde `ampliar_contexto()` → `RecoveryCycle.__init__()` → `RecoveryGenerator.generate_all()`.
  - Lo mismo aplica a `DecisionesGenerator` y `ObjetivoGenerator`: si `estructura != "cronologico"`, se omiten.
  - Un archivo externo con estructura cronológica SÍ genera los 4 archivos.
- **Estado:** ❌ Pendiente
- **Dependencias:** F1

### F3 — Crear clase `CascadaAccesoLLM` (criterios 29, 30)

- **Archivos:** `pipeline.py` (o nuevo módulo `cascada_acceso.py`)
- **Cambio quirúrgico:**
  - Crear clase `CascadaAccesoLLM` con:
    - `__init__(self, workspace_dir)`: inicializa estado (contador de tareas, configuración).
    - `procesar_tarea(self, tarea) -> bool`: método principal que ejecuta la cascada por una tarea individual.
    - `_nivel1_worker_bun(self, tarea) -> bool`: intenta con Worker Bun. Monitorea progreso (2 intervalos consecutivos 16-32s sin progreso = caída).
    - `_nivel2_proxy_zai(self, tarea) -> bool`: intenta con proxy Z.ai directo. Backoff 429 vive aquí.
    - `_nivel3_subagentes(self, tarea) -> bool`: el agente CZAI lanza subagentes con Task tool. Si no completan, publica pending_task.
  - El flujo de `procesar_tarea()`:
    ```
    1. Nivel 1 (Worker Bun) → si completo, return True
    2. Nivel 2 (proxy Z.ai) → si completo, return True
    3. Si Nivel 2 dio 429 sostenido o cae → retry Nivel 1 → si completo, return True
    4. Nivel 3 (subagentes del agente CZAI) → si completo, return True
    5. Si Nivel 3 no completo → publicar pending_task, return False
    ```
  - Una instancia de `CascadaAccesoLLM` se crea una vez por sesión y se reutiliza por tarea.
- **Estado:** ❌ Pendiente
- **Dependencias:** F2

### F4 — Implementar Nivel 3 correcto (criterio 31)

- **Archivos:** `pipeline.py` (método `_nivel3_subagentes` de la clase `CascadaAccesoLLM`)
- **Cambio quirúrgico:**
  - El método `_nivel3_subagentes(tarea)`:
    1. El proceso devuelve el control al agente CZAI con la tarea (vía `result.pending_tasks` o vía el daemon).
    2. El agente CZAI lanza el subagente con Task tool usando el `PROMPT_FUSIONADO_W1W2W3`.
    3. El subagente escribe el RESUMEN + 3 archivos `_responses/`.
    4. El proceso verifica con `_bloque_esta_completo()` si la tarea se completó.
    5. Si se completó → return True. Si no → publicar pending_task en `_pending_tasks.json` y return False.
  - **Importante:** el proceso NO puede invocar el Task tool directamente. La sincronización entre el proceso y el agente CZAI se hace vía `result.pending_tasks` (el proceso devuelve la lista, el agente CZAI la procesa, llama `collect_responses()` para integrar, y el proceso re-verifica).
- **Estado:** ❌ Pendiente
- **Dependencias:** F3

### F5 — Mover backoff 429 a `_nivel2_proxy_zai()` (criterio 32)

- **Archivos:** `pipeline.py`
- **Cambio quirúrgico:**
  - Eliminar el bucle while con backoff 429 de `_enriquecer_con_proxy_zai()`.
  - La función `_enriquecer_con_proxy_zai()` hace UN solo intento por llamada. Si falla (429 u otro error), return False inmediatamente.
  - El método `_nivel2_proxy_zai(self, tarea)` de la clase `CascadaAccesoLLM`:
    1. Llama a `_enriquecer_con_proxy_zai()`.
    2. Si return False y el error fue 429 → espera con backoff exponencial (30s→60s→120s→240s→480s→600s) y reintenta.
    3. Si el 429 persiste tras N reintentos → return False (para que `procesar_tarea` haga retry Nivel 1 o caiga a Nivel 3).
    4. Si el error no fue 429 → return False inmediatamente (caer a Nivel 3).
  - El bucle D7 de MAX_ITER_W3=5 (feedback al LLM) se mantiene en `_enriquecer_con_proxy_zai()` — eso sí es validación W3, no backoff 429.
- **Estado:** ❌ Pendiente
- **Dependencias:** F3

### F6 — Mover IndiceGenerator al final del pipeline (criterio 33)

- **Archivos:** `pipeline.py`, `generation/recovery_generator.py`
- **Cambio quirúrgico:**
  - Actualmente `RecoveryGenerator.generate_all()` invoca `IndiceGenerator` durante la integración de respuestas (cuando los bloques aún no tienen `tema_a_archivo` poblado).
  - Mover la invocación del IndiceGenerator al final del pipeline (P19), DESPUÉS del enriquecimiento (P14) y la consolidación de decisiones (P18).
  - En ese punto, los bloques ya tienen RESUMEN y los temas están poblados, así que `01_indice_recuperacion.md` se genera con contenido real (no placeholder).
  - Mantener la invocación de `00_estado_actual.md`, `02_decisiones_clave.md`, `03_objetivo_proyecto.md` en su posición actual (depende de `estructura`, ver F2).
- **Estado:** ❌ Pendiente
- **Dependencias:** F2

### F7 — Refactorizar `_enriquecer_bloques_con_fallback()` para usar `CascadaAccesoLLM`

- **Archivos:** `pipeline.py`
- **Cambio quirúrgico:**
  - `_enriquecer_bloques_con_fallback()` actualmente procesa todos los bloques en bloque (Nivel 1 para todos → Nivel 2 para los restantes → Nivel 3 para los que queden).
  - Refactorizar para que invoque `CascadaAccesoLLM.procesar_tarea()` por cada bloque individual:
    ```python
    cascada = CascadaAccesoLLM(workspace_dir=workspace_dir)
    for bloque in bloques_sin_resumen:
        completado = cascada.procesar_tarea(bloque)
        if not completado:
            # La propia cascada ya publicó la pending_task si Nivel 3 falló
            pass
    ```
  - Mantener la función `_enriquecer_bloques_con_fallback()` como wrapper que crea la instancia de `CascadaAccesoLLM` y la reutiliza por bloque.
- **Estado:** ❌ Pendiente
- **Dependencias:** F3, F4, F5

### F8 — Reconstruir contexto desde `exchanges_czai_consolidados.md`

- **Qué se hace:**
  1. Borrar workspace `contexto_recuperacion/` actual.
  2. Invocar al daemon (puerto 8088) con `ampliar_contexto("file", "exchanges_czai_consolidados.md")`.
  3. El daemon ejecuta el pipeline de 19 pasos con las correcciones F1-F7.
  4. P4.2 detecta estructura cronológica → se generan los 4 archivos (F2).
  5. P14 dispara la cascada con `CascadaAccesoLLM` (F3-F5, F7).
  6. P17 bucle D7 garantiza completitud.
  7. P19 genera `01_indice_recuperacion.md` con contenido real (F6).
- **Estado:** ❌ Pendiente
- **Dependencias:** F1-F7

### F9 — Gauntlet de terminación (7 pasos + 33 criterios)

- **Qué se hace:**
  1. Tras F8, ejecutar los 7 pasos del Gauntlet sobre el workspace reconstruido.
  2. Verificar los 33 criterios de aceptación (26 heredados + 7 nuevos).
  3. Si no pasa → bucle D7 (P17) con MAX_ITER=5.
  4. Si pasa → empaquetado (I.3.a) desbloqueado.
- **Estado:** ❌ Pendiente
- **Dependencias:** F8

---

## Orden de ejecución

| Fase | Descripción | Estado | Dependencias |
|---|---|---|---|
| F1 | Corregir bug F7: propagar `estructura` a `BloqueGenerator` | ❌ | ninguna |
| F2 | Corregir bug F8: omisión por `estructura`, no por `origen` | ❌ | F1 |
| F3 | Crear clase `CascadaAccesoLLM` | ❌ | F2 |
| F4 | Implementar Nivel 3 correcto | ❌ | F3 |
| F5 | Mover backoff 429 a `_nivel2_proxy_zai()` | ❌ | F3 |
| F6 | Mover IndiceGenerator al final (P19) | ❌ | F2 |
| F7 | Refactorizar `_enriquecer_bloques_con_fallback()` | ❌ | F3, F4, F5 |
| F8 | Reconstruir contexto desde `exchanges_czai_consolidados.md` | ❌ | F1-F7 |
| F9 | Gauntlet de terminación (7 pasos + 33 criterios) | ❌ | F8 |

**Total:** 9 fases quirúrgicas.

---

## Consideraciones para la implementación

### Modo de ejecución (estrategia v1.6, D6)

- Cada fase se ejecuta con UN solo subagente (Actuador) lanzado por el agente CZAI con el Task tool.
- El agente CZAI valora la respuesta del Actuador como Crítico contra el baremo.
- Si la respuesta no cumple → bucle D7 (modificar prompt → re-entregar al Actuador → re-valorar) hasta MAX_ITER=5.
- Nada se selecciona sin el Director; si existe algo mejor que lo conciliado, se explica y SE RE-CONCILIA antes de implementar.

### Trazabilidad

- Cada fase debe registrar en el worklog CZAI: qué se pidió, qué se hizo, qué archivos se modificaron, qué pendientes quedan.
- Los cambios se commitean al final de cada fase (no al final de toda la implementación) para preservar trazabilidad.

### Validación con datos reales (NH25)

- F8 usa el archivo real `exchanges_czai_consolidados.md` (5.2 MB, 649 exchanges).
- F9 ejecuta el Gauntlet sobre el workspace real generado por F8.
- No se aceptan mocks ni simulaciones como evidencia de veredicto.

### Encapsulamiento de procesos repetitivos (L018)

- La clase `CascadaAccesoLLM` (F3) encapsula la cascada de acceso al LLM.
- El bucle D7 (P17) ya está encapsulado en `_bucle_d7_completitud()` (v6.14).
- La auditoría (AuditorWorkspace) ya es una clase.
- La validación W3 (`_validar_resumen_w3`) ya es un método estático.
- Criterio del Actuador: clase cuando hay estado que preservar (CascadaAccesoLLM), función cuando es stateless (`_validar_resumen_w3`).

### Pendientes que requieren conciliación con el Director

- Si el proxy Z.ai da 429 sostenido durante F8, el bucle D7 de P17 debe escalar al Director con el informe de las 4 preguntas por iteración.
- El daemon (puerto 8088) ya existe de v6.14 — no hay que crearlo de nuevo.

---

**Fin del plan v6.15.**
