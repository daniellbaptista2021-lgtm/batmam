"""CLI REPL do System Clow v0.2.0 — interface estilo Claude Code com ∞ roxo pulsante."""

from __future__ import annotations
import os
import sys
import time
import argparse
import threading
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text
from rich.theme import Theme
from rich.rule import Rule
from rich.syntax import Syntax
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML

from . import __version__
from .agent import Agent
from .session import save_session, load_session, list_sessions
from .memory import list_memories, save_memory, delete_memory
from .skills import create_default_skill_registry
from .tasks import get_task_manager
from .cron import get_cron_manager
from .triggers import get_trigger_server
from .pipeline import parse_pipeline, run_pipeline
from .backup import backup_memory, restore_memory, list_backups
from .logging import log_action
from .agent_types import list_agent_types
from . import config

# ── Cores System Clow ────────────────────────────────────────
GOLD = "#FFD700"
PURPLE = "#A855F7"
DARK_PURPLE = "#7C3AED"

clow_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "muted": "dim",
    "purple": PURPLE,
    "gold": GOLD,
    "diff_add": "bold green",
    "diff_del": "bold red",
})

console = Console(theme=clow_theme)
_skill_registry = create_default_skill_registry()

# ── ANSI codes ───────────────────────────────────────────────
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CLEAR_LINE = "\033[2K\r"
_PURPLE_B = "\033[95m"     # roxo brilhante
_PURPLE_D = "\033[35m"     # roxo escuro
_PURPLE_M = "\033[35m"     # roxo médio
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_WHITE = "\033[37m"
_BLUE = "\033[94m"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ∞ INFINITY PULSE — identidade visual do Clow
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_inf_thread: threading.Thread | None = None
_inf_stop = threading.Event()
_inf_state = "Pensando"

_INF_FRAMES = [
    f"{_BOLD}{_PURPLE_B}∞{_RESET}",   # brilhante
    f"{_PURPLE_B}∞{_RESET}",           # médio-alto
    f"{_PURPLE_D}∞{_RESET}",           # médio
    f"{_DIM}{_PURPLE_D}∞{_RESET}",    # suave
    f"{_PURPLE_D}∞{_RESET}",           # médio
    f"{_PURPLE_B}∞{_RESET}",           # médio-alto
]
_DOTS = ["   ", ".  ", ".. ", "..."]


def _inf_start(state: str = "Pensando") -> None:
    global _inf_thread, _inf_state
    _inf_state = state
    _inf_stop.clear()

    def _pulse():
        fi = 0
        di = 0
        while not _inf_stop.is_set():
            inf = _INF_FRAMES[fi % len(_INF_FRAMES)]
            dots = _DOTS[di % len(_DOTS)]
            sys.stdout.write(f"{_CLEAR_LINE}  {inf} {_DIM}{_inf_state}{dots}{_RESET}")
            sys.stdout.flush()
            fi += 1
            if fi % 2 == 0:
                di += 1
            _inf_stop.wait(0.2)
        sys.stdout.write(_CLEAR_LINE)
        sys.stdout.flush()

    _inf_thread = threading.Thread(target=_pulse, daemon=True, name="clow-inf")
    _inf_thread.start()


def _inf_update(state: str) -> None:
    global _inf_state
    _inf_state = state


def _inf_stop_now() -> None:
    global _inf_thread
    _inf_stop.set()
    if _inf_thread and _inf_thread.is_alive():
        _inf_thread.join(timeout=1)
    _inf_thread = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STREAMING + TOOL DISPLAY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_streaming_buffer: list[str] = []
_in_streaming = False
_thinking_active = False
_first_turn = True  # Não mostra divisória antes do primeiro turno

# Colapsamento APENAS para output de tools (nunca para resposta textual)
TOOL_OUTPUT_MAX_LINES = 8


def on_text_delta(delta: str) -> None:
    """Acumula tokens da resposta. Streaming visual mostra texto cru, Markdown renderizado no final."""
    global _in_streaming, _thinking_active

    if _thinking_active:
        _inf_stop_now()
        _thinking_active = False
        sys.stdout.write("\n")

    if not _in_streaming:
        _in_streaming = True
        sys.stdout.write("  ")

    _streaming_buffer.append(delta)

    # Streaming visual: mostra texto cru com indentação (typewriter effect)
    indented = delta.replace("\n", "\n  ")
    sys.stdout.write(indented)
    sys.stdout.flush()


