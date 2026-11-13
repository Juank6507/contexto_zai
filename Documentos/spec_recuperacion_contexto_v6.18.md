# contexto_zai/Documentos/spec_recuperacion_contexto_v6.18.md
# Spec v6.18 — Orquestación del flujo ampliar_contexto + RecoveryCycle + BlockPacker

**Versión:** 6.18
**Fecha:** 2026-11-13
**Estado:** Pendiente de implementación.
**Especifica continuación de:** spec v6.17.
**Sesión origen:** CZAI 6a00fcb8, elemento C del método DCEPI conciliado.

---

## 1. Propósito

Conectar el flujo completo cuando `contexto_recuperacion/` no existe: `ampliar_contexto` → RecoveryCycle → collect_responses → cascada. Reusar RecoveryCycle y BlockPacker para bloques externos con estructura cronológica. Asegurar que P16 (auditoría final) siempre se realiza tras procesar.

---

## 2. Orden del proceso (19 pasos, sin cambios)

El pipeline se mantiene en 19 pasos. v6.18 corrige la orquestación del flujo.

---

## 3. Decisiones conciliadas

### 1. ampliar_contexto con estructura cronológica pasa por RecoveryCycle y continúa el pipeline completo

Cuando `ampliar_contexto()` detecta `estructura = "cronologico"`, el flujo debe pasar por `RecoveryCycle` que ya construye intercambios (P5), clasifica por tema (P6), y usa `BlockPacker` para ordenar bloques por timestamp descendente (P7). Tras RecoveryCycle, el proceso debe continuar automáticamente con el resto del pipeline: `collect_responses()` → verificar bloques incompletos → disparar cascada → P16 + P17 + P18 + P19.

El flujo completo cuando `contexto_recuperacion/` no existe:
1. `ampliar_contexto()` detecta estructura (P4.2).
2. Si `estructura = "cronologico"`: pasa por RecoveryCycle (construye intercambios, clasifica, BlockPacker ordena descendente, genera bloques físicos + archivos 00-03).
3. Si `estructura = "arbitrario"`: va por ProcesadorDocumento (sin RecoveryCycle, sin BlockPacker).
4. Tras generar los bloques físicos, el proceso continúa: `collect_responses()` integra → verifica bloques incompletos → dispara cascada → P16 + P17 + P18 + P19.
5. Si el archivo es grande y hay pending_tasks de extracción (caso arbitrario), los subagentes extraen antes de `collect_responses()`.

**Fix v6.18:** `ampliar_contexto()` con estructura cronológica NO debe hacer `return` tras RecoveryCycle. Debe continuar con el resto del pipeline.

**Nota sobre número de bloques:** RecoveryCycle agrupa por tamaño de tokens (hasta 70K por bloque). 649 intercambios en bloques de ~70K tokens = 22 bloques (no 50). Esto es correcto: ProcesadorDocumento dividía por líneas fijas (~30K tokens/bloque = 50 bloques). RecoveryCycle divide por tokens (~70K tokens/bloque = 22 bloques).

### 2. BlockPacker para bloques externos cronológicos

Reusar código vía BlockPacker. Cuando `ampliar_contexto()` procesa un archivo con `estructura = "cronologico"`, los bloques deben ordenarse por timestamp descendente (bloque_01 = más reciente). Esto se logra pasando por RecoveryCycle que ya usa BlockPacker.

### 3. P2 no se realiza si no existe contexto_recuperacion

Si `contexto_recuperacion/` no existe, P2 (auditoría inicial) no se realiza — carece de sentido auditar lo que no existe. El proceso va directo a procesar la fuente.

### 4. P16 siempre se realiza tras procesar

P16 (auditoría final) SIEMPRE se realiza después de procesar, sin importar si el contexto existía previamente o se creó desde cero. P16 verifica el estado real del workspace tras el enriquecimiento.

### 5. collect_responses() se invoca tras la extracción de subagentes

El flujo orquestado depende de la estructura detectada:

**Si estructura = cronológica:**
`ampliar_contexto` → RecoveryCycle (construye intercambios, clasifica, BlockPacker ordena descendente, genera bloques) → subagentes extraen contenido → `collect_responses()` integra → proceso verifica incompletos → dispara cascada → P16 + P17 + P18 + P19.

**Si estructura = no cronológica (arbitraria):**
`ampliar_contexto` → ProcesadorDocumento (divide en lotes, publica pending_tasks) → subagentes extraen contenido → `collect_responses()` integra → proceso verifica incompletos → dispara cascada → P16 + P17 + P18 + P19.

La diferencia: cronológica pasa por RecoveryCycle (con BlockPacker), no cronológica no pasa por RecoveryCycle. Ambos flujos terminan con collect_responses → cascada → P16+P17+P18+P19.

---

## 4. Baremo táctico

### Criterios de aceptación (5 nuevos de v6.18)

1. Cuando `ampliar_contexto()` detecta `estructura = "cronologico"`, pasa por RecoveryCycle.
2. Los bloques externos cronológicos se ordenan por timestamp descendente (bloque_01 = más reciente) vía BlockPacker.
3. Si `contexto_recuperacion/` no existe, P2 no se realiza.
4. P16 siempre se realiza tras procesar.
5. El flujo ampliar_contexto → RecoveryCycle → collect_responses → cascada → P16+P17+P18+P19 está orquestado en el daemon.

---

**Fin de la spec v6.18.**
