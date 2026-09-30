# contexto_zai/mini-services/worker-cascade/setup.ps1
# Script de setup y verificación para Windows (PowerShell 5+).
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
#   .\setup.ps1              → verifica todo y arranca el worker si OK.
#   .\setup.ps1 -Check       → solo verifica, no arranca.
#   .\setup.ps1 -SelfTest    → solo corre el self-test.
#
# Salida: 0 si todo OK, 1 si algún check falla.

#Requires -Version 5.0
[CmdletBinding()]
param(
  [switch]$Check,
  [switch]$SelfTest
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

function Write-OK($msg)   { Write-Host "✓ $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "⚠ $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "✗ $msg" -ForegroundColor Red }

Write-Host "=== Worker Cascade v6.1 — Setup ==="
Write-Host ""

# ── 1. Verificar Bun ────────────────────────────────────────────
Write-Host "1. Verificando Bun runtime..."
$bunCmd = Get-Command bun -ErrorAction SilentlyContinue
if (-not $bunCmd) {
  Write-Err "Bun no está instalado."
  Write-Host "   Instalar con: powershell -c `"irm bun.sh/install.ps1 | iex`""
  exit 1
}
$bunVersionOutput = & bun --version 2>$null
$bunVersion = $bunVersionOutput.Trim()
$bunMajor = ($bunVersion -split '\.')[0]
if ([int]$bunMajor -lt 1) {
  Write-Err "Bun versión $bunVersion es demasiado vieja. Se requiere >= 1.0."
  exit 1
}
Write-OK "Bun $bunVersion instalado."

# ── 2. Verificar archivos del worker ─────────────────────────────
Write-Host ""
Write-Host "2. Verificando archivos del worker..."
$requiredFiles = @("index.ts", "cli.ts", "package.json", "tests\self_test.ts")
foreach ($f in $requiredFiles) {
  $fullPath = Join-Path $ScriptDir $f
  if (-not (Test-Path $fullPath)) {
    Write-Err "Falta archivo: $f"
    exit 1
  }
}
Write-OK "Archivos del worker presentes."

# ── 3. Verificar workspace dir ────────────────────────────────────
Write-Host ""
Write-Host "3. Verificando workspace dir..."
$workspaceDir = $env:CZAI_WORKSPACE_DIR
if (-not $workspaceDir) {
  $workspaceDir = "$env:USERPROFILE\czai_workspace"
  Write-Warn "CZAI_WORKSPACE_DIR no seteada. Usando default: $workspaceDir"
}
if (-not (Test-Path $workspaceDir)) {
  Write-Warn "Workspace dir no existe: $workspaceDir"
  Write-Host "   Setear CZAI_WORKSPACE_DIR o crear el directorio."
} else {
  Write-OK "Workspace dir existe: $workspaceDir"
  $pendingFile = Join-Path $workspaceDir "_pending_blocks.json"
  if (-not (Test-Path $pendingFile)) {
    Write-Warn "No hay _pending_blocks.json en el workspace."
    Write-Host "   El worker arrancará pero no procesará bloques."
  } else {
    try {
      $pending = Get-Content $pendingFile -Raw | ConvertFrom-Json
      $count = $pending.blocks.Count
      Write-OK "_pending_blocks.json con $count bloques."
    } catch {
      Write-Warn "_pending_blocks.json no se pudo parsear."
    }
  }
}

# ── 4. Verificar proxy APA (opcional) ────────────────────────────
Write-Host ""
Write-Host "4. Verificando proxy APA (opcional)..."
$proxyUrl = $env:CZAI_PROXY_URL
if (-not $proxyUrl) {
  $proxyUrl = "http://localhost:3000/api/zai-proxy/v1/chat/completions"
}
try {
  $body = @{ model = "glm-4-flash"; messages = @(@{ role = "user"; content = "ping" }); max_tokens = 3 } | ConvertTo-Json -Depth 5
  $null = Invoke-RestMethod -Uri $proxyUrl -Method POST -ContentType "application/json" -Body $body -TimeoutSec 3 -ErrorAction Stop
  Write-OK "Proxy APA accesible en $proxyUrl"
} catch {
  Write-Warn "Proxy APA no accesible en $proxyUrl"
  Write-Host "   El worker arrancará pero fallará al procesar bloques."
  Write-Host "   Para desarrollo, usar 'bun run cli.ts --self-test' (no requiere proxy)."
}

# ── 5. Self-test ─────────────────────────────────────────────────
Write-Host ""
Write-Host "5. Corriendo self-test (valida las 4 soluciones sin proxy APA)..."
$testResult = & bun run cli.ts --self-test 2>&1
Write-Host $testResult
if ($LASTEXITCODE -eq 0) {
  Write-OK "Self-test pasó."
} else {
  Write-Err "Self-test falló."
  exit 1
}

# ── Decisión final ───────────────────────────────────────────────
Write-Host ""
Write-Host "=== Resumen del setup ==="
Write-Host "  Bun: $bunVersion"
Write-Host "  Workspace: $workspaceDir"
Write-Host "  Proxy: $proxyUrl"
Write-Host ""

if ($Check) {
  Write-Host "Setup OK. No arrancando worker (-Check mode)."
  exit 0
} elseif ($SelfTest) {
  Write-Host "Setup OK. No arrancando worker (-SelfTest mode ya corrió)."
  exit 0
} else {
  Write-Host "Setup OK. Arrancando worker..."
  Write-Host "  (Ctrl+C para detener)"
  Write-Host ""
  & bun run cli.ts run
}
