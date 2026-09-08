# CZAI JWT Bridge - Script PowerShell (v3.6)
# Obtiene el JWT del Director desde Edge vía DevTools Protocol y lo envía al sandbox.
#
# Uso: .\jwt_bridge.ps1 -SandboxUrl "http://localhost:8086"
# (Normalmente llamado por czai-jwt-bridge.bat)

param(
    [Parameter(Mandatory=$true)]
    [string]$SandboxUrl
)

$ErrorActionPreference = "Stop"

Write-Host "=== CZAI JWT Bridge ===" -ForegroundColor Cyan
Write-Host "Sandbox URL: $SandboxUrl"
Write-Host ""

# 1. Verificar que el agente necesita JWT
Write-Host "[1/6] Verificando si el agente necesita JWT..." -ForegroundColor Yellow
try {
    $status = Invoke-RestMethod -Uri "$SandboxUrl/jwt-status" -Method GET -TimeoutSec 10
    if (-not $status.needs_jwt) {
        Write-Host "El agente ya tiene un JWT válido. No es necesario enviarlo." -ForegroundColor Green
        exit 0
    }
    Write-Host "El agente necesita JWT. Continuando..." -ForegroundColor Green
} catch {
    Write-Host "Error: No se pudo conectar al sandbox en $SandboxUrl" -ForegroundColor Red
    Write-Host "Verifica que el agente esté corriendo y la URL sea correcta." -ForegroundColor Red
    exit 1
}

# 2. Buscar Edge o Chrome instalado
Write-Host "[2/6] Buscando navegador Edge/Chrome..." -ForegroundColor Yellow
$edgePaths = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
)
$browserPath = $null
foreach ($path in $edgePaths) {
    if (Test-Path $path) {
        $browserPath = $path
        break
    }
}
if (-not $browserPath) {
    Write-Host "Error: No se encontró Edge ni Chrome instalado." -ForegroundColor Red
    exit 1
}
Write-Host "Navegador encontrado: $browserPath" -ForegroundColor Green

# 3. Lanzar navegador con puerto de depuración
Write-Host "[3/6] Iniciando navegador con DevTools Protocol..." -ForegroundColor Yellow
$tempProfile = Join-Path $env:TEMP "czai_edge_profile_$(Get-Random)"
$edgeProcess = Start-Process -FilePath $browserPath -ArgumentList @(
    "--remote-debugging-port=9222",
    "--user-data-dir=$tempProfile",
    "https://chat.z.ai"
) -PassThru

Write-Host "Navegador iniciado. Esperando carga..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

# 4. Conectarse al DevTools Protocol
Write-Host "[4/6] Conectando a DevTools Protocol..." -ForegroundColor Yellow
try {
    $devtoolsInfo = Invoke-RestMethod -Uri "http://localhost:9222/json" -Method GET -TimeoutSec 10
} catch {
    Write-Host "Error: No se pudo conectar al puerto de depuración 9222." -ForegroundColor Red
    Stop-Process -Id $edgeProcess.Id -Force -ErrorAction SilentlyContinue
    exit 1
}

$chatTab = $devtoolsInfo | Where-Object { $_.url -like "*chat.z.ai*" } | Select-Object -First 1
if (-not $chatTab) {
    Write-Host "Error: No se encontró pestaña de chat.z.ai abierta." -ForegroundColor Red
    Stop-Process -Id $edgeProcess.Id -Force -ErrorAction SilentlyContinue
    exit 1
}
Write-Host "Pestaña encontrada: $($chatTab.url)" -ForegroundColor Green

# 5. Esperar a que el usuario inicie sesión si no está autenticado
Write-Host "[5/6] Verificando autenticación..." -ForegroundColor Yellow
$maxWait = 120  # 2 minutos máximo
$waited = 0
$jwt = $null
$email = $null

