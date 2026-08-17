# -*- coding: utf-8 -*-
"""
ZK Boost - CS2 Optimizer (v2.0)
--------------------------------
Otimizador VAC-Safe para Counter-Strike 2.

Métodos utilizados (nenhum deles toca a memória do jogo):
  - psutil  -> CPU Affinity / Priority Class do processo cs2.exe
  - I/O     -> injeção não-destrutiva de arquivos .cfg
  - powercfg / ipconfig / netsh -> comandos nativos do Windows

Build:
    pyinstaller --noconfirm --onefile --windowed --name "ZK Boost" zk_boost.py
"""

import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk
import psutil

import zk_diagnostics as diag

# --------------------------------------------------------------------------- #
# CONSTANTES
# --------------------------------------------------------------------------- #

IS_WINDOWS = os.name == "nt"
APP_VERSION = "2.0"

# ATENÇÃO: os GUIDs de plano de energia NÃO são iguais entre máquinas.
# Planos duplicados pela BIOS, por utilitários do fabricante ou por
# `powercfg -duplicatescheme` recebem GUID próprio — hardcodar o GUID do
# "Alto Desempenho" faz o recurso falhar silenciosamente em boa parte dos PCs.
# Os planos são descobertos em runtime via zk_diagnostics.list_power_plans().
#
# Único GUID estável em todas as instalações: o Equilibrado padrão do Windows,
# usado apenas como último recurso na restauração.
GUID_BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"

MARKER_START = "// >>> ZK BOOST START"
MARKER_END = "// <<< ZK BOOST END"
EXEC_LINE = "exec zk_boost"

CS2_CFG_RELATIVE = os.path.join(
    "steamapps", "common", "Counter-Strike Global Offensive", "game", "csgo", "cfg"
)

COLOR_BG_CARD = "#212121"
COLOR_ACCENT = "#00a8ff"
COLOR_DANGER = "#8b3a3a"
COLOR_DANGER_HOVER = "#a94545"


# --------------------------------------------------------------------------- #
# HELPERS DE SISTEMA
# --------------------------------------------------------------------------- #

def get_config_dir() -> str:
    """Guarda as settings no %APPDATA% (o .exe pode estar em pasta read-only)."""
    base = os.getenv("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "ZKBoost")
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError:
        return os.path.dirname(os.path.abspath(sys.argv[0]))


CONFIG_FILE = os.path.join(get_config_dir(), "zk_settings.json")


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_hidden(command: str, timeout: int = 60):
    """Executa um comando do Windows sem piscar janela de console."""
    if not IS_WINDOWS:
        return False, "Recurso disponível apenas no Windows."
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
        output = (result.stdout or result.stderr or "").strip()
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Tempo limite excedido."
    except OSError as exc:
        return False, str(exc)


def find_cs2_process():
    """Retorna o psutil.Process do cs2.exe ou None."""
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
    """Descobre instalações da Steam via registro + caminhos comuns."""
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
        r"C:\Program Files (x86)\Steam",
        r"C:\Program Files\Steam",
        r"C:\Steam",
        r"D:\Steam",
        r"D:\SteamLibrary",
        r"E:\SteamLibrary",
    ])
    return roots


