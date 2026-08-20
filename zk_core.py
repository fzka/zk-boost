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
APP_VERSION = "3.0"

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


# --------------------------------------------------------------------------- #
# CFG DO JOGO
# --------------------------------------------------------------------------- #

def build_cfg_lines(tracers=True, subtick=True, restore=False) -> list:
    lines = [
        "// ================================",
        f"// ZK BOOST AUTO-CFG v{APP_VERSION}",
        "// Arquivo gerado automaticamente.",
        "// ================================",
    ]
    if restore:
        return lines + [
            'r_drawtracers_firstperson "1"',
            'cl_net_buffer_ticks "0"',
            'engine_low_latency_sleep_after_client_tick "true"',
            'echo "ZK BOOST: valores padrao restaurados"',
        ]

    lines.append('r_drawtracers_firstperson "0"' if tracers
                 else 'r_drawtracers_firstperson "1"')
    if subtick:
        lines += [
            'cl_net_buffer_ticks "0"',
            'engine_low_latency_sleep_after_client_tick "true"',
        ]
    # Prova visual no console do jogo de que a integração carregou.
    lines.append('echo "ZK BOOST carregado"')
    return lines


def apply_game_config(cfg_path, tracers=True, subtick=True, restore=False) -> Result:
    """Escreve zk_boost.cfg e registra o exec no autoexec sem apagar nada."""
    if not cfg_path or not os.path.isdir(cfg_path):
        return Result(False, "Pasta do CS2 não definida")

    try:
        cfg_file = os.path.join(cfg_path, "zk_boost.cfg")
        with open(cfg_file, "w", encoding="utf-8") as handle:
            handle.write("\n".join(build_cfg_lines(tracers, subtick, restore)) + "\n")
    except OSError as exc:
        return Result(False, "Falha ao escrever zk_boost.cfg", str(exc))

    autoexec = os.path.join(cfg_path, "autoexec.cfg")
    block = f"{MARKER_START}\n{EXEC_LINE}\n{MARKER_END}\n"
    try:
        content = ""
        if os.path.exists(autoexec):
            with open(autoexec, "r", encoding="utf-8", errors="ignore") as handle:
                content = handle.read()

        if MARKER_START not in content and EXEC_LINE not in content:
            with open(autoexec, "a" if content else "w", encoding="utf-8") as handle:
                if content and not content.endswith("\n"):
                    handle.write("\n")
                handle.write(block)
    except OSError as exc:
        return Result(False, "Falha ao atualizar autoexec.cfg", str(exc))

    action = "restaurada" if restore else "aplicada"
    return Result(True, f"CFG {action} (binds preservados)",
                  "Reinicie o CS2 para os valores valerem.")


# --------------------------------------------------------------------------- #
# CPU
# --------------------------------------------------------------------------- #

def affinity_target():
    """Processadores lógicos que o jogo deve usar.

    Com SMT ativo, o núcleo físico 0 é composto por DOIS lógicos (0 e 1).
    Remover apenas o 0 deixa o jogo no núcleo que se queria isolar.
    Retorna (alvo, removidos, smt).
    """
    logical = psutil.cpu_count(logical=True) or 1
    physical = psutil.cpu_count(logical=False) or logical
    smt = logical > physical

    excluded = [0, 1] if smt and logical > 2 else [0]
    target = [cpu for cpu in range(logical) if cpu not in excluded]

    if len(target) < 2:
        return None, excluded, smt
    return target, excluded, smt


