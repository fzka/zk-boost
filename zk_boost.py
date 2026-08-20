# -*- coding: utf-8 -*-
"""
ZK Boost — Otimizador para Counter-Strike 2
--------------------------------------------
Interface. Toda a lógica de sistema vive em zk_core.py.

Build:
    pyinstaller --noconfirm --onedir --windowed --uac-admin --name "ZK-Boost" \
        --version-file version_info.txt --collect-all customtkinter zk_boost.py
"""

import os
import threading
from tkinter import filedialog

import customtkinter as ctk
import psutil

import zk_core as core
import zk_theme as t
from zk_ui_diagnostics import DiagnosticsPanel

ctk.set_appearance_mode("dark")

APP_VERSION = core.APP_VERSION


class ResultDialog(ctk.CTkToplevel):
    """Relatório de uma operação: uma linha por Result, com ícone colorido.

    Segue o mesmo padrão visual dos cards do diagnóstico — status como cor
    de fato importa, texto corrido de OK/X era ilegível em execução real.
    """

    def __init__(self, parent, title, results):
        super().__init__(parent)
        self.configure(fg_color=t.INK)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)

        wrapper = ctk.CTkFrame(self, fg_color=t.SURFACE, corner_radius=10)
        wrapper.pack(fill="both", expand=True, padx=1, pady=1)

        # Cabeçalho
        header = ctk.CTkFrame(wrapper, fg_color="transparent")
        header.pack(fill="x", padx=26, pady=(22, 6))

        ok_count = sum(1 for r in results if r.ok)
        eyebrow = f"{ok_count} de {len(results)} concluídos"
        accent = t.VERIFIED if ok_count == len(results) else t.SIGNAL

        ctk.CTkLabel(header, text=eyebrow.upper(), anchor="w",
                     font=t.font(10, "bold"), text_color=accent
                     ).pack(fill="x")

        ctk.CTkLabel(header, text=title, anchor="w",
                     font=t.display(18), text_color=t.TEXT
                     ).pack(fill="x", pady=(2, 0))

        # Lista de resultados
        list_box = ctk.CTkFrame(wrapper, fg_color="transparent")
        list_box.pack(fill="both", expand=True, padx=26, pady=(14, 4))

        for result in results:
            self._render_row(list_box, result)

        # Rodapé
        footer = ctk.CTkFrame(wrapper, fg_color="transparent")
        footer.pack(fill="x", padx=26, pady=(10, 20))
        t.primary_button(footer, "Fechar", self.destroy, width=110
                         ).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Return>", lambda e: self.destroy())
        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()
        self._center_over(parent)
        self.grab_set()
        self.focus_force()

    def _render_row(self, parent, result):
        if result.ok:
            color, glyph = t.VERIFIED, "✓"
        elif result.needs_admin:
            color, glyph = t.SIGNAL, "!"
        else:
            color, glyph = t.DANGER, "×"

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=6)

        ctk.CTkLabel(row, text=glyph, width=22, anchor="n",
                     font=t.font(14, "bold"), text_color=color
                     ).pack(side="left", padx=(0, 10))

        text = ctk.CTkFrame(row, fg_color="transparent")
        text.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(text, text=result.message, anchor="w", justify="left",
                     font=t.font(12, "bold"), text_color=t.TEXT,
                     wraplength=420).pack(fill="x")

        if result.detail:
            ctk.CTkLabel(text, text=result.detail, anchor="w", justify="left",
                         font=t.font(11), text_color=t.TEXT_MUTED,
                         wraplength=420).pack(fill="x", pady=(1, 0))

    def _center_over(self, parent):
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        try:
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            x = px + (pw - width) // 2
            y = py + (ph - height) // 2
        except Exception:
            x = (self.winfo_screenwidth() - width) // 2
            y = (self.winfo_screenheight() - height) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")


