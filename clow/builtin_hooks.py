"""Built-in hooks for Clow — seguranca, qualidade, automacao.

Hooks nativos que rodam in-process (sem shell), cobrindo:
  - SecretScanner: detecta 30+ padroes de secrets em staged files
  - ConventionalCommits: valida formato de commit messages
  - DangerousCommandBlocker: bloqueia comandos destrutivos em 3 niveis
  - TDDGate: exige test file antes de editar producao
  - ChangeLogger: registra toda mutacao em CSV
  - ScopeGuard: detecta edicoes fora do escopo declarado
  - PlanGate: avisa quando nao ha spec recente

Cada hook e uma classe com metodo check(context) -> BuiltinHookResult.
"""

from __future__ import annotations

import csv
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Result ──────────────────────────────────────────────────────

@dataclass
class BuiltinHookResult:
    """Resultado de um hook built-in.

    action:
        "allow" — hook aprova a acao
        "deny"  — hook bloqueia a acao
        "warn"  — hook avisa mas permite
    """
    action: str = "allow"    # "allow", "deny", "warn"
    message: str = ""
    details: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.action == "deny"

    @property
    def is_warning(self) -> bool:
        return self.action == "warn"


# ── Registry ────────────────────────────────────────────────────

BUILTIN_HOOKS: dict[str, "BaseBuiltinHook"] = {}


def _register(cls: type) -> type:
    """Decorator que registra o hook no dicionario global."""
    instance = cls()
    BUILTIN_HOOKS[instance.name] = instance
    return cls


# ── Base ────────────────────────────────────────────────────────

class BaseBuiltinHook:
    """Classe base para hooks built-in."""
    name: str = ""
    description: str = ""
    event: str = ""            # pre_tool_call, post_tool_call, on_exit, etc.
    tool_filter: str = ""      # vazio = todas as tools

    def check(self, context: dict[str, Any]) -> BuiltinHookResult:
        raise NotImplementedError


# ── Helpers ─────────────────────────────────────────────────────

