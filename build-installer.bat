@echo off
:: ═══════════════════════════════════════════════════════════════
::  RevivaX — Build do Instalador (Inno Setup)
::  Requer build PyInstaller pronto em dist\RevivaX
:: ═══════════════════════════════════════════════════════════════
setlocal

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║       RevivaX — Gerando Instalador...               ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

if not exist "dist\RevivaX\RevivaX.exe" (
    echo  [INFO] Build PyInstaller nao encontrado. Gerando primeiro...
    call build.bat --no-pause
    if %errorlevel% neq 0 exit /b %errorlevel%
)

set "ISCC_CMD="
where ISCC >nul 2>&1
if %errorlevel% equ 0 set "ISCC_CMD=ISCC"

if not defined ISCC_CMD if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_CMD=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC_CMD if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_CMD=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if not defined ISCC_CMD (
    echo  [ERRO] Inno Setup Compiler (ISCC.exe) nao encontrado.
    echo  [INFO] Instale o Inno Setup 6 e rode novamente.
    exit /b 1
)

echo  [1/1] Compilando instalador...
"%ISCC_CMD%" installer.iss
if %errorlevel% neq 0 (
    echo  [ERRO] Falha ao gerar instalador.
    exit /b %errorlevel%
)

echo.
echo  [OK] Instalador gerado em dist\installer\RevivaX-Setup.exe
echo.
exit /b 0
