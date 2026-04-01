"""CLI REPL interativo do Batmam v0.2.0 — com streaming, diff visual, skills, plan mode, tasks, cron, triggers, web, pipeline, backup."""

from __future__ import annotations
import os
import sys
import time
import argparse
import difflib
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
from .skills import create_default_skill_registry
from .tasks import get_task_manager
from .cron import get_cron_manager
from .triggers import get_trigger_server
from .pipeline import parse_pipeline, run_pipeline
from .backup import backup_memory, restore_memory, list_backups
from .logging import log_action
from .agent_types import list_agent_types
from . import config

# ── Tema estilo Claude Code — limpo, minimal ────────────────
GOLD = "#FFD700"
DARK_GOLD = "#B8860B"

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
    "user_text": "bold white",
    "agent_label": "bold #87CEEB",
    "diff_add": "bold green",
    "diff_del": "bold red",
    "plan_mode": "bold #FF6B6B",
    "result_border": "dim",
})

console = Console(theme=batmam_theme)

# ── Skill registry global ───────────────────────────────────
_skill_registry = create_default_skill_registry()


def _separator(label: str = "", style: str = "dim") -> None:
    if label:
        console.print(Rule(f" {label} ", style=style))
    else:
        console.print(Rule(style=style))


# ── ANSI helpers ────────────────────────────────────────────
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"
_CLEAR_LINE = "\033[2K\r"
_GOLD_ANSI = "\033[33m"
_CYAN_ANSI = "\033[36m"
_GREEN_ANSI = "\033[32m"
_RED_ANSI = "\033[31m"
_WHITE_ANSI = "\033[37m"

# ── Thinking Spinner (🦇 pulsando) ──────────────────────────
import threading as _threading

_spinner_thread: _threading.Thread | None = None
_spinner_stop = _threading.Event()

_BAT_FRAMES = [
    f"{_BOLD}{_GOLD_ANSI}🦇{_RESET}",
    f"{_BOLD}{_GOLD_ANSI}🦇{_RESET}",
    f"{_GOLD_ANSI}🦇{_RESET}",
    f"{_DIM}{_GOLD_ANSI}🦇{_RESET}",
    f"{_DIM}🦇{_RESET}",
    f"{_DIM}{_GOLD_ANSI}🦇{_RESET}",
    f"{_GOLD_ANSI}🦇{_RESET}",
    f"{_BOLD}{_GOLD_ANSI}🦇{_RESET}",
]
_DOTS_FRAMES = ["   ", ".  ", ".. ", "..."]


def _start_thinking_spinner() -> None:
    global _spinner_thread
    _spinner_stop.clear()

    def _spin():
        frame_idx = 0
        dots_idx = 0
        while not _spinner_stop.is_set():
            bat = _BAT_FRAMES[frame_idx % len(_BAT_FRAMES)]
            dots = _DOTS_FRAMES[dots_idx % len(_DOTS_FRAMES)]
            sys.stdout.write(f"{_CLEAR_LINE}  {bat} {_DIM}Pensando{dots}{_RESET}")
            sys.stdout.flush()
            frame_idx += 1
            if frame_idx % 2 == 0:
                dots_idx += 1
            _spinner_stop.wait(0.15)
        sys.stdout.write(f"{_CLEAR_LINE}")
        sys.stdout.flush()

    _spinner_thread = _threading.Thread(target=_spin, daemon=True, name="bat-spinner")
    _spinner_thread.start()


def _stop_thinking_spinner() -> None:
    global _spinner_thread
    _spinner_stop.set()
    if _spinner_thread and _spinner_thread.is_alive():
        _spinner_thread.join(timeout=1)
    _spinner_thread = None


# ── Estado global do streaming ────────────────────────────────
_streaming_buffer: list[str] = []
_in_streaming = False
_thinking_active = False
_stream_line_count = 0
_stream_collapsed = False
MAX_VISIBLE_LINES = 4