def _git_staged_files(cwd: str | None = None) -> list[str]:
    """Retorna lista de arquivos staged no git."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True, text=True,
            cwd=cwd or os.getcwd(), timeout=10,
        )
        if proc.returncode == 0:
            return [f.strip() for f in proc.stdout.strip().splitlines() if f.strip()]
    except Exception:
        pass
    return []


def _git_staged_content(filepath: str, cwd: str | None = None) -> str:
    """Retorna conteudo staged de um arquivo."""
    try:
        proc = subprocess.run(
            ["git", "show", f":{filepath}"],
            capture_output=True, text=True,
            cwd=cwd or os.getcwd(), timeout=10,
        )
        if proc.returncode == 0:
            return proc.stdout
    except Exception:
        pass
    return ""


# ── 1. SecretScanner ────────────────────────────────────────────

@dataclass
class _SecretPattern:
    name: str
    pattern: re.Pattern
    severity: str  # "critical", "high", "medium"

# yapf: disable
_SECRET_PATTERNS: list[_SecretPattern] = [
    # ── AWS ──
    _SecretPattern("AWS Access Key",          re.compile(r"AKIA[0-9A-Z]{16}"),                                          "critical"),
    _SecretPattern("AWS Secret Key",          re.compile(r"(?i)aws(.{0,20})?['\"][0-9a-zA-Z/+]{40}['\"]"),              "critical"),
    # ── Anthropic ──
    _SecretPattern("Anthropic API Key",       re.compile(r"sk-ant-api\d{2}-[A-Za-z0-9\-_]{20,}"),                       "critical"),
    # ── OpenAI ──
    _SecretPattern("OpenAI API Key",          re.compile(r"sk-[a-zA-Z0-9]{48,}"),                                       "critical"),
    # ── Google ──
    _SecretPattern("Google API Key",          re.compile(r"AIza[0-9A-Za-z\-_]{35}"),                                    "critical"),
    _SecretPattern("Google OAuth Secret",     re.compile(r"GOCSPX-[A-Za-z0-9\-_]{28,}"),                                "high"),
    # ── Stripe ──
    _SecretPattern("Stripe Live Key",         re.compile(r"sk_live_[0-9a-zA-Z]{24,}"),                                  "critical"),
    _SecretPattern("Stripe Test Key",         re.compile(r"sk_test_[0-9a-zA-Z]{24,}"),                                  "high"),
    _SecretPattern("Stripe Restricted Key",   re.compile(r"rk_live_[0-9a-zA-Z]{24,}"),                                  "critical"),
    # ── GitHub ──
    _SecretPattern("GitHub PAT (classic)",    re.compile(r"ghp_[0-9a-zA-Z]{36}"),                                       "critical"),
    _SecretPattern("GitHub OAuth Token",      re.compile(r"gho_[0-9a-zA-Z]{36}"),                                       "critical"),
    _SecretPattern("GitHub App Token",        re.compile(r"ghs_[0-9a-zA-Z]{36}"),                                       "high"),
    _SecretPattern("GitHub Refresh Token",    re.compile(r"ghr_[0-9a-zA-Z]{36}"),                                       "high"),
    _SecretPattern("GitHub Fine-grained PAT", re.compile(r"github_pat_[0-9a-zA-Z_]{22,}"),                              "critical"),
    # ── Vercel ──
    _SecretPattern("Vercel Token",            re.compile(r"(?i)vercel[_\-]?(?:api[_\-]?)?(?:token|key)['\"]?\s*[:=]\s*['\"][A-Za-z0-9]{24,}['\"]"), "high"),
    # ── Supabase ──
    _SecretPattern("Supabase Service Key",    re.compile(r"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+"), "high"),
    # ── HuggingFace ──
    _SecretPattern("HuggingFace Token",       re.compile(r"hf_[A-Za-z0-9]{34,}"),                                       "high"),
    # ── Replicate ──
    _SecretPattern("Replicate Token",         re.compile(r"r8_[A-Za-z0-9]{38,}"),                                       "high"),
    # ── Groq ──
    _SecretPattern("Groq API Key",            re.compile(r"gsk_[A-Za-z0-9]{48,}"),                                      "high"),
    # ── Databricks ──
    _SecretPattern("Databricks Token",        re.compile(r"dapi[0-9a-f]{32}"),                                          "high"),
    # ── GitLab ──
    _SecretPattern("GitLab PAT",              re.compile(r"glpat-[A-Za-z0-9\-_]{20,}"),                                 "critical"),
    _SecretPattern("GitLab Pipeline Token",   re.compile(r"glptt-[A-Za-z0-9\-]{20,}"),                                  "high"),
    # ── DigitalOcean ──
    _SecretPattern("DigitalOcean Token",      re.compile(r"dop_v1_[a-f0-9]{64}"),                                       "high"),
    _SecretPattern("DigitalOcean OAuth",      re.compile(r"doo_v1_[a-f0-9]{64}"),                                       "high"),
    # ── Linear ──
    _SecretPattern("Linear API Key",          re.compile(r"lin_api_[A-Za-z0-9]{40,}"),                                  "high"),
    # ── Notion ──
    _SecretPattern("Notion Integration",      re.compile(r"secret_[A-Za-z0-9]{43}"),                                    "high"),
    _SecretPattern("Notion Internal Token",   re.compile(r"ntn_[A-Za-z0-9]{40,}"),                                      "high"),
    # ── Figma ──
    _SecretPattern("Figma PAT",              re.compile(r"figd_[A-Za-z0-9\-_]{40,}"),                                   "high"),
    # ── npm ──
    _SecretPattern("npm Token",              re.compile(r"npm_[A-Za-z0-9]{36}"),                                         "critical"),
    # ── PyPI ──
    _SecretPattern("PyPI Token",             re.compile(r"pypi-AgEIcHlwaS5vcmc[A-Za-z0-9\-_]{50,}"),                    "critical"),
    # ── Slack ──
    _SecretPattern("Slack Bot Token",        re.compile(r"xoxb-[0-9]{10,}-[0-9]{10,}-[A-Za-z0-9]{24}"),                 "critical"),
    _SecretPattern("Slack User Token",       re.compile(r"xoxp-[0-9]{10,}-[0-9]{10,}-[A-Za-z0-9]{24,}"),               "critical"),
    _SecretPattern("Slack Webhook",          re.compile(r"https://hooks\.slack\.com/services/T[A-Z0-9]{8,}/B[A-Z0-9]{8,}/[A-Za-z0-9]{24}"), "high"),
    # ── Telegram ──
    _SecretPattern("Telegram Bot Token",     re.compile(r"[0-9]{8,10}:[A-Za-z0-9_-]{35}"),                              "high"),
    # ── Discord ──
    _SecretPattern("Discord Bot Token",      re.compile(r"[MN][A-Za-z\d]{23,}\.[\w-]{6}\.[\w-]{27,}"),                  "critical"),
    _SecretPattern("Discord Webhook",        re.compile(r"https://discord(?:app)?\.com/api/webhooks/\d+/[\w\-]+"),       "high"),
    # ── Twilio ──
    _SecretPattern("Twilio API Key",         re.compile(r"SK[0-9a-fA-F]{32}"),                                           "high"),
    _SecretPattern("Twilio Auth Token",      re.compile(r"(?i)twilio[_\-]?auth[_\-]?token\s*[:=]\s*['\"][a-f0-9]{32}['\"]"), "critical"),
    # ── SendGrid ──
    _SecretPattern("SendGrid API Key",       re.compile(r"SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43}"),                 "critical"),
    # ── Private Keys ──
    _SecretPattern("RSA Private Key",        re.compile(r"-----BEGIN RSA PRIVATE KEY-----"),                              "critical"),
    _SecretPattern("EC Private Key",         re.compile(r"-----BEGIN EC PRIVATE KEY-----"),                               "critical"),
    _SecretPattern("OpenSSH Private Key",    re.compile(r"-----BEGIN OPENSSH PRIVATE KEY-----"),                          "critical"),
    _SecretPattern("PGP Private Key",        re.compile(r"-----BEGIN PGP PRIVATE KEY BLOCK-----"),                        "critical"),
    # ── Database Connection Strings ──
    _SecretPattern("Database URL",           re.compile(r"(?i)(?:postgres|mysql|mongodb|redis)://[^\s'\"]{10,}"),         "critical"),
    _SecretPattern("SQLite with password",   re.compile(r"(?i)sqlite.*password\s*[:=]"),                                  "high"),
    # ── JWT ──
    _SecretPattern("JWT Secret",             re.compile(r"(?i)jwt[_\-]?secret\s*[:=]\s*['\"][^\s'\"]{8,}['\"]"),          "high"),
    # ── Generic ──
    _SecretPattern("Generic API Key",        re.compile(r"(?i)api[_\-]?key\s*[:=]\s*['\"][A-Za-z0-9\-_]{20,}['\"]"),     "medium"),
    _SecretPattern("Generic Secret",         re.compile(r"(?i)(?:secret|password|passwd|pwd)\s*[:=]\s*['\"][^\s'\"]{8,}['\"]"), "medium"),
]
# yapf: enable

# Extensoes que devem ser ignoradas no scan (binarios, etc.)
_BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".woff", ".woff2", ".ttf", ".eot",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".7z",
    ".exe", ".dll", ".so", ".dylib",
    ".pyc", ".pyo", ".class", ".o",
    ".sqlite", ".db", ".lock",
})


@_register
class SecretScanner(BaseBuiltinHook):
    """Escaneia staged files buscando 30+ padroes de secrets.

    Bloqueia em findings critical/high. Avisa em medium.
    """
    name = "secret_scanner"
    description = "Scans staged git files for secrets and credentials"
    event = "pre_tool_call"
    tool_filter = "bash"

    def check(self, context: dict[str, Any]) -> BuiltinHookResult:
        # Apenas intercepta comandos git commit
        tool_args = str(context.get("tool_args", ""))
        if "git" not in tool_args or "commit" not in tool_args:
            return BuiltinHookResult(action="allow")

        cwd = context.get("cwd")
        staged = _git_staged_files(cwd)
        if not staged:
            return BuiltinHookResult(action="allow", message="No staged files to scan.")

        findings: list[str] = []
        has_blocking = False

        for filepath in staged:
            ext = Path(filepath).suffix.lower()
            if ext in _BINARY_EXTENSIONS:
                continue

            content = _git_staged_content(filepath, cwd)
            if not content:
                continue

            for line_num, line in enumerate(content.splitlines(), 1):
                for pat in _SECRET_PATTERNS:
                    if pat.pattern.search(line):
                        sev = pat.severity.upper()
                        entry = f"[{sev}] {pat.name} in {filepath}:{line_num}"
                        findings.append(entry)
                        if pat.severity in ("critical", "high"):
                            has_blocking = True

        if not findings:
            return BuiltinHookResult(action="allow", message="Secret scan: clean.")

        msg = f"Secret scan found {len(findings)} issue(s):\n" + "\n".join(findings)
        if has_blocking:
            return BuiltinHookResult(action="deny", message=msg, details=findings)
        return BuiltinHookResult(action="warn", message=msg, details=findings)


# ── 2. ConventionalCommits ──────────────────────────────────────

_CONVENTIONAL_PATTERN = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert)"
    r"(\([a-zA-Z0-9_\-./]+\))?!?:\s.{1,}"
)


@_register
class ConventionalCommits(BaseBuiltinHook):
    """Valida que commit messages seguem Conventional Commits.

    Formato: type(scope): description
    Types: feat, fix, docs, style, refactor, perf, test, chore, ci, build, revert
    """
    name = "conventional_commits"
    description = "Validates commit messages follow Conventional Commits pattern"
    event = "pre_tool_call"
    tool_filter = "bash"

    VALID_TYPES = {
        "feat", "fix", "docs", "style", "refactor",
        "perf", "test", "chore", "ci", "build", "revert",
    }

    def check(self, context: dict[str, Any]) -> BuiltinHookResult:
        tool_args = str(context.get("tool_args", ""))
        if "git" not in tool_args or "commit" not in tool_args:
            return BuiltinHookResult(action="allow")

        # Extrai a mensagem de commit do argumento -m
        commit_msg = self._extract_commit_message(tool_args)
        if not commit_msg:
            # Pode ser commit sem -m (abre editor), permite
            return BuiltinHookResult(action="allow")

        # Valida formato
        first_line = commit_msg.strip().splitlines()[0] if commit_msg.strip() else ""
        if not first_line:
            return BuiltinHookResult(
                action="deny",
                message="Commit message is empty.",
            )

        if _CONVENTIONAL_PATTERN.match(first_line):
            return BuiltinHookResult(
                action="allow",
                message=f"Commit message OK: {first_line[:60]}",
            )

        return BuiltinHookResult(
            action="warn",
            message=(
                f"Commit message does not follow Conventional Commits:\n"
                f"  Got: {first_line[:80]}\n"
                f"  Expected: type(scope): description\n"
                f"  Valid types: {', '.join(sorted(self.VALID_TYPES))}"
            ),
        )

    @staticmethod
    def _extract_commit_message(args: str) -> str:
        """Extrai mensagem de -m 'msg' ou -m \"msg\" do comando git."""
        # Tenta -m "..." ou -m '...'
        patterns = [
            re.compile(r"""-m\s*"((?:[^"\\]|\\.)*)"\s*"""),
            re.compile(r"""-m\s*'((?:[^'\\]|\\.)*)'\s*"""),
            re.compile(r"""-m\s+(\S+)"""),
        ]
        for p in patterns:
            m = p.search(args)
            if m:
                return m.group(1)
        # Tenta heredoc $(cat <<'EOF' ... EOF)
        heredoc = re.search(r"<<'?EOF'?\s*\n(.*?)\nEOF", args, re.DOTALL)
        if heredoc:
            return heredoc.group(1)
        return ""


