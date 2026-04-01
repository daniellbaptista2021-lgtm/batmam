"""CLI REPL interativo do Batmam — com streaming e visual premium."""

from __future__ import annotations
import os
import sys
import time
import argparse
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme
from rich.rule import Rule
from rich.columns import Columns
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML

from . import __version__
from .agent import Agent
from .models import Session
from .session import save_session, load_session, list_sessions
from .memory import list_memories, save_memory, delete_memory
from .prompts import WELCOME_BANNER
from . import config

# ── Cores do Batmam ──────────────────────────────────────────
#   Dourado/Gold: #FFD700  → texto do usuário
#   Branco:                → resposta do Batmam
#   Cyan:                  → informações do sistema
#   Amarelo escuro:        → bordas e decoração

GOLD = "#FFD700"
DARK_GOLD = "#B8860B"
BORDER_COLOR = "#5C5C3D"

batmam_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "tool": "bold magenta",
    "tool.name": "bold #87CEEB",
    "muted": "dim",
    "accent": "bold cyan",
    "bat": f"bold {GOLD}",
    "gold": GOLD,
    "dark_gold": DARK_GOLD,
    "user_text": f"bold {GOLD}",
    "border": BORDER_COLOR,
    "agent_label": "bold #87CEEB",
})

console = Console(theme=batmam_theme)

# ── Constantes visuais ───────────────────────────────────────
SEPARATOR_CHAR = "─"
CORNER_TL = "╭"
CORNER_TR = "╮"
CORNER_BL = "╰"
CORNER_BR = "╯"
VERT = "│"
HORIZ = "─"


def _separator(label: str = "", style: str = "border") -> None:
    """Imprime uma linha separadora estilizada."""
    if label:
        console.print(Rule(f" {label} ", style=style, characters=HORIZ))
    else:
        console.print(Rule(style=style, characters=HORIZ))


def _user_header() -> None:
    """Imprime o cabeçalho da área do usuário."""
    w = console.width or 80
    line = f"{CORNER_TL}{HORIZ * 2} [gold]Daniel[/] {HORIZ * (w - 14)}{CORNER_TR}"
    console.print(f"[dark_gold]{line}[/]")


def _user_footer() -> None:
    """Imprime o rodapé da área do usuário."""
    w = console.width or 80
    line = f"{CORNER_BL}{HORIZ * (w - 2)}{CORNER_BR}"
    console.print(f"[dark_gold]{line}[/]")


def _agent_header() -> None:
    """Imprime o cabeçalho da resposta do Batmam."""
    w = console.width or 80
    line = f"{CORNER_TL}{HORIZ * 2} [agent_label]🦇 Batmam[/] {HORIZ * (w - 17)}{CORNER_TR}"
    console.print(f"[border]{line}[/]")


def _agent_footer() -> None:
    """Imprime o rodapé da resposta do Batmam."""
    w = console.width or 80
    line = f"{CORNER_BL}{HORIZ * (w - 2)}{CORNER_BR}"
    console.print(f"[border]{line}[/]")


# ── Estado global do streaming ────────────────────────────────
_streaming_buffer: list[str] = []
_in_streaming = False
_agent_box_open = False


def on_text_delta(delta: str) -> None:
    """Streaming em tempo real — imprime cada pedaço conforme chega."""
    global _in_streaming, _agent_box_open
    if not _in_streaming:
        _in_streaming = True
        if not _agent_box_open:
            _agent_header()
            _agent_box_open = True
        sys.stdout.write("  ")  # Indentação dentro da box
    sys.stdout.write(delta)
    sys.stdout.flush()
    _streaming_buffer.append(delta)


def on_text_done(text: str) -> None:
    """Chamado quando o texto completo está pronto."""
    global _in_streaming
    if _in_streaming:
        sys.stdout.write("\n")
        sys.stdout.flush()
        _in_streaming = False
    _streaming_buffer.clear()