def on_text_done(text: str) -> None:
    """Finaliza streaming — re-renderiza como Markdown formatado."""
    global _in_streaming

    full_text = "".join(_streaming_buffer)
    _streaming_buffer.clear()

    if _in_streaming:
        # Conta linhas exibidas pelo streaming cru para apagar
        raw_lines = full_text.count("\n") + 1

        # Apaga o texto cru do streaming (move cursor para cima e limpa)
        sys.stdout.write("\r")
        for _ in range(raw_lines):
            sys.stdout.write(f"\033[A{_CLEAR_LINE}")
        sys.stdout.flush()

        # Re-renderiza como Markdown formatado com rich
        if full_text.strip():
            md = Markdown(full_text.strip())
            console.print(md, width=min(console.width - 4, 100))

        console.print()
        _in_streaming = False


def _tool_label(name: str, args: dict) -> str:
    """Gera label descritiva da tool no estilo Claude Code."""
    if name == "bash":
        return f"Run command: {args.get('command', '')[:100]}"
    elif name == "read":
        return f"Read file: {args.get('file_path', '')}"
    elif name == "write":
        return f"Write file: {args.get('file_path', '')}"
    elif name == "edit":
        return f"Edit file: {args.get('file_path', '')}"
    elif name == "glob":
        return f"Search files: {args.get('pattern', '')}"
    elif name == "grep":
        return f"Search content: {args.get('pattern', '')}"
    elif name == "agent":
        return f"Launch agent: {args.get('description', args.get('task', '')[:50])}"
    elif name == "web_search":
        return f"Web search: {args.get('query', '')}"
    elif name == "web_fetch":
        return f"Fetch URL: {args.get('url', '')[:80]}"
    elif name == "notebook_edit":
        return f"Notebook: {args.get('operation', '')} {args.get('file_path', '')}"
    elif name.startswith("task_"):
        action = name.replace("task_", "").capitalize()
        return f"Task {action}: {args.get('title', args.get('task_id', ''))}"
    elif name.startswith("mcp__"):
        return f"MCP: {name.split('__')[-1]}"
    return f"{name}"


def on_tool_call(name: str, args: dict) -> None:
    """Formato Claude Code: ⏺ Label descritiva."""
    global _in_streaming, _thinking_active

    if _thinking_active:
        _inf_update(f"Executando {name}")

    if _in_streaming:
        sys.stdout.write("\n")
        sys.stdout.flush()
        _in_streaming = False

    label = _tool_label(name, args)
    sys.stdout.write(f"  {_BLUE}⏺{_RESET} {label}\n")
    sys.stdout.flush()


def on_tool_result(name: str, status: str, output: str) -> None:
    """Resultado compactado com ⎿."""
    if status == "error":
        sys.stdout.write(f"  {_RED}⎿ Error{_RESET}\n")
        if output:
            for line in output.strip().splitlines()[:3]:
                sys.stdout.write(f"    {_RED}{line[:120]}{_RESET}\n")
        sys.stdout.flush()
    elif status == "denied":
        sys.stdout.write(f"  {_RED}⎿ Action cancelled{_RESET}\n")
        sys.stdout.flush()
    else:
        if name == "edit" and "```diff" in output:
            _show_diff(output)
        elif output:
            lines = output.strip().splitlines()
            if len(lines) <= TOOL_OUTPUT_MAX_LINES:
                for line in lines:
                    sys.stdout.write(f"  {_DIM}⎿ {line[:150]}{_RESET}\n")
            else:
                for line in lines[:4]:
                    sys.stdout.write(f"  {_DIM}⎿ {line[:150]}{_RESET}\n")
                sys.stdout.write(f"  {_DIM}⎿ ... +{len(lines) - 4} lines{_RESET}\n")
        sys.stdout.write("\n")
        sys.stdout.flush()


def _show_diff(output: str) -> None:
    """Diff colorido."""
    in_diff = False
    count = 0
    for line in output.splitlines():
        if line.startswith("```diff"):
            in_diff = True
            continue
        if line.startswith("```") and in_diff:
            break
        if in_diff:
            count += 1
            if count > 20:
                sys.stdout.write(f"  {_DIM}⎿ ... (diff truncated){_RESET}\n")
                break
            if line.startswith("+") and not line.startswith("+++"):
                sys.stdout.write(f"  {_GREEN}⎿ {line}{_RESET}\n")
            elif line.startswith("-") and not line.startswith("---"):
                sys.stdout.write(f"  {_RED}⎿ {line}{_RESET}\n")
            elif line.startswith("@@"):
                sys.stdout.write(f"  {_CYAN}⎿ {line}{_RESET}\n")
            else:
                sys.stdout.write(f"  {_DIM}⎿ {line}{_RESET}\n")
    sys.stdout.flush()


