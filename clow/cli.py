"""CLI REPL do System Clow v0.2.0 — interface estilo Claude Code com ∞ roxo pulsante."""

from __future__ import annotations
import os
import sys
import time
import argparse
import threading
try:
    import tty
    import termios
    _HAS_TERMIOS = True
except ImportError:
    _HAS_TERMIOS = False
from pathlib import Path

import re as _re

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text
from rich.theme import Theme
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.box import ROUNDED
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
# ∞ INFINITY PULSE — feedback visual estilo Claude Code
# ∞ roxo pulsante durante TODA operacao (modelo, tools, bash)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from .spinner import ClowSpinner

_spinner = ClowSpinner()
_spinner_agent_name = ""  # Nome do modelo ativo para exibicao

# Badge roxo para tool calls: ⟡ NomeDaTool
_TOOL_BADGE = "\033[1;38;5;129m"  # bold roxo
_BADGE_RESET = "\033[0m"


def _format_model_name(model: str) -> str:
    """Formata nome do modelo para exibicao elegante.

    'claude-sonnet-4-20250514'  -> 'Claude Sonnet'
    'claude-haiku-4-5-20251001' -> 'Claude Haiku'
    'gpt-4.1'                   -> 'GPT-4.1'
    'gpt-4.1-mini'              -> 'GPT-4.1 Mini'
    """
    m = model.lower()

    # Claude models
    if "claude" in m:
        if "sonnet" in m:
            return "Claude Sonnet"
        elif "haiku" in m:
            return "Claude Haiku"
        return "Claude"

    # OpenAI models
    if m.startswith("gpt-"):
        # gpt-4.1 -> GPT-4.1, gpt-4.1-mini -> GPT-4.1 Mini
        rest = model[4:]  # Remove "gpt-"
        parts = rest.split("-")
        version = parts[0]  # "4.1"
        suffix = " ".join(p.capitalize() for p in parts[1:] if p)
        return f"GPT-{version}" + (f" {suffix}" if suffix else "")

    if m.startswith("o") and (len(m) <= 2 or m[1:].replace("-", "").replace(".", "").isalnum()):
        return model.upper()

    return model


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STREAMING + TOOL DISPLAY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_streaming_buffer: list[str] = []
_in_streaming = False
_thinking_active = False
_first_turn = True  # Não mostra divisória antes do primeiro turno

# Colapsamento APENAS para output de tools (nunca para resposta textual)
TOOL_OUTPUT_MAX_LINES = 8


def _clean_text(text: str) -> str:
    """Remove espaços em branco excessivos — máximo 1 linha em branco entre seções."""
    text = _re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _split_tables(text: str) -> list[dict]:
    """Separa texto normal de blocos de tabela markdown."""
    lines = text.split('\n')
    parts: list[dict] = []
    current_text: list[str] = []
    current_table: list[str] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        is_table_line = stripped.startswith('|') and stripped.endswith('|') and len(stripped) > 2

        if is_table_line:
            if not in_table:
                if current_text:
                    parts.append({'type': 'text', 'content': '\n'.join(current_text)})
                    current_text = []
                in_table = True
            current_table.append(stripped)
        else:
            if in_table:
                if current_table:
                    parts.append({'type': 'table', 'content': current_table})
                    current_table = []
                in_table = False
            current_text.append(line)

    if current_table:
        parts.append({'type': 'table', 'content': current_table})
    if current_text:
        parts.append({'type': 'text', 'content': '\n'.join(current_text)})

    return parts


def _build_rich_table(table_lines: list[str]) -> Table:
    """Converte linhas de tabela markdown em rich.Table."""
    table = Table(
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        pad_edge=True,
        expand=False,
        box=ROUNDED,
    )

    # Header
    headers = [cell.strip() for cell in table_lines[0].split('|')[1:-1]]
    for header in headers:
        table.add_column(header, style="white", overflow="fold")

    # Dados (pula separador |---|---|)
    for line in table_lines[2:] if len(table_lines) > 2 else []:
        cells = [cell.strip() for cell in line.split('|')[1:-1]]
        # Garante mesmo número de colunas
        while len(cells) < len(headers):
            cells.append("")
        table.add_row(*cells[:len(headers)])

    return table


