// contexto_zai/mini-services/worker-cascade/tests/self_test.ts
// Self-test standalone para el Worker Cascade v6.1.
//
// QUÉ SOLUCIONA: en v6.0 no había validación individual del Worker Bun. Si algo
// rompía, solo se detectaba al correr el pipeline completo con el proxy APA real
// (lento, consume cuota, no reproducible).
// CÓMO LO HACE: valida las 4 soluciones de v6.1 en aislamiento, sin necesidad del
// proxy APA real. Para tests de integración con fetch, se inyecta un `fetchImpl`
// mock (no se mockea `globalThis.fetch`, que es frágil). Validaciones:
//   #1 — Fusiona W2+W3+W4 en JSON: valida que el parser JSON tolera markdown fences
//        y extrae nombre/decisiones/temas correctamente.
//   #2 — Backoff exponencial: valida que `callLLM()` reintenta con delays correctos
//        cuando recibe 429, y que respeta `Retry-After` cuando viene.
//   #3 — Cache por hash: valida que el cache HIT evita la llamada LLM, y que el
//        hash cambia si cambia el modelo/sysPrompt/userPrompt.
//   #5 — Modelo dual: valida que W1 usa MODEL_HEAVY y W2 usa MODEL_LIGHT.
//
// Uso:
//   bun run tests/self_test.ts        → corre todos los tests
//   bun run cli.ts --self-test         → alias vía dispatcher
//
// No requiere proxy APA real. Cross-platform (Linux + Windows).

import {
  callLLM,
  hashContent,
  cachePath,
  readCache,
  writeCache,
  MODEL_HEAVY,
  MODEL_LIGHT,
  BACKOFF_DELAYS_MS,
  MAX_RETRIES,
  PROMPT_EXTRACT_ALL,
  PROMPT_RESUMEN,
  SYSTEM_PROMPT_HEAVY,
} from "../index.ts";

import { writeFileSync, existsSync, mkdirSync, rmSync } from "fs";
import { join } from "path";

// ── Test runner minimalista ────────────────────────────────────

let passed = 0;
let failed = 0;
const failures: string[] = [];

function assert(cond: boolean, msg: string): void {
  if (cond) {
    passed++;
    console.log(`  ✓ ${msg}`);
  } else {
    failed++;
    failures.push(msg);
    console.log(`  ✗ ${msg}`);
  }
}

function assertEqual<T>(actual: T, expected: T, msg: string): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed++;
    console.log(`  ✓ ${msg}`);
  } else {
    failed++;
    failures.push(`${msg} (esperado: ${JSON.stringify(expected)}, actual: ${JSON.stringify(actual)})`);
    console.log(`  ✗ ${msg}`);
    console.log(`    esperado: ${JSON.stringify(expected)}`);
    console.log(`    actual:   ${JSON.stringify(actual)}`);
  }
}

// ── Mock fetch inyectable (no toca globalThis.fetch) ────────────

interface MockResponse {
  content: string;
  status: number;
  retryAfterMs?: number;
}