def _close_agent_box() -> None:
    """Fecha a box do agente se estiver aberta."""
    global _agent_box_open
    if _agent_box_open:
        _agent_footer()
        _agent_box_open = False


def on_tool_call(name: str, args: dict) -> None:
    """Chamado quando o modelo chama uma ferramenta."""
    global _in_streaming, _agent_box_open
    if _in_streaming:
        sys.stdout.write("\n")
        sys.stdout.flush()
        _in_streaming = False

    if not _agent_box_open:
        _agent_header()
        _agent_box_open = True

    detail = ""
    if name == "bash":
        detail = args.get("command", "")[:120]
    elif name in ("read", "write", "edit"):
        detail = args.get("file_path", "")
    elif name == "glob":
        detail = args.get("pattern", "")
    elif name == "grep":
        detail = args.get("pattern", "")
    elif name == "agent":
        detail = args.get("description", args.get("task", "")[:60])
    elif name == "web_search":
        detail = args.get("query", "")
    elif name == "web_fetch":
        detail = args.get("url", "")[:100]
    elif name == "notebook_edit":
        op = args.get("operation", "")
        detail = f"{op} {args.get('file_path', '')}"
    elif name.startswith("mcp__"):
        detail = str(args)[:80]

    icon = _tool_icon(name)
    console.print(f"  [tool.name]{icon} {name}[/]  [muted]{detail}[/]")


def on_tool_result(name: str, status: str, output: str) -> None:
    """Chamado quando uma ferramenta retorna resultado."""
    if status == "error":
        console.print(f"  [error]✗ {name} falhou[/]")
        if output:
            for line in output.strip().splitlines()[:5]:
                console.print(f"    [error]{line}[/]")
    elif status == "denied":
        console.print(f"  [warning]⊘ {name} negado[/]")
    else:
        if name == "bash" and output:
            lines = output.strip().splitlines()
            if len(lines) <= 8:
                for line in lines:
                    console.print(f"    [muted]{line}[/]")
            else:
                for line in lines[:4]:
                    console.print(f"    [muted]{line}[/]")
                console.print(f"    [muted]... ({len(lines)} linhas)[/]")
                for line in lines[-2:]:
                    console.print(f"    [muted]{line}[/]")
        console.print(f"  [success]✓ {name}[/]")


def _tool_icon(name: str) -> str:
    icons = {
        "bash": "⚡",
        "read": "📖",
        "write": "✏️",
        "edit": "🔧",
        "glob": "🔍",
        "grep": "🔎",
        "agent": "🤖",
        "web_search": "🌐",
        "web_fetch": "📡",
        "notebook_edit": "📓",
    }
    if name.startswith("mcp__"):
        return "🔌"
    return icons.get(name, "⚙️")


def ask_confirmation(message: str) -> bool:
    """Pede confirmação do usuário."""
    console.print()
    console.print(Panel(
        message,
        title="[warning]⚠ Permissão Necessária[/]",
        border_style="yellow",
        padding=(0, 1),
    ))
    try:
        resp = console.input(f"  [{GOLD}](s)im / (n)ão / (a)sempre: [/]").strip().lower()
        if resp in ("a", "sempre", "always"):
            config.AUTO_APPROVE_BASH = True
            config.AUTO_APPROVE_WRITE = True
            console.print("  [info]Auto-approve ativado para esta sessão.[/]")
            return True
        return resp in ("s", "y", "sim", "yes", "")
    except (EOFError, KeyboardInterrupt):
        return False


# ── Comandos Internos ─────────────────────────────────────────