def _render_response(text: str) -> None:
    """Renderiza resposta do agente: Markdown para texto, rich.Table para tabelas."""
    cleaned = _clean_text(text)
    if not cleaned:
        return

    parts = _split_tables(cleaned)
    width = min(console.width - 4, 100)

    for part in parts:
        if part['type'] == 'table' and len(part['content']) >= 2:
            try:
                table = _build_rich_table(part['content'])
                console.print(table)
            except Exception:
                # Fallback: renderiza como markdown se der erro
                console.print(Markdown('\n'.join(part['content'])), width=width)
        else:
            content = part['content']
            cleaned_part = _clean_text(content)
            if cleaned_part:
                console.print(Markdown(cleaned_part), width=width)


def on_text_delta(delta: str) -> None:
    """Acumula tokens. Mostra spinner 'Gerando...' durante streaming."""
    global _in_streaming, _thinking_active

    if _thinking_active or _spinner.is_running:
        _spinner.stop()
        _thinking_active = False

    _streaming_buffer.append(delta)

    # Primeira vez: inicia indicador de geracao
    if not _in_streaming:
        _in_streaming = True
        _spinner.start(f"{_spinner_agent_name} gerando resposta...")


def on_text_done(text: str) -> None:
    """Finaliza streaming — renderiza tudo com Rich Markdown. Sem markdown cru."""
    global _in_streaming

    _spinner.stop()

    full_text = "".join(_streaming_buffer)
    _streaming_buffer.clear()

    if _in_streaming:
        # Renderiza com Rich Markdown — limpo, sem asteriscos
        if full_text.strip():
            console.print()
            _render_response(full_text)
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
    elif name == "whatsapp_send":
        return f"WhatsApp: {args.get('phone', '')} — {args.get('message', '')[:60]}"
    elif name == "http_request":
        return f"HTTP {args.get('method', 'GET')}: {args.get('url', '')[:80]}"
    elif name == "supabase_query":
        return f"SQL: {args.get('query', '')[:80]}"
    elif name == "n8n_workflow":
        return f"n8n {args.get('action', '')}: {args.get('workflow_id', '')}"
    elif name == "docker_manage":
        return f"Docker {args.get('action', '')}: {args.get('container', '')}"
    elif name == "git_advanced":
        return f"Git {args.get('action', '')}: {args.get('target', '')}"
    elif name == "scraper":
        return f"Scrape: {args.get('url', '')[:80]}"
    elif name == "image_gen":
        return f"Image gen: {args.get('prompt', '')[:60]}"
    elif name == "pdf_tool":
        return f"PDF {args.get('action', '')}: {args.get('input_path', args.get('output_path', ''))}"
    elif name == "spreadsheet":
        return f"Spreadsheet {args.get('action', '')}: {args.get('file_path', '')}"
    elif name.startswith("mcp__"):
        return f"MCP: {name.split('__')[-1]}"
    return f"{name}"


def on_tool_call(name: str, args: dict) -> None:
    """Formato Claude Code: badge roxo ⟡ + spinner durante execucao."""
    global _in_streaming, _thinking_active

    # Para spinner anterior (se estava "Pensando...")
    _spinner.stop()
    _thinking_active = False

    if _in_streaming:
        sys.stdout.write("\n")
        sys.stdout.flush()
        _in_streaming = False

    # Badge roxo com nome da tool capitalizado
    tool_display = name.replace("_", " ").title()
    label = _tool_label(name, args)
    sys.stdout.write(f"  {_TOOL_BADGE}\u27e1 {tool_display}{_BADGE_RESET}  {_DIM}{label}{_RESET}\n")
    sys.stdout.flush()

    # Inicia spinner DURANTE a execucao da tool (momento critico)
    _thinking_active = True
    _spinner.start(f"Executando {tool_display}...")