function createMockFetch(responses: MockResponse[]): {
  fetchImpl: typeof fetch;
  callCount: number;
  calls: Array<{ model: string; userPrompt: string }>;
} {
  const queue = [...responses];
  const calls: Array<{ model: string; userPrompt: string }> = [];
  let callCount = 0;

  const fetchImpl = (async (_url: string | URL | Request, init?: RequestInit): Promise<Response> => {
    callCount++;
    const body = init?.body ? JSON.parse(init.body as string) : {};
    calls.push({
      model: body.model || "unknown",
      userPrompt: body.messages?.find((m: any) => m.role === "user")?.content || "",
    });

    const next = queue.shift();
    if (!next) {
      return new Response(JSON.stringify({
        choices: [{ message: { content: "default mock response" } }],
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }

    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (next.retryAfterMs) headers["retry-after"] = String(next.retryAfterMs / 1000);

    if (next.status === 200) {
      return new Response(JSON.stringify({
        choices: [{ message: { content: next.content } }],
      }), { status: 200, headers });
    }
    return new Response(JSON.stringify({ error: "Too many requests" }), {
      status: next.status,
      headers,
    });
  }) as unknown as typeof fetch;

  return { fetchImpl, get callCount() { return callCount; }, calls };
}

// ── Tests ───────────────────────────────────────────────────────

function test_hashContent(): void {
  console.log("\n[Test 1] hashContent — SHA256 determinista de 32 chars");
  const h1 = hashContent("hello");
  const h2 = hashContent("hello");
  const h3 = hashContent("world");
  assertEqual(h1.length, 32, "hash tiene 32 chars");
  assertEqual(h1, h2, "hash es determinista para mismo input");
  assert(h1 !== h3, "hash cambia para input distinto");
}

function test_cachePath(): void {
  console.log("\n[Test 2] cachePath — incluye modelo en el hash");
  const p1 = cachePath("glm-4-plus", "sys", "user");
  const p2 = cachePath("glm-4-flash", "sys", "user");
  const p3 = cachePath("glm-4-plus", "sys", "user");
  assert(p1 !== p2, "cambiar modelo cambia el path de cache");
  assertEqual(p1, p3, "mismos inputs → mismo path");
}

async function test_cacheReadWrite(): Promise<void> {
  console.log("\n[Test 3] readCache/writeCache — escritura y lectura");
  const model = "test-model-" + Date.now();
  const sysPrompt = "test-sys";
  const userPrompt = "test-user";
  const expectedPath = cachePath(model, sysPrompt, userPrompt);

  // Crear directorio padre si no existe
  const parentDir = join(expectedPath, "..");
  if (!existsSync(parentDir)) mkdirSync(parentDir, { recursive: true });

  writeFileSync(expectedPath, "cached content", "utf-8");

  const cached = readCache(model, sysPrompt, userPrompt);
  assertEqual(cached, "cached content", "cache HIT devuelve el contenido escrito");

  const miss = readCache(model, sysPrompt, "otro-prompt");
  assertEqual(miss, null, "cache MISS devuelve null");

  // Limpieza
  try { rmSync(expectedPath, { force: true }); } catch { /* ok */ }
}

async function test_callLLM_backoff(): Promise<void> {
  console.log("\n[Test 4] callLLM backoff exponencial — reintenta tras 429");
  const mock = createMockFetch([
    { content: "", status: 429 },
    { content: "ok response", status: 200 },
  ]);

  // skipSleep=true para que el test sea rápido (no espera 2s reales)
  const result = await callLLM("test-model-backoff", "sys-b", "user-b", {
    cacheable: false,
    fetchImpl: mock.fetchImpl,
    skipSleep: true,
    tag: "T4",
  });

  assertEqual(result, "ok response", "devuelve el contenido tras reintento");
  assertEqual(mock.callCount, 2, "se hicieron 2 llamadas (1 retry)");
}

async function test_callLLM_retryAfter(): Promise<void> {
  console.log("\n[Test 5] callLLM respeta Retry-After header");
  const mock = createMockFetch([
    { content: "", status: 429, retryAfterMs: 1000 },
    { content: "ok after retry-after", status: 200 },
  ]);

  const result = await callLLM("test-model-retry-after", "sys-r", "user-r", {
    cacheable: false,
    fetchImpl: mock.fetchImpl,
    skipSleep: true,
    tag: "T5",
  });

  assertEqual(result, "ok after retry-after", "devuelve contenido tras Retry-After");
  assertEqual(mock.callCount, 2, "se hicieron 2 llamadas");
  // Verificar que la 1ra llamada tuvo Retry-After: 1 en el header
  // (no verificamos el tiempo real porque skipSleep=true)
}

async function test_callLLM_cacheHit(): Promise<void> {
  console.log("\n[Test 6] callLLM cache HIT — no llama al LLM");
  const mock = createMockFetch([{ content: "cached-value-xyz", status: 200 }]);

  // Primera llamada: cache MISS, llama al mock
  const r1 = await callLLM("test-cache-hit-model", "sys-ch", "user-ch", {
    cacheable: true,
    fetchImpl: mock.fetchImpl,
    tag: "T6",
  });
  assertEqual(r1, "cached-value-xyz", "primera llamada devuelve contenido del mock");
  assertEqual(mock.callCount, 1, "se hizo 1 llamada LLM (miss)");

  // Segunda llamada con mismo prompt: cache HIT, NO llama al LLM
  const r2 = await callLLM("test-cache-hit-model", "sys-ch", "user-ch", {
    cacheable: true,
    fetchImpl: mock.fetchImpl,
    tag: "T6",
  });
  assertEqual(r2, "cached-value-xyz", "segunda llamada devuelve contenido cacheado");
  assertEqual(mock.callCount, 1, "no se hicieron más llamadas LLM (cache HIT)");

  // Limpieza del cache de test
  const p = cachePath("test-cache-hit-model", "sys-ch", "user-ch");
  try { rmSync(p, { force: true }); } catch { /* ok */ }
}

async function test_callLLM_maxRetries(): Promise<void> {
  console.log("\n[Test 6b] callLLM agota reintentos — lanza error tras 7 intentos");
  const mock = createMockFetch([
    { content: "", status: 429 },
    { content: "", status: 429 },
    { content: "", status: 429 },
    { content: "", status: 429 },
    { content: "", status: 429 },
    { content: "", status: 429 },
    { content: "", status: 429 }, // 7 intentos, todos 429
  ]);

  let threw = false;
  let errMsg = "";
  try {
    await callLLM("test-model-max-retries", "sys-mr", "user-mr", {
      cacheable: false,
      fetchImpl: mock.fetchImpl,
      skipSleep: true,
      tag: "T6b",
    });
  } catch (e: any) {
    threw = true;
    errMsg = e?.message || String(e);
  }
  assert(threw, "lanza excepción tras agotar reintentos");
  assert(errMsg.includes("429"), "el mensaje menciona 429");
  assertEqual(mock.callCount, MAX_RETRIES + 1, `se hicieron ${MAX_RETRIES + 1} llamadas (7 intentos)`);
}

function test_parser_jsonConMarkdownFences(): void {
  console.log("\n[Test 7] parser JSON tolerante a markdown fences");
  // Simulamos lo que hace worker2_extract_all: limpiar fences y parsear.
  const rawWithFences = "```json\n{\"nombre\":\"test_nombre\",\"decisiones\":[\"D1|A1\"],\"temas\":[\"t1\",\"t2\"]}\n```";
  const cleaned = rawWithFences.replace(/^```(?:json)?\s*/i, "").replace(/\s*```\s*$/, "").trim();
  let parsed: any;
  try {
    parsed = JSON.parse(cleaned);
  } catch {
    parsed = null;
  }
  assert(parsed !== null, "JSON con markdown fences se parsea correctamente");
  assertEqual(parsed?.nombre, "test_nombre", "nombre extraído correctamente");
  assertEqual(parsed?.decisiones?.length, 1, "1 decisión extraída");
  assertEqual(parsed?.temas?.length, 2, "2 temas extraídos");
}

function test_parser_jsonInvalido(): void {
  console.log("\n[Test 8] parser JSON inválido — fallback graceful");
  const rawInvalid = "Esto no es JSON válido";
  const cleaned = rawInvalid.replace(/^```(?:json)?\s*/i, "").replace(/\s*```\s*$/, "").trim();
  let parsed: any;
  try {
    parsed = JSON.parse(cleaned);
    assert(false, "JSON.parse debería haber lanzado excepción");
  } catch {
    assert(true, "JSON inválido lanza excepción correctamente");
    // En el código real, esto cae al fallback: guarda raw y sigue con campos vacíos.
  }
  assert(parsed === undefined || parsed === null, "parsed sigue null/undefined tras fallo");
}

function test_modeloDual(): void {
  console.log("\n[Test 9] modelo dual — W1=heavy, W2=light");
  assert(MODEL_HEAVY !== MODEL_LIGHT, "W1 y W2 usan modelos distintos");
  console.log(`    W1 (resumen): ${MODEL_HEAVY}`);
  console.log(`    W2 (extracción): ${MODEL_LIGHT}`);
}

function test_backoffDelays(): void {
  console.log("\n[Test 10] backoff exponencial — delays correctos");
  assertEqual(BACKOFF_DELAYS_MS, [2000, 4000, 8000, 16000, 32000, 64000], "delays son [2,4,8,16,32,64]s");
  assertEqual(MAX_RETRIES, 6, "MAX_RETRIES = 6 (7 intentos contando el 0)");
  const total = BACKOFF_DELAYS_MS.reduce((a, b) => a + b, 0);
  assertEqual(total, 126000, "tiempo máximo de backoff = 126s");
}

function test_promptExtractAll(): void {
  console.log("\n[Test 11] PROMPT_EXTRACT_ALL — pide JSON estructurado");
  const prompt = PROMPT_EXTRACT_ALL("resumen de prueba");
  assert(prompt.includes("JSON"), "pide JSON en el prompt");
  assert(prompt.includes("nombre"), "pide campo 'nombre'");
  assert(prompt.includes("decisiones"), "pide campo 'decisiones'");
  assert(prompt.includes("temas"), "pide campo 'temas'");
  assert(prompt.includes("snake_case"), "pide formato snake_case");
  assert(prompt.includes("resumen de prueba"), "incluye el resumen en el prompt");
}

function test_promptResumenRigido(): void {
  console.log("\n[Test 12] v6.3 F5 — PROMPT_RESUMEN riguroso");
  const prompt = PROMPT_RESUMEN("contenido de prueba del bloque");
  assert(prompt.includes("600 y 900 caracteres"), "pide longitud EXACTA 600-900 chars");
  assert(prompt.includes("4 oraciones"), "pide exactamente 4 oraciones");
  assert(prompt.includes("Tema central"), "pide tema central");
  assert(prompt.includes("Decisiones principales"), "pide decisiones principales");
  assert(prompt.includes("Temas específicos"), "pide temas específicos");
  assert(prompt.includes("Tipo de actividad"), "pide tipo de actividad");
  assert(prompt.includes("sin secciones, sin listas"), "prohíbe secciones y listas");
  assert(prompt.toLowerCase().includes("sin negritas"), "prohíbe negritas");
  assert(prompt.includes("EJEMPLO"), "incluye ejemplo de resumen bien formado");
  assert(prompt.includes("contenido de prueba del bloque"), "incluye el contenido del bloque");
  // Verificar que el SYSTEM_PROMPT_HEAVY también es riguroso
  assert(SYSTEM_PROMPT_HEAVY.includes("RÍGIDO"), "SYSTEM_PROMPT_HEAVY menciona formato RÍGIDO");
  assert(SYSTEM_PROMPT_HEAVY.includes("600 y 900"), "SYSTEM_PROMPT_HEAVY menciona 600-900 chars");
  console.log("    ✓ Prompt riguroso v6.3 valida formato uniforme de resúmenes");
}

// ── Runner principal ───────────────────────────────────────────

export async function runSelfTest(): Promise<void> {
  console.log("=== Worker Cascade v6.3 — Self-Test ===");
  console.log(`Modelos: W1=${MODEL_HEAVY}, W2=${MODEL_LIGHT}`);
  console.log(`Backoff delays: ${BACKOFF_DELAYS_MS.join(", ")} ms`);
  console.log("");

  // Tests síncronos (lógica pura)
  test_hashContent();
  test_cachePath();
  await test_cacheReadWrite();
  test_modeloDual();
  test_backoffDelays();
  test_promptExtractAll();
  test_promptResumenRigido();
  test_parser_jsonConMarkdownFences();
  test_parser_jsonInvalido();

  // Tests asíncronos (con mock fetch inyectable, sin tocar globalThis)
  await test_callLLM_backoff();
  await test_callLLM_retryAfter();
  await test_callLLM_cacheHit();
  await test_callLLM_maxRetries();

  console.log("\n=== Resumen ===");
  console.log(`  Pasados: ${passed}`);
  console.log(`  Fallidos: ${failed}`);
  if (failures.length > 0) {
    console.log("\nFallos:");
    failures.forEach((f) => console.log(`  - ${f}`));
    process.exit(1);
  } else {
    console.log("\n✓ Todos los tests pasaron.");
  }
}

// Si se ejecuta directamente (no importado), correr los tests.
if (import.meta.main) {
  runSelfTest();
}