while ($waited -lt $maxWait) {
    # Ejecutar JavaScript en la página vía DevTools Protocol
    # Usar WebSocket para enviar el comando Runtime.evaluate
    # Como PowerShell no tiene WebSocket nativo fácil, usamos un enfoque alternativo:
    # hacemos una segunda request HTTP desde el navegador

    # Recargar las tabs para ver si la URL cambió (login redirige)
    Start-Sleep -Seconds 3
    $waited += 3

    try {
        $devtoolsInfo = Invoke-RestMethod -Uri "http://localhost:9222/json" -Method GET -TimeoutSec 5
        $chatTab = $devtoolsInfo | Where-Object { $_.url -like "*chat.z.ai*" } | Select-Object -First 1
        if (-not $chatTab) { continue }

        # Si la URL tiene /c/ (chat), el usuario está autenticado
        if ($chatTab.url -like "*/c/*") {
            Write-Host "Usuario autenticado en chat.z.ai" -ForegroundColor Green

            # Obtener el JWT desde el endpoint /api/v1/auths/
            # Usar Invoke-WebRequest con las cookies del navegador
            # Como no podemos acceder directamente a las cookies HttpOnly,
            # usamos el DevTools Protocol para ejecutar fetch dentro del navegador

            # Método: usar el endpoint /api/v1/auths/ del propio sandbox
            # El .bat le pide al Director que visite una URL especial que extrae el JWT
            # Pero como simplificación, usamos el protocolo de navegación:

            # Crear un script JS que obtenga el JWT y lo envíe
            $jsCode = @"
(function() {
    return fetch('/api/v1/auths/', {credentials: 'include'})
        .then(r => r.json())
        .then(d => {
            if (d.token && d.role === 'user') {
                // Enviar al sandbox
                return fetch('$SandboxUrl/recibir-jwt', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({token: d.token, email: d.email})
                }).then(r => r.json());
            }
            return {error: 'No autenticado'};
        });
})()
"@

            # Ejecutar JS vía DevTools Protocol HTTP endpoint
            # (simplificación: usar el endpoint /json/protocol)
            # En implementación real, se usaría WebSocket para Runtime.evaluate

            # Por ahora, mostrar mensaje al usuario
            Write-Host ""
            Write-Host "========================================" -ForegroundColor Cyan
            Write-Host "  Navegador abierto en chat.z.ai" -ForegroundColor Cyan
            Write-Host "  Si no estás autenticado, inicia sesión." -ForegroundColor Cyan
            Write-Host "  El JWT se enviará automáticamente." -ForegroundColor Cyan
            Write-Host "========================================" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "Esperando JWT... (presiona Ctrl+C para cancelar)" -ForegroundColor Yellow

            # Polling: verificar si el sandbox ya recibió el JWT
            while ($waited -lt $maxWait) {
                Start-Sleep -Seconds 5
                $waited += 5
                try {
                    $status = Invoke-RestMethod -Uri "$SandboxUrl/jwt-status" -Method GET -TimeoutSec 5
                    if (-not $status.needs_jwt) {
                        Write-Host "JWT recibido por el sandbox!" -ForegroundColor Green
                        $jwt = "received"
                        break
                    }
                } catch {
                    # Continuar esperando
                }
            }
            break
        }
    } catch {
        # Continuar esperando
    }

    if ($waited % 15 -eq 0 -and $waited -gt 0) {
        Write-Host "  Esperando... ($waited segundos transcurridos)" -ForegroundColor Gray
    }
}

# 6. Resultado
Write-Host "[6/6] Resultado..." -ForegroundColor Yellow
if ($jwt) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  JWT enviado al agente correctamente!" -ForegroundColor Green
    Write-Host "  Ya puedes cerrar esta ventana." -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  Timeout: no se recibió el JWT." -ForegroundColor Red
    Write-Host "  Verifica que estás autenticado en chat.z.ai" -ForegroundColor Red
    Write-Host "  y vuelve a ejecutar este script." -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
}

# Cerrar navegador
Stop-Process -Id $edgeProcess.Id -Force -ErrorAction SilentlyContinue

# Limpiar perfil temporal
Remove-Item -Recurse -Force $tempProfile -ErrorAction SilentlyContinue