def on_tool_result(name: str, status: str, output: str) -> None:
    """Resultado compactado com ⎿. Para o spinner e mostra resultado."""
    global _thinking_active

    # Para o spinner que estava rodando durante a execucao da tool
    _spinner.stop()
    _thinking_active = False

    if status == "error":
        sys.stdout.write(f"  {_RED}\u23bf Error{_RESET}\n")
        if output:
            for line in output.strip().splitlines()[:3]:
                sys.stdout.write(f"    {_RED}{line[:120]}{_RESET}\n")
        sys.stdout.flush()
    elif status == "denied":
        sys.stdout.write(f"  {_RED}\u23bf Action cancelled{_RESET}\n")
        sys.stdout.flush()
    else:
        if name == "edit" and "```diff" in output:
            _show_diff(output)
        elif output:
            lines = output.strip().splitlines()
            if len(lines) <= TOOL_OUTPUT_MAX_LINES:
                for line in lines:
                    sys.stdout.write(f"  {_DIM}\u23bf {line[:150]}{_RESET}\n")
            else:
                for line in lines[:4]:
                    sys.stdout.write(f"  {_DIM}\u23bf {line[:150]}{_RESET}\n")
                sys.stdout.write(f"  {_DIM}\u23bf ... +{len(lines) - 4} lines{_RESET}\n")
        sys.stdout.write("\n")
        sys.stdout.flush()

    # Reinicia spinner "Pensando..." pois o modelo vai processar o resultado
    _thinking_active = True
    _spinner.start("Pensando...")


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


def _read_key() -> str:
    """Le uma tecla ou sequencia de escape (arrows, shift+tab, etc)."""
    if _HAS_TERMIOS:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            # Escape sequences
            if ch == "\x1b":
                ch2 = sys.stdin.read(1) if _select_readable(fd) else ""
                if ch2 == "[":
                    ch3 = sys.stdin.read(1) if _select_readable(fd) else ""
                    if ch3 == "A": return "UP"
                    if ch3 == "B": return "DOWN"
                    if ch3 == "Z": return "SHIFT_TAB"
                    return "ESC"
                return "ESC"
            if ch == "\r" or ch == "\n": return "ENTER"
            if ch == "\t": return "TAB"
            if ch == "\x1b": return "ESC"
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    else:
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"): return "ENTER"
        if ch == "\x1b": return "ESC"
        if ch == "\t": return "TAB"
        if ch == "\x00" or ch == "\xe0":
            ch2 = msvcrt.getwch()
            if ch2 == "H": return "UP"
            if ch2 == "P": return "DOWN"
        return ch


def _select_readable(fd, timeout=0.05) -> bool:
    """Checa se ha dados disponiveis para leitura no fd."""
    import select
    r, _, _ = select.select([fd], [], [], timeout)
    return bool(r)


def _render_menu(options: list[str], selected: int, hints: str):
    """Renderiza menu de selecao sem Rich (ANSI puro) para controle preciso."""
    _P = "\033[38;2;139;92;246m"  # #8B5CF6
    _W = "\033[97m"               # branco
    _G = "\033[38;2;107;114;128m" # #6B7280
    _R = _RESET

    # Move cursor pra cima pra reescrever (linhas = opcoes + 1 hint)
    total_lines = len(options) + 1
    sys.stdout.write(f"\033[{total_lines}A")

    for i, opt in enumerate(options):
        if i == selected:
            sys.stdout.write(f"  {_P}>{_R} {_W}{opt}{_R}\033[K\n")
        else:
            sys.stdout.write(f"    {_G}{opt}{_R}\033[K\n")

    sys.stdout.write(f"  {_G}{hints}{_R}\033[K\n")
    sys.stdout.flush()