def tune_process(affinity=True, priority=True, restore=False) -> list:
    """Ajusta afinidade e prioridade do cs2.exe. Retorna lista de Result."""
    results = []
    process = find_cs2_process()
    if process is None:
        return [Result(False, "CS2 fechado",
                       "Abra o jogo e aplique novamente para os ajustes de CPU.")]

    try:
        if restore:
            process.cpu_affinity(list(range(psutil.cpu_count() or 1)))
            results.append(Result(True, "Afinidade restaurada (todos os núcleos)"))
            if IS_WINDOWS:
                process.nice(psutil.NORMAL_PRIORITY_CLASS)
                results.append(Result(True, "Prioridade restaurada para Normal"))
            return results

        if affinity:
            target, excluded, smt = affinity_target()
            if target is None:
                results.append(Result(False, "CPU com poucos núcleos",
                                      "Afinidade ignorada para não sufocar o jogo."))
            else:
                process.cpu_affinity(target)
                detail = f"CPUs {', '.join(map(str, excluded))} removidas"
                if smt:
                    detail += " (SMT detectado)"
                results.append(Result(True, "Núcleo 0 isolado", detail))

        if priority and IS_WINDOWS:
            process.nice(psutil.HIGH_PRIORITY_CLASS)
            results.append(Result(True, "Prioridade alta aplicada"))

    except psutil.AccessDenied:
        results.append(Result(False, "Acesso negado ao processo do jogo",
                              "Execute o ZK Boost como Administrador.",
                              needs_admin=True))
    except psutil.NoSuchProcess:
        results.append(Result(False, "O CS2 foi fechado durante a operação"))
    except (OSError, ValueError) as exc:
        results.append(Result(False, "Erro ao ajustar a CPU", str(exc)))

    return results


# --------------------------------------------------------------------------- #
# ENERGIA
# --------------------------------------------------------------------------- #

def rank_power_plans() -> list:
    """Planos ordenados por estado mínimo do processador (maior = melhor)."""
    ranked = []
    for plan in diag.list_power_plans():
        state = diag.min_processor_state(plan["guid"])
        ranked.append({**plan, "min_state": state if state is not None else -1})
    ranked.sort(key=lambda item: item["min_state"], reverse=True)
    return ranked


def apply_power_plan(previous_guid_setter=None) -> Result:
    ranked = rank_power_plans()
    if not ranked:
        return Result(False, "Não foi possível listar os planos de energia")

    active = next((p for p in ranked if p["active"]), None)
    if active and previous_guid_setter:
        previous_guid_setter(active["guid"])

    best = ranked[0]
    if active and best["guid"] == active["guid"]:
        return Result(True, f"Plano de energia já ideal ({best['name']})")

    if not is_admin():
        return Result(False, "Plano de energia exige Administrador", needs_admin=True)

    ok, _ = run_hidden(f"powercfg /setactive {best['guid']}")
    if ok:
        return Result(True, f"Plano de energia: {best['name']}")
    return Result(False, "Falha ao alterar o plano de energia")


def restore_power_plan(previous_guid=None) -> Result:
    plans = diag.list_power_plans()
    if not plans:
        return Result(False, "Não foi possível listar os planos de energia")

    available = {plan["guid"]: plan for plan in plans}
    if previous_guid and previous_guid in available:
        target = available[previous_guid]
    elif GUID_BALANCED in available:
        target = available[GUID_BALANCED]
    else:
        ranked = rank_power_plans()
        target = ranked[-1] if ranked else None

    if not target:
        return Result(False, "Nenhum plano de energia adequado encontrado")
    if target["active"]:
        return Result(True, f"Plano de energia já em {target['name']}")
    if not is_admin():
        return Result(False, "Plano de energia exige Administrador", needs_admin=True)

    ok, _ = run_hidden(f"powercfg /setactive {target['guid']}")
    if ok:
        return Result(True, f"Plano de energia restaurado ({target['name']})")
    return Result(False, "Falha ao restaurar o plano de energia")


# --------------------------------------------------------------------------- #
# GAME DVR
# --------------------------------------------------------------------------- #

