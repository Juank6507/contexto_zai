# contexto_zai/Documentación/DIAGNOSTICO_CONSENSO_v4.0.md
# Diagnóstico y Consenso Arquitectónico — CZAI v4.0

**Versión:** 4.0-diag
**Fecha:** 2026-09-13
**Autor:** Agente CZAI (a solicitud del Director)
**Propósito:** Establecer consenso sobre el estado real del proceso contexto_zai
tras detectar desalineaciones arquitectónicas acumuladas entre v3.5, v3.6 y v4.0.
**Base:** Implementación real en commit `55712b1` (H7) + datos reales de la
conversación `13b43432-...` (258-407 mensajes) y del PDF CZAI-01.pdf (208 págs).

---

## 1. Contexto del diagnóstico

El Director solicitó un diagnóstico completo del proceso antes de continuar
implementando H9. La razón: al proponer H9 detecté una "divergencia entre
patrones" que podría ser un síntoma de desalineaciones más profundas
acumuladas durante la evolución del proyecto (v3.0 → v3.6 → v4.0).

Este documento revisa el proceso **con datos reales**, no sintéticos, para
establecer qué funciona, qué no funciona, y dónde hay desalineaciones entre
lo que la spec dice y lo que el código hace.

---

## 2. Los dos patrones de invocación de subagentes

El proceso contexto_zai tiene **DOS patrones arquitectónicos** para invocar
subagentes, que coexisten en el código actual:

### Patrón A — Directo (agente lanza subagentes con Task tool)

```
pipeline.query_context() / ampliar_contexto()
        │
        ├─ Python prepara prompts (no ejecuta subagentes)
        ├─ Devuelve lista de prompts al agente
        │
        ▼
AGENTE PRINCIPAL (Task tool)
        │
        ├─ Lee prompts devueltos
        ├─ Lanza subagentes con Task tool (1 o N en paralelo)
        ├─ Consolida respuestas
        └─ Devuelve respuesta final al Director
```

**Características:**
- El pipeline Python NO ejecuta subagentes.
- El agente principal lanza los subagentes directamente con el Task tool.
- Sin polling, sin TaskBridgeServer, sin `_task_bridge.py`.
- Funciona porque el agente principal tiene el Task tool disponible.

**Dónde se usa:**
- `pipeline.query_context()` (M8) — ✅ funciona, probado con datos reales
- `pipeline.ampliar_contexto()` (H7/M9) para archivos pequeños — ✅ funciona

### Patrón B — Síncrono vía TaskBridgeServer (pipeline llama sub.run())

```
pipeline.run() → Orchestrator → RecoveryCycle
        │
        ├─ EstadoGenerator.generate(exchanges)
        │       └─ sub.run(intercambios)        ← BLOQUEA
        ├─ DecisionesGenerator.generate(exchanges)
        │       └─ sub.run(lote)                ← BLOQUEA
        └─ Subdivider.subdivide(tema, exchanges)
                └─ sub.run(exchanges)            ← BLOQUEA
                        │
                        ▼
                SubagentLauncher.launch()
                        │
                        ▼
                _task_bridge.launch_task()
                        │
                        ├─ POST /task-request al TaskBridgeServer (8087)
                        └─ Polling GET /task-result/{id} cada 2s (hasta 5 min)
                                │
                                ▼
                        Espera que el agente principal lea /pending-tasks
                        y ejecute el Task tool
```

**Características:**
- El pipeline Python ejecuta `sub.run()` síncronamente.
- `SubagentLauncher` envía el prompt al TaskBridgeServer (puerto 8087).
- El pipeline hace polling HTTP esperando el resultado.
- Requiere que el agente principal haga polling de `/pending-tasks` en paralelo.
- **Deadlock síncrono:** si el agente principal está bloqueado ejecutando
  `pipeline.run()` (script Python), no puede lanzar subagentes con el Task tool.

**Dónde se usa:**
- `EstadoGenerator._build_d4()` (M3 D4) — sub.run(intercambios_tema)
- `EstadoGenerator._build_a1()` (M3 A1 resumen truncado) — sub.run([exchange_sintetico])
- `DecisionesGenerator._extract_with_subagent()` (M4) — sub.run(lote)
- `Subdivider._generate_legible_name()` (M7) — sub.run(exchanges)
- `DocumentoIndexerSubagent.run_3_levels()` (v3.6) — N1→N2×N→N3 con launch_parallel()
- `DiscriminatorSubagent` (Capa 3) — sub.run()
- `EstadoSubagent` / `BarridoSubagent` / `MantenimientoSubagent`

