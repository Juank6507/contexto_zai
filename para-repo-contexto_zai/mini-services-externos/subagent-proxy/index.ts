// mini-services/subagent-proxy/index.ts — Proxy de subagentes para contexto_zai v7.0.
/**
 * Proxy de subagentes (v7.0).
 *
 * v7.0 F3+F4: abstracción de plataforma + circuit breaker + clasificación de errores.
 *
 * Cambios v7.0:
 * - LLMProvider interface abstrae el acceso al LLM. Implementación concreta
 *   ZaiLLMProvider usa z-ai-web-dev-sdk (igual que antes). Cuando MB esté
 *   disponible, se añade MBLLMProvider y se inyecta por env var.
 * - CircuitBreaker: si 5 tareas fallan consecutivas, breaker abre, espera 60s.
 * - Clasificación de errores: 401/403/missing X-Token → no recuperable, van a
 *   _failed_tasks.json sin reintento. 429/5xx/network → recuperable, reintenta.
 * - processTask SIEMPRE elimina la tarea de _pending_tasks.json después de
 *   procesarla (éxito o fallo), evitando el bucle infinito de v6.20.
 *
 * Lee tareas pendientes de `_pending_tasks.json`, las ejecuta con el LLMProvider
 * inyectado (default: ZaiLLMProvider), y escribe las respuestas en
 * `_responses/{task_id}.txt`.
 *
 * Uso:
 *   bun run dev          # desarrollo (auto-restart)
 *   bun run start        # producción
 *   CZAI_LLM_PROVIDER=mb bun run dev   # cuando MB esté disponible
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";
import ZAI from "z-ai-web-dev-sdk";

// ── Configuración ──────────────────────────────────────────────

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const WORKSPACE_DIR = process.env.CZAI_WORKSPACE_DIR || "/home/z/my-project/contexto_recuperacion";
const PENDING_FILE = join(WORKSPACE_DIR, "_pending_tasks.json");
const RESPONSES_DIR = join(WORKSPACE_DIR, "_responses");
const PROCESSED_FILE = join(WORKSPACE_DIR, "_processed_tasks.json");
const FAILED_FILE = join(WORKSPACE_DIR, "_failed_tasks.json");
const PROXY_ACTIVE_FILE = join(WORKSPACE_DIR, "_proxy_active");

// Paralelismo (bajo para evitar 429 Too Many Requests)
const MAX_PARALLEL = 2;

// Intervalo de polling (más largo para evitar rate limit)
const POLL_INTERVAL_MS = 3000;

// Backoff exponencial al recibir 429
const RATE_LIMIT_BACKOFF_MS = 10000; // 10s de espera cuando hay rate limit

// Circuit breaker: si 5 fallos consecutivos, breaker abre por 60s.
const BREAKER_THRESHOLD = 5;
const BREAKER_COOLDOWN_MS = 60000;

// ── Logging ────────────────────────────────────────────────────

function log(msg: string) {
  const ts = new Date().toISOString();
  console.log(`[${ts}] ${msg}`);
}

// ── LLMProvider: interfaz abstracta de acceso al LLM ──────────

/**
 * Interfaz abstracta para acceder al LLM.
 *
 * v7.0 F3: abstrae el SDK concreto (z-ai-web-dev-sdk) detrás de una interfaz
 * para que cuando MB esté disponible, se pueda inyectar MBLLMProvider sin
 * tocar el código del proxy.
 *
 * La implementación concreta se elige por env var CZAI_LLM_PROVIDER:
 * - "zai" (default): usa z-ai-web-dev-sdk (SDK oficial de Z.ai).
 * - "mb" (futuro): usará la API de MB.
 */
interface LLMProvider {
  /** Llama al LLM con un prompt y devuelve la respuesta en string. */
  call(prompt: string): Promise<string>;
  /** Devuelve el nombre del proveedor (para logs). */
  name(): string;
}

// ── ZaiLLMProvider: implementación concreta con z-ai-web-dev-sdk ──

class ZaiLLMProvider implements LLMProvider {
  private zaiInstance: any = null;

  constructor() {
    // Inicialización lazy del SDK (puede ser costosa).
  }