def handle_slash_command(cmd: str, agent: Agent) -> bool:
    """Processa comandos /slash. Retorna True se foi um comando válido."""
    parts = cmd.strip().split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command in ("/help", "/h"):
        _show_help()
        return True

    elif command in ("/exit", "/quit", "/q"):
        save_session(agent.session)
        _separator("Fim da Sessão", style="gold")
        console.print(f"[gold]  Sessão salva. Até mais, Daniel! 🦇[/]")
        sys.exit(0)

    elif command in ("/clear", "/reset"):
        system_msg = agent.session.messages[0] if agent.session.messages else None
        agent.session.messages = [system_msg] if system_msg else []
        console.print("[info]  Histórico limpo.[/]")
        return True

    elif command == "/sessions":
        sessions = list_sessions()
        if not sessions:
            console.print("[muted]  Nenhuma sessão salva.[/]")
        else:
            console.print(f"\n[accent]  Sessões ({len(sessions)}):[/]")
            for s in sessions[:20]:
                ts = time.strftime("%d/%m %H:%M", time.localtime(s["created_at"]))
                console.print(
                    f"    [info]{s['id']}[/]  {ts}  "
                    f"[muted]{s['messages']} msgs  {s['cwd']}[/]"
                )
        return True

    elif command == "/resume":
        if not arg:
            console.print("[error]  Use: /resume <session_id>[/]")
            return True
        loaded = load_session(arg.strip())
        if loaded:
            agent.session = loaded
            console.print(f"[success]  Sessão {arg} restaurada ({len(loaded.messages)} msgs).[/]")
        else:
            console.print(f"[error]  Sessão '{arg}' não encontrada.[/]")
        return True

    elif command == "/save":
        save_session(agent.session)
        console.print(f"[success]  Sessão salva: {agent.session.id}[/]")
        return True

    elif command == "/model":
        if arg:
            agent.model = arg.strip()
            config.BATMAM_MODEL = arg.strip()
            console.print(f"[info]  Modelo: {agent.model}[/]")
        else:
            console.print(f"[info]  Modelo atual: {agent.model}[/]")
            console.print("[muted]  Disponíveis: gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, gpt-4o, o3, o4-mini[/]")
        return True

    elif command == "/tokens":
        s = agent.session
        total = s.total_tokens_in + s.total_tokens_out
        console.print(
            f"[info]  Tokens  In: {s.total_tokens_in:,}  "
            f"Out: {s.total_tokens_out:,}  "
            f"Total: {total:,}[/]"
        )
        msgs = len(s.messages)
        turns = len(s.turns)
        console.print(f"[muted]  Mensagens: {msgs}  Turnos: {turns}[/]")
        return True

    elif command == "/cwd":
        console.print(f"[info]  {agent.cwd}[/]")
        return True

    elif command == "/cd":
        if not arg:
            console.print("[error]  Use: /cd <diretório>[/]")
            return True
        new_dir = Path(arg).expanduser().resolve()
        if new_dir.is_dir():
            os.chdir(new_dir)
            agent.cwd = str(new_dir)
            console.print(f"[info]  {new_dir}[/]")
        else:
            console.print(f"[error]  Não encontrado: {new_dir}[/]")
        return True

    elif command == "/approve":
        config.AUTO_APPROVE_BASH = True
        config.AUTO_APPROVE_WRITE = True
        console.print("[warning]  Auto-approve ativado.[/]")
        return True

    elif command == "/compact":
        before = len(agent.session.messages)
        agent._maybe_compact()
        after = len(agent.session.messages)
        console.print(f"[info]  Compactado: {before} → {after} mensagens[/]")
        return True

    elif command == "/memory":
        if arg.startswith("save "):
            mem_parts = arg[5:].split(maxsplit=1)
            if len(mem_parts) < 2:
                console.print("[error]  Use: /memory save <nome> <conteúdo>[/]")
            else:
                save_memory(mem_parts[0], mem_parts[1])
                console.print(f"[success]  Memória salva: {mem_parts[0]}[/]")
        elif arg.startswith("delete "):
            name = arg[7:].strip()
            if delete_memory(name):
                console.print(f"[success]  Memória deletada: {name}[/]")
            else:
                console.print(f"[error]  Memória '{name}' não encontrada.[/]")
        else:
            memories = list_memories()
            if not memories:
                console.print("[muted]  Nenhuma memória salva.[/]")
            else:
                console.print(f"\n[accent]  Memórias ({len(memories)}):[/]")
                for m in memories:
                    console.print(f"    [info]{m['name']}[/]  [muted]({m['type']})[/]")
        return True

    elif command == "/diff":
        import subprocess
        try:
            result = subprocess.run(
                "git diff --stat", shell=True, capture_output=True, text=True, cwd=agent.cwd
            )
            if result.stdout.strip():
                console.print(f"\n[accent]  Git Diff:[/]\n[muted]{result.stdout}[/]")
            else:
                console.print("[muted]  Sem alterações.[/]")
        except Exception:
            console.print("[error]  Erro ao executar git diff.[/]")
        return True

    elif command == "/status":
        import subprocess
        try:
            result = subprocess.run(
                "git status -sb", shell=True, capture_output=True, text=True, cwd=agent.cwd
            )
            console.print(f"\n[muted]{result.stdout}[/]")
        except Exception:
            console.print("[error]  Não é um repositório git.[/]")
        return True

    elif command == "/init":
        batmam_md = Path(agent.cwd) / "BATMAM.md"
        if batmam_md.exists():
            console.print(f"[warning]  BATMAM.md já existe em {agent.cwd}[/]")
        else:
            batmam_md.write_text(
                "# Instruções do Projeto\n\n"
                "<!-- Adicione contexto, regras e instruções do projeto aqui. -->\n"
                "<!-- O Batmam lerá este arquivo automaticamente. -->\n",
                encoding="utf-8",
            )
            console.print(f"[success]  BATMAM.md criado em {agent.cwd}[/]")
        return True

    elif command == "/hooks":
        hooks_list = agent.hooks.list_hooks()
        if not hooks_list:
            console.print("[muted]  Nenhum hook configurado.[/]")
            console.print("[muted]  Configure em ~/.batmam/settings.json[/]")
        else:
            console.print(f"\n[accent]  Hooks:[/]")
            for event, hooks in hooks_list.items():
                console.print(f"    [info]{event}[/]")
                for i, h in enumerate(hooks):
                    tool_filter = f" (tool: {h.tool})" if h.tool else ""
                    blocking = " [BLOCKING]" if h.stop_on_failure else ""
                    console.print(f"      [{i}] {h.command}{tool_filter}{blocking}")
        return True

    elif command == "/plugins":
        plugins = agent.plugins.list_plugins()
        if not plugins:
            console.print("[muted]  Nenhum plugin carregado.[/]")
            console.print(f"[muted]  Coloque plugins em ~/.batmam/plugins/[/]")
        else:
            console.print(f"\n[accent]  Plugins ({len(plugins)}):[/]")
            for p in plugins:
                status_style = "success" if p["status"] == "loaded" else "error"
                console.print(
                    f"    [{status_style}]{p['status']}[/]  "
                    f"[info]{p['name']}[/]  [muted]{p['description']}[/]"
                )
        return True

    elif command == "/mcp":
        servers = agent.mcp.server_status()
        if not servers:
            console.print("[muted]  Nenhum servidor MCP conectado.[/]")
            console.print("[muted]  Configure em ~/.batmam/settings.json[/]")
        else:
            console.print(f"\n[accent]  Servidores MCP ({len(servers)}):[/]")
            for s in servers:
                status = "[success]ON[/]" if s["running"] else "[error]OFF[/]"
                console.print(f"    {status}  [info]{s['name']}[/]  [muted]{s['tools']} tools[/]")
        return True

    elif command == "/tools":
        tools = agent.registry.names()
        console.print(f"\n[accent]  Ferramentas ({len(tools)}):[/]")
        for name in tools:
            tool = agent.registry.get(name)
            desc = tool.description[:60] if tool else ""
            icon = _tool_icon(name)
            console.print(f"    {icon} [info]{name}[/]  [muted]{desc}[/]")
        return True

    return False