---

## 3. Estado real de cada componente (con datos reales)

### 3.1 Extracción de mensajes (Paso 5) — ✅ FUNCIONA

Probado contra el chat real `13b43432-...`:
- `AuthClient.create_share()` → share_id `1d1196b7-...`
- `ChatClient.extract_all_with_raw()` → 407 mensajes (7M chars, ~1.76M tokens)
- Duración: 1.9s
- Sin subagentes involucrados.

**Conclusión:** Extracción sólida, no requiere cambios.

### 3.2 Clasificación léxica (Paso 6, Capa 1+2) — ✅ FUNCIONA

Probado con 407 mensajes reales:
- `ExchangeBuilder.build()` → 247 exchanges
- `MessageClassifier.classify_exchanges()` → 51 temas
- `BlockPacker.pack()` → 36 bloques (multi-tema por archivo)
- `_metadata.json` con `tema_a_archivo` (51 entradas → 36 archivos)
- Duración: ~9s
- Sin subagentes involucrados.

**Conclusión:** Clasificación léxica sólida. Problema pendiente: nombres
recursivos (`_2`, `_3`) cuando Subdivider subdivide sin namer (Patrón B
no cableado).

### 3.3 Generación de 3 archivos (Paso 7) — ⚠️ FUNCIONA EN MODO REGEX

Probado con datos reales:
- `00_estado_actual.md`: 6 secciones presentes (D1, D4, A1, A2, A3, A4)
  - D4 genérico: "No se identifican restricciones explícitas"
  - A4 genérico: "esperar la siguiente instrucción del Director"
  - A1 sin truncado inteligente (solo texto textual)
- `01_indice_recuperacion.md`: mapeo tema→archivo OK
- `02_decisiones_clave.md`: 31 "decisiones" la mayoría falsos positivos (regex)

**Causa raíz:** El `Orchestrator.activate()` (línea 151 de `orchestrator.py`)
crea `RecoveryCycle(...)` **sin pasar `subagent_launcher`**:
```python
cycle = RecoveryCycle(
    jwt=self._jwt,
    chat_id=self._chat_id,
    workspace_dir=self._workspace_dir,
    download_dir=self._download_dir,
    decision_extractor=self._decision_extractor,
    # ← falta: subagent_launcher=SubagentLauncher()
)
```

Como `subagent_launcher=None`:
- `Subdivider(launcher=None)` → H6 namer no activado → nombres recursivos
- El bloque `if subagent_launcher is not None:` no se ejecuta → generadores
  quedan con regex fallback

**Conclusión:** La generación produce archivos, pero en modo regex (no v4.0).
Las mejoras M3/M4/M7 existen en el código pero no se activan porque el
launcher no se cablea.

### 3.4 query_context (M8) — ✅ FUNCIONA

Probado con datos reales (`contexto_recuperacion/`):
- `query_context("¿Qué se decidió sobre JWT?")` → modo distributed, 3 bloques
  candidatos (bloque_01, 02, 03), 3 prompts preparados
- El agente principal lanza los subagentes directamente con Task tool
- Subagente leyó bloque_22.md (128K chars) y devolvió respuesta completa
  de 8 líneas sobre JWT/autenticación
- Sin TaskBridgeServer, sin polling

**Conclusión:** M8 funciona perfectamente. Es el Patrón A.

### 3.5 ampliar_contexto (H7/M9) — ✅ FUNCIONA (parcial)

Probado con archivos reales:
- Archivo pequeño (`documento_chico.txt`, 9 tokens): devuelve
  `needs_agent_read: true` → el agente lo lee directo. ✅
- Archivo grande: intenta indexar vía `DocumentoIndexerSubagent` que usa
  Patrón B → requiere TaskBridgeServer + polling → deadlock síncrono.

**Conclusión:** H7 funciona para archivos pequeños (Patrón A). Para archivos
grandes usa Patrón B y hereda el deadlock.

### 3.6 DocumentoIndexerSubagent.run_3_levels (v3.6) — ✅ FUNCIONÓ EN SESIÓN 10

