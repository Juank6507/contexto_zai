# plantilla_script_entrega_proyecto.ps1 -- plantilla v1.1 (estrategia Z.ai v1.5.4)
# Ubicacion: estrategia/plantillas/plantilla_script_entrega_proyecto.ps1 (PLANTILLA)
# Destino instanciado en cada proyecto (NH15): <RAIZ_DEL_REPO_DEL_PROYECTO>/update_entrega.ps1
#
# ESTANDAR R5 (v1.5): toda implementacion de cualquier agente viaja con su script de entrega,
# hermano del update_estrategia.ps1 del meta-proyecto (v4.x). Cubre de forma automatica, sin
# intervencion del Director donde sea posible y con calidad y garantia de implementacion
# completa, los 4 aspectos del cruce:
#   (a) CONTENIDO de la entrega segun su regimen I.3a (proyectos: solo modificados + tests +
#       tests E2E completos), verificado contra MANIFIESTO_ENTREGA.txt (SHA256, umbral cero).
#   (b) FUNCIONAMIENTO EN WINDOWS (I.3b): ejecuta las sentencias de prueba y los tests E2E
#       que viajan con la entrega, con datos reales del proyecto (R4/NH25).
#   (c) CONDICIONES PREVIAS (I.3c): comprueba las precondiciones que la entrega consume.
#   (d) CIERRE POR CONSTRUCCION (I.3e): veredicto JSON umbral cero asentado en el registro
#       de intentos; condiciona el re-clonado final. Recordatorio de retorno consolidado (R1).
#
# LOS 12 PASOS DEL DIRECTOR (v1.1, ampliacion ordenada en la v1.5.4; informe CZAI conciliado):
#   1. El Director descarga el .zip del proyecto en Descargas de Windows (accion manual).
#   2. El script busca el .zip de version mas alta de este proyecto (Find-ZipInFolder).
#   3. El script localiza el repositorio local del proyecto (Find-RepoLocal).
#   4. Asume rutas y .zip detectados como valores predeterminados.
#   5. Pregunta si son correctos y ejecuta la secuencia segun esa informacion (Confirm-Values).
#   6. Elimina el contenido del repositorio local si existe, conservando .git (Remove-RepoLocal).
#   7. Descomprime todo el .zip en el repositorio local (Expand-Zip).
#   8. Valida segun la secuencia (sandbox Linux -> Windows del Director): Test-Contenido +
#      Test-Precondiciones + Test-Funcionamiento (C1-C7).
#   9. Si pasa 100% -> paso siguiente. Si no -> Emit-TxtInforme: .txt legible con el problema
#      (ademas del veredicto JSON); la entrega NO se aplica y vuelve al DCEPI (umbral cero).
#  10. Re-ejecuta los pasos 6 y 7 (re-limpieza y re-descompresion tras la validacion;
#      Re-CleanAndExpand): el repo local queda EXACTO al .zip.
#  11. Actualiza el repositorio del proyecto en GitHub (Invoke-GitCommit + Invoke-GitPush).
#  12. Genera el diff de triple igualdad .zip <-> repo local <-> GitHub y emite SIEMPRE el
#      informe en Descargas (Invoke-DiffCheck). Los pasos 11-12 ejecutan por construccion los
#      subelementos (3) actualizacion del repositorio y (4) diff de comprobacion del elemento I.
#
# AMPLIACION v1.1 (sin reduccion): se ANADEN 8 funciones nuevas para los 12 pasos y se
# mantienen INTACTAS las 8 funciones existentes (Write-Title, Write-Check, Get-VeredictoPath,
# Add-Registro, Test-Contenido, Test-Precondiciones, Test-Funcionamiento; Emit-Veredicto solo
# se amplia con el .txt del paso 9 y el mensaje del nuevo flujo), la interfaz param(), los
# marcadores <<...>> de CONFIGURACION, los codigos C1-C7, el veredicto JSON y el registro de
# intentos. Contrato de instancia R6 sin cambios: sustituir marcadores <<...>> y nada mas.
#
# REGLA DE GENERACION R6 (dcepi.md I.3a): el agente de proyecto instancia ESTA plantilla
# sustituyendo TODOS los marcadores <<...>> por datos reales del proyecto (prohibido el
# hardcoding: los valores viven solo en la seccion CONFIGURACION). El script instanciado es
# parte de la implementacion, pasa el gauntlet de I.2 como cualquier archivo y debe superar
# la escalera de validacion R3: individual -> funcional -> e2e. Si no supera el estandar:
# correcciones oportunas y reintento con MAX_ITER = 5 intentos (I.2); agotados, ESCALADO al
# Director con el problema exacto (que item falla, evidencia, diagnostico), sin rodearlo ni
# reparar procesos ajenos.
#
# USO (quien recibe la entrega, en Windows): pegar la sentencia de lanzamiento que acompana
# la entrega (extrae este script del .zip y lo ejecuta). Con la v1.1 el script pregunta los
# valores detectados (Enter = aceptar) y completa los 12 pasos en una sola ejecucion.
#
# ASCII-only: sin em-dash, sin smart quotes, sin caracteres Unicode especiales.