class ZKBoostApp(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.title(f"ZK Boost {APP_VERSION}")
        self.geometry("1060x680")
        self.minsize(940, 620)
        self.configure(fg_color=t.INK)

        t.init_fonts(self)

        self.busy = False
        self.is_admin = core.is_admin()
        self.pages = {}
        self.nav_buttons = {}
        self.action_buttons = []

        self._load_state()
        self._build_layout()
        self._build_pages()
        self.show_page("painel")

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._tick_monitor()

    # ------------------------------------------------------------------ #
    # ESTADO
    # ------------------------------------------------------------------ #

    def _load_state(self):
        data = core.load_settings()

        def flag(key, default=True):
            value = data.get(key)
            return ctk.BooleanVar(value=value if isinstance(value, bool) else default)

        self.var_affinity = flag("affinity")
        self.var_priority = flag("priority")
        self.var_power = flag("power", False)
        self.var_gamedvr = flag("gamedvr", False)
        self.var_tracers = flag("tracers")
        self.var_subtick = flag("subtick")

        self.var_temp = flag("clean_temp", True)
        self.var_prefetch = flag("clean_prefetch", False)
        self.var_wupdate = flag("clean_wupdate", False)
        self.var_thumbs = flag("clean_thumbs", False)
        self.var_dns = flag("clean_dns", False)

        self.previous_power_guid = data.get("previous_power_guid") or None

        saved = data.get("cs2_cfg_path", "")
        if saved and os.path.isdir(saved):
            self.cs2_cfg_path = saved
        else:
            self.cs2_cfg_path = core.detect_cs2_cfg_path()

    def _state_map(self):
        return {
            "affinity": self.var_affinity, "priority": self.var_priority,
            "power": self.var_power, "gamedvr": self.var_gamedvr,
            "tracers": self.var_tracers, "subtick": self.var_subtick,
            "clean_temp": self.var_temp, "clean_prefetch": self.var_prefetch,
            "clean_wupdate": self.var_wupdate, "clean_thumbs": self.var_thumbs,
            "clean_dns": self.var_dns,
        }

    def save_state(self):
        data = {key: var.get() for key, var in self._state_map().items()}
        data["cs2_cfg_path"] = self.cs2_cfg_path or ""
        data["previous_power_guid"] = self.previous_power_guid or ""
        core.save_settings(data)

    def on_close(self):
        self.save_state()
        self.destroy()

    # ------------------------------------------------------------------ #
    # ESTRUTURA
    # ------------------------------------------------------------------ #

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Barra lateral ---
        sidebar = ctk.CTkFrame(self, fg_color=t.SURFACE, corner_radius=0, width=212)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(1, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(24, 18))
        ctk.CTkLabel(brand, text="ZK BOOST", anchor="w", font=t.display(20),
                     text_color=t.TEXT).pack(fill="x")
        ctk.CTkLabel(brand, text=f"versão {APP_VERSION}", anchor="w",
                     font=t.font(10), text_color=t.TEXT_FAINT).pack(fill="x")

        nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="new", padx=12)

        for key, label in (
            ("painel", "Painel"),
            ("diagnostico", "Diagnóstico"),
            ("otimizacoes", "Otimizações"),
            ("limpeza", "Limpeza"),
            ("restauracao", "Restauração"),
            ("config", "Configurações"),
        ):
            button = ctk.CTkButton(
                nav, text=label, anchor="w", height=38, corner_radius=8,
                font=t.font(13), fg_color="transparent", text_color=t.TEXT_MUTED,
                hover_color=t.RAISED, command=lambda k=key: self.show_page(k),
            )
            button.pack(fill="x", pady=2)
            self.nav_buttons[key] = button

        # --- Assinatura: leitura ao vivo do sistema ---
        # Um app que se apresenta como medidor honesto deve estar sempre
        # medindo algo à vista do usuário.
        monitor = ctk.CTkFrame(sidebar, fg_color=t.RAISED, corner_radius=8)
        monitor.grid(row=2, column=0, sticky="ew", padx=12, pady=16)

        ctk.CTkLabel(monitor, text="AGORA", anchor="w", font=t.font(9, "bold"),
                     text_color=t.TEXT_FAINT).pack(fill="x", padx=12, pady=(10, 3))
        self.monitor_cpu = ctk.CTkLabel(monitor, text="CPU   --%", anchor="w",
                                        font=t.mono(11), text_color=t.TEXT_MUTED)
        self.monitor_cpu.pack(fill="x", padx=12)
        self.monitor_ram = ctk.CTkLabel(monitor, text="RAM   --%", anchor="w",
                                        font=t.mono(11), text_color=t.TEXT_MUTED)
        self.monitor_ram.pack(fill="x", padx=12)
        self.monitor_cs2 = ctk.CTkLabel(monitor, text="CS2   fechado", anchor="w",
                                        font=t.mono(11), text_color=t.TEXT_FAINT)
        self.monitor_cs2.pack(fill="x", padx=12, pady=(0, 10))

        # --- Área de conteúdo ---
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=24, pady=20)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

    def _new_page(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        return page

    def show_page(self, key):
        for name, button in self.nav_buttons.items():
            active = name == key
            button.configure(
                fg_color=t.RAISED if active else "transparent",
                text_color=t.SIGNAL if active else t.TEXT_MUTED,
                font=t.font(13, "bold" if active else "normal"),
            )
        page = self.pages.get(key)
        if page is not None:
            page.tkraise()

    # ------------------------------------------------------------------ #
    # PÁGINAS
    # ------------------------------------------------------------------ #

    def _build_pages(self):
        self._page_painel()
        self._page_diagnostico()
        self._page_otimizacoes()
        self._page_limpeza()
        self._page_restauracao()
        self._page_config()

    # ---------------------------- PAINEL ------------------------------ #

    def _page_painel(self):
        page = self._new_page()
        self.pages["painel"] = page

        t.PageHeader(page, "Painel", "Pronto para otimizar.",
                     eyebrow="Visão geral").grid(row=0, column=0, sticky="ew")

        body = ctk.CTkFrame(page, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        if not self.is_admin:
            banner = ctk.CTkFrame(body, fg_color=t.SURFACE, corner_radius=10,
                                  border_width=1, border_color=t.SIGNAL_DIM)
            banner.grid(row=0, column=0, sticky="ew", pady=(0, 12))
            banner.grid_columnconfigure(0, weight=1)

            texto = ctk.CTkFrame(banner, fg_color="transparent")
            texto.grid(row=0, column=0, sticky="ew", padx=18, pady=14)
            ctk.CTkLabel(texto, text="Sem privilégios de Administrador",
                         anchor="w", font=t.font(13, "bold"),
                         text_color=t.SIGNAL).pack(fill="x")
            ctk.CTkLabel(texto,
                         text="Ajustes de CPU, energia e limpeza do sistema "
                              "serão ignorados.",
                         anchor="w", font=t.font(11),
                         text_color=t.TEXT_MUTED).pack(fill="x")
            t.ghost_button(banner, "Reiniciar elevado", self.restart_elevated,
                           width=160).grid(row=0, column=1, padx=(0, 18))

        console_card = ctk.CTkFrame(body, fg_color=t.SURFACE, corner_radius=10)
        console_card.grid(row=1, column=0, sticky="nsew")
        console_card.grid_columnconfigure(0, weight=1)
        console_card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(console_card, text="REGISTRO", anchor="w",
                     font=t.font(10, "bold"), text_color=t.TEXT_FAINT
                     ).grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))

        self.log_box = ctk.CTkTextbox(
            console_card, fg_color=t.INK, corner_radius=8, font=t.mono(11),
            state="disabled", wrap="word", text_color=t.TEXT_MUTED,
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))

        actions = ctk.CTkFrame(page, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        actions.grid_columnconfigure(0, weight=1)
        button = t.primary_button(actions, "Otimizar agora", self.apply_all,
                                  width=200)
        button.grid(row=0, column=1)
        self.action_buttons.append(button)

        self.log("ZK Boost pronto.")
        if self.cs2_cfg_path:
            self.log(f"Pasta CFG: {self.cs2_cfg_path}")
        else:
            self.log("Pasta CFG do CS2 não localizada — defina em Configurações.")
        if not self.is_admin:
            self.log("Executando sem privilégios de Administrador.")

    # -------------------------- DIAGNÓSTICO --------------------------- #

    def _page_diagnostico(self):
        page = self._new_page()
        self.pages["diagnostico"] = page

        t.PageHeader(page, "Diagnóstico",
                     "Leitura do sistema. Nada é alterado nesta tela.",
                     eyebrow="Análise").grid(row=0, column=0, sticky="ew")

        panel = DiagnosticsPanel(page, on_log=self.log)
        panel.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        self.diagnostics_panel = panel

    # -------------------------- OTIMIZAÇÕES --------------------------- #

    def _page_otimizacoes(self):
        page = self._new_page()
        self.pages["otimizacoes"] = page

        t.PageHeader(page, "Otimizações",
                     "Escolha o que aplicar. Tudo é reversível.",
                     eyebrow="Desempenho").grid(row=0, column=0, sticky="ew")

        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew", pady=(14, 0))

        self._group_label(scroll, "Sistema")
        sistema = t.Card(scroll)
        sistema.pack(fill="x", pady=(0, 18))
        sistema.add_option(
            "Isolar o núcleo 0",
            "Remove do jogo o núcleo que o Windows mais usa para interrupções. "
            "Detecta SMT e remove o par correto.",
            self.var_affinity)
        sistema.add_option(
            "Prioridade alta para o CS2",
            "O Windows passa a atender o jogo antes dos demais processos.",
            self.var_priority)
        sistema.add_option(
            "Plano de energia máximo",
            "Impede que a CPU reduza a frequência durante a partida.",
            self.var_power)
        sistema.add_option(
            "Desativar gravação em segundo plano",
            "O Game DVR grava continuamente usando CPU e o encoder da GPU.",
            self.var_gamedvr)

        self._group_label(scroll, "Jogo")
        jogo = t.Card(scroll)
        jogo.pack(fill="x")
        jogo.add_option(
            "Remover rastros de tiro em 1ª pessoa",
            "Menos partículas na tela ao atirar. Exige reabrir o CS2.",
            self.var_tracers)
        jogo.add_option(
            "Suavização de sub-ticks",
            "Ajusta o buffer de rede e a espera de baixa latência do cliente.",
            self.var_subtick)

        actions = ctk.CTkFrame(page, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        actions.grid_columnconfigure(0, weight=1)
        button = t.primary_button(actions, "Aplicar otimizações",
                                  self.apply_all, width=200)
        button.grid(row=0, column=1)
        self.action_buttons.append(button)

    # ---------------------------- LIMPEZA ----------------------------- #

    def _page_limpeza(self):
        page = self._new_page()
        self.pages["limpeza"] = page

        t.PageHeader(
            page, "Limpeza",
            "Higiene do sistema. Libera espaço em disco, não aumenta FPS.",
            eyebrow="Manutenção").grid(row=0, column=0, sticky="ew")

        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew", pady=(14, 0))

        card = t.Card(scroll)
        card.pack(fill="x")
        card.add_option(
            "Arquivos temporários",
            "Conteúdo da pasta %temp%. Arquivos em uso são preservados.",
            self.var_temp)
        card.add_option(
            "Cache do Windows Update",
            "Instaladores já aplicados. Costuma liberar bastante espaço.",
            self.var_wupdate)
        card.add_option(
            "Cache de miniaturas",
            "Miniaturas do Explorador de Arquivos. São recriadas com o uso.",
            self.var_thumbs)
        card.add_option(
            "Arquivos Prefetch",
            "O Windows usa estes arquivos para abrir programas mais rápido e "
            "os recria sozinho. Limpar não melhora o desempenho.",
            self.var_prefetch)
        card.add_option(
            "Cache DNS",
            "Limpa a resolução de nomes guardada pelo sistema.",
            self.var_dns)

        actions = ctk.CTkFrame(page, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        actions.grid_columnconfigure(0, weight=1)
        button = t.primary_button(actions, "Limpar selecionados",
                                  self.run_cleanup, width=200)
        button.grid(row=0, column=1)
        self.action_buttons.append(button)

    # -------------------------- RESTAURAÇÃO --------------------------- #

    def _page_restauracao(self):
        page = self._new_page()
        self.pages["restauracao"] = page

        t.PageHeader(page, "Restauração",
                     "Desfaz as otimizações aplicadas pelo ZK Boost.",
                     eyebrow="Reverter").grid(row=0, column=0, sticky="ew")

        body = ctk.CTkFrame(page, fg_color=t.SURFACE, corner_radius=10)
        body.grid(row=1, column=0, sticky="new", pady=(14, 0))
        body.grid_columnconfigure(0, weight=1)

        texto = (
            "A restauração devolve o sistema ao estado anterior:\n\n"
            "    O CS2 volta a usar todos os núcleos\n"
            "    A prioridade do processo volta para Normal\n"
            "    O plano de energia volta a ser o que você usava antes\n"
            "    A gravação em segundo plano é reativada\n"
            "    A CFG volta aos valores padrão do jogo\n\n"
            "Arquivos apagados na Limpeza não são recuperados."
        )
        ctk.CTkLabel(body, text=texto, anchor="w", justify="left",
                     font=t.font(12), text_color=t.TEXT_MUTED
                     ).grid(row=0, column=0, sticky="ew", padx=20, pady=20)

        actions = ctk.CTkFrame(page, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        actions.grid_columnconfigure(0, weight=1)
        button = t.ghost_button(actions, "Restaurar padrões", self.restore_all,
                                width=200, danger=True)
        button.grid(row=0, column=1)
        self.action_buttons.append(button)

    # ------------------------- CONFIGURAÇÕES -------------------------- #

    def _page_config(self):
        page = self._new_page()
        self.pages["config"] = page

        t.PageHeader(page, "Configurações", "Caminhos e informações do app.",
                     eyebrow="Ajustes").grid(row=0, column=0, sticky="ew")

        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew", pady=(14, 0))

        self._group_label(scroll, "Counter-Strike 2")
        card = ctk.CTkFrame(scroll, fg_color=t.SURFACE, corner_radius=10)
        card.pack(fill="x", pady=(0, 18))
        card.grid_columnconfigure(0, weight=1)

        box = ctk.CTkFrame(card, fg_color="transparent")
        box.grid(row=0, column=0, sticky="ew", padx=18, pady=14)
        ctk.CTkLabel(box, text="Pasta de configuração", anchor="w",
                     font=t.font(13, "bold"), text_color=t.TEXT).pack(fill="x")
        self.path_label = ctk.CTkLabel(
            box, text=self.cs2_cfg_path or "Não localizada", anchor="w",
            justify="left", font=t.mono(10), text_color=t.TEXT_MUTED,
            wraplength=520)
        self.path_label.pack(fill="x", pady=(2, 0))

        t.ghost_button(card, "Alterar", self.choose_cs2_path, width=110
                       ).grid(row=0, column=1, padx=(0, 18))

        self._group_label(scroll, "Sobre")
        about = ctk.CTkFrame(scroll, fg_color=t.SURFACE, corner_radius=10)
        about.pack(fill="x")
        texto = (
            f"ZK Boost {APP_VERSION} · código aberto sob licença MIT\n"
            "github.com/fzka/zk-boost\n\n"
            "Nada é injetado na memória do jogo. O app usa apenas a API oficial "
            "do Windows, comandos nativos do sistema e escrita de arquivos .cfg — "
            "o mesmo que qualquer configuração feita à mão.\n\n"
            f"Privilégios: {'Administrador' if self.is_admin else 'usuário comum'}"
        )
        ctk.CTkLabel(about, text=texto, anchor="w", justify="left",
                     font=t.font(11), text_color=t.TEXT_MUTED, wraplength=600
                     ).pack(fill="x", padx=20, pady=18)

    def _group_label(self, parent, text):
        ctk.CTkLabel(parent, text=text.upper(), anchor="w",
                     font=t.font(10, "bold"), text_color=t.TEXT_FAINT
                     ).pack(fill="x", pady=(2, 6))

    # ------------------------------------------------------------------ #
    # MONITOR AO VIVO
    # ------------------------------------------------------------------ #

    def _tick_monitor(self):
        try:
            cpu = psutil.cpu_percent(None)
            ram = psutil.virtual_memory().percent
            self.monitor_cpu.configure(text=f"CPU  {cpu:5.0f}%")
            self.monitor_ram.configure(text=f"RAM  {ram:5.0f}%")

            if core.find_cs2_process():
                self.monitor_cs2.configure(text="CS2  em execução",
                                           text_color=t.VERIFIED)
            else:
                self.monitor_cs2.configure(text="CS2  fechado",
                                           text_color=t.TEXT_FAINT)
        except Exception:
            pass
        self.after(2000, self._tick_monitor)

    # ------------------------------------------------------------------ #
    # LOG E ESTADO
    # ------------------------------------------------------------------ #

    def log(self, message):
        self.after(0, self._append_log, message)

    def _append_log(self, message):
        try:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", f"{message}\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        except Exception:
            pass

    def _set_busy(self, busy):
        self.busy = busy
        for button in self.action_buttons:
            button.configure(state="disabled" if busy else "normal")

    def _report(self, title, results):
        self._set_busy(False)
        if not results:
            t.show_info(self, title, "Nada a fazer.")
            return

        dialog = ResultDialog(self, title, results)
        self.wait_window(dialog)

    def restart_elevated(self):
        self.save_state()
        if core.relaunch_as_admin():
            self.destroy()
        else:
            t.show_warning(self, "Elevação recusada",
                           "Feche o ZK Boost e abra novamente com o botão "
                           "direito → 'Executar como administrador'.")

    def choose_cs2_path(self):
        folder = filedialog.askdirectory(
            title="Selecione a pasta .../game/csgo/cfg")
        if folder and os.path.isdir(folder):
            self.cs2_cfg_path = os.path.normpath(folder)
            self.path_label.configure(text=self.cs2_cfg_path)
            self.save_state()
            self.log(f"Pasta CFG definida: {self.cs2_cfg_path}")

    # ------------------------------------------------------------------ #
    # AÇÕES
    # ------------------------------------------------------------------ #

    def apply_all(self):
        if self.busy:
            return
        if (self.var_tracers.get() or self.var_subtick.get()) and not self.cs2_cfg_path:
            t.show_warning(self, "Pasta do CS2 não definida",
                           "Defina a pasta de configuração do jogo em "
                           "Configurações para aplicar as otimizações de CFG.")
            return

        self.save_state()
        self._set_busy(True)
        self.show_page("painel")
        self.log("")
        self.log("— aplicando otimizações —")
        threading.Thread(target=self._worker_apply, daemon=True).start()

    def _worker_apply(self):
        results = []

        if self.var_tracers.get() or self.var_subtick.get():
            results.append(core.apply_game_config(
                self.cs2_cfg_path, self.var_tracers.get(), self.var_subtick.get()))

        if self.var_affinity.get() or self.var_priority.get():
            results.extend(core.tune_process(
                self.var_affinity.get(), self.var_priority.get()))

        if self.var_power.get():
            results.append(core.apply_power_plan(self._remember_power_guid))

        if self.var_gamedvr.get():
            results.append(core.set_game_dvr(False))

        for result in results:
            self.log(("OK  " if result.ok else "X   ") + result.message)

        self.after(0, self._report, "Otimizações aplicadas", results)

    def _remember_power_guid(self, guid):
        self.previous_power_guid = guid
        self.save_state()

    def run_cleanup(self):
        if self.busy:
            return
        if not any(var.get() for var in (self.var_temp, self.var_prefetch,
                                         self.var_wupdate, self.var_thumbs,
                                         self.var_dns)):
            t.show_info(self, "Limpeza", "Selecione ao menos um item para limpar.")
            return

        if not t.ask_confirm(
                self, "Confirmar limpeza",
                "Os arquivos selecionados serão apagados permanentemente. "
                "Feche outros programas para que mais arquivos em uso "
                "possam ser liberados.",
                confirm_text="Limpar", cancel_text="Cancelar"):
            return

        self.save_state()
        self._set_busy(True)
        self.show_page("painel")
        self.log("")
        self.log("— limpando —")
        threading.Thread(target=self._worker_cleanup, daemon=True).start()

    def _worker_cleanup(self):
        results = []
        tasks = [
            (self.var_temp, core.clean_temp),
            (self.var_wupdate, core.clean_windows_update_cache),
            (self.var_thumbs, core.clean_thumbnails),
            (self.var_prefetch, core.clean_prefetch),
            (self.var_dns, core.flush_dns),
        ]
        for var, function in tasks:
            if not var.get():
                continue
            result = function()
            results.append(result)
            self.log(("OK  " if result.ok else "X   ") + result.message)

        total = sum(result.data.get("mb", 0) for result in results)
        if total >= 1:
            results.append(core.Result(True, f"Total liberado: {total:.0f} MB"))

        self.after(0, self._report, "Limpeza concluída", results)

    def restore_all(self):
        if self.busy:
            return
        if not t.ask_confirm(
                self, "Restaurar padrões",
                "Todas as otimizações aplicadas pelo ZK Boost serão desfeitas.",
                confirm_text="Restaurar", cancel_text="Cancelar"):
            return

        self._set_busy(True)
        self.show_page("painel")
        self.log("")
        self.log("— restaurando padrões —")
        threading.Thread(target=self._worker_restore, daemon=True).start()

    def _worker_restore(self):
        results = []

        if self.cs2_cfg_path:
            results.append(core.apply_game_config(self.cs2_cfg_path, restore=True))

        results.extend(core.tune_process(restore=True))
        results.append(core.restore_power_plan(self.previous_power_guid))
        results.append(core.set_game_dvr(True))

        self.previous_power_guid = None
        self.save_state()

        for result in results:
            self.log(("OK  " if result.ok else "X   ") + result.message)

        self.after(0, self._report, "Restauração concluída", results)


if __name__ == "__main__":
    app = ZKBoostApp()
    app.mainloop()