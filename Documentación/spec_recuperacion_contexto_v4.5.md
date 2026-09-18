# contexto_zai/Documentación/spec_recuperacion_contexto_v4.5.md
# Spec v4.5 — Índices multi-bloque + 03_objetivo_proyecto ampliado + eliminación de 04_resumenes

**Versión:** 4.5
**Fecha:** 2026-09-18
**Autor:** Agente CZAI (Sesión 19, con consenso del Director)
**Estado:** Pendiente de validación por el Director.
**Especifica continuación de:** spec v4.4 (sistema de indexado consistente + multi-chat + subagentes cableados).
**Spec asociada:** esta.
**Plan asociado:** plan_refactorizacion_v4.5.md.

---

## 1. Propósito

La v4.5 corrige 3 cosas que quedaron mal en v4.4:

1. **El índice no permite que un tema apunte a varios bloques** — cuando varios chats coexisten, un mismo tema puede estar en bloques de chats distintos. Hoy el código revienta con `ValueError` porque asume unicidad estricta.

2. **El `03_objetivo_proyecto.md` está incompleto** — solo tiene el objetivo del proyecto. Debe tener también: quién es el agente, qué le pasó (pérdida de contexto), y cómo recuperarse siguiendo el camino del proceso.

3. **El `04_resumenes_bloques.md` no debía existir** — fue creado en v4.4 sin consenso. Los resúmenes viven dentro de los bloques (`RESUMEN:`), no en un archivo aparte.

## 2. Los 4 archivos de recuperación (orden de lectura)

El agente, al recuperar contexto, lee los 4 archivos en este orden:

| Orden | Archivo | Qué le dice al agente |
|---|---|---|
| 1º | `03_objetivo_proyecto.md` | Quién es, qué hace, qué le pasó y cómo recuperarse |
| 2º | `00_estado_actual.md` | Qué estaba pasando (última instrucción, restricciones, entregables, errores, siguiente paso) + G0.A + G0.B + G1 |
| 3º | `01_indice_recuperacion.md` | Mapa de temas → bloques |
| 4º | `02_decisiones_clave.md` | Decisiones formales del Director con alcance |

El `03` es el primero porque, antes de saber qué estaba haciendo, el agente necesita saber quién es, qué le pasó y cómo puede recuperarse. Con ese marco, después lee el estado actual, el índice y las decisiones.

## 3. El `03_objetivo_proyecto.md` ampliado

### 3.1. Qué contiene

El archivo pasa de tener un solo componente (el objetivo) a tener **3 componentes**:

#### Componente 1 — Quién es el agente

- Quién es el agente: su rol, su proyecto, su identidad.
- De dónde sale: de la documentación del proyecto (`estrategia/agent-context/identidad.md`) o, si no existe, derivado de los bloques existentes.
- Es relativamente fijo: cambia poco entre recuperaciones.

#### Componente 2 — Qué hace y cuál es el norte

- El objetivo del proyecto: por qué existe, qué se persigue, qué es lo importante.
- De dónde sale: de la documentación del proyecto (`estrategia/agent-context/proyecto.md`) o de la cascada documentación → bloques → contenido mínimo (lo que ya estaba en v4.3 F5).
- Es fijo: lo declara el agente o el Director al arrancar.

#### Componente 3 — Qué te pasó y cómo recuperarte

- Qué le pasó al agente: perdió contexto (se le comprimió la ventana, se quedó sin saber dónde está).
- Cómo puede recuperarse: el camino que el proceso le dicta:
  1. Estás leyendo este archivo — ya empezaste a recuperarte.
  2. Lee `00_estado_actual.md` para saber qué estaba pasando.
  3. Consulta `01_indice_recuperacion.md` para saber dónde está cada tema.
  4. Revisa `02_decisiones_clave.md` para no repetir lo ya decidido.
  5. Si necesitas detalle de un tema, usa `query_context("tu pregunta")`.
  6. Si el proceso te dejó tareas pendientes (`_pending_tasks.json`), lánzalas con el Task tool y llama `collect_responses()`.
  7. Si el Director te pasa información nueva, usa `ampliar_contexto()`.