def ask_confirmation(message: str) -> bool:
    """Permissão estilo Claude Code: (y)es / (n)o / (a)lways allow."""
    sys.stdout.write(f"\n  Do you want to allow this action?\n\n")
    for line in message.splitlines():
        sys.stdout.write(f"  {_DIM}{line}{_RESET}\n")
    sys.stdout.write(f"\n  ({_YELLOW}y{_RESET})es / ({_YELLOW}n{_RESET})o / ({_YELLOW}a{_RESET})lways allow  ")
    sys.stdout.flush()
    try:
        resp = console.input("").strip().lower()
        if resp in ("a", "always"):
            config.AUTO_APPROVE_BASH = True
            config.AUTO_APPROVE_WRITE = True
            sys.stdout.write(f"  {_DIM}Auto-approve enabled for this session.{_RESET}\n\n")
            sys.stdout.flush()
            return True
        if resp in ("y", "yes", "s", "sim", ""):
            return True
        sys.stdout.write(f"  {_RED}Action cancelled{_RESET}\n\n")
        sys.stdout.flush()
        return False
    except (EOFError, KeyboardInterrupt):
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SLASH COMMANDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def handle_slash_command(cmd: str, agent: Agent) -> bool:
    parts = cmd.strip().split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    # Skills
    skill_name = command[1:]
    skill = _skill_registry.get(skill_name)
    if skill:
        expanded_prompt = skill.execute(arg)
        sys.stdout.write(f"  {_DIM}/{skill_name} →{_RESET}\n")
        _run_agent_turn(agent, expanded_prompt)
        return True

    if command in ("/help", "/h"):
        _show_help()
        return True

    elif command in ("/exit", "/quit", "/q"):
        get_cron_manager().stop_all()
        save_session(agent.session)
        sys.stdout.write(f"\n  {_DIM}Session saved. Goodbye! 🃏{_RESET}\n")
        sys.exit(0)

    elif command in ("/clear", "/reset"):
        system_msg = agent.session.messages[0] if agent.session.messages else None
        agent.session.messages = [system_msg] if system_msg else []
        console.print("  [muted]History cleared.[/]")
        return True

    elif command == "/sessions":
        sessions = list_sessions()
        if not sessions:
            console.print("  [muted]No saved sessions.[/]")
        else:
            console.print(f"\n  [purple]Sessions ({len(sessions)}):[/]")
            for s in sessions[:20]:
                ts = time.strftime("%d/%m %H:%M", time.localtime(s["created_at"]))
                console.print(f"    [info]{s['id']}[/]  {ts}  [muted]{s['messages']} msgs[/]")
        return True

    elif command == "/resume":
        if not arg:
            console.print("  [error]Use: /resume <session_id>[/]")
            return True
        loaded = load_session(arg.strip())
        if loaded:
            agent.session = loaded
            console.print(f"  [success]Session {arg} restored ({len(loaded.messages)} msgs).[/]")
        else:
            console.print(f"  [error]Session '{arg}' not found.[/]")
        return True

    elif command == "/save":
        save_session(agent.session)
        console.print(f"  [success]Session saved: {agent.session.id}[/]")
        return True

    elif command == "/model":
        if arg:
            agent.model = arg.strip()
            config.CLOW_MODEL = arg.strip()
            console.print(f"  [info]Model: {agent.model}[/]")
        else:
            console.print(f"  [info]Model: {agent.model}  ·  Provider: {config.CLOW_PROVIDER}[/]")
            if config.CLOW_PROVIDER == "anthropic":
                console.print("  [muted]claude-sonnet-4-20250514, claude-opus-4-20250514, claude-haiku-4-5-20251001[/]")
            else:
                console.print("  [muted]gpt-4.1, gpt-4.1-mini, o3, o4-mini[/]")
        return True

    elif command == "/tokens":
        s = agent.session
        total = s.total_tokens_in + s.total_tokens_out
        console.print(f"  [info]Tokens  In: {s.total_tokens_in:,}  Out: {s.total_tokens_out:,}  Total: {total:,}[/]")
        return True

    elif command == "/cwd":
        console.print(f"  [info]{agent.cwd}[/]")
        return True

    elif command == "/cd":
        if not arg:
            console.print("  [error]Use: /cd <dir>[/]")
            return True
        new_dir = Path(arg).expanduser().resolve()
        if new_dir.is_dir():
            os.chdir(new_dir)
            agent.cwd = str(new_dir)
            console.print(f"  [info]{new_dir}[/]")
        else:
            console.print(f"  [error]Not found: {new_dir}[/]")
        return True

    elif command == "/approve":
        config.AUTO_APPROVE_BASH = True
        config.AUTO_APPROVE_WRITE = True
        console.print("  [warning]Auto-approve enabled.[/]")
        return True

    elif command == "/compact":
        before = len(agent.session.messages)
        agent._maybe_compact()
        after = len(agent.session.messages)
        console.print(f"  [info]Compacted: {before} → {after} messages[/]")
        return True

    elif command == "/plan":
        if arg.lower() == "off":
            agent.plan_mode = False
            console.print("  [success]Plan mode off. Write enabled.[/]")
        else:
            agent.plan_mode = True
            console.print(f"  [{PURPLE}]Plan mode on. Read-only.[/]")
            console.print("  [muted]Use /plan off to disable.[/]")
        return True

    elif command == "/memory":
        if arg.startswith("save "):
            mem_parts = arg[5:].split(maxsplit=1)
            if len(mem_parts) < 2:
                console.print("  [error]Use: /memory save <name> <content>[/]")
            else:
                save_memory(mem_parts[0], mem_parts[1])
                console.print(f"  [success]Memory saved: {mem_parts[0]}[/]")
        elif arg.startswith("delete "):
            name = arg[7:].strip()
            if delete_memory(name):
                console.print(f"  [success]Memory deleted: {name}[/]")
            else:
                console.print(f"  [error]Memory '{name}' not found.[/]")
        else:
            memories = list_memories()
            if not memories:
                console.print("  [muted]No memories saved.[/]")
            else:
                console.print(f"\n  [purple]Memories ({len(memories)}):[/]")
                for m in memories:
                    console.print(f"    [info]{m['name']}[/]  [muted]({m['type']}) {m.get('description', '')}[/]")
        return True

    elif command == "/tasks":
        manager = get_task_manager()
        tasks = manager.list_all()
        if not tasks:
            console.print("  [muted]No tasks.[/]")
        else:
            icons = {"pending": "○", "in_progress": "◑", "completed": "●", "failed": "✗"}
            console.print(f"\n  [purple]Tasks ({len(tasks)}):[/]")
            for t in tasks:
                icon = icons.get(t.status.value, "?")
                style = "success" if t.status.value == "completed" else ("error" if t.status.value == "failed" else "info")
                console.print(f"    {icon} [{style}][{t.id}][/] {t.title}  [muted]({t.status.value})[/]")
            console.print(f"  [muted]{manager.summary()}[/]")
        return True

    elif command == "/cron":
        return _handle_cron(arg, agent)

    elif command == "/trigger":
        return _handle_trigger(arg, agent)

    elif command == "/diff":
        import subprocess
        try:
            result = subprocess.run("git diff --stat", shell=True, capture_output=True, text=True, cwd=agent.cwd)
            if result.stdout.strip():
                diff_result = subprocess.run("git diff", shell=True, capture_output=True, text=True, cwd=agent.cwd)
                if diff_result.stdout:
                    for line in diff_result.stdout.splitlines()[:60]:
                        if line.startswith("+") and not line.startswith("+++"):
                            console.print(f"  [diff_add]{line}[/]")
                        elif line.startswith("-") and not line.startswith("---"):
                            console.print(f"  [diff_del]{line}[/]")
                        else:
                            console.print(f"  [muted]{line}[/]")
                console.print(f"\n  [muted]{result.stdout.strip()}[/]")
            else:
                console.print("  [muted]No changes.[/]")
        except Exception:
            console.print("  [error]Error running git diff.[/]")
        return True

    elif command == "/status":
        import subprocess
        try:
            result = subprocess.run("git status -sb", shell=True, capture_output=True, text=True, cwd=agent.cwd)
            console.print(f"\n  [muted]{result.stdout.strip()}[/]")
        except Exception:
            console.print("  [error]Not a git repository.[/]")
        return True

    elif command == "/init":
        clow_md = Path(agent.cwd) / "CLOW.md"
        if clow_md.exists():
            console.print(f"  [warning]CLOW.md already exists in {agent.cwd}[/]")
        else:
            clow_md.write_text("# Project Instructions\n\n<!-- Add context and rules here. Clow reads this automatically. -->\n", encoding="utf-8")
            console.print(f"  [success]CLOW.md created in {agent.cwd}[/]")
        return True

    elif command == "/hooks":
        hooks_list = agent.hooks.list_hooks()
        if not hooks_list:
            console.print("  [muted]No hooks configured.[/]")
        else:
            console.print(f"\n  [purple]Hooks:[/]")
            for event, hooks in hooks_list.items():
                console.print(f"    [info]{event}[/]")
                for i, h in enumerate(hooks):
                    console.print(f"      [{i}] {h.command}")
        return True

    elif command == "/plugins":
        plugins = agent.plugins.list_plugins()
        if not plugins:
            console.print("  [muted]No plugins loaded.[/]")
        else:
            console.print(f"\n  [purple]Plugins ({len(plugins)}):[/]")
            for p in plugins:
                console.print(f"    [info]{p['name']}[/]  [muted]{p['description']}[/]")
        return True

    elif command == "/mcp":
        servers = agent.mcp.server_status()
        if not servers:
            console.print("  [muted]No MCP servers connected.[/]")
        else:
            console.print(f"\n  [purple]MCP Servers ({len(servers)}):[/]")
            for s in servers:
                status = "[success]ON[/]" if s["running"] else "[error]OFF[/]"
                console.print(f"    {status}  [info]{s['name']}[/]  [muted]{s['tools']} tools[/]")
        return True

    elif command == "/tools":
        tools = agent.registry.names()
        console.print(f"\n  [purple]Tools ({len(tools)}):[/]")
        for name in tools:
            tool = agent.registry.get(name)
            desc = tool.description[:60] if tool else ""
            console.print(f"    [info]{name}[/]  [muted]{desc}[/]")
        return True

    elif command == "/agents":
        types = list_agent_types()
        console.print(f"\n  [purple]Agent Types ({len(types)}):[/]")
        for at in types:
            tools_str = ", ".join(sorted(at.allowed_tools)[:6]) if at.allowed_tools else "all"
            console.print(f"    [info]{at.name}[/]  [muted]{at.description[:60]}[/]")
            console.print(f"      [muted]Tools: {tools_str}[/]")
        return True

    elif command == "/stale":
        from .memory import cleanup_stale_memories
        stale = cleanup_stale_memories(agent.cwd)
        if stale:
            console.print(f"\n  [warning]Stale memories ({len(stale)}):[/]")
            for s in stale:
                console.print(f"    [muted]{s}[/]")
        else:
            console.print("  [success]No stale memories.[/]")
        return True

    elif command == "/skills":
        skills = _skill_registry.list_all()
        console.print(f"\n  [purple]Skills ({len(skills)}):[/]")
        for s in skills:
            aliases = f" ({', '.join('/' + a for a in s.aliases)})" if s.aliases else ""
            console.print(f"    [info]/{s.name}[/]{aliases}  [muted]{s.description}[/]")
        return True

    elif command == "/background":
        bg_status = agent.get_background_status()
        if not bg_status:
            console.print("  [muted]No background agents.[/]")
        else:
            console.print(f"\n  [purple]Background Agents ({len(bg_status)}):[/]")
            for info in bg_status:
                style = "success" if info["status"] == "completed" else ("error" if info["status"] == "error" else "info")
                console.print(f"    [{style}]{info['status']}[/]  [info]{info['id']}[/]  [muted]{info['description']}[/]")
        return True

    elif command == "/web":
        _start_web_server(arg)
        return True

    elif command == "/pipeline":
        if not arg:
            console.print('  [error]Use: /pipeline "step1" -> "step2" -> "step3"[/]')
            return True
        return _handle_pipeline(arg, agent)

    elif command == "/backup":
        return _handle_backup(arg)

    elif command == "/chatwoot":
        return _handle_chatwoot(arg)

    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SUB-HANDLERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _handle_cron(arg: str, agent: Agent) -> bool:
    cron = get_cron_manager()
    if not arg or arg == "list":
        jobs = cron.list_all()
        if not jobs:
            console.print("  [muted]No cron jobs.[/]")
        else:
            console.print(f"\n  [purple]Cron Jobs ({len(jobs)}):[/]")
            for j in jobs:
                interval = cron.format_interval(j.interval_seconds)
                status = "[success]active[/]" if j.active else "[muted]paused[/]"
                console.print(f"    {status}  [info]{j.id}[/]  every {interval}  [muted]{j.prompt[:40]}... ({j.run_count}x)[/]")
        return True

    parts = arg.split(maxsplit=1)
    subcmd = parts[0].lower()

    if subcmd == "create" and len(parts) > 1:
        create_parts = parts[1].split(maxsplit=1)
        if len(create_parts) < 2:
            console.print("  [error]Use: /cron create <interval> <prompt>[/]")
            return True
        interval_str = create_parts[0]
        prompt = create_parts[1].strip("'\"")

        def factory():
            return Agent(cwd=agent.cwd, model=agent.model, auto_approve=True, is_subagent=True)
        cron.set_agent_factory(factory)

        try:
            job = cron.create(prompt, interval_str)
            console.print(f"  [success]Cron job created: {job.id}[/]  [muted]{interval_str} · {prompt[:50]}[/]")
        except ValueError as e:
            console.print(f"  [error]{e}[/]")
        return True

    elif subcmd == "delete" and len(parts) > 1:
        if cron.delete(parts[1].strip()):
            console.print(f"  [success]Cron job deleted.[/]")
        else:
            console.print(f"  [error]Job not found.[/]")
        return True

    elif subcmd == "pause" and len(parts) > 1:
        if cron.pause(parts[1].strip()):
            console.print(f"  [info]Cron job paused.[/]")
        else:
            console.print(f"  [error]Job not found.[/]")
        return True

    elif subcmd == "resume" and len(parts) > 1:
        if cron.resume(parts[1].strip()):
            console.print(f"  [success]Cron job resumed.[/]")
        else:
            console.print(f"  [error]Job not found.[/]")
        return True

    console.print("  [error]Use: /cron [list|create|delete|pause|resume][/]")
    return True


