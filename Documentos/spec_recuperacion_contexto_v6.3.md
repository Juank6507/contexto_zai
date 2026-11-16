# contexto_zai/Documentos/spec_recuperacion_contexto_v6.3.md
# Spec v6.3 — Calidad de contexto: pendientes obligatorias, índice preservado, A1 robusto, sort cronológico, resumen riguroso

**Versión:** 6.3
**Fecha:** 2026-09-27
**Autor:** Agente CZAI (Sesión 25, con consenso del Director)
**Estado:** Spec pendiente de implementación.
**Especifica continuación de:** spec v6.2 (fallback al agente con subagentes cuando el proxy APA falla).
**Spec asociada:** esta.
**Plan asociado:** plan_refactorizacion_v6.3.md.

---

## 1. Propósito

La v6.2 resolvió el problema del proxy APA caído (fallback al agente). Pero al
auditar el contexto generado end-to-end con datos reales (chat EP 02 + chat
actual = 80 bloques + 4 archivos de recuperación), el Director detectó **5
defectos** que la v6.3 debe corregir:

1. El proceso termina con tareas pendientes sin ejecutar → el archivo
   `02_decisiones_clave.md` sale vacío ("0 decisiones") aunque hay cientos.
2. El proceso no preserva el índice cuando se fusionan contextos de varios
   chats → `01_indice_recuperacion.md` solo lista los bloques del chat actual,
   no los del EP 02 fusionados después.
3. La sección A1 de `00_estado_actual.md` sale con basura cuando el último
   intercambio real contiene volcados de documentación externa.
4. Los bloques tienen períodos invertidos y exchanges desordenados porque ni
   `ExchangeBuilder` ni `BlockPacker` ordenan por timestamp.
5. Los RESUMEN de los bloques son inconsistentes (5 formatos distintos,
   79% excede 1500 chars) porque el prompt del subagente es demasiado laxo.

Las 5 soluciones son **complementarias y atienden a las 5 decisiones del Director**.

### 1.1. Decisiones del Director (textuales)

> **Problema 1**: Hay que garantizar que no queden tareas pendientes antes de terminar el proceso.
>
> **Problema 2**: Tenemos que garantizar que el proceso siempre genere los índices correspondientes y que no sean eliminados por los procesos subsiguientes.
>
> **Problema 3**: Se tiene que garantizar para el bien de la recuperación que el proceso en esta sección A1 de `00_estado_actual.md` contiene todo el tema completo correspondiente del último intercambio o si es excesivamente muy grande se genere la un truncado inteligente para que lo genere en un tamaño determinado.
>
> **Problema 4**: Correcto (sort cronológico en BlockPacker y ExchangeBuilder).
>
> **Problema 5**: El prompt que hace al agente generar el resumen debe tener parámetros y enfoques rígidos que hagan que se generen resúmenes similares, donde no falte la información pertinente.

## 2. Los 5 problemas que la v6.3 ataca

| # | Problema | Causa raíz | Fase |
|---|---|---|---|
| 1 | `02_decisiones_clave.md` vacío ("0 decisiones") aunque hay cientos | El proceso termina devolviendo `pending_tasks` sin ejecutar; el agente principal no las completa | F1 |
| 2 | `01_indice_recuperacion.md` no lista bloques de chats anteriores (EP 02) | El `IndiceGenerator` solo ve los `blocks` que el proceso generó en esta corrida, ignora los bloques físicos preexistentes en el workspace | F2 |
| 3 | Sección A1 de `00_estado_actual.md` con volcado de docs pytest | `_build_a1()` filtra intercambios virtuales pero no detecta contenido "basura" (volcados externos en el último exchange real) | F3 |
| 4 | Períodos invertidos y exchanges desordenados en bloques | `ExchangeBuilder.build()` no ordena por timestamp; `BlockPacker.pack()` tampoco | F4 |
| 5 | RESUMEN inconsistente (5 formatos, 79% > 1500 chars) | Prompt del subagente es laxo: "máximo 1000 chars" sin estructura rígida | F5 |

## 3. La solución: 5 mejoras quirúrgicas

### 3.1. F1 — Garantizar que no queden tareas pendientes antes de terminar

