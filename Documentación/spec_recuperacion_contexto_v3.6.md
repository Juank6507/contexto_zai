# Spec v3.6 — JWT automático vía .bat + Subagentes paralelos para documentos grandes

**Versión:** 3.6
**Fecha:** 2026-09-06
**Autor:** Agente CZAI
**Estado:** Pendiente de validación por el Director.
**Especifica continuación de:** spec v3.5 (indexación de documentos adjuntos).

---

## 1. Problema

La spec v3.5 introdujo la indexación de documentos adjuntos mediante subagentes efímeros. Quedaron 2 problemas sin resolver:

### Problema 1 — Obtención del JWT (fricción para el Director)

El agente necesita el JWT del Director para acceder a la API de Z.ai. Hoy el Director tiene que:
1. Abrir DevTools (F12).
2. Ir a Application → Cookies.
3. Buscar la cookie `token`.
4. Copiar el valor.
5. Pegarlo en el chat o pasarlo al proceso.

Esto no es natural y dificulta la adopción por usuarios no técnicos.

### Problema 2 — Documentos muy grandes llenan el contexto del subagente

La spec v3.5 delega la lectura de documentos adjuntos a un **único** `DocumentoIndexerSubagent`. Si el documento es muy grande (ej: 1.000 páginas = ~1M tokens), el subagente puede:
- Llenar su contexto y no poder procesar todo el documento.
- Truncar la lectura (el `Read` tool tiene límite de líneas).
- Devolver un resumen incompleto porque no vio todo el contenido.

## 2. Solución

### Solución 1 — JWT automático vía `.bat` con PowerShell + Edge + DevTools Protocol

**Mecanismo:**

1. El agente (sandbox) detecta que no tiene JWT disponible.
2. Expone 3 endpoints HTTP temporales:
   - `GET /jwt-status` → `{"needs_jwt": true|false}`
   - `POST /recibir-jwt` → recibe el JWT y lo persiste
   - `GET /czai-jwt-bridge.bat` → sirve el script descargable
3. El agente le dice al Director: "Descarga este archivo y haz doble click".
4. El Director descarga `czai-jwt-bridge.bat` (3 KB) y hace doble click.
5. El `.bat` ejecuta PowerShell silenciosamente, que:
   - Lanza Edge con `--remote-debugging-port=9222`.
   - Edge abre `chat.z.ai` (donde el Director ya tiene sesión).
   - PowerShell se conecta a Edge vía DevTools Protocol (WebSocket).
   - PowerShell ejecuta `fetch('/api/v1/auths/')` dentro de la página de `chat.z.ai`.
   - El navegador envía las cookies automáticamente (sesión del Director).
   - Z.ai responde con `{token: "eyJhbG...", role: "user"}`.
   - PowerShell captura el JWT de la respuesta.
   - PowerShell envía el JWT al sandbox: `POST /recibir-jwt`.
   - PowerShell cierra Edge.
   - Muestra "JWT enviado correctamente" y se cierra.
6. El sandbox persiste el JWT en `.browser_auth_state.json`.
7. El agente sigue trabajando automáticamente.

**Pre-instalado en todos los Windows 10/11:**
- PowerShell (viene con Windows desde Windows 7).
- Microsoft Edge (viene con Windows 10/11, basado en Chromium).
- DevTools Protocol (integrado en Edge y Chrome).

**No requiere instalar:**
- Python.
- Extensiones del navegador.
- DevTools manuales.
- Copiar/pegar cookies.

**Interacción del Director:**
- Descargar `czai-jwt-bridge.bat` (3 KB).
- Doble click.
- Una vez en la vida (el JWT no expira).

### Solución 2 — Subagentes paralelos en 3 niveles para documentos grandes

**Arquitectura:**

