<div align="center">

# ⚡ ZK BOOST

**Otimizador de performance para Counter-Strike 2 — 100% VAC-Safe**

[![Build Windows](https://github.com/fzka/zk-boost/actions/workflows/build.yml/badge.svg)](https://github.com/fzka/zk-boost/actions/workflows/build.yml)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

</div>

---

## O que é

O ZK Boost ajusta o que está **fora** do jogo para o CS2 render mais: prioridade
de processo, afinidade de CPU, plano de energia, cache de rede e arquivos
temporários — além de gerenciar uma CFG de performance sem apagar suas binds.

### Por que é VAC-Safe

Nada é injetado na memória do processo. O software usa apenas:

| Recurso | Método |
| --- | --- |
| Afinidade e prioridade | API oficial do Windows via `psutil` |
| Plano de energia | `powercfg` (nativo do Windows) |
| Cache de rede | `ipconfig` / `netsh` (nativos do Windows) |
| CFG do jogo | Escrita de arquivo `.cfg` — mesmo método de qualquer config manual |

Todas as alterações são reversíveis pelo botão **RESTAURAR PADRÕES**.

---

## Funcionalidades

- **Isolamento do Core 0** — remove o núcleo que o Windows mais usa para interrupções
- **Alta prioridade de processamento** para o `cs2.exe`
- **Plano de energia máximo** (Ultimate Performance, com fallback para Alto Desempenho)
- **Otimização de rede** — flush de DNS e, opcionalmente, reset de Winsock/TCP-IP
- **Limpeza de temporários** com relatório de espaço liberado
- **CFG integrada** — rastros de tiro em 1ª pessoa e suavização de sub-ticks
- **Injeção não-destrutiva** — o `autoexec.cfg` é apenas complementado, nunca sobrescrito
- **Reversão completa** de tudo com um clique

---

## Instalação

Baixe o `ZK-Boost.exe` mais recente em [Releases](../../releases) e execute
**como Administrador** (ajustes de CPU e energia exigem elevação).

> O executável é gerado automaticamente pelo GitHub Actions a partir deste
> código-fonte. Você pode auditar cada build na aba Actions.

---

## Desenvolvimento

### Rodando do código-fonte (Windows)

```bash
git clone https://github.com/fzka/zk-boost.git
cd zk-boost
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python zk_boost.py
```

### Desenvolvendo no Linux / macOS

O app é Windows-only em runtime, mas dá para iterar a interface em qualquer
sistema usando o **modo simulação**, que substitui todas as chamadas ao SO por
stubs e escreve as CFGs numa sandbox em `~/.zkboost-sim/`:

```bash
sudo apt install python3-tk     # o customtkinter depende do tkinter
pip install -r requirements.txt
python zk_sim.py
```

### Compilando

O build oficial roda em CI (`.github/workflows/build.yml`). PyInstaller **não
faz cross-compile**, então gerar o `.exe` a partir do Linux não funciona — use
o Actions ou uma máquina Windows:

```bash
pyinstaller --noconfirm --onefile --windowed --uac-admin \
  --name "ZK-Boost" --collect-all customtkinter zk_boost.py
```

Para publicar uma versão:

```bash
git tag v2.0.0 && git push origin v2.0.0
```

---

## Roadmap

- [ ] Ícone e identidade visual próprios (`assets/icon.ico`)
- [ ] Perfis salvos (Competitivo / Casual / Streaming)
- [ ] Detecção automática do CS2 abrindo, com aplicação em background
- [ ] Benchmark antes/depois (1% low, frametime)
- [ ] Editor de CFG dentro do app
- [ ] Tradução PT-BR / EN

---

## Contribuindo

Issues e pull requests são bem-vindos. Ao propor mudanças que envolvam o jogo,
mantenha o princípio inegociável do projeto: **nada que toque a memória do
processo do CS2**.

---

## Aviso

Este software altera configurações do Windows. Todas as operações são
reversíveis pelo próprio app, mas use por sua conta e risco. O ZK Boost não é
afiliado à Valve Corporation.

## Licença

MIT — veja [LICENSE](LICENSE).