def _library_folders(steam_root: str) -> list:
    """Lê o libraryfolders.vdf para achar bibliotecas em outros discos."""
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
    """Tenta localizar automaticamente a pasta .../game/csgo/cfg."""
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
# APLICAÇÃO
# --------------------------------------------------------------------------- #

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class ZKBoostApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"ZK Boost v{APP_VERSION} - CS2 Optimizer")
        self.geometry("520x780")
        self.minsize(480, 620)
        self.resizable(True, True)

        self.busy = False

        # --- Variáveis de Sistema ---
        self.var_affinity = ctk.BooleanVar(value=True)
        self.var_priority = ctk.BooleanVar(value=True)
        self.var_power = ctk.BooleanVar(value=False)

        # --- Variáveis de Manutenção ---
        self.var_network = ctk.BooleanVar(value=False)
        self.var_cleanup = ctk.BooleanVar(value=False)

        # --- Variáveis de Jogo ---
        self.var_tracers = ctk.BooleanVar(value=True)
        self.var_subtick = ctk.BooleanVar(value=True)
        self.var_terms = ctk.BooleanVar(value=False)

        self.cs2_cfg_path = None
        self.previous_power_guid = None
        self.load_settings()

        self.build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.log("ZK Boost pronto.")
        if self.cs2_cfg_path:
            self.log(f"Pasta CFG detectada: {self.cs2_cfg_path}")
        else:
            self.log("Pasta CFG do CS2 ainda não definida.")
        if not is_admin():
            self.log("Sem privilégios de administrador — CPU/Energia podem falhar.")

    # ------------------------------------------------------------------ #
    # PERSISTÊNCIA
    # ------------------------------------------------------------------ #

    def load_settings(self):
        data = {}
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
        except (OSError, ValueError):
            data = {}

        for key, var in self._settings_map().items():
            if key in data and isinstance(data[key], bool):
                var.set(data[key])

        saved_path = data.get("cs2_cfg_path", "")
        if saved_path and os.path.isdir(saved_path):
            self.cs2_cfg_path = saved_path
        else:
            self.cs2_cfg_path = detect_cs2_cfg_path()

        # Sobrevive ao fechamento do app: sem isso, quem desse boost e
        # reiniciasse perderia a referência do plano de energia original.
        self.previous_power_guid = data.get("previous_power_guid") or None

    def _settings_map(self):
        return {
            "affinity": self.var_affinity,
            "priority": self.var_priority,
            "power": self.var_power,
            "network": self.var_network,
            "cleanup": self.var_cleanup,
            "tracers": self.var_tracers,
            "subtick": self.var_subtick,
        }

    def save_settings(self):
        data = {key: var.get() for key, var in self._settings_map().items()}
        data["cs2_cfg_path"] = self.cs2_cfg_path or ""
        data["previous_power_guid"] = self.previous_power_guid or ""
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
        except OSError as exc:
            self.log(f"Não foi possível salvar as preferências ({exc}).")

    def on_close(self):
        self.save_settings()
        self.destroy()

    # ------------------------------------------------------------------ #
    # INTERFACE
    # ------------------------------------------------------------------ #

    def build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ---------- Cabeçalho ----------
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(15, 5))
        ctk.CTkLabel(
            header, text="⚡ ZK BOOST",
            font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold"),
        ).pack()
        ctk.CTkLabel(
            header, text="Maximum Performance for CS2 · 100% VAC-Safe",
            text_color="gray", font=ctk.CTkFont(size=12),
        ).pack()

        # ---------- Área rolável ----------
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=25, pady=5)
        body.grid_columnconfigure(0, weight=1)

        # Sistema
        self._section_title(body, "⚙️ Otimizações de Sistema")
        frame_sys = self._card(body)
        self._switch(frame_sys, "Desabilitar uso do Core 0 (Afinidade)", self.var_affinity)
        self._switch(frame_sys, "Forçar Alta Prioridade de Processamento", self.var_priority)
        self._switch(frame_sys, "Ativar Plano de Energia Máxima", self.var_power)

        # Manutenção
        self._section_title(body, "🧹 Manutenção do Windows")
        frame_maint = self._card(body)
        self._switch(frame_maint, "Otimizar Rede (Flush DNS e Winsock)", self.var_network)
        self._switch(frame_maint, "Limpar Cache e Arquivos Temporários", self.var_cleanup)

        # Jogo
        self._section_title(body, "🎮 Otimizações de Jogo (CFG Integrada)")
        frame_game = self._card(body)
        self._switch(frame_game, "Desabilitar Rastros de Tiro (1ª Pessoa)", self.var_tracers)
        self._switch(frame_game, "Suavização Avançada de Sub-Ticks", self.var_subtick)

        # Console de log
        self._section_title(body, "📋 Console")
        self.log_box = ctk.CTkTextbox(
            body, height=130, fg_color=COLOR_BG_CARD, corner_radius=8,
            font=ctk.CTkFont(family="Consolas", size=11), state="disabled", wrap="word",
        )
        self.log_box.pack(fill="both", expand=True, pady=(0, 5))

        # ---------- Rodapé ----------
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=25, pady=(0, 15))
        footer.grid_columnconfigure((0, 1), weight=1)

        terms = ctk.CTkFrame(footer, fg_color="transparent")
        terms.grid(row=0, column=0, columnspan=2, pady=(5, 8))
        ctk.CTkCheckBox(
            terms, text="Aceito os", variable=self.var_terms,
            checkbox_width=18, checkbox_height=18, font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 5))
        ctk.CTkButton(
            terms, text="Termos de Segurança", width=0, height=0,
            fg_color="transparent", text_color=COLOR_ACCENT, hover_color=COLOR_BG_CARD,
            font=ctk.CTkFont(size=12, underline=True), command=self.show_terms,
        ).pack(side="left")

        self.btn_boost = ctk.CTkButton(
            footer, text="INJETAR BOOST", height=45, corner_radius=8,
            font=ctk.CTkFont(size=15, weight="bold"), command=self.apply_optimizations,
        )
        self.btn_boost.grid(row=1, column=0, sticky="ew", padx=(0, 5))

        self.btn_restore = ctk.CTkButton(
            footer, text="RESTAURAR PADRÕES", height=45, corner_radius=8,
            fg_color=COLOR_DANGER, hover_color=COLOR_DANGER_HOVER,
            font=ctk.CTkFont(size=15, weight="bold"), command=self.restore_defaults,
        )
        self.btn_restore.grid(row=1, column=1, sticky="ew", padx=(5, 0))

    def _section_title(self, parent, text):
        ctk.CTkLabel(
            parent, text=text, anchor="w",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(fill="x", pady=(10, 5))

    def _card(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=COLOR_BG_CARD, corner_radius=8)
        frame.pack(fill="x", pady=(0, 5))
        return frame

    def _switch(self, parent, text, variable):
        ctk.CTkSwitch(
            parent, text=text, variable=variable, font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=15, pady=8)

    def show_terms(self):
        messagebox.showinfo(
            "Segurança ZK Boost",
            "O ZK Boost usa métodos 100% autorizados pela Valve.\n\n"
            "• Nada é injetado na memória do jogo.\n"
            "• Suas binds e mira originais nunca são apagadas.\n"
            "• Todas as alterações podem ser desfeitas em RESTAURAR PADRÕES.\n\n"
            "Alterações de CPU, energia e rede afetam o Windows e exigem "
            "execução como Administrador.",
        )

    # ------------------------------------------------------------------ #
    # LOG / ESTADO
    # ------------------------------------------------------------------ #

    def log(self, message):
        """Thread-safe: pode ser chamado de dentro das threads de trabalho."""
        self.after(0, self._append_log, message)

    def _append_log(self, message):
        try:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", f"› {message}\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        except Exception:
            pass

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.btn_boost.configure(state=state)
        self.btn_restore.configure(state=state)

    def _finish(self, title, lines):
        self._set_busy(False)
        messagebox.showinfo(title, "\n".join(lines) if lines else "Nada a fazer.")

    # ------------------------------------------------------------------ #
    # CAMINHO DO CS2
    # ------------------------------------------------------------------ #

    def ensure_cs2_path(self) -> bool:
        if self.cs2_cfg_path and os.path.isdir(self.cs2_cfg_path):
            return True

        detected = detect_cs2_cfg_path()
        if detected:
            self.cs2_cfg_path = detected
            self.save_settings()
            return True

        messagebox.showinfo(
            "Caminho não encontrado",
            "Não encontramos a pasta do CS2.\nPor favor, selecione a pasta 'cfg' do jogo.",
        )
        folder = filedialog.askdirectory(title="Selecione a pasta .../game/csgo/cfg")
        if folder and os.path.isdir(folder):
            self.cs2_cfg_path = os.path.normpath(folder)
            self.save_settings()
            return True
        return False

    # ------------------------------------------------------------------ #
    # MÓDULO: CFG DO JOGO
    # ------------------------------------------------------------------ #

    def _build_cfg_lines(self, restore=False):
        lines = [
            "// ================================",
            f"// ZK BOOST AUTO-CFG v{APP_VERSION}",
            "// Arquivo gerado automaticamente.",
            "// ================================",
        ]
        if restore:
            lines += [
                'r_drawtracers_firstperson "1"',
                'cl_net_buffer_ticks "0"',
                'engine_low_latency_sleep_after_client_tick "true"',
                "// Valores padrão restaurados pelo ZK Boost.",
            ]
            return lines

        lines.append(
            'r_drawtracers_firstperson "0"' if self.var_tracers.get()
            else 'r_drawtracers_firstperson "1"'
        )
        if self.var_subtick.get():
            lines += [
                'cl_net_buffer_ticks "0"',
                'engine_low_latency_sleep_after_client_tick "true"',
            ]
        return lines

    def apply_cfg_injection(self, restore=False) -> bool:
        """Escreve zk_boost.cfg e registra o exec no autoexec.cfg sem apagar nada."""
        try:
            cfg_file = os.path.join(self.cs2_cfg_path, "zk_boost.cfg")
            with open(cfg_file, "w", encoding="utf-8") as handle:
                handle.write("\n".join(self._build_cfg_lines(restore)) + "\n")
        except OSError as exc:
            self.log(f"Falha ao escrever zk_boost.cfg: {exc}")
            return False

        autoexec = os.path.join(self.cs2_cfg_path, "autoexec.cfg")
        block = f"{MARKER_START}\n{EXEC_LINE}\n{MARKER_END}\n"
        try:
            content = ""
            if os.path.exists(autoexec):
                with open(autoexec, "r", encoding="utf-8", errors="ignore") as handle:
                    content = handle.read()

            if MARKER_START in content or EXEC_LINE in content:
                return True  # já integrado, não duplica

            with open(autoexec, "a" if content else "w", encoding="utf-8") as handle:
                if content and not content.endswith("\n"):
                    handle.write("\n")
                handle.write(block)
            return True
        except OSError as exc:
            self.log(f"Falha ao atualizar autoexec.cfg: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # MÓDULO: REDE
    # ------------------------------------------------------------------ #

    def optimize_network(self, deep=False):
        results = []
        ok, _ = run_hidden("ipconfig /flushdns")
        results.append(("Cache DNS limpo", ok))

        ok, _ = run_hidden("ipconfig /registerdns")
        results.append(("DNS registrado novamente", ok))

        if deep:
            ok, _ = run_hidden("netsh winsock reset")
            results.append(("Winsock resetado (requer reinício)", ok))
            ok, _ = run_hidden("netsh int ip reset")
            results.append(("Pilha TCP/IP resetada (requer reinício)", ok))

        for label, success in results:
            self.log(f"{'✔️' if success else '❌'} {label}")
        return any(success for _, success in results)

    # ------------------------------------------------------------------ #
    # MÓDULO: LIMPEZA DE TEMP
    # ------------------------------------------------------------------ #

    def clean_temp_files(self):
        temp_dir = os.environ.get("TEMP") or os.environ.get("TMP")
        if not temp_dir or not os.path.isdir(temp_dir):
            self.log("❌ Pasta %temp% não encontrada.")
            return None

        temp_dir = os.path.normpath(temp_dir)
        # Trava de segurança: nunca operar na raiz de um disco.
        drive, tail = os.path.splitdrive(temp_dir)
        if tail.strip("\\/") == "":
            self.log("❌ Caminho de %temp% inseguro. Limpeza abortada.")
            return None

        freed, removed, skipped = 0, 0, 0
        try:
            entries = list(os.scandir(temp_dir))
        except OSError as exc:
            self.log(f"❌ Não foi possível ler %temp%: {exc}")
            return None

        for entry in entries:
            try:
                if entry.is_file() or entry.is_symlink():
                    size = entry.stat().st_size
                    os.remove(entry.path)
                    freed += size
                    removed += 1
                elif entry.is_dir():
                    size = self._folder_size(entry.path)
                    shutil.rmtree(entry.path)
                    freed += size
                    removed += 1
            except (OSError, PermissionError):
                skipped += 1  # arquivo em uso: ignorar é o comportamento seguro

        mb = freed / (1024 * 1024)
        self.log(f"✔️ Temp: {removed} itens removidos ({mb:.1f} MB), {skipped} em uso.")
        return mb

    @staticmethod
    def _folder_size(path):
        total = 0
        for root, _, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
        return total

    # ------------------------------------------------------------------ #
    # MÓDULO: ENERGIA
    # ------------------------------------------------------------------ #

    def _rank_power_plans(self):
        """Lista os planos disponíveis ordenados por potencial de desempenho.

        O critério é o estado mínimo do processador (PROCTHROTTLEMIN): quanto
        maior, menos a CPU reduz frequência durante a partida. Isso evita
        depender do nome do plano, que muda conforme o idioma do Windows.
        """
        plans = diag.list_power_plans()
        ranked = []
        for plan in plans:
            state = diag.min_processor_state(plan["guid"])
            ranked.append({**plan, "min_state": state if state is not None else -1})
        ranked.sort(key=lambda item: item["min_state"], reverse=True)
        return ranked

    def apply_power_plan(self):
        """Ativa o plano de maior desempenho disponível nesta máquina."""
        ranked = self._rank_power_plans()
        if not ranked:
            self.log("❌ Não foi possível listar os planos de energia.")
            return False, "Não foi possível listar os planos de energia"

        active = next((p for p in ranked if p["active"]), None)
        if active:
            # Guarda o plano do usuário para que a restauração devolva
            # exatamente o que ele tinha, e não um padrão genérico.
            self.previous_power_guid = active["guid"]
            self.save_settings()

        best = ranked[0]
        if active and best["guid"] == active["guid"]:
            self.log(f"✔️ Plano de energia já ideal: {best['name']}.")
            return True, f"Plano de energia já ideal ({best['name']})"

        ok, _ = run_hidden(f"powercfg /setactive {best['guid']}")
        if ok:
            self.log(f"✔️ Plano de energia alterado para {best['name']}.")
            return True, f"Plano de energia: {best['name']}"

        self.log("❌ Falha ao alterar o plano de energia.")
        return False, "Falha ao alterar o plano de energia"

    def restore_power_plan(self):
        """Devolve o plano que estava ativo antes do boost."""
        plans = diag.list_power_plans()
        if not plans:
            return False, "Não foi possível listar os planos de energia"

        available = {plan["guid"]: plan for plan in plans}
        target = None

        if self.previous_power_guid and self.previous_power_guid in available:
            target = available[self.previous_power_guid]
        elif GUID_BALANCED in available:
            target = available[GUID_BALANCED]
        else:
            # Sem histórico e sem o Equilibrado padrão: usa o plano de menor
            # estado mínimo de processador, que é o mais conservador presente.
            ranked = self._rank_power_plans()
            target = ranked[-1] if ranked else None

        if not target:
            return False, "Nenhum plano de energia adequado encontrado"

        if target["active"]:
            return True, f"Plano de energia já em {target['name']}"

        ok, _ = run_hidden(f"powercfg /setactive {target['guid']}")
        if ok:
            self.previous_power_guid = None
            self.save_settings()
            self.log(f"✔️ Plano de energia restaurado para {target['name']}.")
            return True, f"Plano de energia restaurado ({target['name']})"

        return False, "Falha ao restaurar o plano de energia"

    # ------------------------------------------------------------------ #
    # AÇÃO: BOOST
    # ------------------------------------------------------------------ #

    def apply_optimizations(self):
        if self.busy:
            return
        if not self.var_terms.get():
            messagebox.showwarning("Aviso", "Aceite os Termos de Segurança.")
            return

        if (self.var_tracers.get() or self.var_subtick.get()) and not self.ensure_cs2_path():
            messagebox.showwarning("Aviso", "Pasta do CS2 não definida. CFG não aplicada.")
            return

        deep_network = False
        if self.var_network.get():
            deep_network = messagebox.askyesno(
                "Otimização de Rede",
                "Aplicar também o reset profundo (Winsock + TCP/IP)?\n\n"
                "Isso exige reiniciar o PC e pode desconectar VPNs.\n"
                "Escolha 'Não' para apenas limpar o cache DNS.",
            )

        if self.var_cleanup.get():
            confirm = messagebox.askyesno(
                "Limpeza de Temporários",
                "Arquivos da pasta %temp% serão apagados.\n"
                "Feche programas abertos antes de continuar.\n\nDeseja prosseguir?",
            )
            if not confirm:
                self.var_cleanup.set(False)

        self.save_settings()
        self._set_busy(True)
        self.log("--- Iniciando BOOST ---")
        threading.Thread(target=self._run_apply, args=(deep_network,), daemon=True).start()

    def _run_apply(self, deep_network):
        report = []
        try:
            # 1. CFG do jogo
            if self.cs2_cfg_path and (self.var_tracers.get() or self.var_subtick.get()):
                if self.apply_cfg_injection(restore=False):
                    report.append("✔️ CFG injetada no jogo (binds protegidos)")
                    self.log("✔️ CFG injetada com sucesso.")
                else:
                    report.append("❌ Falha ao injetar a CFG")

            # 2. CPU
            report.extend(self._tune_process(restore=False))

            # 3. Energia
            if self.var_power.get():
                ok, message = self.apply_power_plan()
                report.append(("✔️ " if ok else "❌ ") + message)

            # 4. Rede
            if self.var_network.get():
                if self.optimize_network(deep=deep_network):
                    report.append("✔️ Rede otimizada (DNS limpo)")
                    if deep_network:
                        report.append("⚠️ Reinicie o PC para concluir o reset de rede")
                else:
                    report.append("❌ Falha ao otimizar a rede")

            # 5. Limpeza
            if self.var_cleanup.get():
                freed = self.clean_temp_files()
                if freed is not None:
                    report.append(f"✔️ Temporários limpos ({freed:.1f} MB liberados)")
                else:
                    report.append("❌ Falha na limpeza de temporários")

        except Exception as exc:  # rede de segurança: a GUI nunca deve travar
            self.log(f"❌ Erro inesperado: {exc}")
            report.append(f"❌ Erro inesperado: {exc}")

        self.log("--- BOOST finalizado ---")
        self.after(0, self._finish, "ZK BOOST", ["Relatório de Injeção:", ""] + report)

    # ------------------------------------------------------------------ #
    # AÇÃO: RESTAURAR
    # ------------------------------------------------------------------ #

    def restore_defaults(self):
        if self.busy:
            return
        confirm = messagebox.askyesno(
            "Restaurar Padrões",
            "Isto irá desfazer as otimizações:\n\n"
            "• CS2 volta a usar todos os núcleos (incluindo o Core 0)\n"
            "• Prioridade do processo volta para Normal\n"
            "• CFG volta aos valores padrão (rastros habilitados)\n"
            "• Plano de energia volta para Equilibrado\n\n"
            "Deseja continuar?",
        )
        if not confirm:
            return

        self._set_busy(True)
        self.log("--- Restaurando padrões ---")
        threading.Thread(target=self._run_restore, daemon=True).start()

    def _run_restore(self):
        report = []
        try:
            # 1. CFG padrão
            if self.cs2_cfg_path and os.path.isdir(self.cs2_cfg_path):
                if self.apply_cfg_injection(restore=True):
                    report.append("✔️ CFG restaurada (rastros habilitados)")
                    report.append("ℹ️ Reinicie o CS2 para os valores padrão valerem")
                    self.log("✔️ zk_boost.cfg reescrito com os valores padrão.")
                else:
                    report.append("❌ Falha ao restaurar a CFG")
            else:
                report.append("⚠️ Pasta do CS2 não definida — CFG não alterada")

            # 2. CPU
            report.extend(self._tune_process(restore=True))

            # 3. Energia
            ok, message = self.restore_power_plan()
            report.append(("✔️ " if ok else "❌ ") + message)

        except Exception as exc:
            self.log(f"❌ Erro inesperado: {exc}")
            report.append(f"❌ Erro inesperado: {exc}")

        self.log("--- Restauração finalizada ---")
        self.after(0, self._finish, "ZK BOOST", ["Relatório de Restauração:", ""] + report)

    # ------------------------------------------------------------------ #
    # CPU (compartilhado entre boost e restore)
    # ------------------------------------------------------------------ #

    def _affinity_target(self):
        """Calcula quais processadores lógicos o CS2 deve usar.

        Com SMT/Hyper-Threading ativo, o núcleo físico 0 é composto por DOIS
        processadores lógicos (0 e 1). Remover apenas o 0 deixa o jogo rodando
        no mesmo núcleo físico que se queria isolar — a otimização vira placebo.

        Retorna (lista_alvo, lista_removida, smt_ativo).
        """
        logical = psutil.cpu_count(logical=True) or 1
        physical = psutil.cpu_count(logical=False) or logical
        smt = logical > physical

        excluded = [0, 1] if smt and logical > 2 else [0]
        target = [cpu for cpu in range(logical) if cpu not in excluded]

        # Nunca deixar o jogo com menos de dois processadores lógicos.
        if len(target) < 2:
            return None, excluded, smt
        return target, excluded, smt

    def _tune_process(self, restore=False):
        report = []
        wants_cpu = restore or self.var_affinity.get() or self.var_priority.get()
        if not wants_cpu:
            return report

        process = find_cs2_process()
        if process is None:
            self.log("⚠️ cs2.exe não está em execução.")
            report.append("⚠️ CS2 fechado — abra o jogo e aplique de novo para a CPU")
            return report

        try:
            if restore:
                process.cpu_affinity(list(range(psutil.cpu_count() or 1)))
                report.append("✔️ Afinidade restaurada (todos os núcleos)")
                self.log("✔️ Afinidade restaurada.")
                if IS_WINDOWS:
                    process.nice(psutil.NORMAL_PRIORITY_CLASS)
                    report.append("✔️ Prioridade restaurada para Normal")
                    self.log("✔️ Prioridade Normal restaurada.")
                return report

            if self.var_affinity.get():
                target, excluded, smt = self._affinity_target()
                if target is None:
                    report.append("⚠️ CPU com poucos núcleos — afinidade ignorada")
                else:
                    process.cpu_affinity(target)
                    label = (
                        f"✔️ Core 0 isolado (CPUs {', '.join(map(str, excluded))} removidas)"
                    )
                    if smt:
                        label += " — SMT detectado"
                    report.append(label)
                    self.log(label.replace("✔️ ", ""))

            if self.var_priority.get() and IS_WINDOWS:
                process.nice(psutil.HIGH_PRIORITY_CLASS)
                report.append("✔️ Prioridade Alta aplicada")
                self.log("✔️ Prioridade Alta aplicada.")

        except psutil.AccessDenied:
            self.log("❌ Acesso negado ao processo cs2.exe.")
            report.append("❌ Acesso negado — execute o ZK Boost como Administrador")
        except psutil.NoSuchProcess:
            report.append("⚠️ O CS2 foi fechado durante a operação")
        except (OSError, ValueError) as exc:
            self.log(f"❌ Erro ao ajustar a CPU: {exc}")
            report.append(f"❌ Erro ao ajustar a CPU: {exc}")

        return report


# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    app = ZKBoostApp()
    app.mainloop()
