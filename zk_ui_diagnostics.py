# -*- coding: utf-8 -*-
"""
ZK Boost — Painel de Diagnóstico
---------------------------------
Interface do módulo zk_diagnostics. Mantido separado da janela principal
para que a lógica de coleta e a apresentação evoluam de forma independente.

O scan roda em thread própria: nenhuma consulta ao WMI ou ao powercfg pode
congelar a janela.
"""

import threading

import customtkinter as ctk

import zk_actions as actions
import zk_core as core
import zk_diagnostics as diag
import zk_theme as theme

# Paleta por status. O cinza do INFO é proposital: só o que exige atenção
# recebe cor, senão a tela vira um mural de alertas e nada se destaca.
STATUS_STYLE = {
    diag.STATUS_OK: (theme.VERIFIED, "OK"),
    diag.STATUS_WARN: (theme.SIGNAL, "!"),
    diag.STATUS_INFO: (theme.TEXT_MUTED, "·"),
    diag.STATUS_ERROR: (theme.DANGER, "X"),
}

COLOR_CARD = theme.SURFACE
COLOR_MUTED = theme.TEXT_MUTED


class DiagnosticsPanel(ctk.CTkFrame):
    """Aba de diagnóstico: escaneia o sistema e apresenta os achados."""

    def __init__(self, master, on_log=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        self.on_log = on_log or (lambda message: None)
        self.scanning = False
        self.findings = []
        self.cards = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()

        self.results = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.results.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.results.grid_columnconfigure(0, weight=1)

        self._show_placeholder()

    # ------------------------------------------------------------------ #
    # CABEÇALHO
    # ------------------------------------------------------------------ #

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        self.summary_label = ctk.CTkLabel(
            header, text="Nenhuma análise executada ainda.",
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w", justify="left",
        )
        self.summary_label.grid(row=0, column=0, sticky="w")

        self.scan_button = ctk.CTkButton(
            header, text="Analisar PC", width=130, height=34, corner_radius=8,
            font=theme.font(12, "bold"), command=self.start_scan,
            fg_color=theme.SIGNAL, hover_color=theme.SIGNAL_HOVER,
            text_color=theme.INK,
        )
        self.scan_button.grid(row=0, column=1, sticky="e", padx=(10, 0))

        self.progress = ctk.CTkProgressBar(header, height=4, progress_color=theme.SIGNAL)
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.progress.set(0)

    def _show_placeholder(self):
        ctk.CTkLabel(
            self.results,
            text=(
                "O ZK Boost pode verificar o estado do seu PC antes de mudar "
                "qualquer coisa.\n\n"
                "A análise é somente leitura: nada é alterado, nada é enviado "
                "pela internet."
            ),
            font=ctk.CTkFont(size=12), text_color=COLOR_MUTED,
            wraplength=620, justify="left",
        ).pack(anchor="w", pady=20)

    # ------------------------------------------------------------------ #
    # EXECUÇÃO
    # ------------------------------------------------------------------ #

    def start_scan(self):
        if self.scanning:
            return
        self.scanning = True
        self.scan_button.configure(state="disabled", text="Analisando…")
        self.progress.set(0)
        self.summary_label.configure(text="Analisando o sistema…")

        for widget in self.results.winfo_children():
            widget.destroy()

        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        def progress(index, total, label):
            self.after(0, self._update_progress, index / total, label)

        try:
            findings = diag.run_diagnostics(progress=progress)
        except Exception as exc:
            self.after(0, self._scan_failed, str(exc))
            return
        self.after(0, self._render, findings)

    def _update_progress(self, ratio, label):
        self.progress.set(ratio)
        self.summary_label.configure(text=f"Analisando: {label}…")

    def _scan_failed(self, message):
        self.scanning = False
        self.scan_button.configure(state="normal", text="Analisar PC")
        self.progress.set(0)
        self.summary_label.configure(text="A análise falhou.")
        ctk.CTkLabel(
            self.results, text=message, text_color=theme.DANGER,
            font=ctk.CTkFont(size=12), wraplength=620, justify="left",
        ).pack(anchor="w", pady=10)

    # ------------------------------------------------------------------ #
    # RENDERIZAÇÃO
    # ------------------------------------------------------------------ #

    def _render(self, findings):
        self.findings = findings
        self.scanning = False
        self.scan_button.configure(state="normal", text="Analisar novamente")
        self.progress.set(1)

        counts = diag.summarize(findings)
        warnings = counts.get(diag.STATUS_WARN, 0)
        errors = counts.get(diag.STATUS_ERROR, 0)

        if warnings == 0 and errors == 0:
            summary = "Nenhum ponto de atenção encontrado."
        elif warnings == 1:
            summary = "1 ponto de atenção encontrado."
        else:
            summary = f"{warnings} pontos de atenção encontrados."
        self.summary_label.configure(text=summary)
        self.on_log(f"Diagnóstico concluído — {summary.lower()}")

        # Pontos de atenção primeiro: o usuário não deveria precisar rolar
        # para descobrir o que está errado.
        order = {
            diag.STATUS_WARN: 0,
            diag.STATUS_ERROR: 1,
            diag.STATUS_OK: 2,
            diag.STATUS_INFO: 3,
        }
        self.cards = {}
        for finding in sorted(findings, key=lambda f: order.get(f.status, 9)):
            self._render_card(finding)

    def _render_card(self, finding):
        """Desenha um card. Guarda a referência para poder reescrevê-lo
        depois de uma correção, sem exigir novo scan completo."""
        card = ctk.CTkFrame(self.results, fg_color=COLOR_CARD, corner_radius=8)
        card.pack(fill="x", pady=4)
        card.grid_columnconfigure(1, weight=1)
        self.cards[finding.key] = card
        self._fill_card(card, finding)

    def _fill_card(self, card, finding):
        for child in card.winfo_children():
            child.destroy()

        color, icon = STATUS_STYLE.get(finding.status, (theme.TEXT_MUTED, "?"))

        ctk.CTkLabel(
            card, text=icon, text_color=color, width=22,
            font=theme.font(14, "bold"),
        ).grid(row=0, column=0, sticky="nw", padx=(12, 0), pady=(12, 0))

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.grid(row=0, column=1, sticky="ew", padx=(4, 12), pady=(12, 12))
        content.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(content, text=finding.label, anchor="w", justify="left",
                     font=theme.font(12, "bold"), text_color=theme.TEXT
                     ).pack(fill="x")

        ctk.CTkLabel(content, text=finding.value, anchor="w", justify="left",
                     text_color=color, font=theme.font(12), wraplength=600
                     ).pack(fill="x")

        if finding.detail:
            ctk.CTkLabel(content, text=finding.detail, anchor="w",
                         justify="left", text_color=COLOR_MUTED,
                         font=theme.font(11), wraplength=600
                         ).pack(fill="x", pady=(4, 0))

        if finding.recommendation:
            ctk.CTkLabel(content, text="→ " + finding.recommendation,
                         anchor="w", justify="left", text_color=theme.SIGNAL,
                         font=theme.font(11), wraplength=600
                         ).pack(fill="x", pady=(4, 0))

        # Botão de correção, quando existe uma. Cards verdes não recebem
        # botão: oferecer "corrigir" no que está certo só confunde.
        action = actions.for_finding(finding)
        if action:
            button = ctk.CTkButton(
                card, text=action.label, width=130, height=30, corner_radius=6,
                font=theme.font(11, "bold"), fg_color="transparent",
                text_color=theme.SIGNAL, border_width=1,
                border_color=theme.SIGNAL_DIM, hover_color=theme.RAISED,
                command=lambda: self._run_action(finding, action),
            )
            button.grid(row=0, column=2, sticky="ne", padx=(0, 12), pady=12)

    # ------------------------------------------------------------------ #
    # CORREÇÕES
    # ------------------------------------------------------------------ #

    def _run_action(self, finding, action):
        """Executa a correção em thread e reescreve apenas o card afetado."""
        if action.needs_admin and not core.is_admin():
            theme.show_warning(
                self.winfo_toplevel(), "Requer Administrador",
                "Esta correção altera uma configuração protegida do Windows. "
                "Reinicie o ZK Boost como Administrador para aplicá-la.")
            return

        card = self.cards.get(finding.key)
        if card is None:
            return

        for child in card.winfo_children():
            if isinstance(child, ctk.CTkButton):
                child.configure(state="disabled", text="Aplicando...")

        threading.Thread(target=self._action_worker,
                         args=(finding, action), daemon=True).start()

    def _action_worker(self, finding, action):
        result = action.run()
        updated = None
        if result.ok and action.recheck:
            try:
                updated = action.recheck()
            except Exception:
                updated = None
        self.after(0, self._action_done, finding, result, updated)

    def _action_done(self, finding, result, updated):
        self.on_log(("OK  " if result.ok else "X   ") + result.message)

        card = self.cards.get(finding.key)
        if card is not None:
            self._fill_card(card, updated or finding)

        if result.ok and result.detail:
            theme.show_success(self.winfo_toplevel(), result.message,
                               result.detail)
        elif not result.ok:
            theme.show_warning(self.winfo_toplevel(), "Não foi possível aplicar",
                               result.detail or result.message)