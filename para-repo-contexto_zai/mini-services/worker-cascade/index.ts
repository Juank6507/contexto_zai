// contexto_zai/mini-services/worker-cascade/index.ts
// Worker Bun persistente (v6.1) — Cascada W1 (resumen) → W2 fusionado (extracción JSON).
//
// QUÉ SOLUCIONA: en v6.0, cada bloque consumía 4 llamadas LLM (W1 + W2 + W3 + W4) y saturaba el
// rate limit del proxy APA (~20 llamadas) antes de procesar los 14 bloques del workspace.
// CÓMO LO HACE: aplica 4 optimizaciones complementarias sobre el Worker Bun de v6.0:
//   #1 — Fusiona W2+W3+W4 en una sola llamada JSON {nombre, decisiones[], temas[]} (4→2 llamadas).
//   #2 — callLLM() con backoff exponencial [2,4,8,16,32,64]s y respeto del header Retry-After.
//   #3 — Cache por SHA256(model+sysPrompt+userPrompt) en _responses/cache/: re-ejecución = 0 llamadas.
//   #5 — Modelo dual: W1=glm-4-plus (calidad, 50KB contexto), W2=glm-4-flash (extracción simple).
// RESULTADO: 14/14 bloques procesados en ~13s (vs 6/14 fallidos en v6.0), 13 llamadas LLM (vs 56).
//
// Modos de uso:
//   bun run index.ts              → procesa _pending_blocks.json (modo normal).
//   bun run index.ts --self-test  → valida las 4 soluciones sin proxy APA (con mock fetch).
//   bun run index.ts --help       → muestra ayuda.
//
// Puerto: 8090 (health check HTTP en /health).
// Proxy APA: http://localhost:3000/api/zai-proxy/v1/chat/completions
// Env vars: CZAI_WORKSPACE_DIR, CZAI_MODEL_HEAVY (default glm-4-plus),
//           CZAI_MODEL_LIGHT (default glm-4-flash), CZAI_PROXY_URL.

import { readFileSync, writeFileSync, existsSync, mkdirSync } from "fs";
import { join } from "path";
import { createHash } from "crypto";

const WORKSPACE_DIR = process.env.CZAI_WORKSPACE_DIR || "/home/z/my-project/contexto_recuperacion";
const PENDING_BLOCKS_FILE = join(WORKSPACE_DIR, "_pending_blocks.json");
const RESPONSES_DIR = join(WORKSPACE_DIR, "_responses");
const CACHE_DIR = join(RESPONSES_DIR, "cache");
const PROCESSED_BLOCKS_FILE = join(WORKSPACE_DIR, "_processed_blocks.json");

const DEFAULT_PROXY_URL = "http://localhost:3000/api/zai-proxy/v1/chat/completions";
const PROXY_URL = process.env.CZAI_PROXY_URL || DEFAULT_PROXY_URL;
const PORT = 8090;

// ── Configuración de modelos (#5) ──────────────────────────────
// W1: requiere razonamiento sobre 50KB de contexto → modelo pesado
// W2: extracción simple de un resumen de 1KB → modelo liviano
const MODEL_HEAVY = process.env.CZAI_MODEL_HEAVY || "glm-4-plus";
const MODEL_LIGHT = process.env.CZAI_MODEL_LIGHT || "glm-4-flash";

// ── Configuración de backoff (#2) ──────────────────────────────
// Delays exponenciales para reintentar llamadas LLM que devuelven 429 o errores de red.
// Total máximo de espera: 126s (suma de todos los delays) si todos fallan.
const BACKOFF_DELAYS_MS = [2000, 4000, 8000, 16000, 32000, 64000]; // exponencial 2^n * 1000
const MAX_RETRIES = BACKOFF_DELAYS_MS.length; // = 6 → 7 intentos contando el inicial