# ── 3. DangerousCommandBlocker ──────────────────────────────────

@dataclass
class _DangerPattern:
    name: str
    pattern: re.Pattern
    level: str  # "catastrophic", "critical_path", "suspicious"
    message: str


# yapf: disable
_DANGER_PATTERNS: list[_DangerPattern] = [
    # ── CATASTROPHIC (block always) ──
    _DangerPattern(
        "rm root",
        re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*(/|/\*)\b"),
        "catastrophic",
        "Attempted to delete root filesystem",
    ),
    _DangerPattern(
        "rm home",
        re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*(~/|~\s|/home)\b"),
        "catastrophic",
        "Attempted to delete home directory",
    ),
    _DangerPattern(
        "rm wildcard root",
        re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*\*\s*$"),
        "catastrophic",
        "Attempted to rm * (wildcard at root context)",
    ),
    _DangerPattern(
        "dd device",
        re.compile(r"\bdd\s+.*of=/dev/[a-z]"),
        "catastrophic",
        "Attempted to write directly to device with dd",
    ),
    _DangerPattern(
        "mkfs",
        re.compile(r"\bmkfs\b"),
        "catastrophic",
        "Attempted to format filesystem",
    ),
    _DangerPattern(
        "fork bomb",
        re.compile(r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;?\s*:"),
        "catastrophic",
        "Fork bomb detected",
    ),
    _DangerPattern(
        "fork bomb alt",
        re.compile(r"\bwhile\s+true\s*;\s*do\s+fork"),
        "catastrophic",
        "Fork bomb variant detected",
    ),
    _DangerPattern(
        "chmod 777 root",
        re.compile(r"\bchmod\s+(-[a-zA-Z]*\s+)*777\s+/\s*$"),
        "catastrophic",
        "Attempted to chmod 777 root filesystem",
    ),
    _DangerPattern(
        "chmod recursive root",
        re.compile(r"\bchmod\s+(-[a-zA-Z]*)?R\s+777\s+/"),
        "catastrophic",
        "Attempted recursive chmod 777 on root",
    ),
    _DangerPattern(
        "dev/null overwrite",
        re.compile(r">\s*/dev/sda"),
        "catastrophic",
        "Attempted to overwrite device",
    ),

    # ── CRITICAL PATH (block) ──
    _DangerPattern(
        "rm .clow",
        re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*.*\.clow(/|\s|$)"),
        "critical_path",
        "Attempted to delete .clow directory",
    ),
    _DangerPattern(
        "rm .git",
        re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*.*\.git(/|\s|$)"),
        "critical_path",
        "Attempted to delete .git directory",
    ),
    _DangerPattern(
        "rm .env",
        re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*.*\.env\b"),
        "critical_path",
        "Attempted to delete .env file",
    ),
    _DangerPattern(
        "rm package.json",
        re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*.*package\.json\b"),
        "critical_path",
        "Attempted to delete package.json",
    ),
    _DangerPattern(
        "rm requirements.txt",
        re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*.*requirements\.txt\b"),
        "critical_path",
        "Attempted to delete requirements.txt",
    ),
    _DangerPattern(
        "mv .clow",
        re.compile(r"\bmv\s+.*\.clow(/|\s)"),
        "critical_path",
        "Attempted to move .clow directory",
    ),
    _DangerPattern(
        "mv .git",
        re.compile(r"\bmv\s+.*\.git(/|\s)"),
        "critical_path",
        "Attempted to move .git directory",
    ),
    _DangerPattern(
        "mv .env",
        re.compile(r"\bmv\s+.*\.env\s"),
        "critical_path",
        "Attempted to move .env file",
    ),

    # ── SUSPICIOUS (warn) ──
    _DangerPattern(
        "chained rm",
        re.compile(r"\brm\b.*&&.*\brm\b"),
        "suspicious",
        "Multiple rm commands chained together",
    ),
    _DangerPattern(
        "rm wildcard",
        re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*\S*\*"),
        "suspicious",
        "rm with wildcard pattern",
    ),
    _DangerPattern(
        "find -delete",
        re.compile(r"\bfind\b.*-delete\b"),
        "suspicious",
        "find with -delete flag",
    ),
    _DangerPattern(
        "xargs rm",
        re.compile(r"\bxargs\s+.*\brm\b"),
        "suspicious",
        "xargs piped to rm",
    ),
    _DangerPattern(
        "rm -rf with variable",
        re.compile(r"\brm\s+-[a-zA-Z]*f[a-zA-Z]*\s+\$"),
        "suspicious",
        "rm -rf with shell variable (potential unset variable danger)",
    ),
    _DangerPattern(
        "truncate",
        re.compile(r">\s*/etc/"),
        "suspicious",
        "Redirect overwriting system file",
    ),
    _DangerPattern(
        "curl pipe shell",
        re.compile(r"\bcurl\b.*\|\s*(ba)?sh\b"),
        "suspicious",
        "Piping curl output to shell",
    ),
    _DangerPattern(
        "wget pipe shell",
        re.compile(r"\bwget\b.*\|\s*(ba)?sh\b"),
        "suspicious",
        "Piping wget output to shell",
    ),

    # ── DEPLOY / REMOTE CODE EXECUTION (block always) ──
    _DangerPattern(
        "git clone remote",
        re.compile(r"\bgit\s+clone\s+(https?://|git@|ssh://)"),
        "catastrophic",
        "Attempted to clone from remote repository — blocked for security",
    ),
    _DangerPattern(
        "git pull remote",
        re.compile(r"\bgit\s+pull\s+(?!origin\s+HEAD)"),
        "catastrophic",
        "Attempted git pull from remote — deploy via GitHub is blocked",
    ),
    _DangerPattern(
        "deploy script",
        re.compile(r"\b(bash|sh|\./).*deploy(\.sh)?\b"),
        "catastrophic",
        "Attempted to run deploy script — blocked for security",
    ),
    _DangerPattern(
        "systemctl restart clow",
        re.compile(r"\bsystemctl\s+(restart|start|stop|reload)\s+"),
        "catastrophic",
        "Attempted to control system services — blocked for security",
    ),
    _DangerPattern(
        "pip install from url",
        re.compile(r"\bpip\s+install\s+.*https?://"),
        "catastrophic",
        "Attempted pip install from URL — remote code execution risk",
    ),
    _DangerPattern(
        "git fetch remote",
        re.compile(r"\bgit\s+fetch\s+\S"),
        "critical_path",
        "Attempted git fetch from remote — blocked for security",
    ),
    _DangerPattern(
        "wget github",
        re.compile(r"\b(wget|curl)\b.*github\.com"),
        "critical_path",
        "Attempted to download from GitHub — blocked for security",
    ),
    _DangerPattern(
        "python setup install",
        re.compile(r"\bpython\b.*setup\.py\s+install"),
        "critical_path",
        "Attempted setup.py install — remote code execution risk",
    ),
]
# yapf: enable


@_register
class DangerousCommandBlocker(BaseBuiltinHook):
    """Bloqueia comandos destrutivos em 3 niveis de severidade.

    CATASTROPHIC: rm /, dd, mkfs, fork bombs — sempre bloqueia
    CRITICAL PATH: rm/mv em .clow/, .git/, .env, etc. — sempre bloqueia
    SUSPICIOUS: rm com wildcard, find -delete — avisa
    """
    name = "dangerous_command_blocker"
    description = "Blocks catastrophic and dangerous shell commands"
    event = "pre_tool_call"
    tool_filter = "bash"

    def check(self, context: dict[str, Any]) -> BuiltinHookResult:
        command = str(context.get("tool_args", ""))
        if not command.strip():
            return BuiltinHookResult(action="allow")

        findings: list[str] = []
        worst_level = "suspicious"

        for dp in _DANGER_PATTERNS:
            if dp.pattern.search(command):
                findings.append(f"[{dp.level.upper()}] {dp.message}")
                if dp.level == "catastrophic":
                    worst_level = "catastrophic"
                elif dp.level == "critical_path" and worst_level != "catastrophic":
                    worst_level = "critical_path"

        if not findings:
            return BuiltinHookResult(action="allow")

        msg = f"Dangerous command detected ({len(findings)} issue(s)):\n" + "\n".join(findings)

        if worst_level in ("catastrophic", "critical_path"):
            return BuiltinHookResult(action="deny", message=msg, details=findings)

        return BuiltinHookResult(action="warn", message=msg, details=findings)


# ── 4. TDDGate ──────────────────────────────────────────────────

# Extensoes de codigo de producao que exigem test
_PROD_EXTENSIONS = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx",
    ".go", ".rs", ".rb", ".java", ".kt",
    ".cs", ".cpp", ".c", ".swift",
})