```
Documento muy grande (>50K tokens)
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  NIVEL 1 (Divisor)                                            │
│                                                               │
│  - Recibe el documento grande                                 │
│  - Calcula N bloques matemáticamente:                         │
│      N = ceil(total_tokens / MAX_TOKENS_POR_SUBAGENTE_N2)     │
│  - Lanza N subagentes de Nivel 2 EN PARALELO                  │
│  - Si N > MAX_SUBAGENTES_N2_PARALELOS (3):                    │
│      Lanza en lotes de 3                                      │
│  - Espera a que todos terminen                                │
│  - Acumula los N índices parciales                            │
│  - Se cierra                                                  │
└──────────────────────┬────────────────────────────────────────┘
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
  [N2-1]           [N2-2]           [N2-3]      (lote 1, máx 3)
  Lee bloque 1     Lee bloque 2     Lee bloque 3
  Clasifica        Clasifica        Clasifica
  Devuelve índice  Devuelve índice  Devuelve índice
       │               │               │
       └───────────────┼───────────────┘
                       │
                       ▼
                   [N2-4, N2-5, ...]            (lote 2, si hay más)
                       │
                       ▼
                   ... (hasta completar N bloques)
                       │
                       ▼ (el proceso pasa los N índices al N3)
┌──────────────────────────────────────────────────────────────┐
│  NIVEL 3 (Conciliador)                                        │
│                                                               │
│  - Recibe los N índices parciales de los N2                   │
│  - Reubica temas para evitar duplicados                       │
│  - Rehace 01_indice_recuperacion.md con todo organizado       │
│  - Genera resumen final para el agente principal              │
│  - Se cierra                                                  │
└──────────────────────────────────────────────────────────────┘
```

**Decisiones clave:**

| Aspecto | Decisión |
|---|---|
| Quién decide la cantidad de bloques | Nivel 1, con cálculo matemático |
| Quién lanza los N2 | Nivel 1 (no el proceso principal) |
| Cómo se lanzan los N2 | En paralelo real (siempre) |
| Límite paralelo para clasificación profunda | 3 subagentes a la vez |
| Si N > 3 | Se procesan en lotes de 3 |
| Comunicación entre niveles | N2 devuelven índices al N1, el proceso los pasa al N3 |
| Umbral de activación | Documentos >50K tokens van al flujo de 3 niveles |

**3 niveles de delegación:**

```
Documento adjunto
    │
    ▼
DocumentDelegator.should_delegate(size, context, override)
    │
    ├── size < 1000 tokens → LECTURA DIRECTA (agente principal lee)
    │
    ├── 1000 ≤ size ≤ 50000 tokens → SUBAGENTE ÚNICO (DocumentoIndexerSubagent actual)
    │
    └── size > 50000 tokens → FLUJO DE 3 NIVELES (N1 → N2×N → N3)
```

**Límites por tipo de tarea (conocimiento del agente):**

| Tipo de tarea | Límite paralelo | Aplicación |
|---|---|---|
| Lectura simple de archivos | 5 | Futuras tareas |
| Búsqueda puntual | 8 | Futuras tareas |
| Clasificación profunda + indexación | 3 | **Nivel 2** |

## 3. Arquitectura OOP

### Patrón reutilizable: Divisor + Conciliador

```
ContentDelegator (clase base abstracta, ya existe v3.5)
├── DocumentDelegator (ya existe)
└── Subdivider (ya existe, refactor v3.5)

SubagentLauncher (ya existe)
├── launch()              → 1 subagente (ya existe)
├── launch_many()         → N subagentes secuencial (ya existe)
└── launch_parallel()     → N subagentes en paralelo (NUEVO, genérico)
    │
    └── usa: concurrent.futures.ThreadPoolExecutor
         con max_workers = límite según tipo de tarea

Divisor (NUEVO, clase base abstracta)
├── particionar(contenido) → list[Porcion]
├── lanzar_subagentes(porciones, max_paralelos) → list[Respuesta]
└── implementaciones:
    └── DocumentoDivisor : Divisor
        └── particiona documento por páginas/tokens

Conciliador (NUEVO, clase base abstracta)
├── conciliar(respuestas) → RespuestaConsolidada
├── producir_resumen_final() → str
└── implementaciones:
    └── DocumentoConciliador : Conciliador
        └── combina índices parciales en índice consolidado
```

### Diagrama de clases

```
Divisor (abstract)
├── particionar() → list[Porcion]           (abstract)
├── lanzar_subagentes(porciones, max) → list[Respuesta]  (concreto, usa launch_parallel)
└── DocumentoDivisor : Divisor
    └── particionar(documento) → list[PorcionDocumento]

Conciliador (abstract)
├── conciliar(respuestas) → Consolidado     (abstract)
├── producir_resumen_final() → str          (abstract)
└── DocumentoConciliador : Conciliador
    ├── conciliar(indices_parciales) → IndiceConsolidado
    └── producir_resumen_final() → str

SubagentLauncher (modificado)
└── launch_parallel(requests, max_workers) → list[SubagentResponse]
    └── usa ThreadPoolExecutor

DocumentoIndexerSubagent (modificado)
├── run(attachment) → DocumentoIndexResult                    (ya existe, para docs <50K)
└── run_3_levels(attachment) → DocumentoIndexResult           (NUEVO, para docs >50K)
    ├── Lanza DivisorSubagent (N1)
    ├── N1 lanza N2×N en paralelo
    ├── Proceso pasa índices al ConciliadorSubagent (N3)
    └── N3 devuelve resultado consolidado
```

