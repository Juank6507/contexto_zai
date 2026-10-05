#!/usr/bin/env bash
# contexto_zai/mini-services/worker-cascade/setup.sh
# Script de setup y verificación para Linux/macOS.
#
# QUÉ SOLUCIONA: en v6.0 no había verificación de entorno antes de arrancar el
# Worker Bun. Si faltaba Bun o el proxy APA no respondía, el worker fallaba en
# runtime con errores crípticos.
# CÓMO LO HACE: verifica los prerequisitos antes de arrancar:
#   1. Bun runtime instalado (versión >= 1.0).
#   2. Proxy APA accesible (opcional, solo si CZAI_PROXY_URL está seteada).
#   3. Workspace dir existe y tiene _pending_blocks.json.
#   4. Self-test pasa (valida las 4 soluciones sin proxy APA real).
#
# Uso:
#   ./setup.sh              → verifica todo y arranca el worker si OK.
#   ./setup.sh --check      → solo verifica, no arranca.
#   ./setup.sh --self-test  → solo corre el self-test.
#
# Salida: 0 si todo OK, 1 si algún check falla.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ok() { echo -e "${GREEN}✓ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
err() { echo -e "${RED}✗ $1${NC}"; }

echo "=== Worker Cascade v6.1 — Setup ==="
echo ""

# ── 1. Verificar Bun ────────────────────────────────────────────
echo "1. Verificando Bun runtime..."
if ! command -v bun &>/dev/null; then
  err "Bun no está instalado."
  echo "   Instalar con: curl -fsSL https://bun.sh/install | bash"
  exit 1
fi
BUN_VERSION=$(bun --version)
BUN_MAJOR=$(echo "$BUN_VERSION" | cut -d. -f1)
if [ "$BUN_MAJOR" -lt 1 ]; then
  err "Bun versión $BUN_VERSION es demasiado vieja. Se requiere >= 1.0."
  exit 1
fi
ok "Bun $BUN_VERSION instalado."

# ── 2. Verificar archivos del worker ─────────────────────────────
echo ""
echo "2. Verificando archivos del worker..."
for f in index.ts cli.ts package.json tests/self_test.ts; do
  if [ ! -f "$SCRIPT_DIR/$f" ]; then
    err "Falta archivo: $f"
    exit 1
  fi
done
ok "Archivos del worker presentes."

# ── 3. Verificar workspace dir ────────────────────────────────────
echo ""
echo "3. Verificando workspace dir..."
WORKSPACE_DIR="${CZAI_WORKSPACE_DIR:-/home/z/my-project/contexto_recuperacion}"
if [ ! -d "$WORKSPACE_DIR" ]; then
  warn "Workspace dir no existe: $WORKSPACE_DIR"
  echo "   Setear CZAI_WORKSPACE_DIR o crear el directorio."
  # No es fatal: el worker puede crear el dir si tiene permisos.
else
  ok "Workspace dir existe: $WORKSPACE_DIR"
  if [ ! -f "$WORKSPACE_DIR/_pending_blocks.json" ]; then
    warn "No hay _pending_blocks.json en el workspace."
    echo "   El worker arrancará pero no procesará bloques."
  else
    COUNT=$(jq '.blocks | length' "$WORKSPACE_DIR/_pending_blocks.json" 2>/dev/null || echo "?")
    ok "_pending_blocks.json con $COUNT bloques."
  fi
fi

# ── 4. Verificar proxy APA (opcional) ────────────────────────────
echo ""
echo "4. Verificando proxy APA (opcional)..."
PROXY_URL="${CZAI_PROXY_URL:-http://localhost:3000/api/zai-proxy/v1/chat/completions}"
if curl -s -o /dev/null -m 3 -X POST "$PROXY_URL" \
  -H "Content-Type: application/json" \
  -d '{"model":"glm-4-flash","messages":[{"role":"user","content":"ping"}],"max_tokens":3}' 2>/dev/null; then
  ok "Proxy APA accesible en $PROXY_URL"
else
  warn "Proxy APA no accesible en $PROXY_URL"
  echo "   El worker arrancará pero fallará al procesar bloques."
  echo "   Para desarrollo, usar 'bun run cli.ts --self-test' (no requiere proxy)."
fi

# ── 5. Self-test ─────────────────────────────────────────────────
echo ""
echo "5. Corriendo self-test (valida las 4 soluciones sin proxy APA)..."
if bun run cli.ts --self-test; then
  ok "Self-test pasó."
else
  err "Self-test falló."
  exit 1
fi

# ── Decisión final ───────────────────────────────────────────────
echo ""
echo "=== Resumen del setup ==="
echo "  Bun: $BUN_VERSION"
echo "  Workspace: $WORKSPACE_DIR"
echo "  Proxy: $PROXY_URL"
echo ""

if [ "${1:-}" = "--check" ]; then
  echo "Setup OK. No arrancando worker (--check mode)."
  exit 0
elif [ "${1:-}" = "--self-test" ]; then
  echo "Setup OK. No arrancando worker (--self-test mode ya corrió)."
  exit 0
else
  echo "Setup OK. Arrancando worker..."
  echo "  (Ctrl+C para detener)"
  echo ""
  exec bun run cli.ts run
fi