**Evidencia documentada en worklog Sesión 10:**
- Se ejecutó contra CZAI-01.pdf (208 págs, 165K tokens) con subagentes reales.
- Particionado en 2 porciones (págs 1-112 + 113-208).
- 2 subagentes N2 lanzados en paralelo (en un solo mensaje con 2 Task tools).
- N3 consolidó: 5 temas únicos.
- Ahorro de contexto: 99.9% (165K tokens → 108 tokens del resumen).

**Cómo funcionó:** El agente principal (yo, en esa sesión) ejecutó el pipeline
en foreground, y mientras tanto hacía polling manual de `/pending-tasks` en
el TaskBridgeServer, lanzando los subagentes N2 con el Task tool cuando
aparecían pendientes. El polling manual del agente resolvió el deadlock
síncrono en esa sesión específica.

**Conclusión:** run_3_levels funciona cuando el agente hace polling manual.
Pero esto requiere que el agente sepa que tiene que hacer polling, lo cual
no está documentado en la spec v4.0 como un paso obligatorio del flujo.

---

## 4. Desalineaciones arquitectónicas detectadas

### Desalineación 1 — Coexistencia de Patrón A y Patrón B

La spec v4.0 dice explícitamente (M8, líneas 141, 150, 158):
> "Sin polling, sin TaskBridgeServer."
> "No se usa TaskBridgeServer ni `_task_bridge.py` para consultas."

Pero al mismo tiempo, M3/M4/M7 usan `sub.run()` que va por el Patrón B
(TaskBridgeServer + polling). El diagrama de arquitectura (línea 269) muestra:
```
SUBAGENTLAUNCHER → _task_bridge → TaskBridgeServer (8087)
```
como el camino principal, sin distinguir que M8 no lo usa.

**Estado real:** Coexisten dos patrones sin reconciliar. M8/M9-pequeño usan
Patrón A (funciona). M3/M4/M7/M9-grande/v3.6-3niveles usan Patrón B
(requiere polling manual del agente).

### Desalineación 2 — Launcher no cableado en Orchestrator

Ni la spec v4.0 ni el plan v4.0 mencionan al `Orchestrator`. Cero menciones.
Como consecuencia, ningún milestone H1-H8 incluye `process/orchestrator.py`
en su lista de archivos intervenidos.

El código H7 en `recovery_cycle.py` (línea 158) hace:
```python
if subagent_launcher is not None:
    estado_gen = EstadoGenerator(launcher=subagent_launcher)
    decisiones_gen = DecisionesGenerator(launcher=subagent_launcher)
```

Pero como el Orchestrator nunca pasa `subagent_launcher`, esa rama nunca
se ejecuta. El código está ahí pero está muerto.

### Desalineación 3 — IncrementalCycle no acepta launcher

`IncrementalCycle` (para actualizaciones incrementales tras la primera
recuperación) **no tiene parámetro `subagent_launcher`** en su constructor.
Si se cableara el launcher en Orchestrator, solo llegaría a RecoveryCycle,
no a IncrementalCycle. Las actualizaciones incrementales nunca usarían
subagentes.

### Desalineación 4 — El "hallazgo crítico" de Sesión 16 no se propagó

La spec v4.0 M8 (línea 124) documenta:
> "Hallazgo crítico (Sesión 16): Se probó con datos reales que los subagentes
> NO tienen acceso al Task tool. Solo el agente principal puede lanzar
> subagentes."

Este hallazgo se aplicó a M8 ( Patrón A) pero NO se propagó a M3/M4/M7.
M3/M4/M7 siguen usando `sub.run()` que asume que el subagente o el pipeline
pueden lanzar Task tools, lo cual es falso según el hallazgo de Sesión 16.

### Desalineación 5 — v3.6 run_3_levels funcionó pero no es reproducible

El worklog Sesión 10 documenta que run_3_levels funcionó con subagentes
reales. Pero funcionó porque el agente (yo) hacía polling manual de
`/pending-tasks` mientras el pipeline corría en background. Esto:
- No está documentado como paso obligatorio en la spec.
- No es reproducible si el pipeline corre en foreground (deadlock).
- No es reproducible si el pipeline corre en background y muere
  (Problema 6, documentado pero no resuelto).

### Desalineación 6 — Problema 6 (muerte silenciosa en background) no resuelto