**Principio**: el proceso `pipeline.run()` NO debe devolver `pending_tasks` sin
haber intentado ejecutarlas todas. Si el proxy APA está disponible, las
ejecuta vía el Worker Bun. Si no, las ejecuta vía fallback al agente (v6.2).
**Solo si ambas fallan**, el proceso las devuelve como pendientes — pero en
ese caso el proceso no debe marcar `success=True`.

**Implementación**: en `pipeline.run()`, después de `_enriquecer_bloques_post_run()`,
añadir un bloque `_ejecutar_pending_tasks_obligatorias()` que:

1. Si `result.pending_tasks` está vacío → continuar.
2. Si no está vacío → intentar `collect_responses()` (que ejecuta las tareas
   vía el proxy APA si está disponible).
3. Si tras `collect_responses()` aún quedan pendientes → el proceso las
   ejecuta síncronamente lanzando los subagentes correspondientes vía el
   `Task tool` del agente (esto requiere que `pipeline.run()` sea llamado por
   el agente principal, que es el caso normal).
4. Si tras todo eso aún quedan pendientes → marcar `result.success=False` y
   loggear el error, pero NO ocultar las pendientes.

**Cambio en `OrchestratorResult`**: añadir campo `pending_tasks_resolved: int`
que cuenta cuántas se ejecutaron con éxito. Si > 0 y queda alguna sin
resolver, loggear warning.

### 3.2. F2 — Preservar índice de chats anteriores (no sobrescribir)

**Principio**: cuando el proceso corre sobre un chat nuevo (Caso 4: otro
chat distinto → RecoveryCycle), el `IndiceGenerator` debe **incluir los
bloques físicos preexistentes en el workspace**, no solo los que el proceso
generó en esta corrida.

**Implementación**: en `IndiceGenerator.generate()`, antes de construir el
mapeo, escanear el `workspace_dir` en busca de `bloque_*.md` existentes que
no estén en la lista `blocks` actual. Añadirlos al mapeo con un flag
`chat_origen: "anterior"` para distinguirlos.

**Cambio en `RecoveryMetadata`**: el campo `chats_procesados` ya existe (v4.4),
pero el `IndiceGenerator` no lo usa. v6.3 hace que el índice incluya una
sección "Bloques de chats anteriores" que lista los bloques que están en
el workspace pero no fueron generados en esta corrida, agrupados por
`chat_id` de origen.

**Garantía de no eliminación**: el `RecoveryCycle._escribir_archivos()`
debe verificar si un archivo `01_indice_recuperacion.md` existe antes de
sobrescribirlo. Si existe, hacer **merge** en vez de sobrescribir:
- Conservar las secciones existentes de "Bloques de chats anteriores".
- Actualizar las secciones del chat actual.
- Nunca eliminar bloques del índice.

### 3.3. F3 — Sección A1 con tema completo + truncado inteligente robusto

**Principio**: la sección A1 debe contener **todo el tema completo del último
intercambio real**, no solo el último mensaje. Si el tema es excesivamente
grande, se aplica el truncado inteligente existente (16K textual + 4K resumen)
— pero el filtrado debe ser más robusto:

**Mejoras al filtro de A1**:

1. **Filtrar volcados externos**: si el contenido del último intercambio
   real es mayor a 10K chars y parece ser un volcado de documentación
   externa (no una respuesta del agente), buscar hacia atrás el último
   intercambio cuyo contenido sea < 10K chars.

2. **Filtrar respuestas "Lee este link:"**: si el último intercambio real
   tiene como `director_msg.content` algo que empieza con "Lee este link:"
   o "Lee este documento:" o "Lee esta URL:", saltar al anterior.

3. **Garantizar tema completo**: en vez de tomar solo el último intercambio,
   tomar **todos los intercambios recientes que pertenezcan al tema activo**
   (no solo el último). Si la suma supera 16K chars, truncar inteligentemente.

**Cambio en `EstadoGenerator._build_a1()`**: añadir parámetro
`ultimo_exchange_real` que ya viene filtrado por el `generate()` principal.
Aplicar el filtro de volcados externos (punto 1) dentro de `_build_a1`.

### 3.4. F4 — Sort cronológico en ExchangeBuilder y BlockPacker

**Principio**: los intercambios deben estar ordenados por `start_timestamp`
antes de empaquetarse en bloques.

**Implementación**:

1. **`ExchangeBuilder.build()`**: al final del método, antes de devolver la
   lista de intercambios, ordenar por `start_timestamp` ascendente:
   ```python
   exchanges.sort(key=lambda ex: ex.start_timestamp)
   ```

