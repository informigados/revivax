@echo off
:: ═══════════════════════════════════════════════════════════════
::  RevivaX — Build do Executável (PyInstaller)
::  Gera o executável standalone em dist\RevivaX\RevivaX.exe
:: ═══════════════════════════════════════════════════════════════
setlocal

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

:: ── PyInstaller: empacota tudo em um unico executável ─────────────
python -m PyInstaller --noconfirm --log-level=WARN ^
    --name "RevivaX" ^
    --add-data "web/templates;templates" ^
    --add-data "web/static;static" ^
    --icon NONE ^
    --clean ^
    main.py

if %errorlevel% equ 0 (
    echo.
    echo  ╔══════════════════════════════════════════════════════╗
    echo  ║  [OK] Build concluido com sucesso!                  ║
    echo  ║                                                      ║
    echo  ║  Executavel: dist\RevivaX\RevivaX.exe               ║
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
pause
exit /b %errorlevel%
