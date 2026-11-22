# Worker Cascade v6.1 — CZAI

Worker Bun persistente que procesa bloques de chat con una cascada optimizada:
**Worker 1** (resumen) → **Worker 2 fusionado** (extracción JSON).

## Las 4 soluciones de v6.1

| # | Solución | Efecto |
|---|---|---|
| 1 | Fusión W2+W3+W4 en una sola llamada JSON | 4 → 2 llamadas LLM por bloque (−50%) |
| 2 | Backoff exponencial con Retry-After | Resiliente a 429s sin intervención manual |
| 3 | Cache por hash SHA256 del prompt | Re-ejecuciones = 0 llamadas LLM |
| 5 | Modelo dual (glm-4-plus + glm-4-flash) | W1 calidad, W2 velocidad |

**Resultado**: 14/14 bloques procesados en ~13s (vs 6/14 fallidos en v6.0), 13 llamadas LLM (vs 56).

## Requisitos

- **Bun** runtime >= 1.0 ([instalar](https://bun.sh/))
- **Proxy APA** accesible (solo para modo `run`; no se necesita para `--self-test`)
- **Workspace dir** con `_pending_blocks.json` (bloques a procesar)

## Inicio rápido

### Linux/macOS
```bash
cd mini-services/worker-cascade
./setup.sh                # verifica entorno + arranca worker
./setup.sh --check        # solo verifica, no arranca
./setup.sh --self-test    # solo corre self-test
```

### Windows (PowerShell)
```powershell
cd mini-services\worker-cascade
.\setup.ps1                # verifica entorno + arranca worker
.\setup.ps1 -Check         # solo verifica
.\setup.ps1 -SelfTest      # solo self-test
```

### Comandos disponibles (cross-platform)
```bash
bun run cli.ts                  # modo normal (procesa _pending_blocks.json)
bun run cli.ts run              # alias de modo normal
bun run cli.ts --self-test      # valida las 4 soluciones sin proxy APA
bun run cli.ts --help           # muestra ayuda
bun run cli.ts --version        # muestra versión
```

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `CZAI_WORKSPACE_DIR` | `/home/z/my-project/contexto_recuperacion` (Linux) o `%USERPROFILE%\czai_workspace` (Windows) | Directorio del workspace |
| `CZAI_MODEL_HEAVY` | `glm-4-plus` | Modelo para W1 (resumen) |
| `CZAI_MODEL_LIGHT` | `glm-4-flash` | Modelo para W2 (extracción) |
| `CZAI_PROXY_URL` | `http://localhost:3000/api/zai-proxy/v1/chat/completions` | URL del proxy APA |

## Estructura de archivos

```
mini-services/worker-cascade/
├── index.ts            # Worker Bun principal (cascada W1 → W2)
├── cli.ts              # Dispatcher CLI (--self-test, --help, run)
├── package.json        # Scripts npm
├── setup.sh            # Setup para Linux/macOS
├── setup.ps1           # Setup para Windows
├── README.md           # Este archivo
└── tests/
    └── self_test.ts    # Tests standalone (valida las 4 soluciones)
```

## Self-test

El self-test valida las 4 soluciones **sin necesidad del proxy APA real**:

```bash
bun run cli.ts --self-test
```

Tests cubiertos (34 tests, ~1s):

1. `hashContent` — SHA256 determinista de 32 chars
2. `cachePath` — incluye modelo en el hash
3. `readCache`/`writeCache` — escritura y lectura
4. `callLLM` backoff exponencial — reintenta tras 429
5. `callLLM` respeta `Retry-After` header
6. `callLLM` cache HIT — no llama al LLM
7. Parser JSON tolerante a markdown fences
8. Parser JSON inválido — fallback graceful
9. Modelo dual — W1≠W2
10. Backoff delays correctos `[2,4,8,16,32,64]s`
11. `PROMPT_EXTRACT_ALL` — pide JSON estructurado

## Arquitectura

```
_pending_blocks.json (entrada)
        ↓
   ┌──────────────────────────────────┐
   │  Worker Bun (puerto 8090)        │
   │                                  │
   │  por cada bloque:                │
   │    1. W1: leer bloque completo  │
   │       → generar resumen (1KB)    │
   │       → escribir al inicio del   │
   │         bloque físico            │
   │       [idempotente si ya tiene   │
   │        RESUMEN:]                 │
   │                                  │
   │    2. W2-fusionado: leer resumen │
   │       → 1 llamada JSON           │
   │       → {nombre, decisiones[],   │
   │          temas[]}                │
   │       [cache HIT: 0 llamadas]    │
   │                                  │
   └──────────────────────────────────┘
        ↓
_responses/ (salida)
  ├── bloque_NN_resumen.txt
  ├── bloque_NN_nombre.txt
  ├── bloque_NN_decisiones.txt
  ├── bloque_NN_temas.txt
  └── cache/   (cache por hash)
```

## Hallazgo clave: rate limit compartido

El rate limit del proxy APA (`internal-api.z.ai`) es **compartido entre modelos** por
JWT. Usar dos modelos en paralelo NO dobla la cuota. Pero `glm-4-flash` responde más
rápido para extracciones simples, así que se reserva para W2 (latencia), no para
aumentar throughput.

## Health check

```bash
curl http://localhost:8090/health
# {"status":"ok","version":"v6.1","models":{"heavy":"glm-4-plus","light":"glm-4-flash"},...}
```
