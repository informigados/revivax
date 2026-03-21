"""
RevivaX - Runtime path helpers
Separa recursos empacotados de diretórios graváveis da aplicação.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "RevivaX"
SOURCE_ROOT = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_runtime_root() -> Path:
    """
    Retorna o diretório gravável base da aplicação.

    Prioridade:
    1. `REVIVAX_HOME`
    2. `%LOCALAPPDATA%\\RevivaX` no Windows empacotado
    3. `~/.revivax` em outros ambientes empacotados
    4. raiz do projeto em modo fonte
    """
    custom_home = os.environ.get("REVIVAX_HOME", "").strip()
    if custom_home:
        return Path(custom_home).expanduser().resolve()

    if is_frozen():
        if os.name == "nt":
            localappdata = os.environ.get("LOCALAPPDATA", "").strip()
            if localappdata:
                return (Path(localappdata) / APP_NAME).resolve()
        return (Path.home() / ".revivax").resolve()

    return SOURCE_ROOT


def get_logs_dir() -> Path:
    return (get_runtime_root() / "logs").resolve()


def get_recovered_dir() -> Path:
    return (get_runtime_root() / "recovered").resolve()


def get_tools_dir() -> Path:
    return (get_runtime_root() / "tools").resolve()