def _show_help() -> None:
    console.print(Panel(
        "[gold]Conversa[/]\n"
        "  Digite normalmente para conversar com o agente\n"
        "  [muted]Termine com \\\\ para multi-linha[/]\n"
        "  [muted]!comando[/]  — executa bash direto\n"
        "\n"
        "[gold]Navegação[/]\n"
        "  [info]/cd <dir>[/]       — muda diretório\n"
        "  [info]/cwd[/]            — mostra diretório atual\n"
        "  [info]/status[/]         — git status\n"
        "  [info]/diff[/]           — git diff\n"
        "\n"
        "[gold]Sessões[/]\n"
        "  [info]/sessions[/]       — lista sessões\n"
        "  [info]/resume <id>[/]    — retoma sessão\n"
        "  [info]/save[/]           — salva sessão\n"
        "  [info]/clear[/]          — limpa histórico\n"
        "  [info]/compact[/]        — compacta contexto\n"
        "\n"
        "[gold]Memória[/]\n"
        "  [info]/memory[/]              — lista memórias\n"
        "  [info]/memory save <n> <t>[/] — salva memória\n"
        "  [info]/memory delete <n>[/]   — deleta memória\n"
        "\n"
        "[gold]Config[/]\n"
        "  [info]/model[/] [nome]   — mostra/altera modelo\n"
        "  [info]/tokens[/]         — uso de tokens\n"
        "  [info]/approve[/]        — auto-approve\n"
        "  [info]/init[/]           — cria BATMAM.md\n"
        "\n"
        "[gold]Extensões[/]\n"
        "  [info]/tools[/]          — lista ferramentas\n"
        "  [info]/hooks[/]          — lista hooks\n"
        "  [info]/plugins[/]        — lista plugins\n"
        "  [info]/mcp[/]            — lista servidores MCP\n"
        "\n"
        "  [info]/exit[/]           — sai do Batmam\n",
        title=f"[{GOLD}]🦇 Batmam — Ajuda[/]",
        border_style=DARK_GOLD,
        padding=(1, 2),
    ))


