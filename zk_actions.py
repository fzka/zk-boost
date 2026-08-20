# -*- coding: utf-8 -*-
"""
ZK Boost — Ações corretivas
----------------------------
Liga cada achado do diagnóstico a uma correção, quando ela existe.

Nem todo problema tem botão, e isso é deliberado. XMP se ativa na BIOS,
driver se atualiza pelo site do fabricante — prometer um clique onde ele
não existe seria mentir. Nesses casos o app orienta em vez de agir.
"""

import webbrowser
from dataclasses import dataclass
from typing import Callable, Optional

import zk_core as core
import zk_diagnostics as diag


@dataclass
class Action:
    """Correção disponível para um achado.

    recheck devolve o Finding atualizado depois da correção, para que o
    card se reescreva sozinho em vez de exigir um novo scan completo.
    """
    label: str
    run: Callable[[], core.Result]
    recheck: Optional[Callable[[], diag.Finding]] = None
    confirm: str = ""          # se preenchido, pede confirmação antes
    needs_admin: bool = False


# --------------------------------------------------------------------------- #
# CORREÇÕES
# --------------------------------------------------------------------------- #

def _fix_game_dvr() -> core.Result:
    return core.set_game_dvr(False)


def _fix_power_plan() -> core.Result:
    return core.apply_power_plan()


def _open_nvidia_downloads() -> core.Result:
    """Abre a página oficial de drivers. Baixar e instalar fica com o usuário.

    Automatizar instalação de driver exigiria baixar e executar binário de
    terceiros — exatamente o comportamento que faz antivírus classificar
    otimizador como malware, e com razão.
    """
    try:
        webbrowser.open("https://www.nvidia.com/pt-br/drivers/", new=2)
        return core.Result(True, "Página de drivers aberta no navegador",
                           "Baixe a versão Game Ready para sua placa.")
    except Exception as exc:
        return core.Result(False, "Não foi possível abrir o navegador", str(exc))


def _open_task_manager() -> core.Result:
    ok, _ = core.run_hidden("start taskmgr")
    if ok:
        return core.Result(True, "Gerenciador de Tarefas aberto",
                           "Feche o que não estiver usando antes da partida.")
    return core.Result(False, "Não foi possível abrir o Gerenciador de Tarefas")


# --------------------------------------------------------------------------- #
# REGISTRO
# --------------------------------------------------------------------------- #

_REGISTRY = {
    "gamedvr": Action(
        label="Desativar",
        run=_fix_game_dvr,
        recheck=diag.check_game_dvr,
    ),
    "power": Action(
        label="Ajustar plano",
        run=_fix_power_plan,
        recheck=diag.check_power_plan,
        needs_admin=True,
    ),
    "gpu": Action(
        label="Abrir downloads",
        run=_open_nvidia_downloads,
    ),
    "background": Action(
        label="Ver processos",
        run=_open_task_manager,
        recheck=diag.check_background_load,
    ),
}


def for_finding(finding) -> Optional[Action]:
    """Ação disponível para um achado, ou None.

    Só oferecemos botão quando há de fato algo a corrigir: um card verde
    com botão de 'corrigir' confunde mais do que ajuda.
    """
    if finding.status not in (diag.STATUS_WARN, diag.STATUS_ERROR):
        return None
    return _REGISTRY.get(finding.key)