def on_text_delta(delta: str) -> None:
    """Streaming em tempo real — formato Claude Code."""
    global _in_streaming, _thinking_active, _stream_line_count, _stream_collapsed
    if _thinking_active:
        _stop_thinking_spinner()
        _thinking_active = False
    if not _in_streaming:
        _in_streaming = True
        _stream_line_count = 0
        _stream_collapsed = False

    _streaming_buffer.append(delta)
    newlines = delta.count("\n")
    if newlines > 0:
        _stream_line_count += newlines

    if not _stream_collapsed:
        if _stream_line_count <= MAX_VISIBLE_LINES:
            sys.stdout.write(delta)
            sys.stdout.flush()
        else:
            parts = delta.split("\n", 1)
            sys.stdout.write(parts[0])
            sys.stdout.flush()
            _stream_collapsed = True


def on_text_done(text: str) -> None:
    """Chamado quando o texto completo está pronto."""
    global _in_streaming, _stream_collapsed, _stream_line_count

    full_text = "".join(_streaming_buffer)
    total_lines = full_text.count("\n") + 1

    if _in_streaming:
        if _stream_collapsed and total_lines > MAX_VISIBLE_LINES:
            hidden = total_lines - MAX_VISIBLE_LINES
            sys.stdout.write(f"\n{_DIM}  ⎿ ... +{hidden} linhas{_RESET}")
        sys.stdout.write("\n")
        sys.stdout.flush()
        _in_streaming = False

    _streaming_buffer.clear()
    _stream_line_count = 0
    _stream_collapsed = False


def on_tool_call(name: str, args: dict) -> None:
    """Formato Claude Code: ⏵ ToolName detail"""
    global _in_streaming, _thinking_active
    if _thinking_active:
        _stop_thinking_spinner()
        _thinking_active = False
    if _in_streaming:
        sys.stdout.write("\n")
        sys.stdout.flush()
        _in_streaming = False

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
        detail = f"{args.get('operation', '')} {args.get('file_path', '')}"
    elif name.startswith("task_"):
        detail = args.get("title", args.get("task_id", ""))
    elif name.startswith("mcp__"):
        detail = str(args)[:80]

    # Formato: ⏵ tool_name detail
    sys.stdout.write(f"  {_CYAN_ANSI}⏵ {name}{_RESET} {_DIM}{detail}{_RESET}\n")
    sys.stdout.flush()


def on_tool_result(name: str, status: str, output: str) -> None:
    """Formato Claude Code: ⎿ resultado compactado."""
    if status == "error":
        sys.stdout.write(f"  {_RED_ANSI}⎿ ✗ erro{_RESET}\n")
        if output:
            for line in output.strip().splitlines()[:3]:
                sys.stdout.write(f"    {_RED_ANSI}{line[:120]}{_RESET}\n")
        sys.stdout.flush()
    elif status == "denied":
        sys.stdout.write(f"  {_GOLD_ANSI}⎿ ⊘ negado{_RESET}\n")
        sys.stdout.flush()
    else:
        if name == "edit" and "```diff" in output:
            _show_diff_output(output)
        elif output:
            lines = output.strip().splitlines()
            if len(lines) <= 5:
                for line in lines:
                    sys.stdout.write(f"  {_DIM}⎿ {line[:150]}{_RESET}\n")
            else:
                for line in lines[:3]:
                    sys.stdout.write(f"  {_DIM}⎿ {line[:150]}{_RESET}\n")
                sys.stdout.write(f"  {_DIM}⎿ ... +{len(lines) - 3} linhas{_RESET}\n")
        sys.stdout.flush()