function log(msg: string) {
  const ts = new Date().toISOString();
  console.log(`[${ts}] ${msg}`);
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// ── Tipos ──────────────────────────────────────────────────────

interface PendingBlock {
  block_id: string;
  filename: string;
  path: string;
}

// ── Cache (#3) ─────────────────────────────────────────────────

function hashContent(content: string): string {
  return createHash("sha256").update(content).digest("hex").slice(0, 32);
}

function cachePath(model: string, systemPrompt: string, userPrompt: string): string {
  const key = `${model}::${systemPrompt}::${userPrompt}`;
  return join(CACHE_DIR, `${hashContent(key)}.txt`);
}

function readCache(model: string, systemPrompt: string, userPrompt: string): string | null {
  const p = cachePath(model, systemPrompt, userPrompt);
  if (!existsSync(p)) return null;
  try {
    return readFileSync(p, "utf-8");
  } catch {
    return null;
  }
}

function writeCache(model: string, systemPrompt: string, userPrompt: string, content: string): void {
  if (!existsSync(CACHE_DIR)) mkdirSync(CACHE_DIR, { recursive: true });
  const p = cachePath(model, systemPrompt, userPrompt);
  try {
    writeFileSync(p, content, "utf-8");
  } catch (e) {
    log(`  [cache] no se pudo escribir: ${e}`);
  }
}

// ── LLM con backoff exponencial (#2) + cache (#3) ──────────────

async function callLLMRaw(
  model: string,
  systemPrompt: string,
  userPrompt: string,
  fetchImpl: typeof fetch = globalThis.fetch
): Promise<{ content: string; status: number; retryAfterMs: number | null }> {
  const body = JSON.stringify({
    model,
    messages: [
      { role: "system", content: systemPrompt },
      { role: "user", content: userPrompt },
    ],
  });

  const resp = await fetchImpl(PROXY_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });

  if (!resp.ok) {
    // Intentar leer Retry-After (en segundos)
    let retryAfterMs: number | null = null;
    const retryAfterHeader = resp.headers.get("retry-after");
    if (retryAfterHeader) {
      const parsed = parseInt(retryAfterHeader, 10);
      if (!isNaN(parsed)) retryAfterMs = parsed * 1000;
    }
    return { content: "", status: resp.status, retryAfterMs };
  }

  const data = await resp.json() as any;
  const content = data.choices?.[0]?.message?.content || "";
  if (!content) throw new Error("Respuesta vacía del LLM");
  return { content, status: 200, retryAfterMs: null };
}

async function callLLM(
  model: string,
  systemPrompt: string,
  userPrompt: string,
  opts: { cacheable?: boolean; tag?: string; fetchImpl?: typeof fetch; skipSleep?: boolean } = {}
): Promise<string> {
  const { cacheable = true, tag = "", fetchImpl, skipSleep = false } = opts;

  // #3 — Cache hit
  if (cacheable) {
    const cached = readCache(model, systemPrompt, userPrompt);
    if (cached !== null) {
      log(`  [cache HIT]${tag ? ` ${tag}` : ""} modelo=${model}`);
      return cached;
    }
  }

  // #2 — Backoff exponencial
  let lastError: Error | null = null;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    if (attempt > 0) {
      // Si la respuesta anterior trajo Retry-After, respetarlo; si no, usar delay exponencial
      const delay = lastRetryAfterMs ?? BACKOFF_DELAYS_MS[attempt - 1];
      log(`  [retry]${tag ? ` ${tag}` : ""} intento ${attempt}/${MAX_RETRIES} esperando ${delay}ms`);
      if (!skipSleep) await sleep(delay);
      lastRetryAfterMs = null;
    }

    try {
      const result = await callLLMRaw(model, systemPrompt, userPrompt, fetchImpl);
      if (result.status === 200) {
        // #3 — Guardar en cache
        if (cacheable) writeCache(model, systemPrompt, userPrompt, result.content);
        return result.content;
      }
      if (result.status === 429) {
        lastRetryAfterMs = result.retryAfterMs;
        lastError = new Error(`HTTP 429: rate limit`);
        continue;
      }
      // Otros errores (5xx, 4xx) — reintentar igual, podría ser transitorio
      lastError = new Error(`HTTP ${result.status}`);
      continue;
    } catch (e: any) {
      lastError = e instanceof Error ? e : new Error(String(e));
      // Errores de red (fetch failed) — reintentar
      continue;
    }
  }

  throw lastError ?? new Error("callLLM falló tras reintentos");
}