def _handle_trigger(arg: str, agent: Agent) -> bool:
    trigger = get_trigger_server()
    parts = arg.split(maxsplit=1) if arg else [""]
    subcmd = parts[0].lower()

    if subcmd == "start":
        port = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 7777
        trigger.port = port

        def factory():
            return Agent(cwd=agent.cwd, model=agent.model, auto_approve=True, is_subagent=True)
        trigger.set_agent_factory(factory)
        info = trigger.start()
        console.print(f"  [success]{info}[/]")
        return True

    elif subcmd == "stop":
        console.print(f"  [info]{trigger.stop()}[/]")
        return True

    elif subcmd == "status" or not subcmd:
        if trigger.running:
            console.print(f"  [success]Trigger server running on port {trigger.port}[/]")
            console.print(f"  [muted]Token: {trigger.token}[/]")
            results = trigger.list_results()
            if results:
                console.print(f"\n  [purple]Recent triggers ({len(results)}):[/]")
                for r in results[:10]:
                    style = "success" if r.status == "completed" else ("error" if r.status == "error" else "info")
                    console.print(f"    [{style}]{r.status}[/]  [info]{r.id}[/]  [muted]{r.prompt[:40]}[/]")
        else:
            console.print("  [muted]Trigger server not running. Use /trigger start[/]")
        return True

    console.print("  [error]Use: /trigger [start|stop|status][/]")
    return True