def _show_diff_output(output: str) -> None:
    """Diff colorido no formato Claude Code."""
    in_diff = False
    count = 0
    for line in output.splitlines():
        if line.startswith("```diff"):
            in_diff = True
            continue
        if line.startswith("```") and in_diff:
            in_diff = False
            continue
        if in_diff:
            count += 1
            if count > 12:
                sys.stdout.write(f"  {_DIM}⎿ ... (diff truncado){_RESET}\n")
                break
            if line.startswith("+") and not line.startswith("+++"):
                sys.stdout.write(f"  {_GREEN_ANSI}⎿ {line}{_RESET}\n")
            elif line.startswith("-") and not line.startswith("---"):
                sys.stdout.write(f"  {_RED_ANSI}⎿ {line}{_RESET}\n")
            elif line.startswith("@@"):
                sys.stdout.write(f"  {_CYAN_ANSI}⎿ {line}{_RESET}\n")
            else:
                sys.stdout.write(f"  {_DIM}⎿ {line}{_RESET}\n")
    sys.stdout.flush()


def ask_confirmation(message: str) -> bool:
    sys.stdout.write(f"\n  {_GOLD_ANSI}⚠ Permissão necessária{_RESET}\n")
    for line in message.splitlines():
        sys.stdout.write(f"  {_DIM}{line}{_RESET}\n")
    sys.stdout.flush()
    try:
        resp = console.input(f"  [{GOLD}](s)im / (n)ão / (a)sempre: [/]").strip().lower()
        if resp in ("a", "sempre", "always"):
            config.AUTO_APPROVE_BASH = True
            config.AUTO_APPROVE_WRITE = True
            console.print("  [info]Auto-approve ativado.[/]")
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

    # ── Skills (verificar primeiro) ──
    skill_name = command[1:]  # Remove '/'
    skill = _skill_registry.get(skill_name)
    if skill:
        expanded_prompt = skill.execute(arg)
        console.print(f"  [muted]/{skill_name} →[/]")
        _run_agent_turn(agent, expanded_prompt)
        return True

    if command in ("/help", "/h"):
        _show_help()
        return True

    elif command in ("/exit", "/quit", "/q"):
        get_cron_manager().stop_all()
        save_session(agent.session)
        console.print(f"\n[muted]  Sessão salva. Até mais! 🦇[/]")
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
            console.print(f"[info]  Modelo atual: {agent.model}  │  Provider: {config.BATMAM_PROVIDER}[/]")
            if config.BATMAM_PROVIDER == "anthropic":
                console.print("[muted]  Disponíveis: claude-sonnet-4-20250514, claude-opus-4-20250514, claude-haiku-4-5-20251001[/]")
            else:
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

    # ── Plan Mode ──
    elif command == "/plan":
        if arg.lower() == "off":
            agent.plan_mode = False
            console.print("[success]  Plan mode desativado. Escrita liberada.[/]")
        else:
            agent.plan_mode = True
            console.print("[plan_mode]  Plan mode ativado. Apenas leitura permitida.[/]")
            console.print("[muted]  Use /plan off para desativar.[/]")
        return True

    # ── Memory ──
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
                    desc = f"  [muted]{m.get('description', '')}[/]" if m.get("description") else ""
                    console.print(f"    [info]{m['name']}[/]  [muted]({m['type']})[/]{desc}")
        return True

    # ── Tasks ──
    elif command == "/tasks":
        manager = get_task_manager()
        tasks = manager.list_all()
        if not tasks:
            console.print("[muted]  Nenhuma task.[/]")
        else:
            icons = {"pending": "○", "in_progress": "◑", "completed": "●", "failed": "✗"}
            console.print(f"\n[accent]  Tasks ({len(tasks)}):[/]")
            for t in tasks:
                icon = icons.get(t.status.value, "?")
                style = "success" if t.status.value == "completed" else ("error" if t.status.value == "failed" else "info")
                console.print(f"    {icon} [{style}][{t.id}][/] {t.title}  [muted]({t.status.value})[/]")
            console.print(f"  [muted]{manager.summary()}[/]")
        return True

    # ── Cron ──
    elif command == "/cron":
        return _handle_cron(arg, agent)

    # ── Triggers ──
    elif command == "/trigger":
        return _handle_trigger(arg, agent)

    # ── Diff ──
    elif command == "/diff":
        import subprocess
        try:
            result = subprocess.run(
                "git diff --stat", shell=True, capture_output=True, text=True, cwd=agent.cwd
            )
            if result.stdout.strip():
                # Mostra diff colorido
                diff_result = subprocess.run(
                    "git diff", shell=True, capture_output=True, text=True, cwd=agent.cwd
                )
                if diff_result.stdout:
                    for line in diff_result.stdout.splitlines()[:60]:
                        if line.startswith("+") and not line.startswith("+++"):
                            console.print(f"  [diff_add]{line}[/]")
                        elif line.startswith("-") and not line.startswith("---"):
                            console.print(f"  [diff_del]{line}[/]")
                        elif line.startswith("@@"):
                            console.print(f"  [accent]{line}[/]")
                        else:
                            console.print(f"  [muted]{line}[/]")
                console.print(f"\n[muted]{result.stdout}[/]")
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

    elif command == "/agents":
        types = list_agent_types()
        console.print(f"\n[accent]  Tipos de Agent ({len(types)}):[/]")
        for at in types:
            tools_str = ", ".join(sorted(at.allowed_tools)[:6]) if at.allowed_tools else "todas"
            console.print(f"    [info]{at.name}[/]  [muted]{at.description[:60]}[/]")
            console.print(f"      [muted]Tools: {tools_str} | Max iter: {at.max_iterations}[/]")
        return True

    elif command == "/stale":
        from .memory import cleanup_stale_memories
        stale = cleanup_stale_memories(agent.cwd)
        if stale:
            console.print(f"\n[warning]  Memórias potencialmente stale ({len(stale)}):[/]")
            for s in stale:
                console.print(f"    [muted]{s}[/]")
        else:
            console.print("[success]  Nenhuma memória stale detectada.[/]")
        return True

    elif command == "/skills":
        skills = _skill_registry.list_all()
        console.print(f"\n[accent]  Skills ({len(skills)}):[/]")
        for s in skills:
            aliases = f" ({', '.join('/' + a for a in s.aliases)})" if s.aliases else ""
            cat = f" [{s.category}]" if s.category != "built-in" else ""
            console.print(f"    [info]/{s.name}[/]{aliases}  [muted]{s.description}{cat}[/]")
        return True

    elif command == "/background":
        bg_status = agent.get_background_status()
        if not bg_status:
            console.print("[muted]  Nenhum background agent.[/]")
        else:
            console.print(f"\n[accent]  Background Agents ({len(bg_status)}):[/]")
            for info in bg_status:
                style = "success" if info["status"] == "completed" else ("error" if info["status"] == "error" else "info")
                console.print(
                    f"    [{style}]{info['status']}[/]  "
                    f"[info]{info['id']}[/]  [muted]{info['description']}[/]"
                )
        return True

    elif command == "/web":
        _start_web_server(arg)
        return True

    # ── Pipeline (#25) ──
    elif command == "/pipeline":
        if not arg:
            console.print("[error]  Use: /pipeline \"etapa 1\" -> \"etapa 2\" -> \"etapa 3\"[/]")
            console.print("[muted]  Ex: /pipeline \"analisa código\" -> \"gera testes\" -> \"faz review\"[/]")
            return True
        return _handle_pipeline(arg, agent)

    # ── Backup (#22) ──
    elif command == "/backup":
        return _handle_backup(arg)

    # ── Chatwoot (#20) ──
    elif command == "/chatwoot":
        return _handle_chatwoot(arg)

    return False


