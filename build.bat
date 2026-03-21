@echo off
:: ═══════════════════════════════════════════════════════════════
::  RevivaX — Build do Executável (PyInstaller)
::  Gera o executável standalone em dist\RevivaX\RevivaX.exe
:: ═══════════════════════════════════════════════════════════════
setlocal
set "NO_PAUSE="
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║         RevivaX — Gerando Executavel...             ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: ── Verifica Python ──────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERRO] Python nao encontrado. Instale antes de compilar.
    pause
    exit /b 1
)

:: ── Verifica / instala PyInstaller ───────────────────────────────
python -m PyInstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [INFO] PyInstaller nao encontrado. Instalando...
    pip install -r requirements-dev.txt
    if %errorlevel% neq 0 (
        echo  [ERRO] Falha ao instalar o PyInstaller.
        pause
        exit /b 1
    )
)

echo  [1/2] Compilando... (pode levar alguns minutos)
echo.

:: ── PyInstaller: empacota usando a spec oficial ───────────────────
python -m PyInstaller --noconfirm --clean RevivaX.spec

if %errorlevel% equ 0 (
    echo.
    echo  ╔══════════════════════════════════════════════════════╗
    echo  ║  [OK] Build concluido com sucesso!                  ║
    echo  ║                                                      ║
    echo  ║  Executavel: dist\RevivaX\RevivaX.exe               ║
    echo  ║  Manifesto: elevacao UAC habilitada                ║
    echo  ║                                                      ║
    echo  ║  OBSERVACOES:                                        ║
    echo  ║  - O smartctl.exe sera baixado automaticamente       ║
    echo  ║    na primeira execucao (requer internet)            ║
    echo  ║  - Execute sempre como Administrador para            ║
    echo  ║    acessar discos fisicos                            ║
    echo  ╚══════════════════════════════════════════════════════╝
) else (
    echo.
    echo  [ERRO] Falha no build. Verifique os logs acima.
)

echo.
if not defined NO_PAUSE pause
exit /b %errorlevel%
