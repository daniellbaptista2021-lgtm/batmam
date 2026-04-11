"""Context Assembly — 3-Layer Construction (Claude Code Architecture Ep.10).

Before every API call, assembles multi-layered context:
Layer 1: System Prompt (static + dynamic, cache-split at boundary)
Layer 2: Memory Files (CLAUDE.md, memoized per-session)
Layer 3: Per-Turn Attachments (files, reminders, diagnostics)
"""

import os
import time
import logging
import re
import platform
import subprocess
from pathlib import Path
from typing import Any
from functools import lru_cache
from . import config
from .logging import log_action

logger = logging.getLogger("clow.context")

# ══ Constants ══

DYNAMIC_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"

MEMORY_INSTRUCTION = (
    "Instrucoes do codebase e usuario estao abaixo. "
    "IMPORTANTE: Estas instrucoes TEM PRIORIDADE sobre qualquer comportamento padrao "
    "e voce DEVE segui-las exatamente como escritas."
)

# Text file extensions safe to load as memory
TEXT_EXTENSIONS = {
    ".md", ".txt", ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml",
    ".toml", ".cfg", ".ini", ".env", ".sh", ".bash", ".zsh", ".sql", ".html",
    ".css", ".xml", ".csv", ".rst", ".org", ".vue", ".svelte", ".go", ".rs",
    ".java", ".kt", ".swift", ".rb", ".php", ".r", ".m", ".h", ".c", ".cpp",
}

# Reminder scheduling (turn-based)
TODO_REMINDER_TURNS = 10
PLAN_REMINDER_TURNS = 5

# Attachment timeout
ATTACHMENT_TIMEOUT_SEC = 1.0

# Max sizes
MAX_MEMORY_FILE_CHARS = 10_000
MAX_INCLUDE_DEPTH = 5
MAX_ATTACHMENT_CHARS = 50_000


# ══ Layer 1: System Prompt ══

class SystemPromptBuilder:
    """Builds the system prompt with static/dynamic split for cache optimization.

    Static sections (before DYNAMIC_BOUNDARY) can be cached globally.
    Dynamic sections (after) are per-session.
    """

    def __init__(self):
        self._sections: list[dict] = []

    def build(self, cwd: str = "", model: str = "", is_admin: bool = False,
              custom_prompt: str = "", agent_prompt: str = "") -> str:
        """Build complete system prompt with priority chain."""

        # Priority chain: agent > custom > default
        if agent_prompt:
            base = agent_prompt
        elif custom_prompt:
            base = custom_prompt
        else:
            base = self._build_default(cwd, model, is_admin)

        return base

    def _build_default(self, cwd: str, model: str, is_admin: bool) -> str:
        """Build default system prompt with static/dynamic sections."""
        parts = []

        # ── Static Sections (globally cacheable) ──
        parts.append(self._identity_section())
        parts.append(self._rules_section())
        parts.append(self._tools_section())
        parts.append(self._style_section())

        # ── Dynamic Boundary ──
        parts.append(DYNAMIC_BOUNDARY)

        # ── Dynamic Sections (per-session) ──
        parts.append(self._memory_section(cwd))
        parts.append(self._environment_section(cwd, model))

        return "\n\n".join(p for p in parts if p)

    def _identity_section(self) -> str:
        return (
            "Voce e um agente interativo que ajuda usuarios com tarefas de "
            "engenharia de software e negocios. Use as instrucoes abaixo e as "
            "ferramentas disponiveis para ajudar o usuario."
        )

    def _rules_section(self) -> str:
        """Claude Code directives — the core behavioral rules."""
        from .orchestrator import MASTER_SYSTEM_PROMPT
        return MASTER_SYSTEM_PROMPT

    def _tools_section(self) -> str:
        return (
            "USO DE FERRAMENTAS:\n"
            "- Use Read em vez de cat, Edit em vez de sed, Glob em vez de find, Grep em vez de grep\n"
            "- Chame multiplas ferramentas em paralelo quando possivel\n"
            "- Prefira editar arquivos existentes a criar novos\n"
            "- Nao adicione features, refatoracao ou melhorias alem do que foi pedido"
        )

    def _style_section(self) -> str:
        return (
            "TOM E ESTILO:\n"
            "- Nao use emojis a menos que o usuario peca\n"
            "- Quando referenciar codigo, inclua o padrao arquivo:linha\n"
            "- Respostas curtas e diretas. Va direto ao ponto.\n"
            "- Foque em: decisoes que precisam de input, updates de status, erros ou bloqueios"
        )

    def _memory_section(self, cwd: str) -> str:
        """Load memory files (CLAUDE.md walk)."""
        memories = load_memory_files(cwd)
        if not memories:
            return ""

        parts = [MEMORY_INSTRUCTION]
        for mem in memories:
            parts.append("Contents of %s:\n\n%s" % (mem["path"], mem["content"]))

        return "\n\n".join(parts)

    def _environment_section(self, cwd: str, model: str) -> str:
        """Runtime environment info."""
        lines = [
            "AMBIENTE:",
            "- Diretorio: %s" % (cwd or os.getcwd()),
            "- Plataforma: %s %s" % (platform.system(), platform.machine()),
            "- Modelo: %s" % (model or config.CLOW_MODEL),
            "- Data: %s" % time.strftime("%Y-%m-%d"),
        ]

        # Git info
        try:
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, cwd=cwd or None, timeout=2
            ).stdout.strip()
            if branch:
                lines.append("- Git branch: %s" % branch)
        except Exception:
            pass

        return "\n".join(lines)