def _handle_cron(arg: str, agent: Agent) -> bool:
    """Processa comandos /cron."""
    cron = get_cron_manager()

    if not arg or arg == "list":
        jobs = cron.list_all()
        if not jobs:
            console.print("[muted]  Nenhum cron job.[/]")
        else:
            console.print(f"\n[accent]  Cron Jobs ({len(jobs)}):[/]")
            for j in jobs:
                interval = cron.format_interval(j.interval_seconds)
                status = "[success]ativo[/]" if j.active else "[muted]pausado[/]"
                console.print(
                    f"    {status}  [info]{j.id}[/]  cada {interval}  "
                    f"[muted]{j.prompt[:40]}... ({j.run_count}x)[/]"
                )
        return True

    parts = arg.split(maxsplit=1)
    subcmd = parts[0].lower()

    if subcmd == "create" and len(parts) > 1:
        # /cron create 5m "prompt aqui"
        create_parts = parts[1].split(maxsplit=1)
        if len(create_parts) < 2:
            console.print("[error]  Use: /cron create <intervalo> <prompt>[/]")
            console.print("[muted]  Ex: /cron create 5m 'verificar status do deploy'[/]")
            return True
        interval_str = create_parts[0]
        prompt = create_parts[1].strip("'\"")

        # Configura agent factory
        def factory():
            return Agent(
                cwd=agent.cwd,
                model=agent.model,
                on_text_delta=lambda t: None,
                on_text_done=lambda t: None,
                auto_approve=True,
                is_subagent=True,
            )
        cron.set_agent_factory(factory)

        try:
            job = cron.create(prompt, interval_str)
            console.print(
                f"[success]  Cron job criado: {job.id}[/]\n"
                f"  [muted]Intervalo: {interval_str} | Prompt: {prompt[:60]}[/]"
            )
        except ValueError as e:
            console.print(f"[error]  {e}[/]")
        return True

    elif subcmd == "delete" and len(parts) > 1:
        job_id = parts[1].strip()
        if cron.delete(job_id):
            console.print(f"[success]  Cron job {job_id} deletado.[/]")
        else:
            console.print(f"[error]  Job '{job_id}' não encontrado.[/]")
        return True

    elif subcmd == "pause" and len(parts) > 1:
        job_id = parts[1].strip()
        if cron.pause(job_id):
            console.print(f"[info]  Cron job {job_id} pausado.[/]")
        else:
            console.print(f"[error]  Job '{job_id}' não encontrado.[/]")
        return True

    elif subcmd == "resume" and len(parts) > 1:
        job_id = parts[1].strip()
        if cron.resume(job_id):
            console.print(f"[success]  Cron job {job_id} retomado.[/]")
        else:
            console.print(f"[error]  Job '{job_id}' não encontrado.[/]")
        return True

    console.print("[error]  Uso: /cron [list|create|delete|pause|resume][/]")
    return True