# Patterns de nomes que devem ser ignorados (config, migrations, etc.)
_TDD_SKIP_PATTERNS = [
    re.compile(r"(?i)(conftest|setup|config|settings|__init__|__main__|migrations?|alembic)"),
    re.compile(r"(?i)(\.?test[_\-]|_test\.|\.test\.|\.spec\.|test_)"),
    re.compile(r"(?i)(manage|wsgi|asgi|celery)\.py$"),
    re.compile(r"(?i)/(migrations?|fixtures|scripts|deploy|docs)/"),
]


@_register
class TDDGate(BaseBuiltinHook):
    """Bloqueia edicao de codigo de producao sem test correspondente.

    Busca test files com padroes: TestFile, .test., _test., test_
    Ignora: config, migrations, test files, __init__, scripts.
    """
    name = "tdd_gate"
    description = "Blocks editing production code without corresponding test file"
    event = "pre_tool_call"
    tool_filter = ""  # Filtra write/edit tools internamente

    # Tools que modificam arquivos
    _WRITE_TOOLS = {"write", "edit", "create", "notebook_edit"}

    def check(self, context: dict[str, Any]) -> BuiltinHookResult:
        tool_name = str(context.get("tool_name", "")).lower()
        if tool_name not in self._WRITE_TOOLS:
            return BuiltinHookResult(action="allow")

        # Extrai filepath do tool_args
        tool_args = context.get("tool_args", "")
        filepath = self._extract_filepath(tool_args)
        if not filepath:
            return BuiltinHookResult(action="allow")

        p = Path(filepath)
        ext = p.suffix.lower()

        # So valida extensoes de producao
        if ext not in _PROD_EXTENSIONS:
            return BuiltinHookResult(action="allow")

        # Pula patterns conhecidos (config, migrations, proprios tests)
        rel = str(p)
        for skip in _TDD_SKIP_PATTERNS:
            if skip.search(rel):
                return BuiltinHookResult(action="allow")

        # Busca test file correspondente
        if self._find_test_file(p):
            return BuiltinHookResult(
                action="allow",
                message=f"Test file found for {p.name}",
            )

        return BuiltinHookResult(
            action="deny",
            message=(
                f"No test file found for {p.name}.\n"
                f"Create a test file first (TDD). Searched patterns:\n"
                f"  - {p.stem}Test{ext}, {p.stem}.test{ext}\n"
                f"  - {p.stem}_test{ext}, test_{p.stem}{ext}"
            ),
        )

    @staticmethod
    def _extract_filepath(tool_args: Any) -> str:
        """Extrai filepath dos argumentos da tool."""
        if isinstance(tool_args, dict):
            return str(tool_args.get("file_path", tool_args.get("path", "")))
        if isinstance(tool_args, str):
            # Tenta extrair de JSON string
            try:
                import json
                d = json.loads(tool_args)
                if isinstance(d, dict):
                    return str(d.get("file_path", d.get("path", "")))
            except (json.JSONDecodeError, TypeError):
                pass
            return tool_args
        return ""

    @staticmethod
    def _find_test_file(filepath: Path) -> bool:
        """Verifica se existe test file correspondente."""
        stem = filepath.stem
        ext = filepath.suffix
        parent = filepath.parent

        # Patterns de test file
        test_names = [
            f"{stem}Test{ext}",
            f"{stem}.test{ext}",
            f"{stem}_test{ext}",
            f"test_{stem}{ext}",
            f"{stem}.spec{ext}",
            f"{stem}_spec{ext}",
        ]

        # Busca no mesmo diretorio
        for name in test_names:
            if (parent / name).exists():
                return True

        # Busca em diretorios de test comuns
        test_dirs = ["tests", "test", "__tests__", "spec"]
        for td in test_dirs:
            # Irmao do diretorio pai
            test_dir = parent.parent / td
            if test_dir.is_dir():
                for name in test_names:
                    if (test_dir / name).exists():
                        return True
            # Subdiretorio do pai
            test_dir = parent / td
            if test_dir.is_dir():
                for name in test_names:
                    if (test_dir / name).exists():
                        return True

        return False