def _handle_pipeline(arg: str, agent: Agent) -> bool:
    prompts = parse_pipeline(arg)
    if len(prompts) < 2:
        console.print("  [error]Pipeline needs at least 2 steps separated by '->'[/]")
        return True

    console.print(f"\n  [purple]Pipeline — {len(prompts)} steps:[/]")
    for i, p in enumerate(prompts, 1):
        console.print(f"    [muted]{i}. {p}[/]")
    console.print()

    def factory():
        return Agent(cwd=agent.cwd, model=agent.model, auto_approve=True, is_subagent=True)

    def on_start(i, prompt):
        console.print(f"  [info]◑ Step {i + 1}:[/] {prompt[:60]}")

    def on_done(i, status, output):
        icon = "[success]●[/]" if status == "completed" else "[error]✗[/]"
        console.print(f"  {icon} Step {i + 1} — {status}")

    result = run_pipeline(prompts, factory, on_start, on_done)
    console.print(f"\n  [purple]Pipeline {result.status} in {result.total_duration:.1f}s[/]")
    return True


def _handle_backup(arg: str) -> bool:
    parts = arg.split(maxsplit=1) if arg else [""]
    subcmd = parts[0].lower()

    if subcmd == "create" or not subcmd:
        result = backup_memory()
        console.print(f"  [success]{result}[/]")
        return True
    elif subcmd == "list":
        backups = list_backups()
        if not backups:
            console.print("  [muted]No backups found.[/]")
        else:
            console.print(f"\n  [purple]Backups ({len(backups)}):[/]")
            for b in backups[:15]:
                console.print(f"    [info]{b['name']}[/]  {b['created']}  [muted]{b['size_kb']} KB[/]")
        return True
    elif subcmd == "restore" and len(parts) > 1:
        result = restore_memory(parts[1].strip())
        console.print(f"  [info]{result}[/]")
        return True

    console.print("  [error]Use: /backup [create|list|restore <name>][/]")
    return True


