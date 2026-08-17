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

import zk_diagnostics as diag

# Paleta por status. O cinza do INFO é proposital: só o que exige atenção
# recebe cor, senão a tela vira um mural de alertas e nada se destaca.
STATUS_STYLE = {
    diag.STATUS_OK: ("#3fb950", "✔"),
    diag.STATUS_WARN: ("#d29922", "!"),
    diag.STATUS_INFO: ("#8b949e", "i"),
    diag.STATUS_ERROR: ("#f85149", "×"),
}

COLOR_CARD = "#212121"
COLOR_MUTED = "#9a9a9a"


class DiagnosticsPanel(ctk.CTkFrame):
    """Aba de diagnóstico: escaneia o sistema e apresenta os achados."""

    def __init__(self, master, on_log=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        self.on_log = on_log or (lambda message: None)
        self.scanning = False
        self.findings = []

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
            header, text="Analisar PC", width=120, height=32, corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"), command=self.start_scan,
        )
        self.scan_button.grid(row=0, column=1, sticky="e", padx=(10, 0))

        self.progress = ctk.CTkProgressBar(header, height=4)
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
            wraplength=380, justify="left",
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
            self.results, text=message, text_color="#f85149",
            font=ctk.CTkFont(size=12), wraplength=380, justify="left",
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
        for finding in sorted(findings, key=lambda f: order.get(f.status, 9)):
            self._render_card(finding)

    def _render_card(self, finding):
        color, icon = STATUS_STYLE.get(finding.status, ("#8b949e", "?"))

        card = ctk.CTkFrame(self.results, fg_color=COLOR_CARD, corner_radius=8)
        card.pack(fill="x", pady=4)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card, text=icon, text_color=color, width=22,
            font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=0, column=0, sticky="nw", padx=(12, 0), pady=(10, 0))

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.grid(row=0, column=1, sticky="ew", padx=(4, 12), pady=(10, 10))
        content.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            content, text=finding.label, anchor="w", justify="left",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(fill="x")

        ctk.CTkLabel(
            content, text=finding.value, anchor="w", justify="left",
            text_color=color, font=ctk.CTkFont(size=12),
            wraplength=340,
        ).pack(fill="x")

        if finding.detail:
            ctk.CTkLabel(
                content, text=finding.detail, anchor="w", justify="left",
                text_color=COLOR_MUTED, font=ctk.CTkFont(size=11),
                wraplength=340,
            ).pack(fill="x", pady=(4, 0))

        if finding.recommendation:
            ctk.CTkLabel(
                content, text="→ " + finding.recommendation,
                anchor="w", justify="left", text_color="#d29922",
                font=ctk.CTkFont(size=11), wraplength=340,
            ).pack(fill="x", pady=(4, 0))