# ── 5. ChangeLogger ─────────────────────────────────────────────

@_register
class ChangeLogger(BaseBuiltinHook):
    """Loga toda mutacao de arquivo em CSV (.clow/change_log.csv).

    Colunas: timestamp, tool, file_path, action, details
    Ignora comandos read-only (read, glob, grep, search).
    """
    name = "change_logger"
    description = "Logs every file mutation to CSV"
    event = "post_tool_call"
    tool_filter = ""

    _READ_ONLY_TOOLS = frozenset({
        "read", "glob", "grep", "search", "list_files",
        "web_search", "web_fetch",
    })

    _LOG_DIR = Path.home() / ".clow"
    _LOG_FILE = _LOG_DIR / "change_log.csv"

    def check(self, context: dict[str, Any]) -> BuiltinHookResult:
        tool_name = str(context.get("tool_name", "")).lower()
        if tool_name in self._READ_ONLY_TOOLS:
            return BuiltinHookResult(action="allow")

        filepath = ""
        action = tool_name
        details = ""
        tool_args = context.get("tool_args", "")

        # Extrai filepath
        if isinstance(tool_args, dict):
            filepath = str(tool_args.get("file_path", tool_args.get("path", "")))
            if tool_name == "edit":
                old = str(tool_args.get("old_string", ""))[:50]
                new = str(tool_args.get("new_string", ""))[:50]
                details = f"edit: '{old}' -> '{new}'"
            elif tool_name == "write":
                content = str(tool_args.get("content", ""))
                details = f"write: {len(content)} chars"
            elif tool_name == "bash":
                cmd = str(tool_args.get("command", ""))[:200]
                details = f"cmd: {cmd}"
                filepath = cmd
        elif isinstance(tool_args, str):
            details = tool_args[:200]

        # Loga apenas se ha algo a registrar
        if not filepath and not details:
            return BuiltinHookResult(action="allow")

        self._append_log(tool_name, filepath, action, details)

        return BuiltinHookResult(action="allow")

    def _append_log(self, tool: str, filepath: str, action: str, details: str) -> None:
        """Appenda uma linha ao CSV de log."""
        try:
            self._LOG_DIR.mkdir(parents=True, exist_ok=True)
            file_exists = self._LOG_FILE.exists()

            with open(self._LOG_FILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["timestamp", "tool", "file_path", "action", "details"])
                writer.writerow([
                    datetime.now().isoformat(timespec="seconds"),
                    tool,
                    filepath,
                    action,
                    details,
                ])
        except Exception as e:
            logger.warning("ChangeLogger failed to write: %s", e)