  private async getZAI(): Promise<any> {
    if (!this.zaiInstance) {
      this.zaiInstance = await ZAI.create();
      log("ZaiLLMProvider: instancia de ZAI SDK inicializada.");
    }
    return this.zaiInstance;
  }

  async call(prompt: string): Promise<string> {
    const zai = await this.getZAI();
    const timeoutPromise = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("Timeout 90s")), 90000)
    );
    const completion = await Promise.race([
      zai.chat.completions.create({
        messages: [
          { role: "assistant", content: "Eres un subagente del sistema de recuperación de contexto contexto_zai. Respondes de forma concisa y directa, siguiendo exactamente el formato pedido." },
          { role: "user", content: prompt }
        ],
        thinking: { type: "disabled" },
      }),
      timeoutPromise,
    ]) as any;
    const content = completion.choices?.[0]?.message?.content || "";
    if (!content) throw new Error("Respuesta vacía del LLM");
    return content;
  }

  name(): string {
    return "zai-sdk";
  }
}

// ── Factory: elegir implementación por env var ─────────────────

function createLLMProvider(): LLMProvider {
  const provider = process.env.CZAI_LLM_PROVIDER || "zai";
  if (provider === "mb") {
    // v7.1: cuando MB esté disponible, devolver MBLLMProvider.
    // Por ahora, fallar temprano para no silenciar el error.
    throw new Error(
      "CZAI_LLM_PROVIDER=mb pero MBLLMProvider no está implementado todavía (v7.1). " +
      "Usa CZAI_LLM_PROVIDER=zai (default) o implementa MBLLMProvider."
    );
  }
  return new ZaiLLMProvider();
}

// ── CircuitBreaker ─────────────────────────────────────────────

class CircuitBreaker {
  private consecutiveFailures = 0;
  private openUntil: number = 0; // timestamp ms cuando se puede volver a intentar

  /** Devuelve true si el breaker está abierto (no se deben procesar tareas). */
  isOpen(): boolean {
    if (this.consecutiveFailures < BREAKER_THRESHOLD) return false;
    return Date.now() < this.openUntil;
  }

  /** Registrar un éxito: resetear contador y cerrar breaker. */
  recordSuccess(): void {
    if (this.consecutiveFailures > 0) {
      log(`CircuitBreaker: reset tras éxito (consecutive_failures=${this.consecutiveFailures}).`);
    }
    this.consecutiveFailures = 0;
    this.openUntil = 0;
  }

  /** Registrar un fallo: incrementar contador y abrir breaker si pasa umbral. */
  recordFailure(): void {
    this.consecutiveFailures++;
    if (this.consecutiveFailures >= BREAKER_THRESHOLD) {
      this.openUntil = Date.now() + BREAKER_COOLDOWN_MS;
      log(
        `CircuitBreaker: ABIERTO por ${BREAKER_COOLDOWN_MS / 1000}s ` +
        `(consecutive_failures=${this.consecutiveFailures}). ` +
        `No se procesarán tareas hasta ${new Date(this.openUntil).toISOString()}.`
      );
    }
  }

  /** Tiempo restante de cooldown en ms (0 si cerrado). */
  remainingCooldown(): number {
    if (!this.isOpen()) return 0;
    return this.openUntil - Date.now();
  }
}

const breaker = new CircuitBreaker();

// ── Clasificación de errores ───────────────────────────────────

/**
 * Clasifica un error en recuperable o no recuperable.
 *
 * - No recuperable: 401, 403, "missing X-Token", "Unauthorized", "Invalid API key".
 *   Estas tareas van a _failed_tasks.json sin reintento.
 * - Recuperable: 429, 5xx, ETIMEDOUT, ECONNRESET, "fetch failed", timeouts.
 *   Estas tareas se reintentan (sujetas a circuit breaker).
 */
function isRecoverable(error: unknown): boolean {
  const msg = String((error as any)?.message || error || "");
  // Patrones no recuperables (de autenticación/autorización).
  const nonRecoverablePatterns = [
    "401", "403",
    "missing X-Token",
    "missing X-Token header",
    "Unauthorized",
    "Invalid API key",
    "API key invalid",
    "Forbidden",
  ];
  for (const p of nonRecoverablePatterns) {
    if (msg.includes(p)) return false;
  }
  // El resto se considera recuperable (429, 5xx, red, timeouts, etc.).
  return true;
}

