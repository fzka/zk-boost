# -*- coding: utf-8 -*-
"""
ZK Boost — Módulo de Diagnóstico
---------------------------------
SOMENTE LEITURA. Este módulo nunca altera nada no sistema.
Ele coleta o estado atual do Windows e classifica cada item em:

    OK    -> já está no melhor estado possível
    WARN  -> pode melhorar, com ganho esperado
    INFO  -> informativo, sem ação recomendada
    ERROR -> não foi possível ler

Uso standalone (para testes):
    python zk_diagnostics.py
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass, field

try:
    import winreg
except ImportError:  # permite importar o módulo fora do Windows
    winreg = None

IS_WINDOWS = os.name == "nt"

STATUS_OK = "OK"
STATUS_WARN = "WARN"
STATUS_INFO = "INFO"
STATUS_ERROR = "ERROR"

# Idade do driver de vídeo a partir da qual sugerimos atualização.
DRIVER_AGE_WARN_DAYS = 120

# Processos que representam CPU ociosa, não consumo real. O nome muda com o
# idioma do Windows, por isso a lista cobre as variantes mais comuns.
IDLE_PROCESS_NAMES = {
    "system idle process",
    "processo ocioso do sistema",
    "idle",
}


@dataclass
class Finding:
    """Um item do relatório de diagnóstico."""
    key: str
    label: str
    value: str = "—"
    status: str = STATUS_INFO
    detail: str = ""
    recommendation: str = ""
    data: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# HELPERS DE COLETA
# --------------------------------------------------------------------------- #

def _run(command, timeout=30):
    """Executa um comando sem abrir janela. Retorna (ok, stdout)."""
    if not IS_WINDOWS:
        return False, ""
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            errors="ignore",
            timeout=timeout,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode == 0, (result.stdout or "")
    except (subprocess.TimeoutExpired, OSError):
        return False, ""


def _powershell_json(script, timeout=45):
    """Roda um script PowerShell que devolve JSON e já parseia o resultado."""
    command = (
        'powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass '
        f'-Command "{script}"'
    )
    ok, output = _run(command, timeout=timeout)
    if not ok or not output.strip():
        return None
    try:
        return json.loads(output)
    except ValueError:
        return None


def _reg_read(hive, path, name):
    """Lê um valor do registro. Retorna None se a chave/valor não existir."""
    if not IS_WINDOWS or winreg is None:
        return None
    try:
        with winreg.OpenKey(hive, path) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value
    except (FileNotFoundError, OSError):
        return None


# --------------------------------------------------------------------------- #
# COLETORES
# --------------------------------------------------------------------------- #

def check_os():
    data = _powershell_json(
        "Get-CimInstance Win32_OperatingSystem | "
        "Select-Object Caption, BuildNumber, TotalVisibleMemorySize | "
        "ConvertTo-Json -Compress"
    )
    if not data:
        return Finding("os", "Sistema Operacional", status=STATUS_ERROR,
                       detail="Não foi possível consultar o sistema.")

    caption = (data.get("Caption") or "Windows").strip()
    build = data.get("BuildNumber", "?")
    ram_gb = round((data.get("TotalVisibleMemorySize") or 0) / (1024 * 1024))

    return Finding(
        "os", "Sistema Operacional",
        value=f"{caption} (build {build})",
        status=STATUS_INFO,
        detail=f"{ram_gb} GB de RAM utilizável.",
        data={"build": build, "ram_gb": ram_gb},
    )


def check_cpu():
    data = _powershell_json(
        "Get-CimInstance Win32_Processor | "
        "Select-Object Name, NumberOfCores, NumberOfLogicalProcessors | "
        "ConvertTo-Json -Compress"
    )
    if not data:
        return Finding("cpu", "Processador", status=STATUS_ERROR,
                       detail="Não foi possível consultar a CPU.")
    if isinstance(data, list):
        data = data[0]

    name = (data.get("Name") or "Desconhecido").strip()
    physical = int(data.get("NumberOfCores") or 0)
    logical = int(data.get("NumberOfLogicalProcessors") or 0)
    smt = logical > physical > 0

    detail = f"{physical} núcleos físicos / {logical} threads."
    if smt:
        detail += (
            " SMT ativo: isolar o Core 0 exige remover DOIS processadores "
            "lógicos (0 e 1), não apenas o 0."
        )

    return Finding(
        "cpu", "Processador",
        value=name,
        status=STATUS_INFO,
        detail=detail,
        data={"physical": physical, "logical": logical, "smt": smt},
    )


def check_memory():
    data = _powershell_json(
        "Get-CimInstance Win32_PhysicalMemory | "
        "Select-Object Manufacturer, Capacity, Speed, ConfiguredClockSpeed | "
        "ConvertTo-Json -Compress"
    )
    if not data:
        return Finding("ram", "Memória RAM", status=STATUS_ERROR,
                       detail="Não foi possível consultar a memória.")
    if isinstance(data, dict):
        data = [data]

    modules = len(data)
    rated = max((int(m.get("Speed") or 0) for m in data), default=0)
    running = max((int(m.get("ConfiguredClockSpeed") or 0) for m in data), default=0)
    total_gb = round(sum(int(m.get("Capacity") or 0) for m in data) / (1024 ** 3))

    finding = Finding(
        "ram", "Memória RAM",
        value=f"{total_gb} GB · {modules} módulo(s) · {running} MT/s",
        data={"modules": modules, "rated": rated, "running": running},
    )

    if running and rated and running < rated:
        finding.status = STATUS_WARN
        finding.detail = (
            f"Os pentes são de {rated} MT/s mas estão rodando a {running} MT/s."
        )
        finding.recommendation = (
            "Ative o perfil XMP (Intel) ou EXPO (AMD) na BIOS. É o ajuste de "
            "maior impacto em FPS no CS2 e não pode ser feito por software."
        )
    elif modules < 2:
        finding.status = STATUS_WARN
        finding.detail = "Apenas um módulo instalado — memória em single channel."
        finding.recommendation = (
            "Um segundo pente idêntico habilita dual channel e costuma render "
            "ganho expressivo de FPS."
        )
    else:
        finding.status = STATUS_OK
        finding.detail = "Rodando na frequência nominal, em multi-channel."

    return finding


def _nvidia_version(driver_version):
    """Converte a versão WMI (32.0.15.9186) na versão NVIDIA (591.86)."""
    parts = (driver_version or "").split(".")
    if len(parts) < 4:
        return None
    digits = (parts[2] + parts[3])[-5:]
    if len(digits) != 5 or not digits.isdigit():
        return None
    return f"{digits[:3]}.{digits[3:]}"


def check_gpu():
    data = _powershell_json(
        "Get-CimInstance Win32_VideoController | "
        "Where-Object { $_.AdapterCompatibility -notmatch 'Microsoft' } | "
        "Select-Object Name, DriverVersion, "
        "@{n='DriverDate';e={$_.DriverDate.ToString('yyyy-MM-dd')}} | "
        "ConvertTo-Json -Compress"
    )
    if not data:
        return Finding("gpu", "Placa de Vídeo", status=STATUS_ERROR,
                       detail="Não foi possível consultar a GPU.")
    if isinstance(data, list):
        data = data[0]

    name = (data.get("Name") or "Desconhecida").strip()
    raw_version = data.get("DriverVersion") or ""
    date_str = data.get("DriverDate") or ""

    friendly = _nvidia_version(raw_version) if "NVIDIA" in name.upper() else None
    version_label = friendly or raw_version

    finding = Finding(
        "gpu", "Placa de Vídeo",
        value=f"{name} · driver {version_label}",
        data={"driver_version": raw_version, "driver_date": date_str},
    )

    age_days = None
    try:
        from datetime import date
        year, month, day = (int(p) for p in date_str.split("-"))
        age_days = (date.today() - date(year, month, day)).days
    except (ValueError, AttributeError):
        pass

    if age_days is None:
        finding.status = STATUS_INFO
        finding.detail = "Não foi possível determinar a data do driver."
    elif age_days > DRIVER_AGE_WARN_DAYS:
        finding.status = STATUS_WARN
        finding.detail = f"Driver de {date_str} — {age_days} dias."
        finding.recommendation = (
            "Drivers novos costumam trazer correções de desempenho para o CS2."
        )
    else:
        finding.status = STATUS_OK
        finding.detail = f"Driver recente ({date_str})."

    return finding


def list_power_plans():
    """Lê powercfg /list de forma independente de idioma.

    Os GUIDs dos planos NÃO são universais entre máquinas — por isso eles
    precisam ser descobertos em runtime, nunca hardcoded.
    """
    ok, output = _run("powercfg /list")
    if not ok:
        return []
    plans = []
    pattern = re.compile(r"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})")
    for line in output.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        name = ""
        if "(" in line and ")" in line:
            name = line[line.rfind("(") + 1:line.rfind(")")].strip()
        plans.append({
            "guid": match.group(1),
            "name": name,
            "active": "*" in line,
        })
    return plans


def min_processor_state(guid):
    """Estado mínimo do processador (%) do plano, em modo CA.

    É esta métrica — e não o nome do plano — que diz se a CPU pode reduzir
    frequência durante a partida. Funciona em qualquer idioma do Windows.
    """
    ok, output = _run(f"powercfg /query {guid} SUB_PROCESSOR PROCTHROTTLEMIN")
    if not ok:
        return None
    values = re.findall(r"0x([0-9a-fA-F]{8})", output)
    if not values:
        return None
    try:
        return int(values[-2], 16) if len(values) >= 2 else int(values[-1], 16)
    except ValueError:
        return None


def check_power_plan():
    plans = list_power_plans()
    if not plans:
        return Finding("power", "Plano de Energia", status=STATUS_ERROR,
                       detail="Não foi possível listar os planos.")

    active = next((p for p in plans if p["active"]), None)
    if not active:
        return Finding("power", "Plano de Energia", status=STATUS_ERROR,
                       detail="Nenhum plano ativo identificado.")

    min_state = min_processor_state(active["guid"])
    finding = Finding(
        "power", "Plano de Energia",
        value=active["name"] or active["guid"],
        data={"plans": plans, "active": active, "min_state": min_state},
    )

    if min_state is None:
        finding.status = STATUS_INFO
        finding.detail = f"{len(plans)} planos disponíveis no sistema."
    elif min_state >= 100:
        finding.status = STATUS_OK
        finding.detail = "CPU mantida em 100% — sem downclock durante o jogo."
    else:
        finding.status = STATUS_WARN
        finding.detail = f"A CPU pode cair para {min_state}% de frequência."
        finding.recommendation = (
            "Um plano de alto desempenho evita a oscilação de clock que "
            "provoca stutter em momentos de carga variável."
        )

    return finding


def check_game_dvr():
    enabled = _reg_read(winreg.HKEY_CURRENT_USER, r"System\GameConfigStore",
                        "GameDVR_Enabled") if winreg else None

    finding = Finding("gamedvr", "Game DVR (gravação em segundo plano)",
                      data={"raw": enabled})

    if enabled is None:
        finding.value = "Padrão do Windows"
        finding.status = STATUS_INFO
        finding.detail = "Chave ausente — o Windows usa o comportamento padrão."
    elif int(enabled) == 1:
        finding.value = "Ativado"
        finding.status = STATUS_WARN
        finding.detail = "A gravação em segundo plano consome CPU e GPU continuamente."
        finding.recommendation = "Desativar o Game DVR libera recursos durante a partida."
    else:
        finding.value = "Desativado"
        finding.status = STATUS_OK
        finding.detail = "Sem overhead de captura."

    return finding


def check_game_mode():
    enabled = _reg_read(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar",
                        "AutoGameModeEnabled") if winreg else None

    finding = Finding("gamemode", "Game Mode", data={"raw": enabled})
    if enabled is None:
        finding.value = "Padrão do Windows (ativo)"
        finding.status = STATUS_INFO
        finding.detail = (
            "Chave nunca alterada. No Windows 11 o Game Mode vem ligado e, em "
            "geral, ajuda — não recomendamos mexer sem medir antes."
        )
    else:
        finding.value = "Ativado" if int(enabled) == 1 else "Desativado"
        finding.status = STATUS_INFO
        finding.detail = "Configurado manualmente pelo usuário."
    return finding


def check_hags():
    value = _reg_read(winreg.HKEY_LOCAL_MACHINE,
                      r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
                      "HwSchMode") if winreg else None

    finding = Finding("hags", "Agendamento de GPU acelerado por hardware",
                      data={"raw": value})
    if value is None:
        finding.value = "Padrão do driver"
        finding.status = STATUS_INFO
        finding.detail = "Valor nunca definido — vale o padrão da GPU instalada."
    else:
        finding.value = "Ativado" if int(value) == 2 else "Desativado"
        finding.status = STATUS_INFO
        finding.detail = (
            "O efeito varia por hardware: em algumas máquinas reduz latência, "
            "em outras aumenta stutter. Só mude medindo."
        )
    return finding


def check_mmcss():
    base = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"
    responsiveness = _reg_read(winreg.HKEY_LOCAL_MACHINE, base,
                               "SystemResponsiveness") if winreg else None
    throttling = _reg_read(winreg.HKEY_LOCAL_MACHINE, base,
                           "NetworkThrottlingIndex") if winreg else None
    gpu_priority = _reg_read(winreg.HKEY_LOCAL_MACHINE, base + r"\Tasks\Games",
                             "GPU Priority") if winreg else None
    priority = _reg_read(winreg.HKEY_LOCAL_MACHINE, base + r"\Tasks\Games",
                         "Priority") if winreg else None

    parts = []
    if responsiveness is not None:
        parts.append(f"Responsiveness {responsiveness}")
    if throttling is not None:
        parts.append(f"NetworkThrottling {throttling}")
    if gpu_priority is not None:
        parts.append(f"GPU Priority {gpu_priority}")
    if priority is not None:
        parts.append(f"Priority {priority}")

    return Finding(
        "mmcss", "Agendador Multimídia (MMCSS)",
        value=" · ".join(parts) if parts else "Não configurado",
        status=STATUS_INFO,
        detail=(
            "Valores padrão do Windows. Os ajustes populares nessas chaves têm "
            "evidência fraca de ganho real — o ZK Boost só vai sugerir mudança "
            "aqui depois que o módulo de benchmark puder comprovar diferença."
        ),
        data={
            "SystemResponsiveness": responsiveness,
            "NetworkThrottlingIndex": throttling,
            "GPU Priority": gpu_priority,
            "Priority": priority,
        },
    )


def check_background_load():
    """Processos consumindo CPU agora — puro diagnóstico, sem ação."""
    try:
        import psutil
    except ImportError:
        return Finding("background", "Carga em Segundo Plano",
                       status=STATUS_ERROR, detail="psutil não instalado.")

    try:
        for proc in psutil.process_iter():
            try:
                proc.cpu_percent(None)  # primeira leitura inicializa o contador
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        import time
        time.sleep(1.0)

        cores = psutil.cpu_count() or 1
        loads = []
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                pid = proc.info.get("pid")
                name = proc.info.get("name") or "?"

                # O "System Idle Process" (PID 0) contabiliza a CPU OCIOSA.
                # Incluí-lo inverte a leitura: 98% nele significa 98% de CPU
                # LIVRE, e o diagnóstico acabaria acusando sobrecarga num PC
                # que está parado.
                if pid == 0 or name.lower() in IDLE_PROCESS_NAMES:
                    continue

                usage = proc.cpu_percent(None) / cores
                if usage > 0.5:
                    loads.append((name, usage))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        loads.sort(key=lambda item: item[1], reverse=True)
        top = loads[:5]
        total = sum(usage for _, usage in loads)
    except Exception as exc:
        return Finding("background", "Carga em Segundo Plano",
                       status=STATUS_ERROR, detail=str(exc))

    finding = Finding(
        "background", "Carga em Segundo Plano",
        value=f"{total:.1f}% de CPU em uso",
        data={"top": top},
    )
    if top:
        finding.detail = "Maiores consumidores: " + ", ".join(
            f"{name} ({usage:.1f}%)" for name, usage in top
        )

    # Com o processo ocioso fora da conta, um PC em repouso fica na casa de
    # 1-5%. Acima de 10% já há algo competindo por CPU com o jogo.
    if total > 10:
        finding.status = STATUS_WARN
        finding.recommendation = (
            "Fechar esses programas antes da partida libera CPU para o CS2."
        )
    else:
        finding.status = STATUS_OK
        finding.detail = finding.detail or "Sistema ocioso, sem concorrência pela CPU."

    return finding


# --------------------------------------------------------------------------- #
# ORQUESTRAÇÃO
# --------------------------------------------------------------------------- #

CHECKS = (
    check_os,
    check_cpu,
    check_memory,
    check_gpu,
    check_power_plan,
    check_game_dvr,
    check_game_mode,
    check_hags,
    check_mmcss,
    check_background_load,
)


def run_diagnostics(progress=None):
    """Executa todos os checks. `progress` recebe (indice, total, label)."""
    findings = []
    total = len(CHECKS)
    for index, check in enumerate(CHECKS, start=1):
        try:
            finding = check()
        except Exception as exc:  # um check quebrado nunca derruba o relatório
            finding = Finding(
                key=getattr(check, "__name__", "desconhecido"),
                label="Verificação com falha",
                status=STATUS_ERROR,
                detail=str(exc),
            )
        findings.append(finding)
        if progress:
            progress(index, total, finding.label)
    return findings


def summarize(findings):
    """Conta os status para o resumo no topo do painel."""
    summary = {STATUS_OK: 0, STATUS_WARN: 0, STATUS_INFO: 0, STATUS_ERROR: 0}
    for finding in findings:
        summary[finding.status] = summary.get(finding.status, 0) + 1
    return summary


ICONS = {STATUS_OK: "✔", STATUS_WARN: "!", STATUS_INFO: "i", STATUS_ERROR: "x"}


if __name__ == "__main__":
    print("ZK Boost — Diagnóstico do Sistema\n" + "=" * 60)
    results = run_diagnostics()
    for item in results:
        print(f"\n[{ICONS.get(item.status, '?')}] {item.label}: {item.value}")
        if item.detail:
            print(f"    {item.detail}")
        if item.recommendation:
            print(f"    → {item.recommendation}")
    counts = summarize(results)
    print("\n" + "=" * 60)
    print(f"{counts[STATUS_OK]} ok · {counts[STATUS_WARN]} atenção · "
          f"{counts[STATUS_INFO]} info · {counts[STATUS_ERROR]} erro")