# ── 6. ScopeGuard ──────────────────────────────────────────────

@_register
class ScopeGuard(BaseBuiltinHook):
    """Detecta edicoes fora do escopo declarado em .spec.md.

    Busca .spec.md no diretorio de trabalho e extrai paths declarados
    na secao 'scope' ou 'files'. Avisa (nao bloqueia) se o arquivo
    editado nao esta no escopo.
    """
    name = "scope_guard"
    description = "Warns when files are modified outside declared .spec.md scope"
    event = "pre_tool_call"
    tool_filter = ""

    _WRITE_TOOLS = {"write", "edit", "create", "bash"}

    def check(self, context: dict[str, Any]) -> BuiltinHookResult:
        tool_name = str(context.get("tool_name", "")).lower()
        if tool_name not in self._WRITE_TOOLS:
            return BuiltinHookResult(action="allow")

        cwd = context.get("cwd", os.getcwd())
        spec_files = self._find_spec_files(cwd)
        if not spec_files:
            return BuiltinHookResult(action="allow")

        # Extrai filepath da operacao
        tool_args = context.get("tool_args", "")
        filepath = self._extract_filepath(tool_args)
        if not filepath:
            return BuiltinHookResult(action="allow")

        # Coleta todos os scopes declarados
        declared_paths = set()
        for spec in spec_files:
            declared_paths.update(self._parse_scope(spec))

        if not declared_paths:
            return BuiltinHookResult(action="allow")

        # Verifica se filepath esta no escopo
        filepath_resolved = str(Path(filepath).resolve())
        for dp in declared_paths:
            dp_resolved = str(Path(dp).resolve()) if os.path.isabs(dp) else dp
            # Match parcial: o filepath contem o path declarado ou vice-versa
            if dp_resolved in filepath_resolved or dp in filepath:
                return BuiltinHookResult(action="allow")
            # Glob-like: se dp termina com /, verifica prefixo
            if filepath.startswith(dp) or filepath_resolved.startswith(dp_resolved):
                return BuiltinHookResult(action="allow")

        return BuiltinHookResult(
            action="warn",
            message=(
                f"File '{Path(filepath).name}' is outside declared scope.\n"
                f"Declared scope ({len(declared_paths)} paths): "
                + ", ".join(sorted(declared_paths)[:5])
                + ("\n..." if len(declared_paths) > 5 else "")
            ),
        )

    @staticmethod
    def _find_spec_files(cwd: str) -> list[Path]:
        """Busca .spec.md files no diretorio."""
        results = []
        cwd_path = Path(cwd)
        for p in cwd_path.glob("*.spec.md"):
            results.append(p)
        # Busca tambem em .clow/
        clow_dir = cwd_path / ".clow"
        if clow_dir.is_dir():
            for p in clow_dir.glob("*.spec.md"):
                results.append(p)
        return results

    @staticmethod
    def _parse_scope(spec_file: Path) -> set[str]:
        """Extrai paths declarados na secao scope/files de um .spec.md."""
        paths: set[str] = set()
        try:
            content = spec_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return paths

        in_scope = False
        for line in content.splitlines():
            stripped = line.strip()
            lower = stripped.lower()

            # Detecta inicio de secao scope/files
            if lower.startswith("## scope") or lower.startswith("## files") or lower.startswith("### scope"):
                in_scope = True
                continue

            # Detecta fim da secao (outro heading)
            if in_scope and stripped.startswith("#"):
                in_scope = False
                continue

            # Extrai paths listados
            if in_scope and stripped.startswith("-"):
                path = stripped.lstrip("- ").strip().strip("`").strip()
                if path:
                    paths.add(path)

        return paths

    @staticmethod
    def _extract_filepath(tool_args: Any) -> str:
        if isinstance(tool_args, dict):
            return str(tool_args.get("file_path", tool_args.get("path", tool_args.get("command", ""))))
        if isinstance(tool_args, str):
            try:
                import json
                d = json.loads(tool_args)
                if isinstance(d, dict):
                    return str(d.get("file_path", d.get("path", "")))
            except (json.JSONDecodeError, TypeError):
                pass
        return ""


