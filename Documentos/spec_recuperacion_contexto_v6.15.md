# contexto_zai/Documentos/spec_recuperacion_contexto_v6.15.md
# Spec v6.15 — Corrección de bugs F7/F8 + refactor de la cascada de acceso al LLM

**Versión:** 6.15
**Fecha:** 2026-11-08
**Estado:** Pendiente de implementación.
**Especifica continuación de:** spec v6.14.
**Sesión origen:** CZAI 6a00fcb8, elementos E+P del método DCEPI.

---

## 1. Propósito

Corregir los bugs detectados en la iteración del Gauntlet v6.14 y refactorizar la cascada de acceso al LLM para que cumpla con el diseño conciliado con el Director: por tarea individual, con retry entre niveles, Nivel 3 correcto (agente lanza subagentes primero, pending solo si no completan), y separación clara entre cascada de acceso y bucle D7.

Problemas detectados en v6.14:

1. **Bug F7**: `IntegradorRespuestas._integrar_documento()` no propaga `estructura` a `BloqueGenerator.generate()`. Los bloques externos se generan con cabecera vieja `# Bloque temático: documento_externo_N` en vez de `# Bloque externo N`.
2. **Bug F8 (diseño)**: la omisión de `00_estado_actual.md`, `02_decisiones_clave.md`, `03_objetivo_proyecto.md` depende de `origen="externo"` en vez de `estructura="cronologico"`. Un archivo externo con estructura cronológica SÍ debería generar los 4 archivos.
3. **Cascada de acceso no es OOP ni por tarea individual**: la lógica está dispersa en `_enriquecer_bloques_con_fallback()` (función procedural). No hay clase `CascadaAccesoLLM`. No hay retry a Nivel 1 tras fallo de Nivel 2.
4. **Nivel 3 incorrecto**: el código actual publica pending_tasks y devuelve el control, pero el diseño correcto es: el agente CZAI lanza subagentes con Task tool PRIMERO; las pending_tasks se publican SOLO si los subagentes no completan correctamente.
5. **Backoff 429 mal ubicado**: está dentro de `_enriquecer_con_proxy_zai()` (función de enriquecimiento), pero debería manejarlo el método `_nivel2_proxy_zai()` de la clase `CascadaAccesoLLM`.
6. **`01_indice_recuperacion.md` placeholder**: el IndiceGenerator se invoca pero no tiene datos porque los bloques externos no tienen `tema_a_archivo` poblado tras el enriquecimiento parcial.

---

## 2. Orden del proceso (19 pasos, sin cambios respecto a v6.14)

El pipeline se mantiene en 19 pasos (ver spec v6.14 §2). v6.15 no cambia el orden — corrige la implementación de P14 (cascada de acceso) y P9/P11/P12 (generación de archivos por estructura, no por origen).

---

## 3. Decisiones conciliadas por categoría

### Categoría 1 — Corrección de bugs F7/F8 (2 problemas)

| # | Problema | Decisión |
|---|---|---|
| 1 | Bug F7: `_integrar_documento()` no propaga `estructura` a `BloqueGenerator.generate()` | Modificar `_integrar_documento()` en `coordinador/integrador_respuestas.py` para pasar el parámetro `origen` (o mejor, `estructura`) al invocar `BloqueGenerator.generate()`. Los bloques externos deben tener cabecera `# Bloque externo N`. |
| 2 | Bug F8 (diseño): omisión de archivos depende de `origen` en vez de `estructura` | Cambiar la condición en `RecoveryGenerator.generate_all()`: en vez de `if origen == "externo": omitir EstadoGenerator`, usar `if estructura != "cronologico": omitir`. Lo mismo aplica a `DecisionesGenerator` y `ObjetivoGenerator`. Un archivo externo con estructura cronológica SÍ genera los 4 archivos. |

### Categoría 2 — Refactor cascada de acceso (3 problemas)

