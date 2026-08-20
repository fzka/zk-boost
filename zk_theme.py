# -*- coding: utf-8 -*-
"""
ZK Boost — Sistema de Design
-----------------------------
Tokens e componentes reutilizáveis. Nenhuma cor ou fonte deve ser escrita
diretamente nas telas: tudo vem daqui, para que a identidade mude num
lugar só.

DIREÇÃO VISUAL
A categoria inteira de otimizadores usa azul-marinho com ciano. O ZK Boost
usa grafite neutro com âmbar de sinalização — a cor de instrumento de
medição, não de promessa de FPS. Verde é reservado exclusivamente para
estados verificados como bons, então quando ele aparece, significa algo.
"""

import customtkinter as ctk

# --------------------------------------------------------------------------- #
# COR
# --------------------------------------------------------------------------- #

INK = "#0E0E10"        # fundo da janela
SURFACE = "#161618"    # barra lateral, cartões
RAISED = "#1E1E21"     # linhas de opção
HAIRLINE = "#2A2A2E"   # divisórias

SIGNAL = "#E8B44A"     # âmbar: acento primário, ação, atenção
SIGNAL_DIM = "#8A6A28"
SIGNAL_HOVER = "#F2C468"

VERIFIED = "#4ADE80"   # verde: apenas para o que foi confirmado bom
DANGER = "#F0656F"     # vermelho: destrutivo ou falha

TEXT = "#F0F0F2"
TEXT_MUTED = "#8A8A93"
TEXT_FAINT = "#5C5C64"

STATUS_COLORS = {
    "OK": VERIFIED,
    "WARN": SIGNAL,
    "INFO": TEXT_MUTED,
    "ERROR": DANGER,
}

# --------------------------------------------------------------------------- #
# TIPOGRAFIA
# --------------------------------------------------------------------------- #
# Bahnschrift é a condensada técnica que acompanha o Windows 10/11 — parente
# do DIN usado em instrumentação. Evita o Segoe padrão sem exigir instalação.

_FAMILIES = {"display": "Segoe UI", "body": "Segoe UI", "mono": "Consolas"}


def init_fonts(root):
    """Escolhe as famílias disponíveis. Chamar depois de criar a janela."""
    try:
        import tkinter.font as tkfont
        available = {name.lower() for name in tkfont.families(root)}
    except Exception:
        return

    for role, candidates in (
        ("display", ["Bahnschrift SemiBold", "Bahnschrift", "Segoe UI Semibold"]),
        ("body", ["Segoe UI Variable Text", "Segoe UI"]),
        ("mono", ["Cascadia Mono", "Consolas"]),
    ):
        for candidate in candidates:
            if candidate.lower() in available:
                _FAMILIES[role] = candidate
                break


def font(size=13, weight="normal", role="body"):
    return ctk.CTkFont(family=_FAMILIES[role], size=size, weight=weight)


def display(size=22):
    return ctk.CTkFont(family=_FAMILIES["display"], size=size, weight="bold")


def mono(size=11):
    return ctk.CTkFont(family=_FAMILIES["mono"], size=size)


# --------------------------------------------------------------------------- #
# COMPONENTES
# --------------------------------------------------------------------------- #

class PageHeader(ctk.CTkFrame):
    """Cabeçalho de página: rótulo, título e linha de estado."""

    def __init__(self, master, title, subtitle="", eyebrow=""):
        super().__init__(master, fg_color=SURFACE, corner_radius=10)
        self.grid_columnconfigure(0, weight=1)

        box = ctk.CTkFrame(self, fg_color="transparent")
        box.grid(row=0, column=0, sticky="ew", padx=20, pady=16)
        box.grid_columnconfigure(0, weight=1)

        if eyebrow:
            ctk.CTkLabel(box, text=eyebrow.upper(), anchor="w",
                         font=font(10, "bold"), text_color=SIGNAL_DIM
                         ).pack(fill="x")

        ctk.CTkLabel(box, text=title, anchor="w", font=display(21),
                     text_color=TEXT).pack(fill="x")

        self.subtitle_label = ctk.CTkLabel(
            box, text=subtitle, anchor="w", justify="left",
            font=font(12), text_color=TEXT_MUTED,
        )
        self.subtitle_label.pack(fill="x", pady=(2, 0))

    def set_subtitle(self, text, color=TEXT_MUTED):
        self.subtitle_label.configure(text=text, text_color=color)


class OptionRow(ctk.CTkFrame):
    """Linha de opção: título e descrição à esquerda, controle à direita."""

    def __init__(self, master, title, description="", variable=None,
                 command=None, danger=False):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)

        text_box = ctk.CTkFrame(self, fg_color="transparent")
        text_box.grid(row=0, column=0, sticky="ew", padx=(18, 10), pady=13)
        text_box.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(text_box, text=title, anchor="w", font=font(13, "bold"),
                     text_color=DANGER if danger else TEXT).pack(fill="x")

        if description:
            ctk.CTkLabel(text_box, text=description, anchor="w", justify="left",
                         font=font(11), text_color=TEXT_MUTED,
                         wraplength=520).pack(fill="x", pady=(1, 0))

        self.switch = ctk.CTkSwitch(
            self, text="", variable=variable, command=command,
            width=44, switch_width=42, switch_height=22,
            progress_color=SIGNAL, button_color=TEXT,
            button_hover_color=TEXT, fg_color=HAIRLINE,
        )
        self.switch.grid(row=0, column=1, sticky="e", padx=(0, 18))