# ── REPL Principal ────────────────────────────────────────────

def run_repl(args: argparse.Namespace) -> None:
    """Loop principal do REPL."""

    # Banner premium
    _print_banner()

    # Sessão
    session = None
    if hasattr(args, "resume") and args.resume:
        session = load_session(args.resume)
        if session:
            console.print(f"[success]  Sessão {args.resume} restaurada.[/]\n")

    # Cria agente
    agent = Agent(
        cwd=os.getcwd(),
        session=session,
        model=getattr(args, "model", None) or config.BATMAM_MODEL,
        on_text_delta=on_text_delta,
        on_text_done=on_text_done,
        on_tool_call=on_tool_call,
        on_tool_result=on_tool_result,
        ask_confirmation=ask_confirmation,
        auto_approve=getattr(args, "auto_approve", False),
    )

    # Histórico de input
    history_file = config.BATMAM_HOME / "input_history"
    prompt_session = PromptSession(
        history=FileHistory(str(history_file)),
        auto_suggest=AutoSuggestFromHistory(),
        multiline=False,
    )

    # Prompt inicial (se veio da CLI)
    if hasattr(args, "prompt") and args.prompt:
        initial_prompt = " ".join(args.prompt)
        _show_user_message(initial_prompt)
        _run_agent_turn(agent, initial_prompt)

    # Loop REPL
    while True:
        try:
            # Prompt dourado com prompt_toolkit
            user_input = prompt_session.prompt(
                HTML('<style fg="#FFD700" bold="true">🦇 &gt; </style>'),
            ).strip()

            if not user_input:
                continue

            # Slash command
            if user_input.startswith("/"):
                if handle_slash_command(user_input, agent):
                    continue

            # Bash direto
            if user_input.startswith("!"):
                bash_cmd = user_input[1:].strip()
                if bash_cmd:
                    tool = agent.registry.get("bash")
                    if tool:
                        console.print(f"  [tool.name]⚡ $ {bash_cmd}[/]")
                        output = tool.execute(command=bash_cmd, cwd=agent.cwd)
                        console.print(f"[muted]{output}[/]")
                continue

            # Multi-linha
            while user_input.endswith("\\"):
                user_input = user_input[:-1] + "\n"
                try:
                    user_input += prompt_session.prompt(
                        HTML('<style fg="#B8860B">  ... </style>'),
                    ).strip()
                except (EOFError, KeyboardInterrupt):
                    break

            # Mostra mensagem do usuário em dourado com box
            _show_user_message(user_input)

            # Turno do agente
            _run_agent_turn(agent, user_input)

        except (EOFError, KeyboardInterrupt):
            _separator("Fim da Sessão", style="gold")
            console.print(f"[gold]  Sessão salva. Até mais! 🦇[/]")
            save_session(agent.session)
            break