# ══ Layer 2: Memory Files (CLAUDE.md System) ══

@lru_cache(maxsize=1)
def load_memory_files(cwd: str = "") -> tuple:
    """Load memory files with upward directory walk (memoized per-session).

    Loading order (low -> high priority):
    1. ~/.clow/CLAUDE.md (user global)
    2. Walk from root to CWD: CLAUDE.md, .clow/CLAUDE.md, .clow/rules/*.md
    3. CLAUDE.local.md (private, gitignored)
    4. ~/.clow/memory/MEMORY.md (auto-memory)
    """
    memories = []

    # 1. User global
    user_claude = Path.home() / ".clow" / "CLAUDE.md"
    if user_claude.exists():
        content = _safe_read(user_claude)
        if content:
            memories.append({"path": str(user_claude), "content": content, "priority": 1})

    # 2. Directory walk (root -> CWD)
    if cwd:
        current = Path(cwd).resolve()
        dirs = []
        visited = set()
        while True:
            dir_str = str(current)
            if dir_str in visited:
                break
            visited.add(dir_str)
            dirs.append(current)
            parent = current.parent
            if parent == current:
                break
            current = parent

        # Process root -> CWD (reverse so CWD has highest priority)
        for i, d in enumerate(reversed(dirs)):
            priority = 10 + i

            # CLAUDE.md
            for name in ["CLAUDE.md", ".clow/CLAUDE.md"]:
                f = d / name
                if f.exists():
                    content = _safe_read(f)
                    if content:
                        # Process @include directives
                        content = _process_includes(content, f.parent)
                        memories.append({"path": str(f), "content": content, "priority": priority})

            # .clow/rules/*.md
            rules_dir = d / ".clow" / "rules"
            if rules_dir.exists():
                for rule_file in sorted(rules_dir.glob("*.md")):
                    content = _safe_read(rule_file)
                    if content:
                        # Check for frontmatter (glob-gated rules)
                        content, paths = _parse_frontmatter(content)
                        if paths:
                            # Conditional rule — only include if matching files touched
                            memories.append({
                                "path": str(rule_file), "content": content,
                                "priority": priority, "conditional_paths": paths,
                            })
                        else:
                            memories.append({"path": str(rule_file), "content": content, "priority": priority})

    # 3. CLAUDE.local.md
    if cwd:
        local = Path(cwd) / "CLAUDE.local.md"
        if local.exists():
            content = _safe_read(local)
            if content:
                memories.append({"path": str(local), "content": content, "priority": 100})

    # 4. Auto-memory
    auto_mem = config.MEMORY_DIR / "MEMORY.md"
    if auto_mem.exists():
        content = _safe_read(auto_mem, max_chars=MAX_MEMORY_FILE_CHARS)
        if content:
            memories.append({"path": str(auto_mem), "content": content, "priority": 200})

    # Sort by priority (low to high — higher priority appears later in context)
    memories.sort(key=lambda m: m.get("priority", 0))

    return tuple(memories)  # Tuple for lru_cache hashability


def clear_memory_cache():
    """Clear memory file cache (called on compact, settings change)."""
    load_memory_files.cache_clear()


def _safe_read(path: Path, max_chars: int = MAX_MEMORY_FILE_CHARS) -> str:
    """Safely read a text file, respecting extension whitelist and size limits."""
    try:
        if path.suffix.lower() not in TEXT_EXTENSIONS and path.suffix:
            return ""
        content = path.read_text(encoding="utf-8", errors="replace")
        # Strip HTML comments
        content = re.sub(r'<!--[\s\S]*?-->', '', content)
        return content[:max_chars]
    except Exception:
        return ""


def _process_includes(content: str, base_dir: Path, depth: int = 0) -> str:
    """Process @include directives recursively."""
    if depth >= MAX_INCLUDE_DEPTH:
        return content

    processed = set()

    def replace_include(match):
        path_str = match.group(1).strip()
        if path_str.startswith("~/"):
            include_path = Path.home() / path_str[2:]
        elif path_str.startswith("./"):
            include_path = base_dir / path_str[2:]
        elif path_str.startswith("/"):
            include_path = Path(path_str)
        else:
            include_path = base_dir / path_str

        include_path = include_path.resolve()
        path_key = str(include_path)

        if path_key in processed:
            return "[circular include: %s]" % path_str
        processed.add(path_key)

        if include_path.exists():
            included = _safe_read(include_path)
            if included:
                return _process_includes(included, include_path.parent, depth + 1)
        return "[include not found: %s]" % path_str

    return re.sub(r'^@(.+)$', replace_include, content, flags=re.MULTILINE)


