@echo off
REM CZAI JWT Bridge - Obtiene el JWT del Director y lo envía al sandbox
REM Uso: doble click. Se cierra solo.
REM
REM Este script:
REM 1. Lanza Edge con el puerto de depuración 9222
REM 2. Edge abre chat.z.ai (donde el Director ya tiene sesión)
REM 3. PowerShell se conecta a Edge vía DevTools Protocol
REM 4. Ejecuta fetch('/api/v1/auths/') dentro de la página
REM 5. Captura el JWT de la respuesta
REM 6. Lo envía al sandbox del agente
REM 7. Cierra Edge y se cierra

REM ============================================================
REM CONFIGURACIÓN (el agente reemplaza SANDBOX_URL al servir el archivo)
REM ============================================================
if "%SANDBOX_URL%"=="" set SANDBOX_URL=%%SANDBOX_URL%%

REM Si SANDBOX_URL no fue reemplazado, pedirlo al usuario
if "%SANDBOX_URL%"=="%%SANDBOX_URL%%" (
    set /p SANDBOX_URL="Introduce la URL del sandbox del agente (ej: http://localhost:8086): "
)

echo ============================================
echo  CZAI JWT Bridge
echo ============================================
echo  Sandbox URL: %SANDBOX_URL%
echo ============================================
echo.

REM Ejecutar script PowerShell
powershell -ExecutionPolicy Bypass -File "%~dp0jwt_bridge.ps1" -SandboxUrl "%SANDBOX_URL%"

echo.
echo Presiona cualquier tecla para cerrar...
pause >nul