- Este componente es **fijo**: el proceso lo escribe como template. No cambia entre recuperaciones.

### 3.2. Quién lo escribe

- **Componente 1 y 2**: el proceso los crea automáticamente con la cascada documentación → bloques → contenido mínimo (igual que v4.3 F5). El agente o el Director pueden editar el archivo después para corregir o ampliar.
- **Componente 3**: el proceso lo escribe como template fijo. No se deriva, se incluye siempre.
- **Si el archivo ya existe**: el proceso no lo sobrescribe (respeta lo que el agente/Director escribió).

### 3.3. Formato

```markdown
# Recuperación de contexto del proyecto

## Quién eres

<nombre del agente, su rol, su proyecto>

## Cuál es tu norte

<objetivo del proyecto: por qué existe, qué se persigue>

## Qué te pasó y cómo recuperarte

Has perdido contexto. Esto es normal y tienes un proceso que te ayuda.

1. Estás leyendo este archivo — ya empezaste a recuperarte.
2. Lee `00_estado_actual.md` para saber qué estaba pasando.
3. Consulta `01_indice_recuperacion.md` para saber dónde está cada tema.
4. Revisa `02_decisiones_clave.md` para no repetir lo ya decidido.
5. Si necesitas detalle de un tema, usa `query_context("tu pregunta")`.
6. Si el proceso te dejó tareas pendientes, lánzalas y llama `collect_responses()`.
7. Si el Director te pasa información nueva, usa `ampliar_contexto()`.
```

## 4. El índice `tema_a_archivo` multi-bloque

### 4.1. El cambio

Hoy `tema_a_archivo` es `dict[str, str]` (tema → un archivo). Pasa a ser `dict[str, list[str]]` (tema → varios archivos).

Esto permite que un tema como `configuracion_proyecto` apunte a bloques de distintos chats. El agente, cuando consulta ese tema, encuentra todos los bloques que lo contienen.

### 4.2. `registrar_tema()` arreglado

Hoy `registrar_tema()` revienta si el tema ya existe en otro archivo:

```python
raise ValueError("Violación de unicidad: tema 'X' ya está en 'bloque_A.md'")
```

Pasa a:

- Si el tema no existe → crear entrada con la lista `[archivo]`.
- Si el tema existe y el archivo ya está en la lista → no hacer nada (idempotente).
- Si el tema existe y el archivo no está en la lista → añadir el archivo a la lista.

No revienta nunca. Un tema puede apuntar a tantos bloques como sea necesario.

### 4.3. Impacto en `query_context()`

Cuando el agente consulta un tema, `query_context()` encuentra todos los bloques que lo contienen (no solo uno). Si el tema está en 3 bloques, prepara prompts para que el agente pueda consultar los 3.

### 4.4. Impacto en `01_indice_recuperacion.md`

El índice legible muestra cada tema con todos los bloques donde aparece. Si `configuracion_proyecto` está en `bloque_01.md` y `bloque_15.md`, el índice muestra ambos.

### 4.5. Impacto en el `IndiceGenerator`

`IndiceGenerator._build_tema_a_archivo()` pasa de devolver `dict[str, str]` a `dict[str, list[str]]`.

## 5. Los resúmenes viven en los bloques

### 5.1. Eliminación del `04_resumenes_bloques.md`

El archivo `04_resumenes_bloques.md` y el `ResumenesGenerator` se eliminan. No estaban consensuados y no deben existir.

### 5.2. Los resúmenes viven en los bloques

Cada bloque (`bloque_*.md` y `bloque_externo_*.md`) contiene un campo `RESUMEN:` que el subagente indexador escribió. Ese es el sitio donde viven los resúmenes.