def _handle_trigger(arg: str, agent: Agent) -> bool:
    """Processa comandos /trigger."""
    trigger = get_trigger_server()

    parts = arg.split(maxsplit=1) if arg else [""]
    subcmd = parts[0].lower()

    if subcmd == "start":
        port = 7777
        if len(parts) > 1:
            try:
                port = int(parts[1])
            except ValueError:
                pass
        trigger.port = port

        def factory():
            return Agent(
                cwd=agent.cwd,
                model=agent.model,
                on_text_delta=lambda t: None,
                on_text_done=lambda t: None,
                auto_approve=True,
                is_subagent=True,
            )
        trigger.set_agent_factory(factory)
        info = trigger.start()
        console.print(f"[success]  {info}[/]")
        return True

    elif subcmd == "stop":
        info = trigger.stop()
        console.print(f"[info]  {info}[/]")
        return True

    elif subcmd == "status" or not subcmd:
        if trigger.running:
            console.print(f"[success]  Trigger server rodando na porta {trigger.port}[/]")
            console.print(f"  [muted]Token: {trigger.token}[/]")
            results = trigger.list_results()
            if results:
                console.print(f"\n[accent]  Últimos triggers ({len(results)}):[/]")
                for r in results[:10]:
                    style = "success" if r.status == "completed" else ("error" if r.status == "error" else "info")
                    console.print(f"    [{style}]{r.status}[/]  [info]{r.id}[/]  [muted]{r.prompt[:40]}[/]")
        else:
            console.print("[muted]  Trigger server não está rodando.[/]")
            console.print("[muted]  Use /trigger start [porta][/]")
        return True

    console.print("[error]  Uso: /trigger [start|stop|status][/]")
    return True