2. **`BlockPacker.pack()`**: al inicio del método, para cada tema en
   `exchanges_by_topic`, ordenar los intercambios por `start_timestamp`:
   ```python
   for tema in exchanges_by_topic:
       exchanges_by_topic[tema].sort(key=lambda ex: ex.start_timestamp)
   ```

3. **Verificación**: añadir assert en `__main__` de ambos módulos que verifique
   que los intercambios salen ordenados tras `build()` y `pack()`.

### 3.5. F5 — Prompt de resumen riguroso (formato rígido)

**Principio**: el prompt del subagente resumidor debe ser **rígido** para
garantizar resúmenes similares en estructura y longitud. No debe dejar
libertad al subagente para elegir formato.

**Implementación**: reescribir `PROMPT_RESUMEN` en
`mini-services/worker-cascade/index.ts` con:

1. **Longitud rígida**: "exactamente entre 600 y 900 caracteres" (no "máximo
   1000" que permite 0 o 50).
2. **Estructura rígida**: especificar exactamente 4 oraciones, una por
   aspecto:
   - Oración 1: tema central (1 frase, <100 chars).
   - Oración 2: decisiones principales (1 frase, <200 chars).
   - Oración 3: temas específicos (1 frase, <200 chars).
   - Oración 4: actividad (1 frase, <100 chars).
3. **Prohibiciones explícitas**: sin secciones bold, sin listas, sin
   numeración, sin "Decisiones destacadas:", sin ALL CAPS.
4. **Formato canónico**: un solo párrafo, texto natural, separado por
   puntos.
5. **Ejemplo incluido en el prompt**: mostrar un ejemplo de resumen bien
   formado para que el subagente lo imite.

**Cambio en `mini-services/worker-cascade/index.ts`**: reescribir
`PROMPT_RESUMEN` y `SYSTEM_PROMPT_HEAVY`.

## 4. Lo que se conserva de versiones anteriores

Todo lo de v6.2 y anteriores:

- **Worker Bun v6.1** con las 4 optimizaciones (fusión, backoff, cache, modelo dual).
- **Fallback al agente con subagentes** (v6.2) cuando el proxy APA falla.
- **`_enriquecer_bloques_con_fallback()`** y `_enriquecer_bloques_post_run()`.
- **`ThematicBlock.tiene_resumen()`**.
- **4 archivos de recuperación** (00, 01, 02, 03).
- **Soporte multi-chat** con `chats_procesados` en metadata.
- Todo lo heredado de v5.0, v4.x, etc.

## 5. Lo que se añade en v6.3

- **`pipeline._ejecutar_pending_tasks_obligatorias()`** — ejecuta las
  pending_tasks antes de devolver el resultado.
- **`IndiceGenerator._incluir_bloques_anteriores()`** — escanea el workspace
  en busca de bloques preexistentes y los añade al índice.
- **`RecoveryCycle._merge_indice_si_existe()`** — hace merge del índice
  nuevo con el existente en vez de sobrescribir.
- **`EstadoGenerator._build_a1()` mejorado** — filtra volcados externos y
  garantiza tema completo del último intercambio real.
- **`ExchangeBuilder.build()` con sort** — ordena por timestamp al final.
- **`BlockPacker.pack()` con sort** — ordena por timestamp dentro de cada tema.
- **`PROMPT_RESUMEN` riguroso** en el Worker Bun — formato rígido de 4
  oraciones, 600-900 chars, sin secciones.

## 6. Lo que migra / se queda / se elimina

### 6.1. Migra

| Componente | Antes (v6.2) | Después (v6.3) |
|---|---|---|
| `pipeline.run()` | Devuelve pending_tasks sin ejecutar | Ejecuta pending_tasks antes de devolver |
| `IndiceGenerator` | Solo lista blocks de la corrida actual | Incluye bloques preexistentes del workspace |
| `RecoveryCycle._escribir_archivos()` | Sobrescribe 01_indice si existe | Hace merge del índice |
| `EstadoGenerator._build_a1()` | Filtra virtuales pero no volcados | Filtra volcados externos + tema completo |
| `ExchangeBuilder.build()` | No ordena | Ordena por timestamp al final |
| `BlockPacker.pack()` | No ordena | Ordena por timestamp dentro de cada tema |
| `PROMPT_RESUMEN` (worker-cascade) | Laxo ("máximo 1000 chars") | Rígido (4 oraciones, 600-900 chars, sin secciones) |

### 6.2. Se queda (sin cambios)

- Worker Bun v6.1 (cascada, backoff, cache, modelo dual).
- `_enriquecer_bloques_con_fallback()` (v6.2).
- `_proxy_apa_disponible()` y `_arrancar_worker_y_esperar()` (v6.2).
- 4 archivos de recuperación (estructura y formato).
- `chats_procesados` en metadata.
- Todo el flujo de la Fase 1 (extracción, clasificación, empaquetado).

### 6.3. Se elimina

- El comportamiento de "devolver pending_tasks sin ejecutar" (v6.2 lo permitía).
- El "sobrescribir 01_indice si existe" (v6.3 hace merge).

## 7. Reglas de implementación

- **Cambios quirúrgicos**: solo se modifica lo especificado. No se toca el
  código que ya funciona.
- **Scripts atómicos con auto-tests**: cada módulo intervenido lleva
  auto-tests en `__main__`.
- **OOP**: las nuevas funcionalidades son métodos de las clases existentes.
- **No hardcoding**: límites (longitud de RESUMEN, umbral de volcado) van
  en `config.py`.
- **Comentario en primera línea**: todo archivo intervenido lleva su ruta
  de destino y resumen (DTI regla 6).
- **Tests E2E**: 5 escenarios nuevos que validan los 5 problemas.

## 8. Compatibilidad con v6.2

- Si el proxy APA funciona: el proceso ejecuta las pending_tasks vía Worker
  Bun, no quedan pendientes, `success=True`.
- Si el proxy APA no funciona: el proceso ejecuta las pending_tasks vía
  fallback al agente, no quedan pendientes, `success=True`.
- Si ambas fallan: el proceso devuelve las pending_tasks sin resolver,
  `success=False`, loggea el error.
- El índice siempre preserva los bloques de chats anteriores.
- La sección A1 siempre tiene contenido sustantivo (no basura).
- Los bloques siempre tienen períodos ordenados.
- Los RESUMEN siempre tienen el mismo formato.

## 9. Dependencias nuevas

Ninguna. Todos los cambios son sobre código Python y TypeScript existente.

## 10. Validación

### 10.1. Test E2E 1 — no quedan pendientes

- Mock del proxy APA disponible.
- `pipeline.run()` → Fase 1 + Fase 2 (worker procesa todo) + F1 (ejecuta
  pending_tasks).
- Verificar: `result.pending_tasks == []`, `result.success == True`.

### 10.2. Test E2E 2 — índice preserva chats anteriores

- Workspace con bloques preexistentes (bloque_67 a bloque_80).
- `pipeline.run()` con chat nuevo (genera bloque_01 a bloque_66).
- Verificar: `01_indice_recuperacion.md` lista los 80 bloques, no solo 66.

### 10.3. Test E2E 3 — A1 sin basura

- Último intercambio real con contenido de 20K chars (volcado de docs).
- `pipeline.run()` → sección A1 usa el intercambio anterior (< 10K chars).
- Verificar: A1 no contiene el volcado, contiene el intercambio real.

### 10.4. Test E2E 4 — sort cronológico

- Intercambios desordenados (timestamps 5, 1, 3, 2, 4).
- `pipeline.run()` → bloques con intercambios ordenados 1, 2, 3, 4, 5.
- Verificar: `period_str` de cada bloque tiene fecha inicial < fecha final.

### 10.5. Test E2E 5 — RESUMEN riguroso

- 5 bloques de prueba procesados por el Worker Bun con el nuevo PROMPT_RESUMEN.
- Verificar: todos los RESUMEN están entre 600 y 900 chars, tienen 4 oraciones,
  sin secciones bold/caps/listas.

## 11. Configuración nueva en `config.py`

```python
# v6.3: Calidad de contexto
RESUMEN_MIN_CHARS = 600   # longitud mínima del RESUMEN
RESUMEN_MAX_CHARS = 900   # longitud máxima del RESUMEN
A1_VOLCADO_UMBRAL_CHARS = 10000  # contenido > 10K se considera volcado externo
INDICE_PRESERVAR_ANTERIORES = True  # incluir bloques de chats anteriores
```

---

**Fin de la spec v6.3.**