def ask_confirmation(message: str) -> bool:
    """Menu de selecao visual estilo Claude Code para confirmacao."""
    _P = "\033[38;2;139;92;246m"
    _W = "\033[97m"
    _G = "\033[38;2;107;114;128m"
    _R = _RESET

    # Header
    sys.stdout.write(f"\n  {_W}Do you want to allow this action?{_R}\n\n")
    for line in message.splitlines():
        sys.stdout.write(f"  {_DIM}{line}{_R}\n")
    sys.stdout.write("\n")

    options = [
        "Yes",
        "Yes, allow all during this session",
        "No",
    ]
    hints = "Esc to cancel \u00b7 \u2191\u2193 to navigate"
    selected = 0

    # Renderiza menu inicial
    for i, opt in enumerate(options):
        if i == selected:
            sys.stdout.write(f"  {_P}>{_R} {_W}{opt}{_R}\n")
        else:
            sys.stdout.write(f"    {_G}{opt}{_R}\n")
    sys.stdout.write(f"  {_G}{hints}{_R}\n")
    sys.stdout.flush()

    # Auto-approve ativo? Mostra e aprova
    if config.AUTO_APPROVE_BASH and config.AUTO_APPROVE_WRITE:
        total = len(options) + 1
        sys.stdout.write(f"\033[{total}A")
        for i in range(len(options)):
            sys.stdout.write(f"\033[2K\n")
        sys.stdout.write(f"\033[2K\n")
        sys.stdout.write(f"\033[{total}A")
        sys.stdout.write(f"  {_P}\u2713{_R} {_G}Auto-approved (allow all active){_R}\n\n")
        sys.stdout.flush()
        return True

    try:
        while True:
            key = _read_key()

            if key == "UP":
                selected = (selected - 1) % len(options)
                _render_menu(options, selected, hints)
            elif key == "DOWN":
                selected = (selected + 1) % len(options)
                _render_menu(options, selected, hints)
            elif key == "ENTER":
                break
            elif key == "SHIFT_TAB":
                selected = 1  # "Allow all"
                _render_menu(options, selected, hints)
                break
            elif key == "ESC":
                selected = 2  # "No"
                _render_menu(options, selected, hints)
                break
            elif key in ("y", "Y", "s", "S"):
                selected = 0
                break
            elif key in ("n", "N"):
                selected = 2
                break
            elif key in ("a", "A"):
                selected = 1
                break

        # Resultado
        total = len(options) + 1
        sys.stdout.write(f"\033[{total}A")
        for i in range(total):
            sys.stdout.write(f"\033[2K\n")
        sys.stdout.write(f"\033[{total}A")

        if selected == 0:
            sys.stdout.write(f"  {_P}\u2713{_R} {_W}Approved{_R}\n\n")
            sys.stdout.flush()
            return True
        elif selected == 1:
            config.AUTO_APPROVE_BASH = True
            config.AUTO_APPROVE_WRITE = True
            sys.stdout.write(f"  {_P}\u2713{_R} {_W}Always allowed for this session{_R}\n\n")
            sys.stdout.flush()
            return True
        else:
            sys.stdout.write(f"  \033[31m\u2717\033[0m {_G}Denied{_R}\n\n")
            sys.stdout.flush()
            return False

    except (EOFError, KeyboardInterrupt):
        return False
    except Exception:
        # Fallback se terminal nao suportar
        try:
            sys.stdout.write(f"\n  [Y] Yes  [N] No  [A] Always  ")
            sys.stdout.flush()
            resp = console.input("").strip().lower()
            if resp in ("a", "always"):
                config.AUTO_APPROVE_BASH = True
                config.AUTO_APPROVE_WRITE = True
                console.print("  [blue]\u2713 Always allowed[/]\n")
                return True
            if resp in ("y", "yes", "s", "sim", ""):
                console.print("  [green]\u2713 Approved[/]\n")
                return True
            console.print("  [red]\u2717 Denied[/]\n")
            return False
        except (EOFError, KeyboardInterrupt):
            return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RATE LIMIT — countdown visual
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def show_rate_limit_warning(wait_seconds: int, attempt: int, max_retries: int) -> None:
    """Mostra countdown visual com infinito pulsando durante rate limit."""
    _inf_stop_now()  # Para o pulse normal se estiver rodando

    console.print()
    console.print(
        f"  [yellow]⚠ Rate limit atingido. Aguardando {wait_seconds}s...[/] "
        f"[dim](tentativa {attempt}/{max_retries})[/]"
    )

    # Countdown visual com infinito pulsando
    styles = [
        "bold bright_magenta", "bright_magenta", "magenta",
        "dim magenta", "magenta", "bright_magenta",
    ]
    frame = 0
    for remaining in range(wait_seconds, 0, -1):
        style = styles[frame % len(styles)]
        text = Text()
        text.append("  ")
        text.append("∞", style=style)
        text.append(f" Aguardando rate limit... {remaining}s", style="dim yellow")
        sys.stdout.write(f"\r{' ' * 70}\r")
        sys.stdout.flush()
        console.print(text, end="")
        frame += 1
        time.sleep(1)

    sys.stdout.write(f"\r{' ' * 70}\r")
    sys.stdout.flush()
    console.print("  [green]✓ Retomando...[/]")
    console.print()

    # Reinicia o pulse normal
    _inf_start("Pensando")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SLASH COMMANDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ── Todos os slash commands conhecidos (para sugestao Levenshtein) ──

