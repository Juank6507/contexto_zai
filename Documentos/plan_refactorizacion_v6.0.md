# contexto_zai/Documentación/plan_refactorizacion_v6.0.md
# Plan v6.0 — Limpieza de bloques + Cascada de workers para resúmenes

**Versión:** 6.0
**Fecha:** 2026-09-25
**Autor:** Agente CZAI (Sesión 22, con consenso del Director)
**Estado:** Fases 1-3 implementadas. Fases 4-7 en implementación.
**Continúa de:** plan v5.0 (proxy de subagentes + separación de plataforma).
**Spec asociada:** spec_recuperacion_contexto_v6.0.md.

---

## Estructura del plan

El plan se organiza en 7 fases (F1-F7), divididas en dos bloques:

**Bloque Limpieza (F1-F3)** — fixes que se aplicaron durante la
implementación de v6.0 para desbloquear la cascada. Ya están aplicados y
validados.

**Bloque Cascada (F4-F7)** — montaje del Worker Bun persistente y la
cascada de workers. En implementación.

1. F1 — `BlockPacker.pack()` reparte intercambios de temas grandes.
2. F2 — `RecoveryMetadata.tema_a_archivo` multi-bloque + `registrar_tema()`
   idempotente + `query_context()` y `ProcesadorConsulta` adaptados.
3. F3 — `EstadoGenerator` (4 fixes reaplicados) + `ContentCleaner._parse_tool_calls()`.
4. F4 — Worker Bun persistente (puerto 8090) + Worker 1 (resumen al inicio del bloque).
5. F5 — Workers 2-4 en paralelo sobre el resumen (nombre, decisiones, temas).
6. F6 — Integrador reformado (aplica las 4 respuestas juntas) + consulta multi-bloque.
7. F7 — Tests E2E + medición de latencia.

**Total de archivos nuevos:** ~3 (Worker Bun, su package.json, su _lib.ts
  reutilizando el patrón del proxy v5.0).
**Total de archivos intervenidos:** ~8 (`processing/block_packer.py`,
  `models.py`, `pipeline.py`, `procesadores/procesador_consulta.py`,
  `generation/estado_generator.py`, `processing/content_cleaner.py`,
  `coordinador/integrador_respuestas.py`, `config.py`).
**Tests nuevos:** 10 atómicos + 3 E2E.

---

## F1 — `BlockPacker.pack()` reparte intercambios de temas grandes

**Prioridad:** ALTA — es el bug que aborta el proceso cuando un tema supera 70K.
**Dependencias:** ninguna.
**Estado:** ✅ Implementado.
**Estimación:** 0.5 sesión.

### Qué se hace

1. **`BlockPacker.pack()`** (`processing/block_packer.py`):
   - Antes: si un tema individual superaba `max_tokens_bloque` (70K), lanzaba
     `ValueError` y abortaba el proceso entero.
   - Ahora: detecta el tema grande y **lo reparte en varios bloques**, sin
     pasar por el `Subdivider`.
   - El reparto es **por intercambios completos**: no se corta un
     intercambio por la mitad.
   - Cada bloque resultante lleva el encabezado del tema, con sufijo
     `_parte_N` si hay más de uno (ej: `autenticacion_jwt_parte_1`,
     `autenticacion_jwt_parte_2`).
   - El `Subdivider` sigue existiendo para subdividir por subtemas (cuando
     el tema es grande pero heterogéneo). El `BlockPacker` solo actúa
     cuando el tema no cabe en un bloque aunque sea homogéneo.

2. **Tests atómicos actualizados**:
   - El test existente "tema que supera el límite → ValueError" se
     reemplaza por "tema que supera el límite → se reparte en N bloques".
   - Test nuevo: tema que supera 2× el límite → 2 bloques.
   - Test nuevo: tema que supera 3× el límite → 3 bloques.
   - Test nuevo: intercambio individual que supera el límite (edge case
     extremo) → se queda en su propio bloque con warning.

### Tests individuales

- Test: tema individual >70K → se reparte en 2+ bloques, sin `ValueError`.
- Test: cada bloque resultante respeta el límite de 70K.
- Test: los intercambios no se cortan por la mitad (un intercambio va
  completo en un bloque).