def _handle_pipeline(arg: str, agent: Agent) -> bool:
    """Feature #25: Processa /pipeline."""
    prompts = parse_pipeline(arg)
    if len(prompts) < 2:
        console.print("[error]  Pipeline precisa de pelo menos 2 etapas separadas por '->'[/]")
        return True

    console.print(f"\n[accent]  Pipeline — {len(prompts)} etapas:[/]")
    for i, p in enumerate(prompts, 1):
        console.print(f"    [muted]{i}. {p}[/]")
    console.print()

    def factory():
        return Agent(
            cwd=agent.cwd,
            model=agent.model,
            on_text_delta=lambda t: None,
            on_text_done=lambda t: None,
            auto_approve=True,
            is_subagent=True,
        )

    def on_step_start(i: int, prompt: str):
        console.print(f"  [accent]◑ Etapa {i + 1}:[/] {prompt[:60]}")
        log_action("pipeline_step_start", f"Etapa {i+1}: {prompt[:50]}")

    def on_step_done(i: int, status: str, output: str):
        icon = "[success]✓[/]" if status == "completed" else "[error]✗[/]"
        console.print(f"  {icon} Etapa {i + 1} — {status}")
        if output and status == "completed":
            lines = output.strip().splitlines()
            for line in lines[:3]:
                console.print(f"    [muted]{line[:100]}[/]")
            if len(lines) > 3:
                console.print(f"    [muted]... ({len(lines)} linhas total)[/]")

    result = run_pipeline(prompts, factory, on_step_start, on_step_done)
    console.print(f"\n[accent]  Pipeline {result.status} em {result.total_duration:.1f}s[/]")
    return True


def _handle_backup(arg: str) -> bool:
    """Feature #22: Processa /backup."""
    parts = arg.split(maxsplit=1) if arg else [""]
    subcmd = parts[0].lower()

    if subcmd == "create" or not subcmd:
        result = backup_memory()
        style = "success" if "criado" in result.lower() else "error"
        console.print(f"[{style}]  {result}[/]")
        return True

    elif subcmd == "list":
        backups = list_backups()
        if not backups:
            console.print("[muted]  Nenhum backup encontrado.[/]")
        else:
            console.print(f"\n[accent]  Backups ({len(backups)}):[/]")
            for b in backups[:15]:
                console.print(f"    [info]{b['name']}[/]  {b['created']}  [muted]{b['size_kb']} KB[/]")
        return True

    elif subcmd == "restore" and len(parts) > 1:
        name = parts[1].strip()
        result = restore_memory(name)
        style = "success" if "restaurado" in result.lower() else "error"
        console.print(f"[{style}]  {result}[/]")
        return True

    console.print("[error]  Uso: /backup [create|list|restore <nome>][/]")
    return True


def _handle_chatwoot(arg: str) -> bool:
    """Feature #20: Configura integração Chatwoot."""
    trigger = get_trigger_server()
    parts = arg.split(maxsplit=1) if arg else [""]
    subcmd = parts[0].lower()

    if subcmd == "setup" and len(parts) > 1:
        token = parts[1].strip()
        trigger.configure_chatwoot(token)
        console.print(f"[success]  Chatwoot configurado.[/]")
        console.print(f"  [muted]Token: {token[:8]}...[/]")
        console.print(f"  [muted]Webhook URL: POST http://localhost:{trigger.port}/webhook/chatwoot[/]")
        console.print(f"  [muted]Eventos: {', '.join(trigger._chatwoot_events)}[/]")
        return True

    elif subcmd == "status":
        if trigger._chatwoot_token:
            console.print(f"[success]  Chatwoot configurado[/]")
            console.print(f"  [muted]Eventos: {', '.join(trigger._chatwoot_events)}[/]")
            console.print(f"  [muted]Webhook: POST http://localhost:{trigger.port}/webhook/chatwoot[/]")
        else:
            console.print("[muted]  Chatwoot não configurado.[/]")
        return True

    console.print("[error]  Uso: /chatwoot setup <token> | /chatwoot status[/]")
    console.print("[muted]  Configure o webhook no Chatwoot para:[/]")
    console.print(f"  [muted]POST http://<seu-ip>:{trigger.port}/webhook/chatwoot[/]")
    return True