| # | Problema | Decisión |
|---|---|---|
| 3 | Cascada no es OOP ni por tarea individual | Crear clase `CascadaAccesoLLM` en `pipeline.py` (o nuevo módulo `cascada_acceso.py`) con método `procesar_tarea(tarea) -> bool` que encapsule los 3 niveles con retry. Ante cada tarea, la cascada comienza en Nivel 1. Una instancia se crea una vez y se reutiliza por tarea (OOP + reutilización). |
| 4 | Nivel 3 incorrecto | Implementar Nivel 3 así: (1) el proceso devuelve el control al agente CZAI con la tarea; (2) el agente CZAI lanza el subagente con Task tool; (3) el proceso verifica si se completó (`_bloque_esta_completo()`); (4) SOLO si no se completó, publica pending_task en `_pending_tasks.json`. |
| 5 | Backoff 429 mal ubicado | Mover el bucle de backoff 429 de `_enriquecer_con_proxy_zai()` al método `_nivel2_proxy_zai()` de la clase `CascadaAccesoLLM`. La función `_enriquecer_con_proxy_zai()` hace UN solo intento por llamada. Si Nivel 2 da 429 sostenido, el método decide: esperar y reintentar, o volver a Nivel 1, o caer a Nivel 3. |

### Categoría 3 — Índice no placeholder (1 problema)

| # | Problema | Decisión |
|---|---|---|
| 6 | `01_indice_recuperacion.md` se genera vacío (placeholder) | El IndiceGenerator debe invocarse DESPUÉS del enriquecimiento (P14), no antes. Actualmente se invoca durante la integración de respuestas, cuando los bloques aún no tienen `tema_a_archivo` poblado. Mover la invocación del IndiceGenerator al final del pipeline (P19), tras el enriquecimiento y la consolidación de decisiones. |

### Categoría 4 — Retry entre niveles (1 problema)

| # | Problema | Decisión |
|---|---|---|
| 7 | No hay retry a Nivel 1 tras fallo de Nivel 2 | Cuando Nivel 2 (proxy Z.ai) da 429 sostenido o cae, el método `_nivel2_proxy_zai()` debe volver a probar Nivel 1 (Worker Bun) para la tarea actual. Si Nivel 1 también falla, entonces cae a Nivel 3 (subagentes del agente CZAI). El flujo: Nivel 1 → Nivel 2 → retry Nivel 1 → Nivel 3. |

---

## 4. Baremo táctico derivado del estratégico

### Gauntlet (7 pasos con datos reales, sin cambios respecto a v6.14)

Mismos 7 pasos que v6.14 (ver spec v6.14 §4).

### Criterios de aceptación (7 nuevos de v6.15 + 26 heredados de v6.14 = 33)

**Heredados de v6.14 (26):** mismos que spec v6.14 §4.

**Nuevos de v6.15 (7):**

27. `_integrar_documento()` pasa `estructura` (o `origen`) a `BloqueGenerator.generate()`. Los bloques externos se generan con cabecera `# Bloque externo N` (no `# Bloque temático:`).
28. La omisión de `00_estado_actual.md`, `02_decisiones_clave.md`, `03_objetivo_proyecto.md` depende de `estructura != "cronologico"`, no de `origen == "externo"`. Un archivo externo con estructura cronológica SÍ genera los 4 archivos.
29. Existe clase `CascadaAccesoLLM` con método `procesar_tarea(tarea) -> bool` que encapsula los 3 niveles.
30. La cascada comienza en Nivel 1 por cada tarea (no por lote). Una instancia de `CascadaAccesoLLM` se reutiliza por tarea.
31. Nivel 3: el agente CZAI lanza subagentes con Task tool PRIMERO; las pending_tasks se publican SOLO si los subagentes no completan correctamente.
32. El backoff 429 vive en `_nivel2_proxy_zai()` de la clase `CascadaAccesoLLM`, no en `_enriquecer_con_proxy_zai()`. La función de enriquecimiento hace UN solo intento por llamada.
33. `01_indice_recuperacion.md` se genera al final del pipeline (P19) con `tema_a_archivo` poblado, no vacío (placeholder).

---

**Fin de la spec v6.15.**