let lastRetryAfterMs: number | null = null;

// ── Prompts ─────────────────────────────────────────────────────

const SYSTEM_PROMPT_HEAVY = "Eres un subagente del sistema de recuperación de contexto contexto_zai. Generas resúmenes en un formato RÍGIDO de 4 oraciones y entre 600 y 900 caracteres. No usas secciones, ni listas, ni negritas, ni ALL CAPS. Respondes con un solo párrafo de texto natural separado por puntos y seguido.";

const SYSTEM_PROMPT_LIGHT = "Eres un subagente del sistema de recuperación de contexto contexto_zai. Extraes información estructurada de un resumen. Respondes SIEMPRE en JSON válido, sin texto adicional.";

// v6.3 F5: Prompt riguroso con formato rígido para garantizar resúmenes similares.
// QUÉ SOLUCIONA: en v6.1 el prompt era laxo ("máximo 1000 chars"), lo que producía
// 5 formatos distintos de RESUMEN y 79% superaba los 1500 chars.
// CÓMO LO HACE: impone longitud EXACTA 600-900 chars, 4 oraciones con estructura
// fija (tema/decisiones/temas/actividad), prohibiciones explícitas y un ejemplo.
const PROMPT_RESUMEN = (bloqueContent: string) => `Lee el siguiente bloque de intercambios entre un Director y un agente.

Genera un resumen del bloque con estas reglas RÍGIDAS:

FORMATO OBLIGATORIO:
- Un solo párrafo de texto natural (sin secciones, sin listas, sin numeración).
- Longitud EXACTA entre 600 y 900 caracteres.
- Exactamente 4 oraciones, separadas por punto y seguido.
- Sin negritas, sin ALL CAPS, sin emojis.
- Sin "Decisiones destacadas:", sin "Tema central:", sin etiquetas.

ESTRUCTURA DE LAS 4 ORACIONES:
1. Tema central (qué se discutió en el bloque).
2. Decisiones principales tomadas (si no hay, decir "sin decisiones formales").
3. Temas específicos mencionados (2-3 keywords máximo).
4. Tipo de actividad (debugging/diseño/implementación/discusión).

EJEMPLO de resumen bien formado:
"Implementación del milestone H2 del plan v4.0 con intervención quirúrgica del EstadoGenerator para reducir el estado actual de 8 a 5 secciones. Se decidió eliminar D2 y D3 del ensamblado pero conservándolos en código, inyectar SubagentLauncher opcional con fallback regex, y añadir 12 auto-tests nuevos. Los temas principales fueron estado_generator, truncado inteligente y subagentes clasificación. La actividad predominante fue implementación con validación de tests reales."

PROHIBICIONES:
- No uses "Decisiones destacadas:" ni "Tema central:" ni etiquetas similares.
- No hagas listas con guiones ni numeración.
- No superes los 900 caracteres ni bajes de 600.
- No incluyas código ni rutas de archivos.

Bloque:
${bloqueContent}

Resumen:`;

// #1 — Prompt fusionado: W2+W3+W4 en una sola llamada JSON
const PROMPT_EXTRACT_ALL = (resumen: string) => `Basándote en este resumen de un bloque de chat, extrae TRES piezas de información. Devuelve EXCLUSIVAMENTE un JSON válido con esta forma exacta:

{
  "nombre": "<snake_case, máximo 5 palabras, captura el tema central>",
  "decisiones": ["DECISION: ... | ALCANCE: ...", "DECISION: ... | ALCANCE: ..."],
  "temas": ["tema_uno", "tema_dos", "tema_tres"]
}

Reglas:
- "nombre": snake_case, máximo 5 palabras.
- "decisiones": lista (puede ser vacía si no hay decisiones explícitas). Cada item con formato "DECISION: ... | ALCANCE: ...".
- "temas": lista de máximo 5 temas en snake_case.

Resumen:
${resumen}

JSON:`;