KNOWN_SLASH_COMMANDS = [
    "/help", "/exit", "/quit", "/q", "/clear", "/reset",
    "/sessions", "/resume", "/save", "/model", "/tokens",
    "/cwd", "/cd", "/approve", "/compact", "/plan",
    "/memory", "/tasks", "/cron", "/trigger", "/diff",
    "/status", "/init", "/hooks", "/plugins", "/mcp",
    "/tools", "/agents", "/stale", "/skills",
    "/background", "/web", "/pipeline", "/backup", "/chatwoot",
    # Skills
    "/commit", "/review", "/test", "/refactor", "/explain",
    "/fix", "/simplify", "/batch", "/loop", "/debug",
    "/stuck", "/remember", "/schedule", "/verify", "/security",
    "/perf", "/docs", "/migrate", "/pr", "/changelog",
    "/scaffold", "/cleanup", "/estimate", "/plan", "/diff",
    "/undo", "/search",
]


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Calcula a distancia de Levenshtein entre duas strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


def suggest_slash_command(user_input: str) -> str | None:
    """Sugere o slash command mais proximo usando distancia de Levenshtein.

    Retorna a sugestao se a distancia for <= 3, ou None.
    """
    parts = user_input.strip().split(maxsplit=1)
    cmd = parts[0].lower()

    # Coleta todas as skills registradas tambem
    all_commands = list(KNOWN_SLASH_COMMANDS)
    for skill in _skill_registry.list_all():
        skill_cmd = f"/{skill.name}"
        if skill_cmd not in all_commands:
            all_commands.append(skill_cmd)
        for alias in skill.aliases:
            alias_cmd = f"/{alias}"
            if alias_cmd not in all_commands:
                all_commands.append(alias_cmd)

    best_match = None
    best_distance = 999

    for known in all_commands:
        dist = _levenshtein_distance(cmd, known)
        if dist < best_distance:
            best_distance = dist
            best_match = known

    # So sugere se a distancia for razoavel (max 3 edicoes)
    max_threshold = min(3, len(cmd) // 2 + 1)
    if best_distance <= max_threshold and best_match:
        return best_match

    return None


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
        sys.stdout.write(f"\n  {_DIM}Session saved. Goodbye! {_RESET}\n")
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
                console.print("  [muted]claude-sonnet-4-20250514, claude-haiku-4-5-20251001[/]")
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
        from .webapp import get_app, _get_api_keys
        app = get_app()

        # Verifica TLS
        settings = config.load_settings()
        tls = settings.get("webapp", {}).get("tls", {})
        certfile = tls.get("certfile", "")
        keyfile = tls.get("keyfile", "")

        protocol = "https" if certfile and keyfile else "http"
        console.print(f"  [success]Web app starting at {protocol}://0.0.0.0:{port}[/]")
        console.print(f"  [muted]Docs: {protocol}://localhost:{port}/docs[/]")

        keys = _get_api_keys()
        if keys:
            console.print(f"  [info]Auth: {len(keys)} API key(s) configuradas[/]")
        else:
            console.print("  [warning]Auth: DESABILITADA (configure api_keys em settings.json)[/]")

        console.print("  [muted]Ctrl+C to stop[/]")

        kwargs: dict = {"host": "0.0.0.0", "port": port, "log_level": "warning"}
        if certfile and keyfile:
            kwargs["ssl_certfile"] = certfile
            kwargs["ssl_keyfile"] = keyfile

        uvicorn.run(app, **kwargs)
    except ImportError:
        console.print("  [error]Install: pip install 'clow[web]'[/]")
    except Exception as e:
        console.print(f"  [error]{e}[/]")


def _show_help() -> None:
    help_text = f"""
  {_BOLD}{_PURPLE_B}∞{_RESET} {_BOLD}System Clow{_RESET} {_DIM}v{__version__}{_RESET}

  {_BOLD}Skills — Dev{_RESET}
    /commit          Smart commit
    /review          Code review
    /test            Generate tests
    /refactor        Refactor code
    /explain         Explain code
    /fix             Find & fix bugs
    /simplify        Review quality

  {_BOLD}Skills — Business{_RESET}
    /cotacao         Cotação seguro/funerário PDF
    /proposta        Proposta comercial PDF
    /relatorio       Relatório de vendas
    /leads           Gerencia leads
    /ads             Meta Ads campaigns

  {_BOLD}Skills — Ops{_RESET}
    /deploy          Deploy automatizado
    /backup          Backup VPS completo
    /monitor         Status dos serviços
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

    # Dynamic counts
    try:
        from .tools.base import create_default_registry
        _tool_count = len(create_default_registry()._tools)
    except Exception:
        _tool_count = 24
    try:
        from .skills.loader import list_all_skills
        _skill_count = sum(len(v) for v in list_all_skills().values())
    except Exception:
        _skill_count = 36
    try:
        from .agent_types import AGENT_TYPES
        _agent_count = len(AGENT_TYPES)
    except Exception:
        _agent_count = 8

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
{purple}   ║{r}   {_BOLD}System Clow{r} {dim}v{__version__}{r}                 {purple}║{r}
{purple}   ║{r}   {dim}{provider} · {model_display}{r}               {purple}║{r}
{purple}   ║{r}                                       {purple}║{r}
{purple}   ╚═══════════════════════════════════════╝{r}

  {dim}{os.getcwd()}{r}
  {dim}{_tool_count} tools · {_skill_count} skills · {_agent_count} agent types · /help{r}

""")
    sys.stdout.flush()