# ── 7. PlanGate ─────────────────────────────────────────────────

@_register
class PlanGate(BaseBuiltinHook):
    """Avisa quando codigo esta sendo editado sem .spec.md recente (14 dias).

    Non-blocking — apenas aviso.
    """
    name = "plan_gate"
    description = "Warns when editing code without a recent .spec.md"
    event = "pre_tool_call"
    tool_filter = ""

    _CODE_TOOLS = {"write", "edit", "create"}
    _MAX_AGE_DAYS = 14

    def check(self, context: dict[str, Any]) -> BuiltinHookResult:
        tool_name = str(context.get("tool_name", "")).lower()
        if tool_name not in self._CODE_TOOLS:
            return BuiltinHookResult(action="allow")

        # Verifica se e arquivo de codigo
        tool_args = context.get("tool_args", "")
        filepath = ""
        if isinstance(tool_args, dict):
            filepath = str(tool_args.get("file_path", ""))
        if filepath and Path(filepath).suffix.lower() not in _PROD_EXTENSIONS:
            return BuiltinHookResult(action="allow")

        cwd = context.get("cwd", os.getcwd())
        spec = self._find_most_recent_spec(cwd)

        if spec is None:
            return BuiltinHookResult(
                action="warn",
                message=(
                    "No .spec.md found in project. Consider creating a spec before coding.\n"
                    "A spec helps define scope, acceptance criteria, and prevents scope creep."
                ),
            )

        age = datetime.now() - datetime.fromtimestamp(spec["mtime"])
        if age > timedelta(days=self._MAX_AGE_DAYS):
            return BuiltinHookResult(
                action="warn",
                message=(
                    f"Most recent spec '{spec['name']}' is {age.days} days old "
                    f"(threshold: {self._MAX_AGE_DAYS} days).\n"
                    f"Consider updating or creating a new .spec.md."
                ),
            )

        return BuiltinHookResult(action="allow")

    @staticmethod
    def _find_most_recent_spec(cwd: str) -> dict | None:
        """Busca o .spec.md mais recente no workspace."""
        candidates: list[dict] = []
        cwd_path = Path(cwd)

        # Busca em . e .clow/
        search_dirs = [cwd_path, cwd_path / ".clow"]
        for d in search_dirs:
            if not d.is_dir():
                continue
            for p in d.glob("*.spec.md"):
                try:
                    stat = p.stat()
                    candidates.append({
                        "name": p.name,
                        "path": str(p),
                        "mtime": stat.st_mtime,
                    })
                except OSError:
                    continue

        if not candidates:
            return None

        return max(candidates, key=lambda c: c["mtime"])


