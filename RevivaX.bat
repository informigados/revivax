@echo off
:: ============================================================
::  RevivaX — Launcher com Elevação Automática de Privilégios
::  Solicita privilégios de Administrador via UAC se necessário
:: ============================================================
setlocal EnableDelayedExpansion

:: Define o diretório raiz do projeto como o diretório deste script
set "REVIVAX_DIR=%~dp0"
set "REVIVAX_DIR=%REVIVAX_DIR:~0,-1%"

:: ── Verifica se já está rodando como Administrador ─────────────────────────
net session >nul 2>&1
if %errorlevel% == 0 (
    goto :LAUNCH
)

:: ── Não é admin: solicita elevação via PowerShell UAC ─────────────────────
echo.
echo  [RevivaX] Elevando privilegios de Administrador...
echo  Uma janela de confirmacao UAC sera exibida.
echo.

:: Cria VBScript temporário para reabrir com elevação
set "VBS_TMP=%TEMP%\revivax_elevate.vbs"
(
    echo Set objShell = CreateObject("Shell.Application"^)
    echo objShell.ShellExecute "cmd.exe", "/c """"%~f0"""" :elevated", "", "runas", 1
) > "%VBS_TMP%"

cscript //nologo "%VBS_TMP%"
del /f /q "%VBS_TMP%" 2>nul
exit /b 0

:LAUNCH
:: ── Rodando como Administrador ─────────────────────────────────────────────
cls
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║         RevivaX — Data Recovery System              ║
echo  ║        Sistema de Recuperacao de Arquivos            ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: Muda para o diretório do projeto
cd /d "%REVIVAX_DIR%"

:: ── Verifica Python ─────────────────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERRO] Python nao encontrado no PATH.
    echo.
    echo  Instale o Python 3.10 ou superior em:
    echo    https://www.python.org/downloads/
    echo.
    echo  Certifique-se de marcar "Add Python to PATH" durante a instalacao.
    echo.
    pause
    exit /b 1
)

:: ── Verifica dependências ────────────────────────────────────────────────────
echo  Verificando dependencias...
python -c "import flask, flask_cors, psutil, waitress" >nul 2>&1
if %errorlevel% neq 0 (
    echo  [INFO] Dependencias ausentes. Instalando...
    echo.
    pip install "Flask>=2.3.3" "flask-cors>=4.0.0" "Werkzeug>=2.3.7" "waitress>=3.0.0" "psutil>=5.9.5"
    if %errorlevel% neq 0 (
        echo.
        echo  [ERRO] Falha ao instalar dependencias.
        echo  Verifique sua conexao com a internet e tente novamente.
        pause
        exit /b 1
    )
    echo.
    echo  [OK] Dependencias instaladas com sucesso.
    echo.
)

:: ── Inicia servidor ──────────────────────────────────────────────────────────
echo  Iniciando RevivaX...
echo  O navegador sera aberto automaticamente em instantes.
echo.
echo  Para encerrar, feche esta janela ou pressione Ctrl+C.
echo.

python main.py

:: ── Pausa ao sair ────────────────────────────────────────────────────────────
echo.
echo  RevivaX encerrado.
pause
exit /b 0