def _run_agent_turn(agent: Agent, message: str) -> None:
    global _in_streaming, _thinking_active, _first_turn, _spinner_agent_name
    _spinner_agent_name = _format_model_name(agent.model)
    try:
        log_action("repl_turn", message[:80])
        _thinking_active = True
        _spinner.start("Pensando...")
        agent.run_turn(message)
    except KeyboardInterrupt:
        _spinner.stop()
        _thinking_active = False
        if _in_streaming:
            sys.stdout.write("\n")
            _in_streaming = False
        sys.stdout.write(f"\n  {_DIM}Interrupted.{_RESET}\n\n")
        sys.stdout.flush()
    except Exception as e:
        _spinner.stop()
        _thinking_active = False
        if _in_streaming:
            sys.stdout.write("\n")
            _in_streaming = False
        console.print(f"\n  [error]{e}[/]\n")
    finally:
        _spinner.stop()
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
        on_rate_limit=show_rate_limit_warning,
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
                # Comando nao reconhecido — sugere similar por Levenshtein
                suggestion = suggest_slash_command(user_input)
                if suggestion:
                    console.print(f"  [warning]Comando desconhecido. Voce quis dizer [bold]{suggestion}[/bold]?[/]")
                else:
                    console.print(f"  [warning]Comando desconhecido. Use /help para ver comandos disponiveis.[/]")
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
            sys.stdout.write(f"\n  {_DIM}Session saved. Goodbye! {_RESET}\n")
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