La spec v4.0 M6/H5 dice "diagnosticar primero, intervenir después". H5 se
implementó (tests de diagnóstico en `test_pipeline_background.py`) pero:
- No se encontró el diagnóstico en el worklog.
- El problema persiste: `nohup python3 pipeline.py` muere sin traceback.
- Mientras no se resuelva, el Patrón B no es viable en background.

---

## 5. Lo que SÍ funciona (consenso)

| Componente | Patrón | Estado | Evidencia |
|---|---|---|---|
| Extracción de mensajes | Ninguno (API directa) | ✅ | 407 msgs en 1.9s |
| Clasificación léxica | Ninguno (regex) | ✅ | 247 exchanges → 51 temas |
| BlockPacker | Ninguno (algoritmo) | ✅ | 36 bloques multi-tema |
| MetadataManager | Ninguno (JSON) | ✅ | _metadata.json correcto |
| JWT automático | Bookmarklet + CredentialManager | ✅ | JWT persistente, no expira |
| UI Bridge | Next.js + form POST | ✅ | Badge "Conectado", footer sticky |
| query_context (M8) | **A** | ✅ | Subagente leyó bloque, respondió |
| ampliar_contexto small (M9) | **A** | ✅ | needs_agent_read=true |
| run_3_levels (v3.6) | **B + polling manual** | ⚠️ | Funcionó en Sesión 10 con agente haciendo polling |

## 6. Lo que NO funciona como se planificó (consenso)

| Componente | Planificado | Real | Causa |
|---|---|---|---|
| M3 D4 (restricciones) | Subagente interpreta | Regex genérico | Launcher no cableado |
| M3 A1 (truncado inteligente) | Texto + resumen subagente | Solo texto textual | Launcher no cableado |
| M3 A4 (siguiente paso) | Subagente analiza | Regex genérico | Launcher no cableado |
| M4 (decisiones reales) | Subagente detecta | 31 falsos positivos regex | Launcher no cableado |
| M7 (nombres legibles) | Subagente nombra | Nombres recursivos `_2` | Launcher no cableado |
| Capa 3 (discriminador) | Subagente divide | No se ejecuta | enable_capa3=False por defecto |
| M9 ampliar grande | Indexa con subagente | Deadlock síncrono | Patrón B sin polling |
| M6 (diagnóstico background) | Diagnosticar y arreglar | Tests existen, diagnóstico no | H5 parcial |

---

## 7. Decisión de consenso pendiente

El proceso tiene una bifurcación arquitectónica sin resolver:

**Opción 1 — Unificar todo al Patrón A (directo)**
- M3/M4/M7 dejan de llamar `sub.run()`.
- Los generadores devuelven prompts (como M8).
- El agente principal lanza los subagentes tras `pipeline.run()`.
- Se elimina el TaskBridgeServer y `_task_bridge.py`.
- run_3_levels se rediseña: el agente lanza N2 en paralelo con Task tool.
- **Ventaja:** un solo patrón, sin deadlock, sin polling.
- **Desventaja:** cambia la signature de generate(), requiere refactor.

**Opción 2 — Mantener Patrón B con polling explícito del agente**
- Se cablea el launcher en Orchestrator.
- El agente principal hace polling de `/pending-tasks` tras `pipeline.run()`.
- Se resuelve el Problema 6 (muerte silenciosa) primero.
- **Ventaja:** menos refactor, aprovecha código existente.
- **Desventaja:** dos patrones coexisten, más complejo, depende de M6.

**Opción 3 — Híbrido: Patrón A para M3/M4/M7, Patrón B solo para v3.6 3-niveles**
- M3/M4/M7 se convierten a Patrón A (prompts diferidos).
- run_3_levels mantiene Patrón B (ya funcionó en Sesión 10).
- **Ventaja:** minimiza cambios, conserva lo que funciona.
- **Desventaja:** coexistencia de patrones, complejidad documentada.

---

## 8. Recomendación técnica (no decisión)

La Opción 1 es la más alineada con el hallazgo crítico de Sesión 16
("solo el agente principal puede lanzar subagentes"). Elimina la
complejidad del TaskBridgeServer y resuelve el deadlock de raíz. Pero
requiere un refactor mayor.

La Opción 3 es la más pragmática: convierte M3/M4/M7 al Patrón A (que
ya funciona en M8) y mantiene run_3_levels como está (que funcionó en
Sesión 10 con polling manual).

**Este documento no toma la decisión.** La decisión es del Director.

---

**Fin del documento de diagnóstico.**