# ── Public API ──────────────────────────────────────────────────

def get_builtin_hooks() -> dict[str, BaseBuiltinHook]:
    """Retorna registro de todos os hooks built-in."""
    return BUILTIN_HOOKS


def run_builtin_hook(
    name: str,
    event: str,
    context: dict[str, Any],
) -> BuiltinHookResult | None:
    """Executa um hook built-in especifico pelo nome.

    Retorna None se o hook nao existe ou nao roda neste evento.
    """
    hook = BUILTIN_HOOKS.get(name)
    if hook is None:
        return None

    # Verifica se o hook e para este evento
    if hook.event and hook.event != event:
        return None

    # Verifica filtro de tool
    if hook.tool_filter:
        tool_name = str(context.get("tool_name", ""))
        if tool_name != hook.tool_filter:
            return None

    try:
        return hook.check(context)
    except Exception as e:
        logger.error("Builtin hook '%s' failed: %s", name, e, exc_info=True)
        return BuiltinHookResult(
            action="warn",
            message=f"Hook '{name}' failed: {e}",
        )


def run_all_builtin_hooks(
    event: str,
    context: dict[str, Any],
) -> list[BuiltinHookResult]:
    """Executa todos os hooks built-in relevantes para um evento.

    Retorna lista de resultados. Se algum retorna deny, interrompe a cadeia.
    """
    results: list[BuiltinHookResult] = []

    for name, hook in BUILTIN_HOOKS.items():
        # Verifica evento
        if hook.event and hook.event != event:
            continue

        # Verifica filtro de tool
        if hook.tool_filter:
            tool_name = str(context.get("tool_name", ""))
            if tool_name != hook.tool_filter:
                continue

        try:
            result = hook.check(context)
        except Exception as e:
            logger.error("Builtin hook '%s' failed: %s", name, e, exc_info=True)
            result = BuiltinHookResult(action="warn", message=f"Hook '{name}' error: {e}")

        results.append(result)

        # Deny interrompe a cadeia
        if result.action == "deny":
            break

    return results
