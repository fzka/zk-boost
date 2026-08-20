# -*- coding: utf-8 -*-
"""
ZK Boost — Catálogo de CFG do CS2
----------------------------------
Gera o zk_boost.cfg a partir de um catálogo curado de comandos.

POR QUE UM CATÁLOGO E NÃO UMA LISTA FIXA
Comandos de console mudam entre atualizações do CS2: alguns são removidos,
outros passam a exigir sv_cheats, outros deixam de ter efeito. Guias
populares continuam repetindo comandos de CS:GO que o Source 2 ignora —
cl_interp, cl_updaterate, mat_queue_mode, r_dynamic. Emitir esses comandos
não é neutro: o usuário acredita que otimizou e não otimizou nada.

Cada entrada carrega um nível de confiança. Só o que está em CONFIRMED
entra na CFG por padrão. O que é mito fica registrado em MYTHS, para que
a interface possa explicar por que não usamos — e para que ninguém
reintroduza esses comandos por engano no futuro.
"""

import os
import re
from dataclasses import dataclass, field

import zk_core as core

# Níveis de confiança
CONFIRMED = "confirmed"   # funciona no CS2 atual, efeito conhecido
REVIEW = "review"         # plausível, mas precisa ser validado no console

# Categorias
PERF = "Desempenho"
VISUAL = "Distrações visuais"
NET = "Rede e latência"
AUDIO = "Áudio"
HUD = "Telemetria"


@dataclass
class Cvar:
    """Uma opção de configuração exposta ao usuário."""
    key: str
    label: str
    description: str
    category: str
    on_lines: list                    # linhas quando ativado
    off_lines: list = field(default_factory=list)   # linhas ao restaurar
    tier: str = CONFIRMED
    default: bool = False
    note: str = ""                    # ressalva mostrada na interface


# --------------------------------------------------------------------------- #
# CATÁLOGO
# --------------------------------------------------------------------------- #

CATALOG = [
    # ---------------------------- DESEMPENHO ---------------------------- #
    Cvar(
        "tracers", "Remover rastros de tiro em 1ª pessoa",
        "Menos partículas na tela ao atirar, sem afetar o que os outros veem.",
        PERF,
        on_lines=['r_drawtracers_firstperson "0"'],
        off_lines=['r_drawtracers_firstperson "1"'],
        default=True,
    ),
    Cvar(
        "freezecam", "Desativar câmera de morte",
        "Volta ao jogo imediatamente após morrer, sem a cena de quem matou.",
        PERF,
        on_lines=['cl_disablefreezecam "1"'],
        off_lines=['cl_disablefreezecam "0"'],
        default=True,
    ),

    # ------------------------ DISTRAÇÕES VISUAIS ------------------------ #
    Cvar(
        "instructor", "Desativar dicas do instrutor",
        "Remove as legendas de tutorial que aparecem sobre objetos e armas.",
        VISUAL,
        on_lines=['gameinstructor_enable "0"', 'cl_autohelp "0"'],
        off_lines=['gameinstructor_enable "1"', 'cl_autohelp "1"'],
        default=True,
    ),
    Cvar(
        "advertise", "Não anunciar partida para amigos",
        "Evita que a Steam mostre e permita entrada na sua partida em curso.",
        VISUAL,
        on_lines=['cl_join_advertise "0"'],
        off_lines=['cl_join_advertise "2"'],
    ),

    # -------------------------- REDE E LATÊNCIA ------------------------- #
    Cvar(
        "subtick", "Suavização de sub-ticks",
        "Zera o buffer de recepção e ativa a espera de baixa latência do "
        "cliente após cada tick.",
        NET,
        on_lines=['cl_net_buffer_ticks "0"',
                  'engine_low_latency_sleep_after_client_tick "true"'],
        off_lines=['cl_net_buffer_ticks "0"',
                   'engine_low_latency_sleep_after_client_tick "true"'],
        default=True,
        note="Alguns jogadores relatam que o CS2 redefine o segundo comando "
             "entre sessões. A CFG reaplica a cada início.",
    ),
    Cvar(
        "rate", "Taxa de banda máxima",
        "Libera o teto de dados que o cliente aceita receber do servidor. "
        "Só ajuda em conexão de banda larga estável.",
        NET,
        on_lines=['rate "786432"'],
        off_lines=['rate "196608"'],
    ),

    # ------------------------------ ÁUDIO ------------------------------- #
    Cvar(
        "audio_latency", "Reduzir atraso de áudio",
        "Diminui o buffer de mixagem. Passos e tiros chegam antes, com risco "
        "de estalos em placa de som mais fraca.",
        AUDIO,
        on_lines=['snd_mixahead "0.025"'],
        off_lines=['snd_mixahead "0.05"'],
        note="Se o áudio estalar, desative esta opção.",
    ),

    # --------------------------- TELEMETRIA ----------------------------- #
    Cvar(
        "showfps", "Mostrar FPS e frametime",
        "Contador no canto da tela. Útil para comparar antes e depois de uma "
        "otimização.",
        HUD,
        on_lines=['cl_showfps "1"'],
        off_lines=['cl_showfps "0"'],
    ),
    Cvar(
        "console", "Manter console habilitado",
        "Garante que o console abra com a tecla de acento agudo.",
        HUD,
        on_lines=['con_enable "1"'],
        off_lines=['con_enable "1"'],
        default=True,
    ),
]