def _handle_chatwoot(arg: str) -> bool:
    trigger = get_trigger_server()
    parts = arg.split(maxsplit=1) if arg else [""]
    subcmd = parts[0].lower()

    if subcmd == "setup" and len(parts) > 1:
        trigger.configure_chatwoot(parts[1].strip())
        console.print(f"  [success]Chatwoot configured.[/]")
        console.print(f"  [muted]Webhook: POST http://localhost:{trigger.port}/webhook/chatwoot[/]")
        return True
    elif subcmd == "status":
        if trigger._chatwoot_token:
            console.print(f"  [success]Chatwoot configured[/]")
            console.print(f"  [muted]Events: {', '.join(trigger._chatwoot_events)}[/]")
        else:
            console.print("  [muted]Chatwoot not configured.[/]")
        return True

    console.print("  [error]Use: /chatwoot setup <token> | /chatwoot status[/]")
    return True


def _start_web_server(arg: str) -> None:
    port = int(arg) if arg and arg.isdigit() else 8080
    try:
        import uvicorn
        from .webapp import get_app
        app = get_app()
        console.print(f"  [success]Web app starting at http://0.0.0.0:{port}[/]")
        console.print("  [muted]Ctrl+C to stop[/]")
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
    except ImportError:
        console.print("  [error]Install: pip install fastapi uvicorn[/]")
    except Exception as e:
        console.print(f"  [error]{e}[/]")