_GAME_DVR_KEYS = [
    (r"System\GameConfigStore", "GameDVR_Enabled"),
    (r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled"),
]


def set_game_dvr(enabled: bool) -> Result:
    """Liga/desliga a gravação em segundo plano. Só escreve em HKCU."""
    if not IS_WINDOWS:
        return Result(False, "Disponível apenas no Windows")
    try:
        import winreg
    except ImportError:
        return Result(False, "Registro indisponível")

    value = 1 if enabled else 0
    changed = 0
    for path, name in _GAME_DVR_KEYS:
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0,
                                    winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
                changed += 1
        except OSError:
            continue

    if not changed:
        return Result(False, "Não foi possível alterar o Game DVR")

    estado = "ativada" if enabled else "desativada"
    return Result(True, f"Gravação em segundo plano {estado}",
                  "Efeito completo após reabrir o jogo.")


# --------------------------------------------------------------------------- #
# LIMPEZA
# --------------------------------------------------------------------------- #

def _folder_size(path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def _clean_directory(path, label) -> Result:
    """Remove o conteúdo de um diretório. Arquivos em uso são preservados."""
    if not path or not os.path.isdir(path):
        return Result(False, f"{label}: pasta não encontrada")

    path = os.path.normpath(path)
    # Trava de segurança: nunca operar na raiz de um disco.
    _, tail = os.path.splitdrive(path)
    if tail.strip("\\/") == "":
        return Result(False, f"{label}: caminho inseguro, limpeza abortada")

    freed = removed = skipped = 0
    try:
        entries = list(os.scandir(path))
    except PermissionError:
        return Result(False, f"{label}: acesso negado", needs_admin=True)
    except OSError as exc:
        return Result(False, f"{label}: não foi possível ler", str(exc))

    for entry in entries:
        try:
            if entry.is_file() or entry.is_symlink():
                size = entry.stat().st_size
                os.remove(entry.path)
                freed += size
                removed += 1
            elif entry.is_dir():
                size = _folder_size(entry.path)
                shutil.rmtree(entry.path)
                freed += size
                removed += 1
        except (OSError, PermissionError):
            skipped += 1  # em uso: pular é o comportamento correto

    mb = freed / (1024 * 1024)
    if removed:
        detail = f"{removed} itens removidos"
        if skipped:
            detail += f" · {skipped} em uso foram preservados"
        return Result(True, f"{label}: {mb:.0f} MB liberados", detail,
                      data={"mb": mb})
    return Result(True, f"{label}: já estava limpo", data={"mb": 0})


def clean_temp() -> Result:
    return _clean_directory(os.environ.get("TEMP") or os.environ.get("TMP"),
                            "Temporários")


def clean_prefetch() -> Result:
    if not is_admin():
        return Result(False, "Prefetch exige Administrador", needs_admin=True)
    return _clean_directory(os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                                         "Prefetch"), "Prefetch")


def clean_windows_update_cache() -> Result:
    if not is_admin():
        return Result(False, "Cache do Windows Update exige Administrador",
                      needs_admin=True)
    path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                        "SoftwareDistribution", "Download")
    return _clean_directory(path, "Cache do Windows Update")


def clean_thumbnails() -> Result:
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                        "Microsoft", "Windows", "Explorer")
    if not os.path.isdir(base):
        return Result(False, "Miniaturas: pasta não encontrada")

    freed = removed = skipped = 0
    for entry in os.scandir(base):
        if not entry.name.lower().startswith("thumbcache"):
            continue
        try:
            size = entry.stat().st_size
            os.remove(entry.path)
            freed += size
            removed += 1
        except (OSError, PermissionError):
            skipped += 1

    mb = freed / (1024 * 1024)
    if removed:
        return Result(True, f"Miniaturas: {mb:.0f} MB liberados",
                      f"{removed} arquivos de cache removidos", data={"mb": mb})
    if skipped:
        return Result(True, "Miniaturas: cache em uso pelo Explorer",
                      "Feche o Explorador de Arquivos para limpar.", data={"mb": 0})
    return Result(True, "Miniaturas: já estava limpo", data={"mb": 0})


def flush_dns() -> Result:
    ok, _ = run_hidden("ipconfig /flushdns")
    if ok:
        return Result(True, "Cache DNS limpo")
    return Result(False, "Falha ao limpar o cache DNS")