CATALOG_BY_KEY = {cvar.key: cvar for cvar in CATALOG}

CATEGORIES = [PERF, VISUAL, NET, AUDIO, HUD]


# --------------------------------------------------------------------------- #
# MITOS — comandos que deliberadamente NÃO emitimos
# --------------------------------------------------------------------------- #

MYTHS = [
    ("cl_interp / cl_interp_ratio",
     "Herança de CS:GO. O Source 2 resolve interpolação por sub-tick e ignora "
     "esses valores."),
    ("cl_updaterate / cl_cmdrate",
     "Não existem mais como ajuste do cliente. A taxa é definida pelo servidor."),
    ("mat_queue_mode",
     "Comando do Source 1. Não tem efeito na engine do CS2."),
    ("r_dynamic 0",
     "Removido. Guias que prometem 15-20% de FPS com ele estão copiando "
     "conteúdo de CS:GO."),
    ("net_graph 1",
     "A Valve removeu em 2024. O substituto oficial é o HUD de Telemetria, "
     "nas configurações do jogo."),
    ("cl_forcepreload",
     "Removido do CS2. Não faz nada."),
    ("-d3d9ex / -tickrate nas opções de inicialização",
     "Parâmetros de Source 1. O CS2 usa Vulkan/DirectX 11 e tickrate de "
     "servidor."),
]


# --------------------------------------------------------------------------- #
# GERAÇÃO
# --------------------------------------------------------------------------- #

def build_config(selections: dict, restore=False) -> str:
    """Monta o conteúdo do zk_boost.cfg.

    selections: {chave: bool}. Chaves ausentes contam como desativadas.
    """
    lines = [
        "// ===============================================",
        f"// ZK BOOST v{core.APP_VERSION} — configuração automática",
        "//",
        "// Este arquivo é gerado pelo app e sobrescrito a cada aplicação.",
        "// Não edite aqui: use o app, ou escreva no seu autoexec.cfg, que",
        "// nunca é apagado.",
        "// ===============================================",
        "",
    ]

    for category in CATEGORIES:
        selected = [c for c in CATALOG
                    if c.category == category
                    and (restore or selections.get(c.key))]
        if not selected:
            continue

        lines.append(f"// --- {category} ---")
        for cvar in selected:
            emitted = cvar.off_lines if restore else cvar.on_lines
            lines.extend(emitted)
        lines.append("")

    verb = "padrões restaurados" if restore else "carregado"
    lines.append(f'echo "ZK BOOST {core.APP_VERSION} — {verb}"')
    return "\n".join(lines) + "\n"