def _print_banner() -> None:
    """Banner de inicialização premium."""
    console.print()
    console.print(f"[{GOLD} bold]" + r"""
  ██████   █████  ████████ ███    ███  █████  ███    ███
  ██   ██ ██   ██    ██    ████  ████ ██   ██ ████  ████
  ██████  ███████    ██    ██ ████ ██ ███████ ██ ████ ██
  ██   ██ ██   ██    ██    ██  ██  ██ ██   ██ ██  ██  ██
  ██████  ██   ██    ██    ██      ██ ██   ██ ██      ██
""" + "[/]")
    _separator(style="dark_gold")
    console.print(f"  [{GOLD}]Agente de Código AI[/]  [muted]v{__version__}[/]")
    console.print(f"  [muted]Modelo: {config.BATMAM_MODEL}  │  Dir: {os.getcwd()}[/]")
    console.print(f"  [muted]/help para comandos  │  /exit para sair[/]")
    _separator(style="dark_gold")
    console.print()


def _show_user_message(message: str) -> None:
    """Mostra a mensagem do usuário em dourado dentro de uma box."""
    console.print()
    _user_header()
    # Mostra cada linha com indentação e cor dourada
    for line in message.splitlines():
        console.print(f"  [user_text]{line}[/]")
    _user_footer()
    console.print()


def _run_agent_turn(agent: Agent, message: str) -> None:
    """Executa um turno do agente com tratamento de erro."""
    global _in_streaming, _agent_box_open
    try:
        agent.run_turn(message)
    except KeyboardInterrupt:
        if _in_streaming:
            sys.stdout.write("\n")
            _in_streaming = False
        console.print("[warning]  Interrompido.[/]")
    except Exception as e:
        if _in_streaming:
            sys.stdout.write("\n")
            _in_streaming = False
        console.print(f"[error]  Erro: {e}[/]")
    finally:
        _close_agent_box()


# ── Entry Point ───────────────────────────────────────────────

def main() -> None:
    """Entry point principal do Batmam."""
    parser = argparse.ArgumentParser(
        prog="batmam",
        description="Batmam — Agente de código AI no terminal",
    )
    parser.add_argument("--version", "-v", action="version", version=f"Batmam v{__version__}")
    parser.add_argument("--model", "-m", help=f"Modelo (padrão: {config.BATMAM_MODEL})")
    parser.add_argument("--resume", "-r", help="ID da sessão para retomar")
    parser.add_argument("--auto-approve", "-y", action="store_true", help="Aprovar tudo automaticamente")
    parser.add_argument("--cwd", "-C", help="Diretório de trabalho inicial")
    parser.add_argument("prompt", nargs="*", help="Prompt inicial (opcional)")

    args = parser.parse_args()

    if args.cwd:
        target = Path(args.cwd).expanduser().resolve()
        if target.is_dir():
            os.chdir(target)
        else:
            console.print(f"[error]Diretório não encontrado: {target}[/]")
            sys.exit(1)

    if args.model:
        config.BATMAM_MODEL = args.model

    run_repl(args)


if __name__ == "__main__":
    main()
