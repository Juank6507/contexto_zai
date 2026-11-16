# contexto_zai/Documentos/spec_recuperacion_contexto_v6.17.md
# Spec v6.17 — Cascada de acceso + bucle D7 separados + Nivel 3 integrado + daemon en background

**Versión:** 6.17
**Fecha:** 2026-11-10
**Estado:** Pendiente de implementación.
**Especifica continuación de:** spec v6.16.
**Sesión origen:** CZAI 6a00fcb8, elemento C del método DCEPI conciliado.

---

## 1. Propósito

Implementar las 12 correcciones conciliadas en el elemento C que separan definitivamente la cascada de acceso al LLM del bucle D7 de completitud, integran Nivel 3 al proceso, hacen el proceso persistente y autónomo, y corrigen los bugs de detección de bloques incompletos y propagación de estructura.

---

## 2. Orden del proceso (19 pasos, sin cambios)

El pipeline se mantiene en 19 pasos (ver spec v6.14 §2). v6.17 corrige implementación.

---

## 3. Decisiones conciliadas

### 1. Nivel 3 integrado al proceso

Nivel 3 es funcionalidad de la cascada (algoritmo, no promesa). Los bloques que llegan a Nivel 3 se procesan mediante subagentes automáticamente dentro del proceso. No se dejan como pending_tasks sin procesar. Si Nivel 3 no completa tras el bucle D7, la tarea va a pending_task (para P17).

### 2. Bucle D7 separado de la cascada

El bucle D7 no baja niveles de la cascada. Cuando el D7 no completa tras 5 intentos, la tarea pasa a pending_task. La cascada (Nivel 1 → 2 → 3) y el D7 (reintento con feedback) son mecanismos distintos.

### 3. collect_responses() solo integra respuestas

Lee `_responses/`, integra al workspace, devuelve resultado. No verifica bloques incompletos ni dispara la cascada. El proceso (daemon/pipeline) verifica y dispara.

### 4. Daemon en background con reporte de progreso

El proceso corre en background. En cada respuesta del agente al Director, la frase de control incluye el estado del proceso (progreso, bloques completados, pendientes, si no hace nada lo dice, cuando termina lo dice).

### 5. Detonante de falta de contexto usa RecoveryCycle

Cuando el agente no puede emitir la frase de control, invoca al daemon para que actualice el contexto por RecoveryCycle. Si `contexto_recuperacion/` no existe, lo crea desde lo que existe en ese chat.

### 6. Si contexto_recuperacion existe: solo auditar + completar

Si la carpeta ya existe, el proceso no re-extrae ni re-construye. Audita qué está completo, qué está incompleto, y completa lo faltante. No rehace bloques completos. No borra caché. No quita RESUMENES.

### 7. Función única de bloques incompletos

Unificar `_descubrir_bloques_sin_resumen()` y `_bloque_esta_completo()` en una sola función o clase que detecte bloques incompletos (verificando los 4 artefactos: RESUMEN + 3 archivos _responses). Un bloque con RESUMEN pero sin los 3 archivos es incompleto y debe procesarse — pero solo para completar los archivos faltantes, no para rehacer el RESUMEN.

### 8. Manejo del 429 entre tareas

- Una tarea o grupo recibe 429 en Nivel 1 o Nivel 2 → cae a Nivel 3 para esa tarea.
- Antes de la siguiente tarea: ping para comprobar si el 429 persiste.
- Si persiste → la siguiente tarea va directo a Nivel 3.
- Si no persiste → la siguiente tarea empieza en Nivel 1.
- Si Nivel 1 cae por causa que NO es 429 → Nivel 2 SÍ se prueba.

### 9. Enriquecimiento atómico

Escribir los 4 artefactos (RESUMEN + 3 archivos) juntos o ninguno. Si falla entre medio, el bloque queda en su estado anterior.

### 10. ampliar_contexto() propaga estructura hasta RecoveryGenerator

Los bloques externos con estructura cronológica deben generar los 4 archivos de recuperación.

### 11. Pending_tasks persistente en ambos lugares

Persistir pending_tasks en disco en: (a) el bucle D7, (b) la auditoría de la cascada (`_post_bloque()`). Reusando el mismo código. Las pending_tasks pueden caer desde cualquier nivel.

### 12. Bucle D7 como procedimiento encapsulado

Encapsular en clase o función. Procedimiento: revisar falla → corregir prompt → reintentar → verificar → si cumple, fuera; si no, próxima iteración; si 5 intentos agotados, se mantiene en pending_task. No baja niveles.

---

## 4. Baremo táctico

### Criterios de aceptación (12 nuevos de v6.17)

1. Nivel 3 procesa bloques automáticamente dentro del proceso (no pending_tasks sin procesar).
2. El bucle D7 no baja niveles de la cascada. Pasa a pending_task tras 5 intentos.
3. `collect_responses()` solo integra respuestas. No dispara la cascada.
4. El daemon reporta progreso en la frase de control de cada respuesta del agente.
5. El detonante de falta de contexto usa RecoveryCycle.
6. Si `contexto_recuperacion/` existe, el proceso solo audita y completa (no re-extrae).
7. Existe una función única que detecta bloques incompletos (verifica los 4 artefactos).
8. El 429 entre tareas se maneja con ping: si persiste, directo a Nivel 3; si no, Nivel 1.
9. El enriquecimiento escribe los 4 artefactos atómicamente.
10. `ampliar_contexto()` propaga `estructura` hasta `RecoveryGenerator`.
11. Pending_tasks se persisten en disco en el bucle D7 y en `_post_bloque()` (mismo código).
12. El bucle D7 está encapsulado en clase o función, no disperso.

---

**Fin de la spec v6.17.**