### 5.3. `query_context()` lee resúmenes de los bloques

Cuando `query_context()` identifica bloques candidatos, antes de preparar prompts para subagentes, lee el `RESUMEN:` de cada bloque candidato directamente del archivo físico. Si un resumen responde la pregunta, se lo entrega al agente directamente. Si no, prepara prompts para subagentes.

No hay archivo aparte. El `query_context()` lee de los bloques.

## 6. Lo que se conserva de versiones anteriores

- Todos los principios de v4.2, v4.3 y v4.4.
- La lógica de decisión de 4 casos del `Orchestrator` (v4.4 F1).
- El soporte multi-chat en metadata (v4.4 F2).
- El `IncrementalCycle` con reempaquetado selectivo + regenera índice + acepta `share_id` (v4.4 F3).
- Los subagentes cableados por defecto (v4.4 F5).
- Las secciones G0.A, G0.B, G1 del `00_estado_actual.md` (v4.3).
- La creación automática de `03_objetivo_proyecto.md` con la cascada (v4.3 F5).

## 7. Lo que se añade en v4.5

- `tema_a_archivo` pasa de `dict[str, str]` a `dict[str, list[str]]`.
- `registrar_tema()` arreglado: no revienta, añade a la lista.
- `03_objetivo_proyecto.md` ampliado con 3 componentes (quién es, norte, qué pasó y cómo recuperarse).
- Orden de lectura de los 4 archivos: `03` primero.
- `query_context()` lee resúmenes directamente de los bloques físicos.

## 8. Lo que se desmonta

- `04_resumenes_bloques.md` — se elimina (no debía existir).
- `generation/resumenes_generator.py` — se elimina.
- `_buscar_en_resumenes()` en `pipeline.py` — se elimina y se reemplaza por lectura directa de bloques.
- El modo `resumen_atajo` en `query_context()` — se reemplaza por lectura directa de `RESUMEN:` de los bloques candidatos.

## 9. Reglas de implementación

- **Cambios quirúrgicos:** solo se modifica lo especificado.
- **Scripts atómicos y standalone:** cada archivo intervenido lleva auto-tests en `__main__`.
- **OOP:** las nuevas funcionalidades son responsabilidad de las clases existentes.
- **No hardcoding:** las constantes nuevas van en `config.py`.
- **Tests individuales:** cada módulo intervenido actualiza sus auto-tests.
- **Tests E2E:** `tests/test_v42_e2e.py` se amplía con tests que validan el índice multi-bloque y el `03` ampliado.
- **Comunicación de errores:** ningún subagente falla silenciosamente.
- **Lo que funciona se conserva.**

## 10. Compatibilidad con v4.4

- Si el `_metadata.json` tiene `tema_a_archivo` en formato viejo (`dict[str, str]`), el proceso lo migra automáticamente a formato nuevo (`dict[str, list[str]]`) al leer.
- Los archivos existentes (`00_estado_actual.md`, `01_indice_recuperacion.md`, `02_decisiones_clave.md`, `03_objetivo_proyecto.md`) se conservan.
- Las funciones públicas mantienen su signature.

## 11. Validación

- **`registrar_tema()` multi-bloque:** auto-test que registra el mismo tema en 2 bloques distintos sin que reviente.
- **`tema_a_archivo` multi-bloque:** auto-test que verifica que un tema apunta a varios bloques.
- **Migración de formato viejo:** auto-test que migra `dict[str, str]` a `dict[str, list[str]]`.
- **`03_objetivo_proyecto.md` ampliado:** auto-test que verifica los 3 componentes.
- **`query_context()` con resúmenes de bloques:** auto-test que lee `RESUMEN:` directamente de los bloques.
- **Test E2E:** flujo completo: procesar 2 chats con temas comunes → índice multi-bloque → `query_context` encuentra info de ambos.

---

**Fin de la spec v4.5.**