def build_validation_config() -> str:
    """CFG que pergunta ao próprio jogo se cada comando existe.

    O usuário roda `exec zk_check` no console: comandos válidos exibem a
    descrição, inválidos aparecem como desconhecidos. É a única fonte de
    verdade confiável, já que o jogo muda a cada atualização.
    """
    lines = [
        "// ZK BOOST — verificação de comandos",
        "// Rode no console:  exec zk_check",
        "// Comandos marcados como desconhecidos foram removidos do jogo.",
        "",
        'echo "=== ZK BOOST: verificando comandos ==="',
        "",
    ]
    seen = set()
    for cvar in CATALOG:
        for line in cvar.on_lines:
            name = line.split()[0].strip('"')
            if name in seen:
                continue
            seen.add(name)
            lines.append(f"help {name}")
    lines += ["", 'echo "=== fim da verificação ==="']
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# CONFLITOS
# --------------------------------------------------------------------------- #

_CVAR_PATTERN = re.compile(r'^\s*([a-zA-Z_][\w]*)\s+"?([^"/\s]+)"?', re.MULTILINE)


def detect_conflicts(cfg_path, selections: dict) -> list:
    """Procura comandos do autoexec que anulam os nossos.

    O CS2 aplica a última linha lida. Se o autoexec do usuário definir um
    comando DEPOIS do nosso exec, o nosso é sobrescrito silenciosamente —
    o app relata sucesso e nada muda no jogo. Esse é o motivo mais comum
    de "apliquei e não funcionou".
    """
    autoexec = os.path.join(cfg_path or "", "autoexec.cfg")
    if not cfg_path or not os.path.exists(autoexec):
        return []

    try:
        with open(autoexec, "r", encoding="utf-8", errors="ignore") as handle:
            content = handle.read()
    except OSError:
        return []

    # Só interessa o que vem DEPOIS da nossa linha de exec.
    marker = content.find(core.EXEC_LINE)
    if marker == -1:
        return []
    tail = content[marker + len(core.EXEC_LINE):]

    ours = {}
    for key, enabled in selections.items():
        if not enabled:
            continue
        cvar = CATALOG_BY_KEY.get(key)
        if not cvar:
            continue
        for line in cvar.on_lines:
            parts = line.split(None, 1)
            if len(parts) == 2:
                ours[parts[0]] = (cvar.label, parts[1].strip('"'))

    conflicts = []
    for match in _CVAR_PATTERN.finditer(tail):
        name, value = match.group(1), match.group(2)
        if name in ours:
            label, our_value = ours[name]
            if value != our_value:
                conflicts.append({
                    "cvar": name, "label": label,
                    "ours": our_value, "theirs": value,
                })
    return conflicts


def apply(cfg_path, selections: dict, restore=False) -> core.Result:
    """Escreve a CFG e garante o exec no autoexec, preservando o resto."""
    if not cfg_path or not os.path.isdir(cfg_path):
        return core.Result(False, "Pasta do CS2 não definida")

    try:
        with open(os.path.join(cfg_path, "zk_boost.cfg"), "w",
                  encoding="utf-8") as handle:
            handle.write(build_config(selections, restore))

        with open(os.path.join(cfg_path, "zk_check.cfg"), "w",
                  encoding="utf-8") as handle:
            handle.write(build_validation_config())
    except OSError as exc:
        return core.Result(False, "Falha ao escrever a CFG", str(exc))

    autoexec = os.path.join(cfg_path, "autoexec.cfg")
    block = f"{core.MARKER_START}\n{core.EXEC_LINE}\n{core.MARKER_END}\n"
    try:
        content = ""
        if os.path.exists(autoexec):
            with open(autoexec, "r", encoding="utf-8", errors="ignore") as handle:
                content = handle.read()

        if core.MARKER_START not in content and core.EXEC_LINE not in content:
            with open(autoexec, "a" if content else "w", encoding="utf-8") as handle:
                if content and not content.endswith("\n"):
                    handle.write("\n")
                handle.write(block)
    except OSError as exc:
        return core.Result(False, "Falha ao atualizar autoexec.cfg", str(exc))

    if restore:
        return core.Result(True, "CFG restaurada aos padrões do jogo",
                           "Reinicie o CS2 para os valores valerem.")

    count = sum(1 for key, on in selections.items() if on and key in CATALOG_BY_KEY)
    return core.Result(True, f"CFG aplicada com {count} ajustes",
                       "Reinicie o CS2. O console mostrará 'ZK BOOST carregado'.")