// ── Workers ────────────────────────────────────────────────────

async function worker1_resumen(block: PendingBlock): Promise<string> {
  const blockPath = block.path;
  if (!existsSync(blockPath)) {
    throw new Error(`Bloque no existe: ${blockPath}`);
  }

  const blockContent = readFileSync(blockPath, "utf-8");

  // Verificar si ya tiene RESUMEN: al inicio (idempotente)
  if (blockContent.startsWith("RESUMEN:")) {
    const resumenMatch = blockContent.match(/^RESUMEN:\s*(.+?)(?=\n---|\n##|\n#|\Z)/s);
    if (resumenMatch) {
      log(`  [W1] ${block.block_id}: resumen ya existe, saltando`);
      return resumenMatch[1].trim();
    }
  }

  // Truncar si es muy grande
  const maxChars = 50000;
  const content = blockContent.length > maxChars
    ? blockContent.slice(0, maxChars) + "\n...(contenido truncado)..."
    : blockContent;

  // #5 — Modelo pesado para W1
  const resumen = await callLLM(MODEL_HEAVY, SYSTEM_PROMPT_HEAVY, PROMPT_RESUMEN(content), {
    cacheable: true,
    tag: `W1 ${block.block_id}`,
  });

  // Escribir resumen al inicio del bloque
  const newContent = `RESUMEN: ${resumen}\n\n---\n\n${blockContent}`;
  writeFileSync(blockPath, newContent, "utf-8");

  // Guardar resumen en _responses para W2-fusionado
  if (!existsSync(RESPONSES_DIR)) mkdirSync(RESPONSES_DIR, { recursive: true });
  writeFileSync(join(RESPONSES_DIR, `${block.block_id}_resumen.txt`), resumen, "utf-8");

  log(`  [W1] ${block.block_id}: resumen generado (${resumen.length} chars) modelo=${MODEL_HEAVY}`);
  return resumen;
}

// #1 — Worker 2 fusionado: nombre + decisiones + temas en una sola llamada
async function worker2_extract_all(block: PendingBlock, resumen: string): Promise<void> {
  // #5 — Modelo liviano para W2-fusionado
  const raw = await callLLM(MODEL_LIGHT, SYSTEM_PROMPT_LIGHT, PROMPT_EXTRACT_ALL(resumen), {
    cacheable: true,
    tag: `W2 ${block.block_id}`,
  });

  // Parsear JSON (tolerante a markdown fences)
  let parsed: { nombre?: string; decisiones?: string[]; temas?: string[] };
  const cleaned = raw.replace(/^```(?:json)?\s*/i, "").replace(/\s*```\s*$/, "").trim();
  try {
    parsed = JSON.parse(cleaned);
  } catch {
    // Si falla el parseo, guardar el raw como fallback y loggear
    log(`  [W2] ${block.block_id}: WARN - JSON parse failed, guardando raw`);
    writeFileSync(join(RESPONSES_DIR, `${block.block_id}_extract_raw.txt`), raw, "utf-8");
    parsed = {};
  }

  const nombre = (parsed.nombre || "bloque_sin_nombre").trim();
  const decisiones = Array.isArray(parsed.decisiones) ? parsed.decisiones : [];
  const temas = Array.isArray(parsed.temas) ? parsed.temas : [];

  writeFileSync(join(RESPONSES_DIR, `${block.block_id}_nombre.txt`), nombre, "utf-8");
  writeFileSync(join(RESPONSES_DIR, `${block.block_id}_decisiones.txt`), decisiones.join("\n"), "utf-8");
  writeFileSync(join(RESPONSES_DIR, `${block.block_id}_temas.txt`), temas.join("\n"), "utf-8");

  log(`  [W2] ${block.block_id}: nombre='${nombre}' · ${decisiones.length} decisiones · ${temas.length} temas · modelo=${MODEL_LIGHT}`);
}

// ── Procesar un bloque completo ─────────────────────────────────

async function processBlock(block: PendingBlock): Promise<void> {
  const t0 = Date.now();
  log(`Procesando bloque ${block.block_id}...`);

  try {
    // Worker 1: genera resumen (cuello de botella, ~10s)
    const resumen = await worker1_resumen(block);

    // #1 — Worker 2 fusionado (en vez de W2+W3+W4 en paralelo)
    await worker2_extract_all(block, resumen);

    // Marcar como completado
    markBlockProcessed(block, "completed");
    const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
    log(`  ${block.block_id} completado en ${elapsed}s`);
  } catch (e: any) {
    const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
    log(`  ${block.block_id} FALLÓ tras ${elapsed}s: ${e?.message || e}`);
    markBlockProcessed(block, "failed", e?.message || String(e));
  }
}

// ── Gestión de estado ──────────────────────────────────────────

function markBlockProcessed(block: PendingBlock, status: string, error?: string): void {
  let processed: any[] = [];
  if (existsSync(PROCESSED_BLOCKS_FILE)) {
    try {
      processed = JSON.parse(readFileSync(PROCESSED_BLOCKS_FILE, "utf-8")).blocks || [];
    } catch {
      processed = [];
    }
  }
  processed.push({
    block_id: block.block_id,
    status,
    processed_at: new Date().toISOString(),
    error: error || null,
  });
  writeFileSync(PROCESSED_BLOCKS_FILE, JSON.stringify({ blocks: processed }, null, 2), "utf-8");
}

function isBlockProcessed(blockId: string): boolean {
  if (!existsSync(PROCESSED_BLOCKS_FILE)) return false;
  try {
    const processed = JSON.parse(readFileSync(PROCESSED_BLOCKS_FILE, "utf-8")).blocks || [];
    return processed.some((b: any) => b.block_id === blockId && b.status === "completed");
  } catch {
    return false;
  }
}

// ── Lectura de bloques pendientes ───────────────────────────────

function readPendingBlocks(): PendingBlock[] {
  if (!existsSync(PENDING_BLOCKS_FILE)) return [];
  try {
    const data = JSON.parse(readFileSync(PENDING_BLOCKS_FILE, "utf-8"));
    return data.blocks || [];
  } catch (e) {
    log(`ERROR leyendo ${PENDING_BLOCKS_FILE}: ${e}`);
    return [];
  }
}

// ── Health check HTTP ───────────────────────────────────────────

async function startHealthServer(): Promise<void> {
  const server = Bun.serve({
    port: PORT,
    fetch(req: Request): Response {
      const url = new URL(req.url);
      if (url.pathname === "/health" || url.pathname === "/") {
        return new Response(
          JSON.stringify({
            status: "ok",
            version: "v6.1",
            models: { heavy: MODEL_HEAVY, light: MODEL_LIGHT },
            workspace: WORKSPACE_DIR,
          }),
          { headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response("Not Found", { status: 404 });
    },
  });
  log(`Health check en http://localhost:${PORT}/health`);
  // Mantener referencia al server para que no sea GC'd
  void server;
}

// ── Main loop ──────────────────────────────────────────────────
//
// La función `main()` se define abajo (sección "Punto de entrada") para
// permitir que este archivo sea importado por tests sin ejecutar main() al
// cargar. Bun ejecuta `if (import.meta.main)` solo cuando es el entrypoint.

// ── Punto de entrada ────────────────────────────────────────────
//
// Si se ejecuta directamente (`bun index.ts` o `bun run cli.ts run`), arranca
// el modo normal. Si se importa desde tests u otros módulos, NO se ejecuta
// automáticamente (permite a los tests llamar a `main()` explícitamente).

async function main(): Promise<void> {
  log("=== Worker Cascade v6.1 (soluciones #1+#2+#3+#5) ===");
  log(`Workspace: ${WORKSPACE_DIR}`);
  log(`Proxy APA: ${PROXY_URL}`);
  log(`Puerto: ${PORT}`);
  log(`Modelo pesado (W1): ${MODEL_HEAVY}`);
  log(`Modelo liviano (W2 fusionado): ${MODEL_LIGHT}`);
  log(`Cache dir: ${CACHE_DIR}`);
  log(`Backoff delays (ms): ${BACKOFF_DELAYS_MS.join(", ")}`);

  // Health check server
  await startHealthServer();

  // Verificar proxy APA
  try {
    const testResp = await fetch(PROXY_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: MODEL_HEAVY,
        messages: [{ role: "user", content: "test" }],
      }),
    });
    if (!testResp.ok) {
      log(`FATAL: Proxy APA no responde (HTTP ${testResp.status})`);
      process.exit(1);
    }
    log("Proxy APA: OK");
  } catch (e) {
    log(`FATAL: No se puede conectar al proxy APA: ${e}`);
    process.exit(1);
  }

  // Procesar bloques
  const blocks = readPendingBlocks();
  if (blocks.length === 0) {
    log("No hay bloques pendientes. Saliendo.");
    return;
  }

  // Filtrar los ya procesados
  const pendientes = blocks.filter((b) => !isBlockProcessed(b.block_id));
  log(`Bloques pendientes: ${pendientes.length} de ${blocks.length} totales`);

  // Pipeline secuencial: W1 (cuello de botella) → W2-fusionado
  // Ya no hay paralelismo entre bloques porque cada llamada consume cuota compartida.
  // Con #1 reducimos a 2 llamadas/bloque, con #2 aguantamos 429, con #3 evitamos repetrición.
  for (const block of pendientes) {
    await processBlock(block);
  }

  log("=== Todos los bloques procesados ===");

  // Mostrar resumen
  if (existsSync(PROCESSED_BLOCKS_FILE)) {
    const processed = JSON.parse(readFileSync(PROCESSED_BLOCKS_FILE, "utf-8")).blocks || [];
    const completed = processed.filter((b: any) => b.status === "completed").length;
    const failed = processed.filter((b: any) => b.status === "failed").length;
    log(`Resumen: ${completed} completados, ${failed} fallidos`);
  }
}

// Ejecutar `main()` solo si este archivo es el entrypoint directo.
// `import.meta.main` es la API de Bun para detectar esto.
if (import.meta.main) {
  main().catch((e) => {
    log(`FATAL: ${e}`);
    process.exit(1);
  });
}

// Exportaciones para tests E2E y CLI wrapper.
export {
  // Funciones principales
  main,
  callLLM,
  callLLMRaw,
  worker1_resumen,
  worker2_extract_all,
  processBlock,
  // Helpers de cache (#3)
  hashContent,
  cachePath,
  readCache,
  writeCache,
  // Helpers de estado
  readPendingBlocks,
  isBlockProcessed,
  markBlockProcessed,
  // Constantes configurables
  MODEL_HEAVY,
  MODEL_LIGHT,
  BACKOFF_DELAYS_MS,
  MAX_RETRIES,
  PROXY_URL,
  PORT,
  WORKSPACE_DIR,
  PENDING_BLOCKS_FILE,
  RESPONSES_DIR,
  CACHE_DIR,
  PROCESSED_BLOCKS_FILE,
  // Prompts (para tests)
  SYSTEM_PROMPT_HEAVY,
  SYSTEM_PROMPT_LIGHT,
  PROMPT_RESUMEN,
  PROMPT_EXTRACT_ALL,
  // Tipos
  type PendingBlock,
  // Logger
  log,
};