- Test: el encabezado del tema lleva sufijo `_parte_N` si hay más de uno.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/processing/block_packer.py
```

---

## F2 — `RecoveryMetadata` multi-bloque + adaptadores

**Prioridad:** ALTA — desbloquea la consulta multi-bloque (F6).
**Dependencias:** F1 (el `BlockPacker` reparte temas en varios bloques, así
  que el `tema_a_archivo` tiene que soportar varios archivos por tema).
**Estado:** ✅ Implementado.
**Estimación:** 1 sesión.

### Qué se hace

1. **`RecoveryMetadata.tema_a_archivo`** (`models.py`):
   - Cambia de `dict[str, str]` a `dict[str, list[str]]`.
   - Cada tema apunta a una **lista de archivos** donde aparece.
   - Migración automática: si el `_metadata.json` tiene el formato viejo,
     se migra la primera vez que se lee (cada `str` se convierte en
     `list[str]` con un solo elemento).

2. **`RecoveryMetadata.registrar_tema()`** (`models.py`):
   - Antes: lanzaba `ValueError` si el tema ya estaba en otro archivo
     (unicidad estricta).
   - Ahora: es **idempotente**. Si el tema no existe, lo crea con
     `[archivo]`. Si existe y el archivo no está en la lista, lo añade. Si
     ya está, no hace nada (no duplica).
   - El método `archivo_para_tema(tema)` ahora devuelve `list[str]` (o
     `list[str] | None` para mantener compatibilidad con `Optional`).

3. **`query_context()`** (`pipeline.py`):
   - Antes: leía el primer archivo de `tema_a_archivo[tema]` (un `str`).
   - Ahora: lee **todos los archivos** de la lista. Si el proxy v5.0 está
     disponible, lanza las lecturas en paralelo; si no, secuencialmente.
   - Las respuestas se consolidan (si hay 3 bloques con el tema, la
     respuesta es la unión de las 3 respuestas de subagente).

4. **`ProcesadorConsulta`** (`procesadores/procesador_consulta.py`):
   - Igual que `query_context()`: maneja `dict[str, list[str]]` y lee
     todos los bloques donde aparece el tema.

### Tests individuales

- Test: `registrar_tema("x", "a")` seguido de `registrar_tema("x", "b")`
  → `tema_a_archivo["x"] == ["a", "b"]`.
- Test: `registrar_tema("x", "a")` seguido de `registrar_tema("x", "a")`
  → `tema_a_archivo["x"] == ["a"]` (idempotente, no duplica).
- Test: migración automática de formato viejo (`dict[str, str]`) a nuevo
  (`dict[str, list[str]]`).
- Test: `query_context("tema_en_3_bloques")` lee los 3 bloques.
- Test: `ProcesadorConsulta` lee los 3 bloques y consolida respuestas.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/models.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/pipeline.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/procesadores/procesador_consulta.py
```

---

## F3 — `EstadoGenerator` (4 fixes reaplicados) + `ContentCleaner._parse_tool_calls()`

**Prioridad:** ALTA — calidad del contenido de los bloques y del `00_estado_actual.md`.
**Dependencias:** ninguna (independiente de F1/F2).
**Estado:** ✅ Implementado.
**Estimación:** 1.5 sesiones.

### Qué se hace

#### F3a — `EstadoGenerator` D1: filtra "Lee este link:"

- Antes: si el último mensaje del Director era "Lee este link: ..." (un
  mensaje virtual que el agente inserta cuando el Director le pasa un link
  `/s/`), D1 lo usaba como instrucción literal.
- Ahora: D1 busca el último intercambio **real** del Director (mensaje
  del Director con contenido real, no virtual).

#### F3b — `EstadoGenerator` A1: filtra virtuales + último exchange real

- Antes: A1 podía decir "el agente estaba leyendo un link" si el último
  intercambio era virtual.
- Ahora: A1 filtra intercambios virtuales y usa el último exchange real
  para determinar el tema activo.

#### F3c — `EstadoGenerator` A2: filtra JSON de `tool_calls`

- Antes: A2 detectaba rutas de archivos dentro del JSON crudo de
  `tool_calls` (porque el JSON contenía rutas como argumentos).
- Ahora: A2 solo procesa contenido limpio (gracias a F3e, el contenido
  limpio no tiene JSON crudo de `tool_calls`).