def _show_help() -> None:
    help_text = f"""
  {_BOLD}{_PURPLE_B}∞{_RESET} {_BOLD}System Clow{_RESET} {_DIM}v{__version__}{_RESET}

  {_BOLD}Skills{_RESET}
    /commit          Smart commit
    /review          Code review
    /test            Generate tests
    /refactor        Refactor code
    /explain         Explain code
    /fix             Find & fix bugs
    /simplify        Review quality
    /skills          List all skills

  {_BOLD}Navigation{_RESET}
    /cd <dir>        Change directory
    /status          Git status
    /diff            Git diff

  {_BOLD}Sessions{_RESET}
    /sessions        List sessions
    /resume <id>     Resume session
    /save            Save session
    /clear           Clear history

  {_BOLD}Memory{_RESET}
    /memory          List memories
    /memory save     Save memory
    /memory delete   Delete memory
    /stale           Check stale memories

  {_BOLD}Automation{_RESET}
    /cron            Cron jobs
    /trigger         HTTP triggers
    /pipeline        Multi-agent pipeline
    /chatwoot        Chatwoot integration
    /backup          Memory backup

  {_BOLD}Config{_RESET}
    /model           Show/change model
    /tokens          Token usage
    /plan            Plan mode (read-only)
    /approve         Auto-approve

  {_BOLD}Extensions{_RESET}
    /tools           List tools
    /agents          Agent types
    /hooks           Hooks
    /plugins         Plugins
    /mcp             MCP servers
    /web [port]      Web app + dashboard

    /exit            Exit Clow
"""
    sys.stdout.write(help_text)
    sys.stdout.flush()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BANNER + REPL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _print_banner() -> None:
    provider = config.CLOW_PROVIDER.capitalize()
    model_parts = config.CLOW_MODEL.split("-")
    model_display = "-".join(model_parts[:2]) if len(model_parts) >= 2 else config.CLOW_MODEL

    purple = _PURPLE_B
    gold = f"\033[1m\033[33m"
    dim = _DIM
    r = _RESET

    sys.stdout.write(f"""
{purple}   ╔═══════════════════════════════════════╗{r}
{purple}   ║{r}                                       {purple}║{r}
{purple}   ║{r}   {gold}███████╗██╗      ██████╗ ██╗    ██╗{r}  {purple}║{r}
{purple}   ║{r}   {gold}██╔════╝██║     ██╔═══██╗██║    ██║{r}  {purple}║{r}
{purple}   ║{r}   {gold}██║     ██║     ██║   ██║██║ █╗ ██║{r}  {purple}║{r}
{purple}   ║{r}   {gold}██║     ██║     ██║   ██║██║███╗██║{r}  {purple}║{r}
{purple}   ║{r}   {gold}███████╗███████╗╚██████╔╝╚███╔███╔╝{r}  {purple}║{r}
{purple}   ║{r}   {gold}╚══════╝╚══════╝ ╚═════╝  ╚══╝╚══╝{r}   {purple}║{r}
{purple}   ║{r}                                       {purple}║{r}
{purple}   ║{r}   {_BOLD}System Clow{r} {dim}v{__version__}{r}  🃏               {purple}║{r}
{purple}   ║{r}   {dim}{provider} · {model_display}{r}               {purple}║{r}
{purple}   ║{r}                                       {purple}║{r}
{purple}   ╚═══════════════════════════════════════╝{r}

  {dim}{os.getcwd()}{r}
  {dim}14 tools · 8 skills · 4 agent types · /help{r}

""")
    sys.stdout.flush()