param(
    [string]$EntregaDir = "",      # carpeta DONDE BUSCAR el .zip de la entrega (vacia = Descargas)
    [switch]$SkipTests,            # auxiliar de diagnostico: omite (b); el veredicto lo registra
    [switch]$NoReport              # auxiliar: no escribe informes (json/.txt/diff) en Descargas
)

$ErrorActionPreference = "Stop"

# ============================================================
#  CONFIGURACION (instanciar con datos reales del proyecto;
#  ningun otro punto del script contiene valores fijos)
# ============================================================

$NombreProyecto    = "contexto_zai"           # p. ej. APA
$VersionEntrega    = "6.18"           # p. ej. 1.0 (debe cuadrar con el manifiesto)
$RutaLocalProyecto = "C:\Python\Proyectos\contexto_zai"       # raiz local del repo del proyecto
$RepoGitHub        = "https://github.com/Juank6507/contexto_zai.git"      # URL del repo del proyecto (fichero de entornos)
$RamaPrincipal     = "main"            # p. ej. main

# (a) Contenido requerido de la entrega (regimen I.3a: solo modificados + tests + E2E completos)
$ArchivosRequeridos = @(
        "config.py",
    "pipeline.py",
    "processing/block_packer.py",
    "generation/bloque_generator.py",
    "coordinador/integrador_respuestas.py",
    "tests/test_v42_e2e.py"
)