// ── Tareas pendientes ──────────────────────────────────────────

interface SubagentTask {
  task_id: string;
  purpose: string;
  prompt: string;
}

function readPendingTasks(): SubagentTask[] {
  if (!existsSync(PENDING_FILE)) return [];
  try {
    const raw = readFileSync(PENDING_FILE, "utf-8");
    const data = JSON.parse(raw);
    return data.tasks || [];
  } catch (e) {
    log(`ERROR leyendo ${PENDING_FILE}: ${e}`);
    return [];
  }
}

function writePendingTasks(tasks: SubagentTask[]) {
  const data = { tasks };
  writeFileSync(PENDING_FILE, JSON.stringify(data, null, 2), "utf-8");
}

function removePendingTask(taskId: string): void {
  // v7.0 F4: SIEMPRE elimina la tarea del pending, sin importar si fue éxito o fallo.
  // Esto evita el bucle infinito de v6.20 donde las tareas fallidas se quedaban
  // en _pending_tasks.json para siempre y se reintentaban indefinidamente.
  const tasks = readPendingTasks().filter(t => t.task_id !== taskId);
  writePendingTasks(tasks);
}

function moveTaskToProcessed(task: SubagentTask, response: string, error?: string) {
  let processed: any[] = [];
  if (existsSync(PROCESSED_FILE)) {
    try {
      processed = JSON.parse(readFileSync(PROCESSED_FILE, "utf-8")).tasks || [];
    } catch {
      processed = [];
    }
  }
  processed.push({
    ...task,
    processed_at: new Date().toISOString(),
    response_length: response.length,
    error: error || null,
  });
  writeFileSync(PROCESSED_FILE, JSON.stringify({ tasks: processed }, null, 2), "utf-8");
}

function moveTaskToFailed(task: SubagentTask, error: string): void {
  // v7.0 F4: las tareas no recuperables (401, 403, etc.) van a _failed_tasks.json,
  // separadas del _processed_tasks.json, para diagnóstico sin reintentar.
  let failed: any[] = [];
  if (existsSync(FAILED_FILE)) {
    try {
      failed = JSON.parse(readFileSync(FAILED_FILE, "utf-8")).tasks || [];
    } catch {
      failed = [];
    }
  }
  failed.push({
    ...task,
    failed_at: new Date().toISOString(),
    error,
    reason: "non_recoverable",
  });
  writeFileSync(FAILED_FILE, JSON.stringify({ tasks: failed }, null, 2), "utf-8");
  log(`Tarea ${task.task_id} movida a _failed_tasks.json (non_recoverable: ${error})`);
}

function writeResponse(taskId: string, content: string) {
  if (!existsSync(RESPONSES_DIR)) {
    mkdirSync(RESPONSES_DIR, { recursive: true });
  }
  const respPath = join(RESPONSES_DIR, `${taskId}.txt`);
  writeFileSync(respPath, content, "utf-8");
}

// ── LLM con backoff + clasificación de errores ─────────────────

async function callLLM(
  provider: LLMProvider,
  prompt: string,
  retries = 3
): Promise<string> {
  let lastError: any = null;
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const content = await provider.call(prompt);
      if (!content) throw new Error("Respuesta vacía del LLM");
      return content;
    } catch (e: any) {
      lastError = e;
      const msg = String(e?.message || e);

      // Clasificación de errores (v7.0 F4).
      if (!isRecoverable(e)) {
        // Error no recuperable (401, 403, etc.) — no reintentar.
        log(`Error no recuperable: ${msg}. Abortando reintentos.`);
        throw e;
      }

      // 429 rate limit — backoff exponencial.
      if (msg.includes("429") && attempt < retries) {
        const waitMs = RATE_LIMIT_BACKOFF_MS * attempt;
        log(`429 rate limit (intento ${attempt}/${retries}). Esperando ${waitMs}ms...`);
        await new Promise(r => setTimeout(r, waitMs));
        continue;
      }
      // Otros errores recuperables — reintento con espera.
      if (attempt < retries) {
        log(`Error recuperable en intento ${attempt}/${retries}: ${msg}. Reintentando...`);
        await new Promise(r => setTimeout(r, 5000));
        continue;
      }
      throw e;
    }
  }
  throw lastError;
}