def _run_agent_turn(agent: Agent, message: str) -> None:
    global _in_streaming, _thinking_active, _first_turn
    try:
        log_action("repl_turn", message[:80])
        _thinking_active = True
        _inf_start("Pensando")
        agent.run_turn(message)
    except KeyboardInterrupt:
        _inf_stop_now()
        _thinking_active = False
        if _in_streaming:
            sys.stdout.write("\n")
            _in_streaming = False
        sys.stdout.write(f"\n  {_DIM}Interrupted.{_RESET}\n\n")
        sys.stdout.flush()
    except Exception as e:
        _inf_stop_now()
        _thinking_active = False
        if _in_streaming:
            sys.stdout.write("\n")
            _in_streaming = False
        console.print(f"\n  [error]{e}[/]\n")
    finally:
        if _thinking_active:
            _inf_stop_now()
            _thinking_active = False
        _first_turn = False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN REPL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_repl(args: argparse.Namespace) -> None:
    _print_banner()

    session = None
    if hasattr(args, "resume") and args.resume:
        session = load_session(args.resume)
        if session:
            console.print(f"  [success]Session {args.resume} restored.[/]\n")

    agent = Agent(
        cwd=os.getcwd(),
        session=session,
        model=getattr(args, "model", None) or config.CLOW_MODEL,
        on_text_delta=on_text_delta,
        on_text_done=on_text_done,
        on_tool_call=on_tool_call,
        on_tool_result=on_tool_result,
        ask_confirmation=ask_confirmation,
        auto_approve=getattr(args, "auto_approve", False),
    )

    history_file = config.CLOW_HOME / "input_history"
    prompt_session = PromptSession(
        history=FileHistory(str(history_file)),
        auto_suggest=AutoSuggestFromHistory(),
        multiline=False,
    )

    # Prompt inicial
    if hasattr(args, "prompt") and args.prompt:
        initial_prompt = " ".join(args.prompt)
        _run_agent_turn(agent, initial_prompt)

    while True:
        try:
            if agent.plan_mode:
                prompt_html = HTML(f'<style fg="{PURPLE}">[PLAN] ❯ </style>')
            else:
                prompt_html = HTML(f'<style fg="{PURPLE}" bold="true">❯ </style>')

            user_input = prompt_session.prompt(prompt_html).strip()

            if not user_input:
                continue

            if user_input.startswith("/"):
                if handle_slash_command(user_input, agent):
                    continue

            if user_input.startswith("!"):
                bash_cmd = user_input[1:].strip()
                if bash_cmd:
                    tool = agent.registry.get("bash")
                    if tool:
                        sys.stdout.write(f"  {_BLUE}⏺{_RESET} Run command: {bash_cmd}\n")
                        output = tool.execute(command=bash_cmd, cwd=agent.cwd)
                        if output:
                            for line in output.strip().splitlines()[:10]:
                                sys.stdout.write(f"  {_DIM}⎿ {line[:120]}{_RESET}\n")
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                continue

            # Multi-linha
            while user_input.endswith("\\"):
                user_input = user_input[:-1] + "\n"
                try:
                    user_input += prompt_session.prompt(HTML(f'<style fg="{PURPLE}">  ... </style>')).strip()
                except (EOFError, KeyboardInterrupt):
                    break

            # Divisória entre turnos (não aparece antes do primeiro)
            if not _first_turn:
                console.print()
                console.print(Rule(style="dim bright_black"))
                console.print()

            # Re-renderiza input com background sombreado
            # Move cursor para cima (sobre a linha que prompt_toolkit escreveu) e sobrescreve
            lines_in_input = user_input.count("\n") + 1
            sys.stdout.write(f"\033[{lines_in_input}A")  # move N linhas para cima
            sys.stdout.write(_CLEAR_LINE)
            user_line = Text()
            user_line.append(f"  ❯ {user_input}", style="bold white on grey15")
            user_line.pad_right(console.width)
            console.print(user_line)
            console.print()

            _run_agent_turn(agent, user_input)

        except KeyboardInterrupt:
            sys.stdout.write(f"\n  {_DIM}(Ctrl+C — use /exit to quit){_RESET}\n")
            continue
        except EOFError:
            get_cron_manager().stop_all()
            sys.stdout.write(f"\n  {_DIM}Session saved. Goodbye! 🃏{_RESET}\n")
            save_session(agent.session)
            break
        except Exception as e:
            console.print(f"\n  [error]{e}[/]")
            continue


def main() -> None:
    parser = argparse.ArgumentParser(prog="clow", description="System Clow — AI Code Agent")
    parser.add_argument("--version", "-v", action="version", version=f"Clow v{__version__}")
    parser.add_argument("--model", "-m", help=f"Model (default: {config.CLOW_MODEL})")
    parser.add_argument("--resume", "-r", help="Session ID to resume")
    parser.add_argument("--auto-approve", "-y", action="store_true", help="Auto-approve all actions")
    parser.add_argument("--cwd", "-C", help="Working directory")
    parser.add_argument("--web", action="store_true", help="Start web app")
    parser.add_argument("--port", type=int, default=8080, help="Web server port (default: 8080)")
    parser.add_argument("prompt", nargs="*", help="Initial prompt")

    args = parser.parse_args()

    if args.cwd:
        target = Path(args.cwd).expanduser().resolve()
        if target.is_dir():
            os.chdir(target)
        else:
            console.print(f"[error]Directory not found: {target}[/]")
            sys.exit(1)

    if args.model:
        config.CLOW_MODEL = args.model

    if args.web:
        _start_web_server(str(args.port))
        return

    run_repl(args)


if __name__ == "__main__":
    main()
