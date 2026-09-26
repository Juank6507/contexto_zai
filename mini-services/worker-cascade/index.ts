// /home/z/my-project/mini-services/worker-cascade/index.ts
// Worker Bun persistente que coordina la cascada Worker 1 → Workers 2-4 (v6.0).
/**
 * Lee _pending_blocks.json, procesa cada bloque con la cascada:
 *   Worker 1: lee bloque completo → genera resumen → escribe al inicio del bloque
 *   Workers 2, 3, 4 (en paralelo): leen resumen → extraen nombre, decisiones, temas
 *
 * Pipeline asincrónico: mientras Workers 2-4 del bloque N corren, Worker 1 del bloque N+1 arranca.
 *
 * Puerto: 8090 (health check)
 * Proxy APA: http://localhost:3000/api/zai-proxy/v1/chat/completions
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync } from "fs";
import { join } from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const WORKSPACE_DIR = process.env.CZAI_WORKSPACE_DIR || "/home/z/my-project/contexto_recuperacion";
const PENDING_BLOCKS_FILE = join(WORKSPACE_DIR, "_pending_blocks.json");
const RESPONSES_DIR = join(WORKSPACE_DIR, "_responses");
const PROCESSED_BLOCKS_FILE = join(WORKSPACE_DIR, "_processed_blocks.json");

const PROXY_URL = "http://localhost:3000/api/zai-proxy/v1/chat/completions";
const PORT = 8090;

const MAX_PARALLEL_WORKERS_24 = 3;
const POLL_INTERVAL_MS = 3000;

function log(msg: string) {
  const ts = new Date().toISOString();
  console.log(`[${ts}] ${msg}`);
}

// ── Tipos ──────────────────────────────────────────────────────

interface PendingBlock {
  block_id: string;
  filename: string;
  path: string;
}

// ── LLM ─────────────────────────────────────────────────────────

async function callLLM(systemPrompt: string, userPrompt: string): Promise<string> {
  const body = JSON.stringify({
    model: "glm-4-plus",
    messages: [
      { role: "system", content: systemPrompt },
      { role: "user", content: userPrompt }
    ]
  });

  const resp = await fetch(PROXY_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });

  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`HTTP ${resp.status}: ${text.slice(0, 200)}`);
  }

  const data = await resp.json() as any;
  const content = data.choices?.[0]?.message?.content || "";
  if (!content) throw new Error("Respuesta vacía del LLM");
  return content;
}

// ── Prompts ─────────────────────────────────────────────────────

const SYSTEM_PROMPT = "Eres un subagente del sistema de recuperación de contexto contexto_zai. Respondes de forma concisa y directa.";

const PROMPT_RESUMEN = (bloqueContent: string) => `Lee el siguiente bloque de intercambios entre un Director y un agente.
Genera un resumen abarcador del tema de este bloque. El resumen debe ser un texto natural que capture la esencia del bloque, pero que NO omita estos 4 aspectos:

1. Tema central: ¿de qué trata este bloque?
2. Decisiones: ¿qué decisiones se tomaron?
3. Temas: ¿qué temas específicos se discutieron?
4. Actividad: ¿qué tipo de actividad fue? (debugging/diseño/implementación/discusión)

El resumen debe ser de máximo 1000 chars.

Bloque:
${bloqueContent}

Resumen:`;

const PROMPT_NOMBRE = (resumen: string) => `Basándote en este resumen de un bloque de chat, asigna un nombre legible en snake_case que capture el tema central. Máximo 5 palabras.

Resumen:
${resumen}

Nombre legible:`;

const PROMPT_DECISIONES = (resumen: string) => `Basándote en este resumen, extrae las decisiones reales tomadas.
Para cada decisión, indica su alcance.

Resumen:
${resumen}

Decisiones (formato: DECISION: ... | ALCANCE: ...):`;

const PROMPT_TEMAS = (resumen: string) => `Basándote en este resumen, lista los temas principales discutidos (en snake_case, máximo 5).

Resumen:
${resumen}

Temas principales:`;

// ── Workers ────────────────────────────────────────────────────

async function worker1_resumen(block: PendingBlock): Promise<string> {
  // Worker 1: lee el bloque completo, genera resumen, lo escribe al inicio
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

  const resumen = await callLLM(SYSTEM_PROMPT, PROMPT_RESUMEN(content));

  // Escribir resumen al inicio del bloque
  const newContent = `RESUMEN: ${resumen}\n\n---\n\n${blockContent}`;
  writeFileSync(blockPath, newContent, "utf-8");

  // Guardar resumen en _responses para los Workers 2-4
  if (!existsSync(RESPONSES_DIR)) mkdirSync(RESPONSES_DIR, { recursive: true });
  writeFileSync(join(RESPONSES_DIR, `${block.block_id}_resumen.txt`), resumen, "utf-8");

  log(`  [W1] ${block.block_id}: resumen generado (${resumen.length} chars)`);
  return resumen;
}

async function worker2_nombre(block: PendingBlock, resumen: string): Promise<void> {
  const nombre = await callLLM(SYSTEM_PROMPT, PROMPT_NOMBRE(resumen));
  writeFileSync(join(RESPONSES_DIR, `${block.block_id}_nombre.txt`), nombre.trim(), "utf-8");
  log(`  [W2] ${block.block_id}: nombre='${nombre.trim()}'`);
}

async function worker3_decisiones(block: PendingBlock, resumen: string): Promise<void> {
  const decisiones = await callLLM(SYSTEM_PROMPT, PROMPT_DECISIONES(resumen));
  writeFileSync(join(RESPONSES_DIR, `${block.block_id}_decisiones.txt`), decisiones.trim(), "utf-8");
  log(`  [W3] ${block.block_id}: ${decisiones.length} chars de decisiones`);
}

async function worker4_temas(block: PendingBlock, resumen: string): Promise<void> {
  const temas = await callLLM(SYSTEM_PROMPT, PROMPT_TEMAS(resumen));
  writeFileSync(join(RESPONSES_DIR, `${block.block_id}_temas.txt`), temas.trim(), "utf-8");
  log(`  [W4] ${block.block_id}: temas='${temas.trim()}'`);
}

// ── Procesar un bloque completo ─────────────────────────────────

async function processBlock(block: PendingBlock): Promise<void> {
  const t0 = Date.now();
  log(`Procesando bloque ${block.block_id}...`);

  try {
    // Worker 1: genera resumen (cuello de botella, ~10s)
    const resumen = await worker1_resumen(block);

    // Workers 2, 3, 4 en paralelo sobre el resumen (~3s)
    await Promise.all([
      worker2_nombre(block, resumen),
      worker3_decisiones(block, resumen),
      worker4_temas(block, resumen),
    ]);

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

// ── Main loop ──────────────────────────────────────────────────

async function main() {
  log("=== Worker Cascade v6.0 ===");
  log(`Workspace: ${WORKSPACE_DIR}`);
  log(`Proxy APA: ${PROXY_URL}`);
  log(`Puerto: ${PORT}`);

  // Verificar proxy APA
  try {
    const testResp = await fetch(PROXY_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "glm-4-plus",
        messages: [{ role: "user", content: "test" }]
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
  const pendientes = blocks.filter(b => !isBlockProcessed(b.block_id));
  log(`Bloques pendientes: ${pendientes.length} de ${blocks.length} totales`);

  // Procesar secuencialmente (Worker 1) con Workers 2-4 en paralelo
  // Pipeline asincrónico: mientras W2-4 del bloque N corren, W1 del N+1 arranca
  let prevWorkers: Promise<void> | null = null;

  for (const block of pendientes) {
    // Esperar a que los Workers 2-4 del bloque anterior terminen
    if (prevWorkers) {
      await prevWorkers;
    }

    // Worker 1 del bloque actual (cuello de botella)
    const t0 = Date.now();
    let resumen: string;
    try {
      resumen = await worker1_resumen(block);
    } catch (e: any) {
      log(`  ${block.block_id} FALLÓ en W1: ${e?.message || e}`);
      markBlockProcessed(block, "failed", e?.message || String(e));
      prevWorkers = null;
      continue;
    }

    // Lanzar Workers 2-4 en paralelo (no esperar — arrancar W1 del siguiente)
    prevWorkers = Promise.all([
      worker2_nombre(block, resumen),
      worker3_decisiones(block, resumen),
      worker4_temas(block, resumen),
    ]).then(() => {
      markBlockProcessed(block, "completed");
      const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
      log(`  ${block.block_id} completado en ${elapsed}s`);
    }).catch((e: any) => {
      log(`  ${block.block_id} FALLÓ en W2-4: ${e?.message || e}`);
      markBlockProcessed(block, "failed", e?.message || String(e));
    });
  }

  // Esperar al último bloque
  if (prevWorkers) {
    await prevWorkers;
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

main().catch(e => {
  log(`FATAL: ${e}`);
  process.exit(1);
});
