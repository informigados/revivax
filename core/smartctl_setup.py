"""
RevivaX — Smartctl Setup
Baixa automaticamente o smartctl.exe do smartmontools (Windows)
via GitHub Releases API e o disponibiliza em tools/.

Estratégia: o único asset Windows publicado é o instalador NSIS
(.win32-setup.exe). Rodamos em modo silencioso (/S) numa pasta
temporária, copiamos apenas o smartctl.exe para tools/ e removemos
tudo o mais.

Uso:
    from core.smartctl_setup import ensure_smartctl
    smartctl_path = ensure_smartctl()   # retorna caminho ou None
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import hashlib
import json
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

logger = logging.getLogger(__name__)

# ── Constantes ─────────────────────────────────────────────────────────────────
TOOLS_DIR      = Path(__file__).parent.parent / 'tools'
SMARTCTL_NAME  = 'smartctl.exe' if os.name == 'nt' else 'smartctl'
SMARTCTL_LOCAL = TOOLS_DIR / SMARTCTL_NAME

# GitHub API
GH_API_RELEASES = 'https://api.github.com/repos/smartmontools/smartmontools/releases/latest'
GH_API_HEADERS  = {
    'Accept':     'application/vnd.github+json',
    'User-Agent': 'RevivaX/1.0',
}

# Sufixo do instalador Windows publicado nos releases
WIN_INSTALLER_SUFFIX = '.win32-setup.exe'

NET_TIMEOUT = 60  # segundos


def ensure_smartctl() -> Optional[str]:
    """
    Garante que o smartctl está disponível, nesta ordem de prioridade:

    1. tools/smartctl.exe  (já baixado anteriormente)
    2. PATH do sistema     (instalação manual)
    3. Program Files       (instalador padrão Windows)
    4. Download automático do GitHub Releases (primeira execução)

    Retorna o caminho completo para smartctl ou None se indisponível.
    """
    # 1. Arquivo local na pasta tools/ do projeto
    if SMARTCTL_LOCAL.exists() and _is_executable(str(SMARTCTL_LOCAL)):
        logger.info("smartctl encontrado em tools/: %s", SMARTCTL_LOCAL)
        return str(SMARTCTL_LOCAL)

    # 2. System PATH
    path_cmd = shutil.which('smartctl')
    if path_cmd and _is_executable(path_cmd):
        logger.info("smartctl encontrado no PATH: %s", path_cmd)
        return path_cmd

    # 3. Locais de instalação padrão (Windows)
    if os.name == 'nt':
        standard_paths = [
            Path(r'C:\Program Files\smartmontools\bin\smartctl.exe'),
            Path(r'C:\Program Files (x86)\smartmontools\bin\smartctl.exe'),
        ]
        for p in standard_paths:
            if p.exists() and _is_executable(str(p)):
                logger.info("smartctl encontrado em Program Files: %s", p)
                return str(p)

    # 4. Download automático
    logger.info("smartctl não encontrado localmente. Baixando automaticamente...")
    return _download_smartctl()


def _is_executable(path: str) -> bool:
    """Verifica se o binário responde ao --version sem travar."""
    try:
        r = subprocess.run(
            [path, '--version'],
            capture_output=True, timeout=8, check=False,
            creationflags=0x08000000 if os.name == 'nt' else 0,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _download_smartctl() -> Optional[str]:
    """
    Baixa o instalador NSIS do smartmontools do último release no GitHub,
    executa em modo silencioso numa pasta temporária, copia apenas o
    smartctl.exe para tools/ e remove o restante.
    """
    if os.name != 'nt':
        logger.warning("Download automático suportado apenas no Windows.")
        return None

    # ── Consulta o último release via GitHub API ───────────────────────────────
    try:
        logger.info("Consultando GitHub API para o último release do smartmontools...")
        req      = Request(GH_API_RELEASES, headers=GH_API_HEADERS)
        response = urlopen(req, timeout=NET_TIMEOUT)
        release  = json.loads(response.read().decode())
    except (URLError, Exception) as exc:
        logger.error("Falha ao consultar a API do GitHub: %s", exc)
        return None

    assets   = release.get('assets', [])
    tag_name = release.get('tag_name', 'desconhecida')
    exe_url  = None
    exe_name = None
    exe_digest = None

    for asset in assets:
        name = asset.get('name', '')
        if name.endswith(WIN_INSTALLER_SUFFIX):
            exe_url  = asset.get('browser_download_url')
            exe_name = name
            exe_digest = asset.get('digest')
            logger.info("Release encontrado: %s — asset: %s", tag_name, name)
            break

    if not exe_url:
        logger.error(
            "Nenhum instalador Windows encontrado no release %s. "
            "Baixe manualmente em: https://www.smartmontools.org/wiki/Download",
            tag_name,
        )
        return None

    # ── Baixa o instalador para pasta temporária ───────────────────────────────
    tmp_dir        = Path(tempfile.mkdtemp(prefix='revivax_smart_'))
    installer_path = tmp_dir / exe_name
    install_dir    = tmp_dir / 'install'

    try:
        logger.info("Baixando %s (~1.5 MB)...", exe_url)
        req      = Request(exe_url, headers=GH_API_HEADERS)
        response = urlopen(req, timeout=NET_TIMEOUT)
        installer_path.write_bytes(response.read())
        logger.info("Download concluído: %s", installer_path)
        if not _verify_download_integrity(installer_path, exe_digest):
            logger.error("Falha na validação de integridade do instalador: %s", installer_path)
            return None

        # ── Executa instalador em modo silencioso ──────────────────────────────
        # Flags NSIS: /S = silencioso; /D= = diretório de instalação
        install_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Executando instalador silencioso em: %s", install_dir)
        result = subprocess.run(
            [str(installer_path), '/S', f'/D={install_dir}'],
            timeout=120, check=False,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        if result.returncode not in (0, 1):
            logger.warning("Instalador retornou código %d (pode ser normal).", result.returncode)

        # ── Procura smartctl.exe na pasta instalada ────────────────────────────
        candidates = list(install_dir.rglob('smartctl.exe'))
        if not candidates:
            logger.error("smartctl.exe não encontrado após instalação em: %s", install_dir)
            return None

        smartctl_src = candidates[0]
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(smartctl_src, SMARTCTL_LOCAL)
        logger.info("smartctl.exe copiado para: %s", SMARTCTL_LOCAL)

    except (OSError, subprocess.TimeoutExpired, Exception) as exc:
        logger.error("Falha no download/instalação do smartctl: %s", exc)
        return None
    finally:
        # Limpa todos os arquivos temporários
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    # ── Verifica se o binário funciona ─────────────────────────────────────────
    if _is_executable(str(SMARTCTL_LOCAL)):
        logger.info(
            "smartctl.exe instalado com sucesso em: %s (versão %s)",
            SMARTCTL_LOCAL, tag_name,
        )
        return str(SMARTCTL_LOCAL)

    logger.error(
        "smartctl.exe copiado para %s mas não respondeu ao --version.",
        SMARTCTL_LOCAL,
    )
    return None


def _verify_download_integrity(file_path: Path, expected_digest: Optional[str]) -> bool:
    """Valida o download por digest do release ou assinatura Authenticode."""
    if expected_digest:
        try:
            algo, expected_hash = expected_digest.split(':', 1)
            digest = hashlib.new(algo)
            with open(file_path, 'rb') as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(chunk)
            calculated_hash = digest.hexdigest().lower()
            if calculated_hash == expected_hash.lower():
                return True
            logger.error("Digest do instalador divergente. Esperado=%s calculado=%s", expected_hash, calculated_hash)
            return False
        except (ValueError, OSError) as exc:
            logger.error("Falha ao validar digest do instalador: %s", exc)
            return False

    if os.name == 'nt':
        return _verify_authenticode_signature(file_path)

    logger.warning("Sem digest do release e sem validação de assinatura disponível para %s", file_path)
    return False


def _verify_authenticode_signature(file_path: Path) -> bool:
    """Confere se o binário baixado possui assinatura Authenticode válida."""
    quoted_path = str(file_path).replace("'", "''")
    command = [
        'powershell',
        '-NoProfile',
        '-Command',
        f"(Get-AuthenticodeSignature -FilePath '{quoted_path}').Status",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            creationflags=0x08000000 if os.name == 'nt' else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.error("Falha ao validar assinatura Authenticode de %s: %s", file_path, exc)
        return False

    status = (result.stdout or '').strip()
    if result.returncode == 0 and status == 'Valid':
        return True

    logger.error(
        "Assinatura Authenticode inválida para %s. status=%s stderr=%s",
        file_path,
        status or '<vazio>',
        (result.stderr or '').strip() or '<vazio>',
    )
    return False