// ── Worker ─────────────────────────────────────────────────────

async function processTask(provider: LLMProvider, task: SubagentTask): Promise<void> {
  const t0 = Date.now();
  log(`Procesando tarea ${task.task_id} (purpose=${task.purpose})`);
  try {
    const response = await callLLM(provider, task.prompt);
    writeResponse(task.task_id, response);
    moveTaskToProcessed(task, response);
    breaker.recordSuccess();
    const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
    log(`OK ${task.task_id}: ${response.length} chars en ${elapsed}s`);
  } catch (e: any) {
    const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
    const msg = String(e?.message || e);
    log(`ERROR ${task.task_id} tras ${elapsed}s: ${msg}`);

    // v7.0 F4: clasificar el error.
    if (!isRecoverable(e)) {
      // No recuperable: mover a _failed_tasks.json, NO reintentar.
      moveTaskToFailed(task, msg);
    } else {
      // Recuperable pero agotado reintentos: registrar en processed con error.
      moveTaskToProcessed(task, "", msg);
      breaker.recordFailure();
    }
  } finally {
    // v7.0 F4: SIEMPRE eliminar la tarea del pending, sin importar el resultado.
    // El bucle infinito de v6.20 (tareas fallidas que se reintentaban para siempre)
    // se rompe aquí.
    removePendingTask(task.task_id);
  }
}

async function processPendingTasks(provider: LLMProvider): Promise<void> {
  const tasks = readPendingTasks();
  if (tasks.length === 0) return;

  // v7.0 F4: si el circuit breaker está abierto, no procesar.
  if (breaker.isOpen()) {
    const remaining = Math.ceil(breaker.remainingCooldown() / 1000);
    log(`CircuitBreaker abierto — esperando ${remaining}s antes de procesar ${tasks.length} tarea(s).`);
    return;
  }

  log(`Hay ${tasks.length} tareas pendientes. Procesando hasta ${MAX_PARALLEL} en paralelo.`);
  const batch = tasks.slice(0, MAX_PARALLEL);
  await Promise.all(batch.map(t => processTask(provider, t)));
}

// ── Main loop ──────────────────────────────────────────────────

async function main() {
  log("=== Subagent Proxy v7.0 (LLMProvider + CircuitBreaker + Error Classification) ===");
  log(`Workspace: ${WORKSPACE_DIR}`);
  log(`LLM Provider: ${process.env.CZAI_LLM_PROVIDER || "zai (default)"}`);
  log(`Max paralelo: ${MAX_PARALLEL}`);
  log(`Poll interval: ${POLL_INTERVAL_MS}ms`);
  log(`CircuitBreaker: threshold=${BREAKER_THRESHOLD}, cooldown=${BREAKER_COOLDOWN_MS / 1000}s`);

  // v7.0 F3: construir LLMProvider (default Zai).
  const provider = createLLMProvider();
  log(`LLMProvider instanciado: ${provider.name()}`);

  // Crear archivo _proxy_active
  writeFileSync(PROXY_ACTIVE_FILE, JSON.stringify({
    started_at: new Date().toISOString(),
    pid: process.pid,
    sdk: provider.name(),
    version: "v7.0",
  }), "utf-8");
  log(`Archivo _proxy_active creado.`);

  // Bucle principal
  let iter = 0;
  let consecutive_empty = 0;
  while (true) {
    try {
      const tasks = readPendingTasks();
      if (tasks.length === 0) {
        consecutive_empty++;
        if (consecutive_empty === 1) log("No hay tareas pendientes. Esperando...");
      } else {
        consecutive_empty = 0;
        await processPendingTasks(provider);
      }
    } catch (e) {
      log(`ERROR en iteración ${iter}: ${e}`);
    }
    iter++;
    await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS));
  }
}

main().catch(e => {
  log(`FATAL: ${e}`);
  process.exit(1);
});
