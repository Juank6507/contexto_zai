/**
 * CZAI Bookmarklet Installer
 *
 * Genera un script PowerShell que edita directamente el archivo Bookmarks
 * de Chrome/Edge para insertar el favorito "Conectar CZAI" automáticamente.
 *
 * Flujo del usuario:
 * 1. Descarga el .bat
 * 2. Doble clic
 * 3. El script cierra el navegador, edita el archivo de favoritos, reabre el navegador
 * 4. El favorito "Conectar CZAI" aparece en la barra de favoritos
 */

import { BOOKMARKLET_SOURCE } from './bookmarklet';

/**
 * El script PowerShell que instala el bookmarklet.
 *
 * Cuidado: este string es un template literal de TypeScript.
 * - Los `\\` se convierten en `\` (rutas de Windows)
 * - ${BOOKMARKLET_SOURCE} se interpola con el código JavaScript del bookmarklet
 * - No usar ${...} en el PowerShell (rompería el template literal)
 * - No usar backticks en el PowerShell (rompería el template literal)
 */
export const PS1_SCRIPT = `
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " CZAI Bookmarklet Installer" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host " Esto instalara el favorito 'Conectar CZAI' en tu navegador."
Write-Host " AVISO: Tu navegador se cerrara automaticamente."
Write-Host "        Guarda tu trabajo antes de continuar."
Write-Host ""
Write-Host " Presiona Enter para continuar o Ctrl+C para cancelar..." -ForegroundColor Yellow
Read-Host

# 1. Detect browser (Chrome primero, luego Edge)
$drive = $env:SystemDrive
$chromePaths = @(
    "$drive\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "$drive\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"
)
$edgePaths = @(
    "$drive\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    "$drive\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
)

$browserPath = $null
$browserName = $null
$browserDataDir = $null

foreach ($p in $chromePaths) {
    if (Test-Path $p) {
        $browserPath = $p
        $browserName = "chrome"
        $browserDataDir = Join-Path $env:LOCALAPPDATA "Google\\Chrome\\User Data"
        break
    }
}
if (-not $browserPath) {
    foreach ($p in $edgePaths) {
        if (Test-Path $p) {
            $browserPath = $p
            $browserName = "msedge"
            $browserDataDir = Join-Path $env:LOCALAPPDATA "Microsoft\\Edge\\User Data"
            break
        }
    }
}
if (-not $browserPath) {
    Write-Host "ERROR: No se encontro Chrome ni Edge instalado." -ForegroundColor Red
    Read-Host "Presiona Enter para salir"
    exit 2
}

Write-Host "[1/7] Navegador detectado: $browserName" -ForegroundColor Green

# 2. Find profile (Default o Profile N)
$bookmarksPath = $null
$defaultBookmarks = Join-Path $browserDataDir "Default\\Bookmarks"
if (Test-Path $defaultBookmarks) {
    $bookmarksPath = $defaultBookmarks
} else {
    $profileDirs = Get-ChildItem $browserDataDir -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "Profile *" }
    foreach ($dir in $profileDirs) {
        $candidate = Join-Path $dir.FullName "Bookmarks"
        if (Test-Path $candidate) {
            $bookmarksPath = $candidate
            break
        }
    }
}
if (-not $bookmarksPath) {
    Write-Host "ERROR: No se encontro el archivo de favoritos." -ForegroundColor Red
    Write-Host "  Abre $browserName al menos una vez antes de ejecutar este instalador." -ForegroundColor Yellow
    Read-Host "Presiona Enter para salir"
    exit 5
}
Write-Host "[2/7] Perfil encontrado: $bookmarksPath" -ForegroundColor Green

# 3. Close browser
Write-Host "[3/7] Cerrando $browserName..." -ForegroundColor Cyan
Get-Process -Name $browserName -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
$stillRunning = Get-Process -Name $browserName -ErrorAction SilentlyContinue
if ($stillRunning) {
    Write-Host "  El navegador sigue abierto. Cerralo manualmente." -ForegroundColor Yellow
    Read-Host "  Presiona Enter cuando este cerrado"
}
Write-Host "  Listo." -ForegroundColor Green

# 4. Backup
$backupPath = "$bookmarksPath.czai-backup"
Copy-Item $bookmarksPath $backupPath -Force
Write-Host "[4/7] Backup creado: $backupPath" -ForegroundColor Green

# 5. Read bookmarks JSON
$bookmarksJson = Get-Content $bookmarksPath -Raw -Encoding UTF8
$bookmarks = $bookmarksJson | ConvertFrom-Json

$bookmarkBar = $bookmarks.roots.bookmark_bar
if (-not $bookmarkBar) {
    Write-Host "ERROR: Estructura de favoritos invalida." -ForegroundColor Red
    Read-Host "Presiona Enter para salir"
    exit 6
}

# 6. Bookmarklet code (here-string literal, sin interpolacion)
$bookmarkletCode = @'
${BOOKMARKLET_SOURCE}
'@

# 7. Check if already exists
$existing = $bookmarkBar.children | Where-Object { $_.name -eq "Conectar CZAI" }

if ($existing) {
    $existing.url = $bookmarkletCode
    Write-Host "[5/7] Favorito existente actualizado." -ForegroundColor Green
} else {
    # Compute date_added (microseconds since 1601-01-01 UTC, como Chrome)
    $now = [datetime]::UtcNow
    $epoch = [datetime]::new(1601, 1, 1, 0, 0, 0, [DateTimeKind]::Utc)
    $ticks = $now.Ticks - $epoch.Ticks
    $micros = [long]([math]::Floor([double]$ticks / 10.0))
    $dateAdded = $micros.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    $newGuid = [guid]::NewGuid().ToString().ToUpper()
    $newId = [string](Get-Random -Maximum 999999999 -Minimum 100000000)

    $newEntry = [PSCustomObject]@{
        date_added = $dateAdded
        guid = $newGuid
        id = $newId
        name = "Conectar CZAI"
        type = "url"
        url = $bookmarkletCode
    }

    $childrenArray = @($bookmarkBar.children)
    $childrenArray += $newEntry
    $bookmarkBar.children = $childrenArray
    Write-Host "[5/7] Favorito 'Conectar CZAI' agregado a la barra." -ForegroundColor Green
}

# 8. Compute checksum (Chrome usa MD5 sobre url+title de cada bookmark, en orden)
function Process-BookmarkNode {
    param($node, $bytes)
    if ($node.type -eq "url") {
        $urlBytes = [System.Text.Encoding]::UTF8.GetBytes($node.url)
        $bytes.AddRange($urlBytes)
        $nameBytes = [System.Text.Encoding]::UTF8.GetBytes($node.name)
        $bytes.AddRange($nameBytes)
    } elseif ($node.children) {
        foreach ($child in $node.children) {
            Process-BookmarkNode $child $bytes
        }
    }
}

function Compute-BookmarksChecksum {
    param($bookmarks)
    $md5 = [System.Security.Cryptography.MD5]::Create()
    $allBytes = New-Object System.Collections.Generic.List[byte]
    foreach ($rootName in @("bookmark_bar", "other", "synced")) {
        $root = $bookmarks.roots.$rootName
        if ($root -and $root.children) {
            foreach ($child in $root.children) {
                Process-BookmarkNode $child $allBytes
            }
        }
    }
    $hashBytes = $md5.ComputeHash($allBytes.ToArray())
    $checksum = [Convert]::ToBase64String($hashBytes)
    $md5.Dispose()
    return $checksum
}

$checksum = Compute-BookmarksChecksum $bookmarks
$bookmarks.checksum = $checksum
Write-Host "[6/7] Checksum recalculado." -ForegroundColor Green

# 9. Write back (UTF-8 without BOM, como Chrome)
$json = $bookmarks | ConvertTo-Json -Depth 100
[System.IO.File]::WriteAllText($bookmarksPath, $json, [System.Text.UTF8Encoding]::new($false))
Write-Host "[7/7] Archivo de favoritos guardado." -ForegroundColor Green

# 10. Reopen browser
Write-Host ""
Write-Host "Reabriendo navegador en chat.z.ai..." -ForegroundColor Cyan
Start-Process $browserPath -ArgumentList "https://chat.z.ai"
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " LISTO: Favorito 'Conectar CZAI' instalado." -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Pasos siguientes:" -ForegroundColor Cyan
Write-Host "  1. Ve a cualquier chat de Z.ai (URL: chat.z.ai/c/...)"
Write-Host "  2. Haz clic en 'Conectar CZAI' en la barra de favoritos"
Write-Host "  3. Se abrira una nueva pestana con 'Sesion conectada'"
Write-Host "  4. Vuelve al sandbox y recarga la pagina"
Write-Host ""
Write-Host "Si algo sale mal, restaura el backup:" -ForegroundColor Yellow
Write-Host "  Copia: $backupPath"
Write-Host "  A:     $bookmarksPath"
Write-Host ""
Read-Host "Presiona Enter para cerrar"
`;

/**
 * Genera el contenido de un archivo .bat que ejecuta el script PowerShell
 * embebido en base64 (evita problemas de escaping).
 */
export function generateBat(ps1: string): string {
  // PowerShell -EncodedCommand espera UTF-16LE base64
  const bytes = Buffer.from(ps1, 'utf16le');
  const base64 = bytes.toString('base64');

  return [
    '@echo off',
    'chcp 65001 >nul 2>&1',
    '',
    'echo ============================================',
    'echo  CZAI Bookmarklet Installer',
    'echo ============================================',
    'echo.',
    'echo  Esto instalara el favorito "Conectar CZAI" en tu navegador.',
    'echo  AVISO: Tu navegador se cerrara automaticamente.',
    'echo.',
    'pause',
    'echo.',
    `powershell -ExecutionPolicy Bypass -NoProfile -EncodedCommand ${base64}`,
    '',
    'pause',
    '',
  ].join('\r\n');
}