def _start_web_server(arg: str) -> None:
    """Inicia o servidor web FastAPI."""
    port = 8080
    if arg:
        try:
            port = int(arg)
        except ValueError:
            pass

    try:
        import uvicorn
        from .webapp import get_app
        app = get_app()
        console.print(f"[success]  Web app iniciando em http://0.0.0.0:{port}[/]")
        console.print("[muted]  Ctrl+C para parar[/]")
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
    except ImportError:
        console.print("[error]  Instale: pip install fastapi uvicorn[/]")
    except Exception as e:
        console.print(f"[error]  Erro: {e}[/]")


def _show_help() -> None:
    console.print(Panel(
        "[gold]Conversa[/]\n"
        "  Digite normalmente para conversar com o agente\n"
        "  [muted]Termine com \\\\ para multi-linha[/]\n"
        "  [muted]!comando[/]  — executa bash direto\n"
        "\n"
        "[gold]Skills (atalhos)[/]\n"
        "  [info]/commit[/]          — commit inteligente\n"
        "  [info]/review[/]          — code review\n"
        "  [info]/test[/]            — gera testes\n"
        "  [info]/refactor[/]        — refatora código\n"
        "  [info]/explain[/]         — explica código\n"
        "  [info]/fix[/]             — encontra bugs\n"
        "  [info]/init[/]            — inicializa projeto\n"
        "  [info]/simplify[/]        — revisa qualidade\n"
        "  [info]/skills[/]          — lista todos os skills\n"
        "\n"
        "[gold]Plan Mode[/]\n"
        "  [info]/plan[/]            — ativa (somente leitura)\n"
        "  [info]/plan off[/]        — desativa\n"
        "\n"
        "[gold]Tasks[/]\n"
        "  [info]/tasks[/]           — lista tasks\n"
        "\n"
        "[gold]Navegação[/]\n"
        "  [info]/cd <dir>[/]        — muda diretório\n"
        "  [info]/cwd[/]             — mostra diretório\n"
        "  [info]/status[/]          — git status\n"
        "  [info]/diff[/]            — git diff colorido\n"
        "\n"
        "[gold]Sessões[/]\n"
        "  [info]/sessions[/]        — lista sessões\n"
        "  [info]/resume <id>[/]     — retoma sessão\n"
        "  [info]/save[/]            — salva sessão\n"
        "  [info]/clear[/]           — limpa histórico\n"
        "  [info]/compact[/]         — compacta contexto\n"
        "\n"
        "[gold]Memória[/]\n"
        "  [info]/memory[/]               — lista memórias\n"
        "  [info]/memory save <n> <t>[/]  — salva memória\n"
        "  [info]/memory delete <n>[/]    — deleta memória\n"
        "\n"
        "[gold]Cron & Triggers[/]\n"
        "  [info]/cron[/] [list|create|delete] — cron jobs\n"
        "  [info]/trigger[/] [start|stop|status] — HTTP triggers\n"
        "  [info]/chatwoot[/] setup <token>   — integração Chatwoot\n"
        "\n"
        "[gold]Pipeline & Backup[/]\n"
        "  [info]/pipeline[/] \"a\" -> \"b\" -> \"c\" — multi-agent pipeline\n"
        "  [info]/backup[/] [create|list|restore] — backup de memória\n"
        "\n"
        "[gold]Config[/]\n"
        "  [info]/model[/] [nome]    — mostra/altera modelo\n"
        "  [info]/tokens[/]          — uso de tokens\n"
        "  [info]/approve[/]         — auto-approve\n"
        "  [info]/background[/]      — background agents\n"
        "\n"
        "[gold]Extensões[/]\n"
        "  [info]/tools[/]           — lista ferramentas\n"
        "  [info]/hooks[/]           — lista hooks\n"
        "  [info]/plugins[/]         — lista plugins\n"
        "  [info]/mcp[/]             — servidores MCP\n"
        "  [info]/web[/] [porta]     — web app + /dashboard\n"
        "\n"
        "  [info]/exit[/]            — sai do Batmam\n",
        title=f"[{GOLD}]🦇 Batmam v{__version__} — Ajuda[/]",
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
        _run_agent_turn(agent, initial_prompt)

    # Loop REPL
    while True:
        try:
            # Prompt limpo estilo Claude Code
            if agent.plan_mode:
                prompt_html = HTML('<style fg="#FF6B6B">[PLAN] </style><style fg="#FFD700" bold="true">&gt; </style>')
            else:
                prompt_html = HTML('<style fg="#FFD700" bold="true">&gt; </style>')

            user_input = prompt_session.prompt(prompt_html).strip()

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

            # Não repete a mensagem — o usuário já viu o que digitou no prompt
            _run_agent_turn(agent, user_input)

        except KeyboardInterrupt:
            console.print("\n[muted]  (Ctrl+C — use /exit para sair)[/]")
            continue
        except EOFError:
            get_cron_manager().stop_all()
            console.print(f"\n[muted]  Sessão salva. Até mais! 🦇[/]")
            save_session(agent.session)
            break
        except Exception as e:
            console.print(f"\n[error]  Erro inesperado: {e}[/]")
            continue


def _print_banner() -> None:
    provider = config.BATMAM_PROVIDER.capitalize()
    console.print()
    console.print(f"  [{GOLD} bold]🦇 Batmam[/]  [muted]v{__version__}[/]")
    console.print(f"  [muted]{config.BATMAM_MODEL} · {provider} · {os.getcwd()}[/]")
    console.print(f"  [muted]/help para comandos · /exit para sair[/]")
    console.print()


def _run_agent_turn(agent: Agent, message: str) -> None:
    global _in_streaming, _thinking_active
    try:
        log_action("repl_turn", message[:80])
        _thinking_active = True
        _start_thinking_spinner()
        agent.run_turn(message)
    except KeyboardInterrupt:
        _stop_thinking_spinner()
        _thinking_active = False
        if _in_streaming:
            sys.stdout.write("\n")
            _in_streaming = False
        console.print("[warning]  Interrompido.[/]")
    except Exception as e:
        _stop_thinking_spinner()
        _thinking_active = False
        if _in_streaming:
            sys.stdout.write("\n")
            _in_streaming = False
        console.print(f"[error]  Erro: {e}[/]")
    finally:
        if _thinking_active:
            _stop_thinking_spinner()
            _thinking_active = False


# ── Entry Point ───────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="batmam",
        description="Batmam — Agente de código AI no terminal",
    )
    parser.add_argument("--version", "-v", action="version", version=f"Batmam v{__version__}")
    parser.add_argument("--model", "-m", help=f"Modelo (padrão: {config.BATMAM_MODEL})")
    parser.add_argument("--resume", "-r", help="ID da sessão para retomar")
    parser.add_argument("--auto-approve", "-y", action="store_true", help="Aprovar tudo automaticamente")
    parser.add_argument("--cwd", "-C", help="Diretório de trabalho inicial")
    parser.add_argument("--web", action="store_true", help="Iniciar web app")
    parser.add_argument("--port", type=int, default=8080, help="Porta do web server (padrão: 8080)")
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

    # Web mode
    if args.web:
        _start_web_server(str(args.port))
        return

    run_repl(args)


if __name__ == "__main__":
    main()