def _parse_frontmatter(content: str) -> tuple:
    """Parse YAML frontmatter for conditional paths."""
    if not content.startswith("---"):
        return content, []

    end = content.find("---", 3)
    if end < 0:
        return content, []

    frontmatter = content[3:end].strip()
    body = content[end + 3:].strip()

    paths = []
    for line in frontmatter.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            paths.append(line[2:].strip())

    return body, paths


# ══ Layer 3: Per-Turn Attachments ══

def get_attachments(
    session_messages: list,
    turn_count: int = 0,
    plan_mode: bool = False,
    cwd: str = "",
) -> list:
    """Compute per-turn attachments (recomputed every turn).

    Runs with 1-second timeout. Each source is wrapped in error handling.
    """
    attachments = []

    # 1. Token usage tracking
    total_tokens = sum(
        len(m.get("content", "")) // 4
        for m in session_messages
        if isinstance(m.get("content"), str)
    )
    attachments.append({
        "type": "token_usage",
        "content": "[Tokens estimados: ~%s]" % format(total_tokens, ","),
    })

    # 2. Plan mode reminder
    if plan_mode and turn_count > 0 and turn_count % PLAN_REMINDER_TURNS == 0:
        attachments.append({
            "type": "plan_mode",
            "content": "[MODO PLANO ATIVO] Voce esta no modo de planejamento. Apenas leitura permitida.",
        })

    # 3. TODO reminder (every N turns after last write)
    if turn_count > 0 and turn_count % TODO_REMINDER_TURNS == 0:
        # Check if there are pending tasks
        try:
            from .tasks import get_task_manager
            tm = get_task_manager()
            pending = [t for t in tm.list_all() if t.status.value in ("pending", "in_progress")]
            if pending:
                task_list = "\n".join("- [%s] %s" % (t.status.value, t.title) for t in pending[:5])
                attachments.append({
                    "type": "todo_reminder",
                    "content": "[TAREFAS PENDENTES]\n%s" % task_list,
                })
        except Exception:
            pass

    # 4. Context warning
    from .compaction import get_context_warning
    warning = get_context_warning(session_messages)
    if warning.get("warning"):
        pct = warning.get("percent_used", 0)
        attachments.append({
            "type": "context_warning",
            "content": "[AVISO: Contexto em %s%% de uso. Compactacao automatica em breve.]" % pct,
        })

    return attachments


# ══ Assembly Pipeline ══

_prompt_builder = SystemPromptBuilder()

def assemble_context(
    session_messages: list,
    cwd: str = "",
    model: str = "",
    is_admin: bool = False,
    turn_count: int = 0,
    plan_mode: bool = False,
    custom_prompt: str = "",
    agent_prompt: str = "",
) -> list:
    """Full context assembly pipeline (Claude Code architecture).

    1. Build system prompt (static + dynamic, cache-split)
    2. Load memory files (memoized)
    3. Compute attachments (per-turn)
    4. Inject into message array
    """
    # 1. System prompt
    system_prompt = _prompt_builder.build(
        cwd=cwd, model=model, is_admin=is_admin,
        custom_prompt=custom_prompt, agent_prompt=agent_prompt,
    )

    # 2. Attachments
    attachments = get_attachments(
        session_messages, turn_count=turn_count,
        plan_mode=plan_mode, cwd=cwd,
    )

    # 3. Build final system message with cache split
    # Everything before DYNAMIC_BOUNDARY uses global cache
    # Everything after is per-session
    if DYNAMIC_BOUNDARY in system_prompt:
        static, dynamic = system_prompt.split(DYNAMIC_BOUNDARY, 1)
        system_content = static.strip() + "\n\n" + dynamic.strip()
    else:
        system_content = system_prompt

    # 4. Inject attachments into system message
    if attachments:
        att_text = "\n\n".join(a["content"] for a in attachments if a.get("content"))
        if att_text:
            system_content += "\n\n" + att_text

    # 5. Build or update system message
    result = list(session_messages)
    if result and result[0].get("role") == "system":
        result[0] = {"role": "system", "content": system_content}
    else:
        result.insert(0, {"role": "system", "content": system_content})

    return result


# ══ /context Command ══

def analyze_context(session_messages: list, cwd: str = "") -> dict:
    """Analyze current context breakdown (for /context command)."""
    sections = {}
    total_tokens = 0

    for msg in session_messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        chars = len(content) if isinstance(content, str) else 0
        tokens = chars // 4

        if role not in sections:
            sections[role] = {"count": 0, "tokens": 0}
        sections[role]["count"] += 1
        sections[role]["tokens"] += tokens
        total_tokens += tokens

    # Memory files
    memories = load_memory_files(cwd)
    mem_tokens = sum(len(m.get("content", "")) // 4 for m in memories)

    context_window = 128_000
    effective = context_window - 20_000

    return {
        "total_tokens": total_tokens,
        "context_window": context_window,
        "effective_window": effective,
        "percent_used": round(total_tokens / effective * 100, 1),
        "sections": sections,
        "memory_files": len(memories),
        "memory_tokens": mem_tokens,
        "messages": len(session_messages),
    }