# (b) Funcionamiento en Windows: sentencias de prueba y tests E2E (datos reales, R4/NH25)
$SentenciasPrueba = @(
        "cd /d $RutaLocalProyecto && python config.py",
    "cd /d $RutaLocalProyecto && python -c `"from pipeline import ProgressMonitor; print('OK ProgressMonitor')`"",
    "cd /d $RutaLocalProyecto && python -c `"from pipeline import EnriquecimientoOrquestador; assert hasattr(EnriquecimientoOrquestador, '_enriquecer_con_proxy_zai'); print('OK proxy Z.ai')`"",
    "cd /d $RutaLocalProyecto && python -c `"from pipeline import AuditorWorkspace; print('OK AuditorWorkspace')`"",
    "cd /d $RutaLocalProyecto && python -c `"from pipeline import PROMPT_FUSIONADO_W1W2W3; print('OK W1+W2+W3 fusionado')`"",
    "cd /d $RutaLocalProyecto && python -c `"from config import PROGRESS_GROWTH; assert PROGRESS_GROWTH == 2.0; print('OK PROGRESS_GROWTH=2.0')`"",
    "cd /d $RutaLocalProyecto && python -c `"from config import PROXY_ZAI_URL; print('OK PROXY_ZAI_URL=' + PROXY_ZAI_URL)`"",
    "cd /d $RutaLocalProyecto && python -c `"import processing.block_packer; print('OK BlockPacker')`"",
    "cd /d $RutaLocalProyecto && python -c `"f=open('generation/bloque_generator.py').read(); assert 'Bloque cronologico' in f or 'Bloque cronológico' in f; print('OK cabecera cronológica')`"",
    "cd /d $RutaLocalProyecto && python -c `"import os; assert not any('proxy APA' in open(os.path.join(r,f),encoding='utf-8',errors='ignore').read() for r,d,fs in os.walk('.') for f in fs if f.endswith('.py')); print('OK 0 menciones proxy APA')`"",
    "cd /d $RutaLocalProyecto && python pipeline.py",
    "cd /d $RutaLocalProyecto && python coordinador\integrador_respuestas.py"
)
$TestsE2E = @(
        "cd /d $RutaLocalProyecto && python tests\test_v42_e2e.py"
)

# (c) Condiciones previas (I.3c): cada comando debe terminar en exit 0 para cumplir
$CondicionesPrevias = @(
        "python --version"
)

# Lo no automatizable queda senalado y escala (R5): cada item con su razon y quien lo valida
$NoAutomatizable = @(
        "git push a GitHub | el sandbox no tiene credenciales | el Director ejecuta git push manualmente"
)

# Verificacion del retorno consolidado (R1/NH26): la entrega confirma el lugar determinado
$RutaRetornoConsolidado = "retorno/documento_consolidado.md"

# Fuente de datos reales de la validacion (R4/NH25): declarar SIEMPRE
$FuenteDatos = "chat 6a00fcb8 (613 exchanges) + exchanges_czai_consolidados.md (649 exchanges)"           # p. ej. base de datos del proyecto, fixtures reales, API real

# ============================================================
#  FUNCIONES AUXILIARES
# ============================================================

function Write-Title {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  ENTREGA DE PROYECTO - $NombreProyecto (v$VersionEntrega)" -ForegroundColor Cyan
    Write-Host "  estandar R5 v1.5: contenido + Windows + previas + cierre" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Check ($Num, $Texto, $Ok) {
    if ($Ok) {
        Write-Host "  [$Num] [OK]   $Texto" -ForegroundColor Green
    } else {
        Write-Host "  [$Num] [FALLO] $Texto" -ForegroundColor Red
    }
}

function Get-VeredictoPath {
    # Registro de intentos y veredicto asentado (I.3e): vive en la raiz local del proyecto
    return (Join-Path $RutaLocalProyecto "entregas\registro_intentos.log")
}

function Add-Registro ($Linea) {
    $ruta = Get-VeredictoPath
    $dir = Split-Path $ruta -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Add-Content -Path $ruta -Value $Linea -Encoding UTF8
}

# ============================================================
#  (a) CONTENIDO: archivos requeridos + SHA256 contra el manifiesto
# ============================================================

function Test-Contenido {
    Write-Host "  (a) Contenido de la entrega (I.3a)..." -ForegroundColor White
    $fallos = @()

    if ($EntregaDir -eq "" -or -not (Test-Path $EntregaDir)) {
        return @("C1: carpeta de la entrega no indicada o inexistente ($EntregaDir)")
    }

    foreach ($rel in $ArchivosRequeridos) {
        $p = Join-Path $EntregaDir $rel
        if (-not (Test-Path $p)) { $fallos += "C1: falta el archivo requerido $rel" }
    }

    $manifest = Join-Path $EntregaDir "MANIFIESTO_ENTREGA.txt"
    if (-not (Test-Path $manifest)) {
        $fallos += "C2: MANIFIESTO_ENTREGA.txt ausente en la entrega"
    } else {
        foreach ($linea in (Get-Content $manifest)) {
            if ($linea -match "^([0-9a-f]{64})\s{2}(.+)$") {
                $hash = $Matches[1]; $rel = $Matches[2]
                $p = Join-Path $EntregaDir ($rel -replace "/", "\")
                if (Test-Path $p) {
                    $real = (Get-FileHash $p -Algorithm SHA256).Hash.ToLower()
                    if ($real -ne $hash) { $fallos += "C2: SHA256 no cuadra en $rel (umbral cero)" }
                }
            } elseif ($linea -match "^VERSION:\s*(.+)$") {
                if ($Matches[1].Trim() -ne $VersionEntrega) {
                    $fallos += "C2: VERSION del manifiesto ($($Matches[1].Trim())) no cuadra con la configurada ($VersionEntrega)"
                }
            }
        }
    }

    $ret = Join-Path $EntregaDir ($RutaRetornoConsolidado -replace "/", "\")
    if (-not (Test-Path $ret)) {
        $fallos += "C6: el documento consolidado de retorno no esta en $RutaRetornoConsolidado (R1/NH26)"
    }

    Write-Check "C1" "archivos requeridos presentes segun regimen I.3a" (($fallos | Where-Object { $_ -like "C1*" }).Count -eq 0)
    Write-Check "C2" "manifiesto integro, SHA256 umbral cero y VERSION coherente" (($fallos | Where-Object { $_ -like "C2*" }).Count -eq 0)
    Write-Check "C6" "documento consolidado de retorno en el lugar determinado" (($fallos | Where-Object { $_ -like "C6*" }).Count -eq 0)
    return $fallos
}

# ============================================================
#  (c) CONDICIONES PREVIAS
# ============================================================

function Test-Precondiciones {
    Write-Host "  (c) Condiciones previas (I.3c)..." -ForegroundColor White
    $fallos = @()
    $i = 0
    foreach ($cmd in $CondicionesPrevias) {
        $i++
        try {
            $out = & cmd.exe /c $cmd 2>&1
            if ($LASTEXITCODE -ne 0) { $fallos += "C3: precondicion $i fallo ($cmd): $out" }
        } catch {
            $fallos += "C3: precondicion $i lanzo error ($cmd): $_"
        }
    }
    Write-Check "C3" "condiciones previas cumplidas ($($CondicionesPrevias.Count) comprobaciones)" ($fallos.Count -eq 0)
    return $fallos
}

# ============================================================
#  (b) FUNCIONAMIENTO EN WINDOWS: sentencias de prueba + tests E2E
# ============================================================

function Test-Funcionamiento {
    Write-Host "  (b) Funcionamiento en Windows (I.3b)..." -ForegroundColor White
    $fallos = @()

    if ($SkipTests) {
        Write-Check "C4" "funcionamiento OMITIDO por -SkipTests (diagnostico)" $false
        return @("C4: ejecucion con -SkipTests; el veredicto NO valida funcionamiento")
    }

    if ($SentenciasPrueba.Count -eq 0 -or $TestsE2E.Count -eq 0) {
        $fallos += "C4: la entrega no define sentencias de prueba o tests E2E (no se da por validado sin ellos)"
    }

    $i = 0
    foreach ($cmd in $SentenciasPrueba) {
        $i++
        try {
            $out = & cmd.exe /c $cmd 2>&1
            if ($LASTEXITCODE -ne 0) { $fallos += "C4: sentencia de prueba $i fallo ($cmd): $out" }
        } catch {
            $fallos += "C4: sentencia de prueba $i lanzo error ($cmd): $_"
        }
    }

    $j = 0
    foreach ($cmd in $TestsE2E) {
        $j++
        try {
            $out = & cmd.exe /c $cmd 2>&1
            if ($LASTEXITCODE -ne 0) { $fallos += "C4: test E2E $j fallo ($cmd): $out" }
        } catch {
            $fallos += "C4: test E2E $j lanzo error ($cmd): $_"
        }
    }

    Write-Check "C4" "sentencias de prueba ($($SentenciasPrueba.Count)) y tests E2E ($($TestsE2E.Count)) superados" ($fallos.Count -eq 0)
    $datosOk = ($FuenteDatos -ne "" -and $FuenteDatos -notlike "<<*>>")
    Write-Check "C5" "fuente de datos declarada y real o lo mas real posible (R4/NH25)" $datosOk
    if (-not $datosOk) { $fallos += "C5: fuente de datos de la validacion no declarada o con marcador sin instanciar" }
    return $fallos
}

# ============================================================
#  (d) CIERRE: veredicto JSON umbral cero + registro de intentos
# ============================================================

function Emit-Veredicto ($TodosLosFallos) {
    $aprobado = ($TodosLosFallos.Count -eq 0)
    $veredicto = [ordered]@{
        proyecto       = $NombreProyecto
        version        = $VersionEntrega
        fecha          = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        aprobado       = $aprobado
        items_fallados = $TodosLosFallos
        motivo         = ""
        vuelve_a       = ""
        comandos_fallidos = @()
        no_automatizable  = $NoAutomatizable
    }
    if (-not $aprobado) {
        $veredicto.motivo = "Entrega NO aplicada: la entrega vuelve al DCEPI (I.3b). Escalar al Director con el problema exacto: item, evidencia y diagnostico."
        $veredicto.vuelve_a = "DCEPI"
    }

    $json = $veredicto | ConvertTo-Json -Depth 4
    Add-Registro "---- INTENTO $(Get-Date -Format o) ----"
    Add-Registro $json

    Write-Host ""
    if ($aprobado) {
        Write-Host "  VEREDICTO: APROBADO (umbral cero; veredicto asentado en registro_intentos.log)" -ForegroundColor Green
        Write-Host "  Siguiente paso (automatico, pasos 10-12): re-limpieza y re-descompresion," -ForegroundColor Green
        Write-Host "  publicacion en GitHub y diff de triple igualdad con informe en Descargas." -ForegroundColor Green
    } else {
        Write-Host "  VEREDICTO: RECHAZADO ($($TodosLosFallos.Count) items)" -ForegroundColor Red
        Write-Host "  La entrega NO se aplica y vuelve al DCEPI. ESCALAR AL DIRECTOR:" -ForegroundColor Red
        foreach ($f in $TodosLosFallos) { Write-Host "    - $f" -ForegroundColor Red }
    }

    if (-not $NoReport) {
        $informe = Join-Path $env:USERPROFILE "Downloads\VEREDICTO_ENTREGA_${NombreProyecto}_v$VersionEntrega.json"
        $json | Out-File -FilePath $informe -Encoding UTF8
        Write-Host "  Informe: $informe" -ForegroundColor Gray
        if (-not $aprobado) { Emit-TxtInforme $TodosLosFallos }
    }
    return $aprobado
}

# ============================================================
#  PASOS 2-5: LOCALIZAR Y CONFIRMAR (v1.1)
# ============================================================

function Find-ZipInFolder {
    # Paso 2: busca el .zip de version mas alta de este proyecto (patron <proyecto>_v*.zip;
    # seleccion por mayor version del nombre, empate por fecha mas reciente)
    $carpeta = if ($EntregaDir -ne "" -and (Test-Path $EntregaDir)) { $EntregaDir } else { Join-Path $env:USERPROFILE "Downloads" }
    $patron = "${NombreProyecto}_v*.zip"
    $candidatos = @(Get-ChildItem -Path $carpeta -Filter $patron -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    if ($candidatos.Count -eq 0) { return $null }
    $mejor = $null; $mejorV = $null
    foreach ($c in $candidatos) {
        if ($c.Name -match "_v(\d+(?:\.\d+)*)\.zip$") {
            $partes = @($Matches[1].Split(".") | ForEach-Object { [int]$_ })
            $v = [version]((0..3 | ForEach-Object { if ($_ -lt $partes.Count) { $partes[$_] } else { 0 } }) -join ".")
            if ($null -eq $mejorV -or $v -gt $mejorV) { $mejorV = $v; $mejor = $c }
        }
    }
    if ($null -eq $mejor) { $mejor = $candidatos[0] }   # sin version parseable: el mas reciente por fecha
    return $mejor.FullName
}

function Find-RepoLocal {
    # Paso 3: ubicacion del repositorio local del proyecto (predeterminada en CONFIGURACION;
    # si el Director la cambio, la corrige en la pregunta del paso 5)
    return $RutaLocalProyecto
}

function Confirm-Values ($ZipPath, $RepoLocal) {
    # Pasos 4-5: asume lo detectado como predeterminado, pregunta si es correcto y ejecuta
    # (Enter = aceptar; escribir una ruta = sobreescribir)
    Write-Host "  Valores detectados (pasos 2-4):" -ForegroundColor White
    Write-Host "    .zip de la entrega : $ZipPath"
    Write-Host "    repo local destino : $RepoLocal"
    if ($ZipPath -and $ZipPath -match "_v(\d+(?:\.\d+)*)\.zip$") {
        $zipV = $Matches[1]
        if ($zipV -ne $VersionEntrega) {
            Write-Host "    AVISO: version del zip ($zipV) distinta de la configurada ($VersionEntrega); el manifiesto decide (umbral cero)" -ForegroundColor Yellow
        }
    }
    $r1 = Read-Host "  Es correcto el .zip? (Enter = si / pegue la ruta completa de otro .zip)"
    if ($r1 -and $r1.Trim() -ne "") {
        $r1 = $r1.Trim()
        if (-not (Test-Path $r1)) { throw "P5: la ruta del .zip indicada no existe ($r1)" }
        $ZipPath = (Get-Item $r1).FullName
    }
    $r2 = Read-Host "  Es correcto el repo local? (Enter = si / pegue la ruta completa de la carpeta)"
    if ($r2 -and $r2.Trim() -ne "") { $RepoLocal = $r2.Trim() }
    if (-not $ZipPath) { throw "P2: sin .zip de entrega no se continua (no se encontro ${NombreProyecto}_v*.zip)" }
    if (-not $RepoLocal -or $RepoLocal -like "<<*>>") { throw "P3: sin repo local no se continua (indique la ruta en la pregunta del paso 5)" }
    return @($ZipPath, $RepoLocal)
}

# ============================================================
#  PASOS 6-7 y 10: LIMPIAR Y DESCOMPRIMIR (v1.1)
# ============================================================

function Remove-RepoLocal ($RepoLocal) {
    # Pasos 6 y 10: elimina el contenido del repo local conservando .git (reemplazo total)
    if (-not (Test-Path $RepoLocal)) {
        New-Item -ItemType Directory -Path $RepoLocal -Force | Out-Null
    } else {
        Get-ChildItem -Path $RepoLocal -Force | Where-Object { $_.Name -ne ".git" } | Remove-Item -Recurse -Force
    }
    Write-Check "P6" "repo local limpio (conserva .git): $RepoLocal" $true
}

function Expand-Zip ($ZipPath, $RepoLocal) {
    # Pasos 7 y 10: descomprime todo el .zip en el repo local (se espera raiz plana)
    Expand-Archive -Path $ZipPath -DestinationPath $RepoLocal -Force
    Write-Check "P7" ".zip descomprimido integro en el repo local" $true
}

function Re-CleanAndExpand ($ZipPath, $RepoLocal) {
    # Paso 10: tras la validacion 100%, re-limpieza y re-descompresion (el repo queda EXACTO al .zip)
    Remove-RepoLocal $RepoLocal
    Expand-Zip $ZipPath $RepoLocal
    Write-Check "P10" "re-limpieza y re-descompresion tras la validacion (pasos 6-7 re-ejecutados)" $true
}

# ============================================================
#  PASO 9: INFORME .txt LEGIBLE DEL PROBLEMA (v1.1)
# ============================================================

function Emit-TxtInforme ($Fallos) {
    # Paso 9: .txt legible con el problema cuando la validacion no pasa al 100%
    $destino = Join-Path $env:USERPROFILE ("Downloads\PROBLEMA_ENTREGA_" + $NombreProyecto + "_v" + $VersionEntrega + ".txt")
    $lineas = @(
        "PROBLEMA DE ENTREGA - $NombreProyecto v$VersionEntrega",
        "Fecha: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        ".zip evaluado: $EntregaDir",
        "",
        "La validacion no paso al 100%: la entrega NO se aplica y vuelve al DCEPI (I.3b, umbral cero).",
        "Items fallados:",
        ($Fallos | ForEach-Object { "  - $_" }),
        "",
        "Veredicto JSON completo: VEREDICTO_ENTREGA_${NombreProyecto}_v$VersionEntrega.json (Descargas)",
        "Registro de intentos: entregas\registro_intentos.log en el repo local del proyecto"
    )
    $lineas | Out-File -FilePath $destino -Encoding UTF8
    Write-Host "  Informe del problema: $destino" -ForegroundColor Yellow
    return $destino
}

# ============================================================
#  PASOS 11-12: GITHUB Y DIFF DE TRIPLE IGUALDAD (v1.1)
# ============================================================

function Invoke-GitCommit ($RepoLocal) {
    # Paso 11a: commit del contenido reemplazado
    git -C $RepoLocal add -A
    $estado = @(git -C $RepoLocal status --porcelain)
    if ($estado.Count -gt 0) {
        git -C $RepoLocal commit -m "v${VersionEntrega}: reemplazo total desde entrega .zip (manifest SHA256 verificado)" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "P11: git commit fallo en $RepoLocal" }
        Write-Check "P11" "commit generado en el repo local" $true
    } else {
        Write-Check "P11" "sin cambios que comprometer (repo identico)" $true
    }
}

function Invoke-GitPush ($RepoLocal) {
    # Paso 11b: publicacion en GitHub del repo del proyecto
    $rama = git -C $RepoLocal rev-parse --abbrev-ref HEAD
    if (-not $rama) { throw "P11: no se pudo determinar la rama actual de $RepoLocal" }
    git -C $RepoLocal push origin $rama
    if ($LASTEXITCODE -ne 0) { throw "P11: git push fallo (repo $RepoGitHub, rama $rama)" }
    Write-Check "P11" "GitHub actualizado ($RepoGitHub, rama $rama)" $true
}

function Invoke-DiffCheck ($ZipPath, $RepoLocal) {
    # Paso 12: diff de triple igualdad (.zip <-> repo local <-> GitHub); informe SIEMPRE en Descargas
    Write-Host "  Paso 12: diff de triple igualdad (.zip <-> repo local <-> GitHub)..." -ForegroundColor White
    $fallosDiff = @()
    $tmp = Join-Path $env:TEMP ("diff_" + $NombreProyecto + "_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    Expand-Archive -Path $ZipPath -DestinationPath $tmp -Force

    # (1) .zip <-> repo local: SHA256 por ruta relativa, en ambas direcciones
    $zipFiles = @(Get-ChildItem -Path $tmp -Recurse -File | ForEach-Object { [pscustomobject]@{ rel = $_.FullName.Substring($tmp.Length + 1); sha = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower() } })
    foreach ($f in $zipFiles) {
        $p = Join-Path $RepoLocal ($f.rel -replace "/", "\")
        if (-not (Test-Path $p)) { $fallosDiff += "D1: el .zip trae $($f.rel) y el repo local no lo tiene"; continue }
        if ((Get-FileHash $p -Algorithm SHA256).Hash.ToLower() -ne $f.sha) { $fallosDiff += "D1: SHA256 distinto en $($f.rel)" }
    }
    $localFiles = @(Get-ChildItem -Path $RepoLocal -Recurse -File -Force | Where-Object { $_.FullName -notlike "$RepoLocal\.git\*" } | ForEach-Object { [pscustomobject]@{ rel = $_.FullName.Substring($RepoLocal.Length + 1); sha = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower() } })
    foreach ($l in $localFiles) {
        $enZip = $zipFiles | Where-Object { $_.rel -eq $l.rel }
        if (-not $enZip) { $fallosDiff += "D1: el repo local trae $($l.rel) y el .zip no" }
    }

    # (2) repo local <-> GitHub: HEAD local == HEAD remoto y arbol de trabajo limpio
    $rama = git -C $RepoLocal rev-parse --abbrev-ref HEAD
    $localHash = (git -C $RepoLocal rev-parse HEAD).Trim()
    $remoto = @(git ls-remote $RepoGitHub "refs/heads/$rama")
    $remotoHash = ""
    if ($remoto.Count -gt 0) { $remotoHash = ($remoto[0] -split "\s+")[0] }
    if (-not $remotoHash) { $fallosDiff += "D2: GitHub no devolvio HEAD para refs/heads/$rama (repo $RepoGitHub)" }
    elseif ($remotoHash -ne $localHash) { $fallosDiff += "D2: HEAD de GitHub ($remotoHash) distinto del local ($localHash)" }
    $pendiente = @(git -C $RepoLocal status --porcelain)
    if ($pendiente.Count -gt 0) { $fallosDiff += "D2: el arbol de trabajo local tiene cambios sin comprometer ($($pendiente.Count) lineas)" }

    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue

    if (-not $NoReport) {
        $informe = Join-Path $env:USERPROFILE ("Downloads\DIFF_ENTREGA_" + $NombreProyecto + "_v" + $VersionEntrega + ".txt")
        $lineas = @(
            "DIFF DE TRIPLE IGUALDAD - $NombreProyecto v$VersionEntrega",
            "Fecha: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
            ".zip: $ZipPath",
            "Repo local: $RepoLocal (rama $rama, HEAD $localHash)",
            "GitHub: $RepoGitHub (HEAD $remotoHash)",
            "",
            "Veredicto: $(if ($fallosDiff.Count -eq 0) { 'DIFF CERO: .zip == repo local == GitHub' } else { 'DIFERENCIAS: la entrega vuelve al DCEPI (umbral cero)' })",
            "",
            ($fallosDiff | ForEach-Object { "  - $_" })
        )
        $lineas | Out-File -FilePath $informe -Encoding UTF8
        Write-Host "  Informe: $informe" -ForegroundColor Gray
    }
    Write-Check "P12" "triple igualdad .zip == repo local == GitHub ($($zipFiles.Count) archivos)" ($fallosDiff.Count -eq 0)
    return ($fallosDiff.Count -eq 0)
}

# ============================================================
#  PROGRAMA PRINCIPAL (7 fases, 12 pasos del Director)
# ============================================================

Write-Title
Write-Host "  Checklist embebida de la entrega (estandar R5 v1.1, 12 pasos del Director):" -ForegroundColor White

try {
    # Fase 1: Localizar (pasos 2-5; el paso 1 es la descarga manual del Director)
    $zipDetectado = Find-ZipInFolder
    $repoLocal = Find-RepoLocal
    $vals = Confirm-Values $zipDetectado $repoLocal
    $zipFinal = $vals[0]
    $repoLocal = $vals[1].TrimEnd("\")
    $RutaLocalProyecto = $repoLocal   # el registro de intentos sigue al repo local efectivo
    Add-Registro "P1-P5: zip=$zipFinal ; repo=$repoLocal"

    # Fase 2: Limpiar y descomprimir (pasos 6-7)
    Remove-RepoLocal $repoLocal
    Expand-Zip $zipFinal $repoLocal
    $EntregaDir = $repoLocal   # las funciones existentes (a)/(b)/(c) operan sobre el contenido extraido

    # Fase 3: Validar (paso 8)
    $fallos = @()
    $fallos += Test-Contenido
    $fallos += Test-Precondiciones
    $fallos += Test-Funcionamiento
    Write-Check "C7" "cierre por construccion: veredicto asentado y publicacion condicionada (I.3e)" $true

    # Fase 4: Veredicto (paso 9; si no pasa al 100%, .txt con el problema y exit 1)
    $aprobado = Emit-Veredicto $fallos
    if (-not $aprobado) { exit 1 }

    # Fase 5: Re-limpiar y re-descomprimir (paso 10)
    Re-CleanAndExpand $zipFinal $repoLocal

    # Fase 6: Actualizar GitHub (paso 11)
    Invoke-GitCommit $repoLocal
    Invoke-GitPush $repoLocal

    # Fase 7: Diff de triple igualdad (paso 12)
    $okDiff = Invoke-DiffCheck $zipFinal $repoLocal
    if (-not $okDiff) { Add-Registro "P12: diferencias detectadas; la entrega vuelve al DCEPI (umbral cero)"; exit 1 }
    Add-Registro "P12: triple igualdad (.zip == repo local == GitHub) CERO; entrega v$VersionEntrega aplicada y publicada"

    Write-Host ""
    Write-Host "  ACTUALIZACION COMPLETADA - $NombreProyecto v$VersionEntrega (12 pasos del Director)" -ForegroundColor Green
    exit 0
} catch {
    Add-Registro "ABORTADO: $_"
    Write-Host ""
    Write-Host "  ABORTADO (umbral cero): $_" -ForegroundColor Red
    Write-Host "  La entrega NO se aplica. Escalar al Director con el problema exacto." -ForegroundColor Red
    exit 1
}