## 4. Archivos nuevos

| Archivo | Responsabilidad |
|---|---|
| `scripts/czai-jwt-bridge.bat` | Script .bat que el Director ejecuta con doble click |
| `scripts/jwt_bridge.ps1` | Script PowerShell que el .bat invoca (lógica real) |
| `client/credential_manager.py` | Gestiona el JWT: lo pide si falta, lo valida, lo persiste |
| `client/jwt_bridge_server.py` | Mini HTTP server temporal en el sandbox (3 endpoints) |
| `processing/divisor.py` | Clase base abstracta `Divisor` + `DocumentoDivisor` concreto |
| `processing/conciliador.py` | Clase base abstracta `Conciliador` + `DocumentoConciliador` concreto |
| `subagents/divisor_subagent.py` | Subagente N1 (divide + lanza N2) |
| `subagents/conciliador_subagent.py` | Subagente N3 (consolida índices) |

## 5. Archivos a modificar

| Archivo | Cambio |
|---|---|
| `models.py` | Añadir modelos `Porcion`, `IndiceParcial`, `IndiceConsolidado` |
| `config.py` | Añadir constantes de particionado y límites paralelos |
| `subagents/launcher.py` | Añadir `launch_parallel()` con ThreadPoolExecutor |
| `subagents/documento_indexer_subagent.py` | Añadir `run_3_levels()` para flujo de 3 niveles |
| `subagents/__init__.py` | Exportar nuevas clases |
| `pipeline.py` | Añadir `index_document_large()` para docs >50K |
| `recovery_cycle.py` | Detectar tamaño de attachment y elegir entre subagente único o 3 niveles |
| `estrategia/worklog_template.md` | Actualizar Paso 2c con instrucciones del .bat |

## 6. Constantes nuevas en config.py

```python
# v3.6: Particionado de documentos grandes
PARTITION_THRESHOLD_TOKENS = 50000          # docs >50K van a 3 niveles
MAX_TOKENS_POR_SUBAGENTE_N2 = 30000         # cada N2 lee ~30K tokens

# v3.6: Límites de subagentes paralelos por tipo de tarea
MAX_SUBAGENTES_LECTURA_ARCHIVOS = 5
MAX_SUBAGENTES_BUSQUEDA_PUNTUAL = 8
MAX_SUBAGENTES_CLASIFICACION_PROFUNDA = 3   # N2 usa este límite
MAX_SUBAGENTES_N2_PARALELOS = MAX_SUBAGENTES_CLASIFICACION_PROFUNDA  # = 3

# v3.6: JWT Bridge Server
JWT_BRIDGE_SERVER_PORT = 8086                # puerto del mini HTTP server
JWT_BRIDGE_SERVER_HOST = "0.0.0.0"           # accesible desde fuera del sandbox
```

## 7. Compatibilidad con versiones anteriores

- El flujo existente (sin documentos grandes) sigue funcionando igual.
- Los documentos <50K tokens siguen usando `DocumentoIndexerSubagent.run()` (subagente único).
- Los documentos >50K tokens usan `DocumentoIndexerSubagent.run_3_levels()` (3 niveles).
- El JWT manual (pasado explícitamente) sigue funcionando como fallback.
- El `.bat` es opcional: si el Director prefiere pasar el JWT manualmente, puede hacerlo.

## 8. Validación

### 8.1. Auto-tests atómicos

- `client/credential_manager.py`: validación de JWT, persistencia, detección de expiración.
- `client/jwt_bridge_server.py`: 3 endpoints responden correctamente.
- `processing/divisor.py`: particionado matemático, casos edge (doc vacío, 1 bloque, N bloques).
- `processing/conciliador.py`: consolidación de índices, deduplicación de temas.
- `subagents/divisor_subagent.py`: lanza N2 en paralelo, acumula resultados.
- `subagents/conciliador_subagent.py`: recibe índices, genera resumen final.

### 8.2. Tests E2E

- `test_e2e_v36_jwt_bridge`: simula el flujo completo del .bat (mock de DevTools Protocol).
- `test_e2e_v36_3_levels_small_doc`: doc <50K → subagente único (no 3 niveles).
- `test_e2e_v36_3_levels_large_doc`: doc >50K → 3 niveles con mock invoker.
- `test_e2e_v36_parallel_launch`: `launch_parallel()` lanza N subagentes en paralelo real.

## 9. Pendiente de validación

Espero tu validación para pasar a la fase de EJECUCIÓN del plan v3.6.
