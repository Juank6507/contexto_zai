// contexto_zai/mini-services/worker-cascade/cli.ts
// Dispatcher CLI para el Worker Cascade v6.1.
//
// QUÉ SOLUCIONA: el `index.ts` arranca automáticamente `main()` al importarlo,
// lo que impide soportar subcomandos como `--self-test` o `--help`.
// CÓMO LO HACE: este dispatcher lee `process.argv`, decide qué ejecutar, y
// delega al módulo adecuado:
//   - sin args / `run`       → index.ts (modo normal)
//   - `--self-test` / `test` → tests/self_test.ts (valida las 4 soluciones)
//   - `--help` / `-h`        → muestra ayuda
//   - `--version` / `-v`    → muestra versión
//
// Uso:
//   bun run cli.ts                → modo normal (procesa _pending_blocks.json)
//   bun run cli.ts --self-test    → valida las 4 soluciones sin proxy APA real
//   bun run cli.ts --help         → muestra ayuda
//   bun run cli.ts --version      → muestra versión

import { main } from "./index.ts";
import { runSelfTest } from "./tests/self_test.ts";

const VERSION = "6.1.0";

function showHelp(): void {
  console.log(`
Worker Cascade v${VERSION} — CZAI

USO:
  bun run cli.ts [COMANDO]

COMANDOS:
  (sin args)            Procesa _pending_blocks.json (modo normal).
  run                   Alias de modo normal.
  --self-test, test     Valida las 4 soluciones (#1 fusión, #2 backoff, #3 cache, #5 modelo dual)
                        sin necesidad del proxy APA real. Usa mock fetch.
  --help, -h            Muestra esta ayuda.
  --version, -v         Muestra la versión.

ENV VARS:
  CZAI_WORKSPACE_DIR    Directorio del workspace (default: /home/z/my-project/contexto_recuperacion).
  CZAI_MODEL_HEAVY      Modelo para W1 (default: glm-4-plus).
  CZAI_MODEL_LIGHT      Modelo para W2 (default: glm-4-flash).
  CZAI_PROXY_URL        URL del proxy APA (default: http://localhost:3000/api/zai-proxy/v1/chat/completions).

SALIDA:
  El worker procesa los bloques pendientes y escribe resultados en
  _responses/ y _processed_blocks.json dentro del workspace.
`);
}

async function dispatch(): Promise<void> {
  const args = process.argv.slice(2);
  const cmd = args[0] || "run";

  switch (cmd) {
    case "--help":
    case "-h":
    case "help":
      showHelp();
      process.exit(0);
      break;

    case "--version":
    case "-v":
    case "version":
      console.log(`Worker Cascade v${VERSION}`);
      process.exit(0);
      break;

    case "--self-test":
    case "test":
    case "self-test":
      await runSelfTest();
      process.exit(0);
      break;

    case "run":
    default:
      // Modo normal: delega a index.ts main()
      await main();
      break;
  }
}

dispatch().catch((e) => {
  console.error(`FATAL: ${e?.message || e}`);
  process.exit(1);
});
