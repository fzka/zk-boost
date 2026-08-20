# -*- coding: utf-8 -*-
"""
ZK Boost — Núcleo
------------------
Toda a lógica que toca o sistema operacional vive aqui, sem nenhuma
dependência de interface. Isso permite testar as operações no terminal,
reaproveitá-las em outra UI e manter zk_boost.py focado em apresentação.

Cada operação devolve um Result, para que a interface decida como exibir.
"""

import ctypes
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

import psutil

import zk_diagnostics as diag

IS_WINDOWS = os.name == "nt"
APP_VERSION = "3.0.1"

MARKER_START = "// >>> ZK BOOST START"
MARKER_END = "// <<< ZK BOOST END"
EXEC_LINE = "exec zk_boost"

CS2_CFG_RELATIVE = os.path.join(
    "steamapps", "common", "Counter-Strike Global Offensive", "game", "csgo", "cfg"
)

# Único GUID de plano de energia estável entre instalações. Os demais são
# descobertos em runtime: planos duplicados pela BIOS têm GUID próprio.
GUID_BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"


@dataclass
class Result:
    """Resultado de uma operação, pronto para a interface exibir."""
    ok: bool
    message: str
    detail: str = ""
    needs_admin: bool = False
    data: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# INFRAESTRUTURA
# --------------------------------------------------------------------------- #

def get_config_dir() -> str:
    base = os.getenv("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "ZKBoost")
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError:
        return os.path.dirname(os.path.abspath(sys.argv[0]))


CONFIG_FILE = os.path.join(get_config_dir(), "zk_settings.json")


def load_settings() -> dict:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
                return json.load(handle)
    except (OSError, ValueError):
        pass
    return {}


def save_settings(data: dict) -> bool:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        return True
    except OSError:
        return False


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Reabre o app pedindo elevação. True se o Windows aceitou iniciar."""
    if not IS_WINDOWS:
        return False
    try:
        executable = sys.executable
        params = "" if getattr(sys, "frozen", False) else f'"{os.path.abspath(sys.argv[0])}"'
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", executable, params, None, 1
        )
        return int(result) > 32
    except Exception:
        return False


def run_hidden(command: str, timeout: int = 60):
    """Executa comando do Windows sem piscar console. Retorna (ok, saída)."""
    if not IS_WINDOWS:
        return False, "Disponível apenas no Windows."
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, errors="ignore",
            timeout=timeout, startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode == 0, (result.stdout or result.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return False, "Tempo limite excedido."
    except OSError as exc:
        return False, str(exc)


# --------------------------------------------------------------------------- #
# DETECÇÃO DO CS2
# --------------------------------------------------------------------------- #

def find_cs2_process():
    try:
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                if (proc.info.get("name") or "").lower() == "cs2.exe":
                    return psutil.Process(proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return None


def _steam_roots() -> list:
    roots = []
    if IS_WINDOWS:
        try:
            import winreg
            candidates = [
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            ]
            for hive, key_path, value_name in candidates:
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        value, _ = winreg.QueryValueEx(key, value_name)
                        if value:
                            roots.append(os.path.normpath(value))
                except OSError:
                    continue
        except ImportError:
            pass
    roots.extend([
        r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam",
        r"C:\Steam", r"D:\Steam", r"D:\SteamLibrary", r"E:\SteamLibrary",
    ])
    return roots


def _library_folders(steam_root: str) -> list:
    libraries = [steam_root]
    vdf_path = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf_path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if '"path"' in line:
                    parts = line.split('"')
                    if len(parts) >= 4:
                        libraries.append(os.path.normpath(parts[3].replace("\\\\", "\\")))
    except OSError:
        pass
    return libraries


def detect_cs2_cfg_path():
    seen = set()
    for root in _steam_roots():
        for library in _library_folders(root):
            if library in seen:
                continue
            seen.add(library)
            candidate = os.path.join(library, CS2_CFG_RELATIVE)
            if os.path.isdir(candidate):
                return candidate
    return None