class Card(ctk.CTkFrame):
    """Contêiner de linhas, com divisórias entre elas."""

    def __init__(self, master):
        super().__init__(master, fg_color=SURFACE, corner_radius=10)
        self.grid_columnconfigure(0, weight=1)
        self._rows = 0

    def add(self, widget):
        if self._rows:
            divider = ctk.CTkFrame(self, height=1, fg_color=HAIRLINE)
            divider.grid(row=self._rows * 2 - 1, column=0, sticky="ew", padx=18)
        widget.grid(row=self._rows * 2, column=0, sticky="ew")
        self._rows += 1
        return widget

    def add_option(self, title, description="", variable=None, command=None,
                   danger=False):
        return self.add(OptionRow(self, title, description, variable,
                                  command, danger))


def primary_button(master, text, command, width=180):
    return ctk.CTkButton(
        master, text=text, command=command, width=width, height=40,
        corner_radius=8, font=font(13, "bold"),
        fg_color=SIGNAL, hover_color=SIGNAL_HOVER, text_color=INK,
    )


def ghost_button(master, text, command, width=150, danger=False):
    return ctk.CTkButton(
        master, text=text, command=command, width=width, height=38,
        corner_radius=8, font=font(12, "bold"),
        fg_color="transparent", text_color=DANGER if danger else TEXT,
        border_width=1, border_color=DANGER if danger else HAIRLINE,
        hover_color=RAISED,
    )


# --------------------------------------------------------------------------- #
# DIÁLOGO MODAL
# --------------------------------------------------------------------------- #

_INTENT_STYLE = {
    "info":    ("Informação", SIGNAL),
    "warning": ("Atenção",    SIGNAL),
    "confirm": ("Confirmar",  SIGNAL),
    "error":   ("Erro",       DANGER),
    "success": ("Concluído",  VERIFIED),
}


class Dialog(ctk.CTkToplevel):
    """Caixa de diálogo modal com a identidade do ZK Boost.

    Substitui tkinter.messagebox — a versão nativa quebra a coerência visual
    do app com título de sistema, fonte diferente e fundo cinza.
    """

    def __init__(self, parent, title, message, intent="info",
                 confirm_text="OK", cancel_text=None):
        super().__init__(parent)

        eyebrow, accent = _INTENT_STYLE.get(intent, _INTENT_STYLE["info"])

        self.result = False
        self.configure(fg_color=INK)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)

        # Container principal
        wrapper = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=10)
        wrapper.pack(fill="both", expand=True, padx=1, pady=1)

        body = ctk.CTkFrame(wrapper, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=26, pady=(22, 18))

        ctk.CTkLabel(body, text=eyebrow.upper(), anchor="w",
                     font=font(10, "bold"), text_color=accent
                     ).pack(fill="x")

        ctk.CTkLabel(body, text=title, anchor="w", justify="left",
                     font=display(18), text_color=TEXT
                     ).pack(fill="x", pady=(2, 10))

        ctk.CTkLabel(body, text=message, anchor="w", justify="left",
                     font=font(12), text_color=TEXT_MUTED, wraplength=440
                     ).pack(fill="x")

        # Rodapé com botões
        footer = ctk.CTkFrame(wrapper, fg_color="transparent")
        footer.pack(fill="x", padx=26, pady=(0, 20))

        if cancel_text:
            ghost_button(footer, cancel_text, self._on_cancel, width=110
                         ).pack(side="right", padx=(8, 0))

        primary_button(footer, confirm_text, self._on_confirm, width=110
                       ).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Return>", lambda e: self._on_confirm())
        self.bind("<Escape>", lambda e: self._on_cancel())

        # Centraliza sobre a janela pai
        self.update_idletasks()
        self._center_over(parent)

        # Modal: bloqueia interação com o pai até fechar
        self.grab_set()
        self.wait_visibility()
        self.focus_force()

    def _center_over(self, parent):
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            x = px + (pw - width) // 2
            y = py + (ph - height) // 2
        except Exception:
            x = (self.winfo_screenwidth() - width) // 2
            y = (self.winfo_screenheight() - height) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _on_confirm(self):
        self.result = True
        self.destroy()

    def _on_cancel(self):
        self.result = False
        self.destroy()


def show_info(parent, title, message):
    dialog = Dialog(parent, title, message, intent="info", confirm_text="OK")
    parent.wait_window(dialog)
    return dialog.result


def show_warning(parent, title, message):
    dialog = Dialog(parent, title, message, intent="warning", confirm_text="OK")
    parent.wait_window(dialog)
    return dialog.result


def show_success(parent, title, message):
    dialog = Dialog(parent, title, message, intent="success", confirm_text="OK")
    parent.wait_window(dialog)
    return dialog.result


def ask_confirm(parent, title, message,
                confirm_text="Continuar", cancel_text="Cancelar"):
    dialog = Dialog(parent, title, message, intent="confirm",
                    confirm_text=confirm_text, cancel_text=cancel_text)
    parent.wait_window(dialog)
    return dialog.result