#### F3d — `EstadoGenerator` A3: filtra virtuales y `tool_calls`

- Antes: A3 detectaba "error" dentro de JSON de `tool_calls` (por ejemplo,
  en el argumento `description` de un Bash que decía "fix del error de
  autenticación").
- Ahora: A3 filtra intercambios virtuales y el contenido de `tool_calls`.
  Solo busca errores en el contenido real del agente.

#### F3e — `ContentCleaner._parse_tool_calls()` (nuevo método)

Nuevo método en `processing/content_cleaner.py` que parsea los
`tool_calls` del contenido del agente y los formatea como **bloques
legibles**:

| tool_call | Formato legible |
|---|---|
| `Write` | `Archivo creado: ruta` + bloque de código con el contenido |
| `Edit` | `Archivo modificado: ruta` |
| `Bash` | `Comando: descripción` + bloque bash con el comando |
| `Read` | `Lectura: ruta` |
| `Task` | `Subagente lanzado: descripción` |

El JSON crudo de `tool_calls` se elimina del contenido limpio. El método
se invoca desde `format_message_content()` cuando el rol es `assistant` y
el contenido contiene `tool_calls`.

**Estructura del método**:

```python
def _parse_tool_calls(self, content: str) -> str:
    """Parsea los tool_calls del contenido del agente y los formatea
    como bloques legibles. Elimina el JSON crudo.
    
    Detecta bloques JSON con clave `tool_calls` (o `tool_call`) y los
    reemplaza por texto legible. Mantiene el resto del contenido.
    """
    # 1. Buscar bloques JSON con tool_calls
    # 2. Parsearlos
    # 3. Formatear cada tool_call con _format_single_tool()
    # 4. Eliminar el JSON crudo del contenido
    # 5. Devolver contenido + bloques legibles
```

### Tests individuales

- Test D1: último mensaje del Director es "Lee este link: ..." → D1
  devuelve la instrucción real anterior.
- Test A1: último intercambio es virtual → A1 usa el último exchange real.
- Test A2: contenido con JSON de `tool_calls` → A2 no detecta rutas dentro
  del JSON.
- Test A3: `tool_call` Bash con `description` que contiene "error" → A3 no
  lo marca como error.
- Test `_parse_tool_calls()` con cada tipo (Write, Edit, Bash, Read, Task).
- Test `_parse_tool_calls()` con contenido mixto (texto + JSON de
  `tool_calls` + texto).
- Test `_parse_tool_calls()` sin `tool_calls` (no rompe).

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/estado_generator.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/processing/content_cleaner.py
```

---

## F4 — Worker Bun persistente + Worker 1 (resumen)

**Prioridad:** ALTA — es el corazón de la cascada.
**Dependencias:** F1, F2, F3 (los bloques que lee el Worker 1 tienen que
  estar limpios y bien empaquetados).
**Estado:** 🚧 En implementación.
**Estimación:** 2 sesiones.

### Qué se hace

1. **Crear `mini-services/worker-cascade/index.ts`** — servicio Bun que:
   - Escucha en el **puerto 8090** (configurable en `config.py`:
     `WORKER_CASCADE_PORT = 8090`).
   - Lee `_pending_blocks.json` periódicamente (cada 2 segundos).
   - Para cada bloque pendiente, lanza **Worker 1**:
     - Lee el bloque completo de disco (`workspace/bloques/bloque_NN.md`).
     - Llama al LLM (`internal-api.z.ai/v1/chat/completions`) con un prompt
       enfocado que pide:
       - **Tema central** del bloque (1-2 frases).
       - **Decisiones** que se tomaron (lista de bullets).
       - **Temas** que aparecen (lista de keywords).
       - **Actividad** del agente (qué hizo: archivos creados, comandos,
         subagentes lanzados).
     - El prompt es **específico para el resumen**: no es el prompt de
       `RESUMEN_TRUNCADO` de v4.4 (que era para contenido truncado), es
       uno nuevo optimizado para bloques completos.
   - El resumen se escribe al inicio del bloque físico, como un bloque
     `## RESUMEN DEL BLOQUE` antes del primer intercambio.
   - El bloque se marca como procesado (se elimina de
     `_pending_blocks.json`).
   - Se publica una **señal** en `_responses/{block_id}_resumen.txt`
     para que el Integrador sepa que el Worker 1 terminó.

2. **Crear `mini-services/worker-cascade/package.json`** — dependencias
   del Worker Bun.

3. **Crear `mini-services/worker-cascade/_lib.ts`** — reutiliza el patrón
   del proxy de APA y del proxy v5.0 (lee `/etc/.z-ai-config`, reenvía a
   `internal-api.z.ai`).

4. **Intervenir `coordinador/orquestador.py`**:
   - Detecta si el Worker Bun está corriendo (verificar si responde en
     el puerto 8090).
   - Si está: el proceso publica bloques en `_pending_blocks.json` y no
     espera — el Worker Bun los procesa en background.
   - Si no está: el proceso funciona como hoy (subagentes efímeros vía
     proxy v5.0 o Task tool).

5. **Intervenir `config.py`**:
   - `WORKER_CASCADE_PORT = 8090`
   - `WORKER_CASCADE_ENABLED = True/False` (detectable automáticamente).
   - `WORKER_CASCADE_POLL_INTERVAL = 2` (segundos).
   - `WORKER_CASCADE_TIMEOUT = 60` (segundos por bloque).

### Tests individuales

- Test: el Worker Bun lee un bloque de `_pending_blocks.json` y escribe
  el resumen al inicio del bloque físico.
- Test: el bloque procesado se elimina de `_pending_blocks.json`.
- Test: el Worker Bun maneja errores del LLM (timeout, 500) sin morir.
- Test: si el Worker Bun no está corriendo, el proceso funciona como
  hoy (backward compatible).

### Validación

```bash
cd /home/z/my-project/mini-services/worker-cascade && bun run dev
# En otra terminal:
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 -c "
from contexto_zai.coordinador import Orquestador
orch = Orquestador(workspace_dir='/tmp/test_cascade')
# Publicar un bloque pendiente
orch.publicar_bloque_pendiente('bloque_01')
# Esperar a que el Worker Bun lo procese
import time; time.sleep(30)
# Verificar que el bloque tiene el resumen al inicio
from pathlib import Path
bloque = Path('/tmp/test_cascade/bloques/bloque_01.md').read_text()
assert '## RESUMEN DEL BLOQUE' in bloque
print('[OK] Worker Bun escribió el resumen')
"
```

---

## F5 — Workers 2-4 en paralelo sobre el resumen

**Prioridad:** ALTA — completa la cascada.
**Dependencias:** F4 (necesita Worker 1 y el resumen escrito).
**Estado:** 🚧 En implementación.
**Estimación:** 1.5 sesiones.

### Qué se hace

1. **Extender `mini-services/worker-cascade/index.ts`**:
   - Una vez que Worker 1 terminó (señal en `_responses/{block_id}_resumen.txt`),
     lanza en paralelo:
     - **Worker 2 (nombre legible)**: lee el resumen (3-5K) y produce un
       nombre legible para el bloque (ej: `autenticacion_jwt_e2e`).
     - **Worker 3 (decisiones)**: lee el resumen y extrae decisiones
       formales con alcance (quién, qué, alcance, fecha).
     - **Worker 4 (temas principales)**: lee el resumen y extrae los
       temas principales con pesos (frecuencia + relevancia).
   - Los 3 workers escriben sus respuestas en:
     - `_responses/{block_id}_nombre.txt`
     - `_responses/{block_id}_decisiones.txt`
     - `_responses/{block_id}_temas.txt`
   - El pipeline es **asincrónico**: el proceso no bloquea esperando a
     Workers 2-4. Cuando el agente llama a `collect_responses()`, el
     proceso integra las que estén listas.

2. **Paralelismo real**: los 3 workers corren como peticiones HTTP
   simultáneas al LLM. No es "paralelo" vía el agente (que consume
   tokens), es paralelo real en el Worker Bun.

3. **Reintentos**: si un worker falla (timeout, 500), el Worker Bun lo
   reintenta 2 veces antes de marcarlo como fallido.

### Tests individuales

- Test: Worker 2 produce un nombre legible (no `bloque_03`).
- Test: Worker 3 extrae decisiones con alcance (no lista genérica).
- Test: Worker 4 extrae temas principales con pesos.
- Test: los 3 workers corren en paralelo (latencia total ≈ la del más
  lento, no la suma).
- Test: si un worker cae, los demás siguen.

### Validación

```bash
cd /home/z/my-project/mini-services/worker-cascade && bun run dev
# En otra terminal:
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 -c "
# Publicar un bloque, esperar a que Worker 1 + Workers 2-4 terminen
from contexto_zai.coordinador import Orquestador
from pathlib import Path
import time
orch = Orquestador(workspace_dir='/tmp/test_cascade')
orch.publicar_bloque_pendiente('bloque_02')
time.sleep(60)  # Worker 1 + Workers 2-4
# Verificar que las 3 respuestas están
for suf in ['nombre', 'decisiones', 'temas']:
    p = Path(f'/tmp/test_cascade/_responses/bloque_02_{suf}.txt')
    print(f'{suf}: {\"OK\" if p.exists() else \"FALTA\"}')
"
```

---

## F6 — Integrador reformado + consulta multi-bloque

**Prioridad:** ALTA — aplica las 4 respuestas de la cascada y permite
  consultar temas repartidos en varios bloques.
**Dependencias:** F4, F5.
**Estado:** 🚧 En implementación.
**Estimación:** 1 sesión.

### Qué se hace

#### F6a — `IntegradorRespuestas` reformado (`coordinador/integrador_respuestas.py`)

- Antes: integraba respuestas una por una (cada subagente entregaba una
  respuesta, y se aplicaba secuencialmente al índice, metadata, etc.).
- Ahora: aplica **las 4 respuestas de un bloque juntas** (resumen +
  nombre + decisiones + temas), porque están correlacionadas y juntas
  dan el cuadro completo.
- Si falta alguna de las 4 (Worker caído, timeout), espera un ciclo
  antes de aplicar las que tenga. Si pasan 2 ciclos sin que lleguen
  todas, aplica las disponibles y marca el bloque como incompleto.
- Nuevo método: `integrar_bloque_completo(block_id) -> bool` que lee las
  4 respuestas, las aplica juntas (resumen ya está en el bloque físico,
  nombre va al índice, decisiones van a `02_decisiones_clave.md`, temas
  van al `tema_a_archivo` de la metadata), y devuelve `True` si todas
  llegaron.

#### F6b — Consulta de bloque reformada (`procesadores/procesador_consulta.py`)

- Antes: cuando el agente consultaba un tema, el `ProcesadorConsulta`
  leía **un solo bloque** (el primero que aparecía en `tema_a_archivo`).
- Ahora: usa el índice (ya actualizado en F2) y lee **todos los bloques
  donde aparece el tema** (gracias a `dict[str, list[str]]`).
- Si el tema está en 3 bloques, lanza 3 consultas (en paralelo si el
  proxy v5.0 está disponible) y consolida las 3 respuestas en una sola.
- La consolidación es simple: si las 3 respuestas coinciden en lo
  esencial, devuelve una respuesta unificada. Si difieren, devuelve las
  3 con su bloque de procedencia.

### Tests individuales

- Test: `IntegradorRespuestas.integrar_bloque_completo()` aplica las 4
  respuestas juntas.
- Test: si falta una respuesta, espera un ciclo antes de aplicar.
- Test: si faltan 2 respuestas tras 2 ciclos, aplica las disponibles y
  marca el bloque como incompleto.
- Test: `ProcesadorConsulta` lee los 3 bloques donde aparece un tema.
- Test: `ProcesadorConsulta` consolida las 3 respuestas en una sola.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/coordinador/integrador_respuestas.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/procesadores/procesador_consulta.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/pipeline.py
```

---

## F7 — Tests E2E y medición de latencia

**Prioridad:** ALTA — valida que todo encaja y mide la mejora.
**Dependencias:** F1, F2, F3, F4, F5, F6.
**Estado:** 🚧 En implementación.
**Estimación:** 1 sesión.

### Qué se hace

1. **Test E2E cascada completa** en `tests/test_v42_e2e.py`:
   - Iniciar el Worker Bun.
   - Llamar `pipeline.run()` con un chat de prueba.
   - Verificar que los bloques pendientes se procesan (Worker 1 + Workers
     2-4).
   - Llamar `collect_responses()`.
   - Verificar que:
     - Los bloques físicos tienen `## RESUMEN DEL BLOQUE` al inicio.
     - El `01_indice_recuperacion.md` tiene nombres legibles.
     - El `02_decisiones_clave.md` tiene decisiones con alcance.
     - El `tema_a_archivo` de la metadata tiene `dict[str, list[str]]`.

2. **Test E2E multi-bloque** en `tests/test_v42_e2e.py`:
   - Procesar un chat donde un tema aparece en 3 bloques distintos.
   - `query_context("tema")` lee los 3 bloques y consolida.

3. **Medición de latencia**:
   - Tiempo total de la cascada vs. flujo v5.0 (subagentes efímeros).
   - Latencia por bloque (Worker 1 + Workers 2-4 en paralelo).
   - Latencia de `collect_responses()` con N bloques pendientes.
   - Documentación de resultados en `tests/resultados_latencia_v6.0.md`.

4. **Verificación final**:

   ```bash
   # Tests atómicos
   cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/tests/run_all_tests.py

   # Test E2E v6.0
   cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/tests/test_v42_e2e.py

   # Lint
   cd /home/z/my-project && bun run lint
   ```

   Todos deben pasar.

### Archivos intervenidos

1. `tests/test_v42_e2e.py`:
   - +2 tests E2E (cascada completa + multi-bloque).
   - Actualizar el contador de tests en `main()`.

2. `tests/resultados_latencia_v6.0.md` (nuevo):
   - Documenta latencias medidas.

---

## Orden de ejecución

| Fase | Sesión estimada | Dependencias | Estado |
|---|---|---|---|
| F1 — `BlockPacker.pack()` reparte temas grandes | Sesión 22 (0.5) | ninguna | ✅ Implementado |
| F2 — `RecoveryMetadata` multi-bloque + adaptadores | Sesión 22 (1.0) | F1 | ✅ Implementado |
| F3 — `EstadoGenerator` fixes + `ContentCleaner._parse_tool_calls()` | Sesión 22 (1.5) | ninguna | ✅ Implementado |
| F4 — Worker Bun persistente + Worker 1 | Sesión 23 (2.0) | F1, F2, F3 | 🚧 En implementación |
| F5 — Workers 2-4 en paralelo | Sesión 24 (1.5) | F4 | 🚧 En implementación |
| F6 — Integrador reformado + consulta multi-bloque | Sesión 24 (1.0) | F4, F5 | 🚧 En implementación |
| F7 — Tests E2E + medición de latencia | Sesión 25 (1.0) | F1-F6 | 🚧 En implementación |

**Total estimado:** 8.5 sesiones.

## Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| El Worker Bun no puede acceder a `internal-api.z.ai` | Baja | Alto | Reutilizar el patrón del proxy de APA y del proxy v5.0 que ya funcionan. |
| El LLM directo no produce el mismo formato que el Task tool | Media | Medio | Los prompts son específicos y piden JSON estructurado. Tests por cada Worker. |
| El Worker Bun muere en segundo plano | Media | Alto | Daemon con `bun --hot` (auto-restart). El proceso detecta si el puerto 8090 no responde y cae al modo v5.0. |
| El Integrador aplica respuestas incompletas porque un Worker cayó | Media | Medio | Espera 2 ciclos antes de aplicar. Marca el bloque como incompleto (visible en logs). |
| La migración de `dict[str, str]` a `dict[str, list[str]]` rompe workspaces existentes | Baja | Alto | Migración automática al leer. Se hace backup del `_metadata.json` antes de migrar. |
| Latencia de la cascada mayor a la esperada | Baja | Medio | Medición en F7. Si es peor, optimizar prompts de Worker 1 (más corto = menos tiempo de lectura del LLM). |
| `BlockPacker.pack()` reparte mal (intercambios cortados) | Baja | Medio | Tests de F1 verifican que los intercambios no se cortan. |
| `ContentCleaner._parse_tool_calls()` no detecta todos los formatos de JSON | Media | Medio | Tests de F3e cubren los 5 tipos de `tool_call`. Si aparecen nuevos, se añaden. |

---

**Fin del plan v6.0.**
