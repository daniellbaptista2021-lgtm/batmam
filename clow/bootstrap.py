"""Bootstrap State & Startup -- Claude Code Architecture (Episode 12).

Fast startup with:
- Fast-path cascade (skip heavy loading for simple commands)
- API preconnection (warm TCP+TLS before first call)
- Bootstrap state singleton (session-wide mutable state, DAG leaf)
- Startup profiler (checkpoint tracking)
- Background prefetch (commands, plugins, hooks)
"""

import os
import time
import threading
import logging
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any
from . import config

logger = logging.getLogger("clow.bootstrap")

# == Startup Profiler ==

_checkpoints: list[tuple[str, float]] = []
_start_time = time.time()

def profile_checkpoint(name: str) -> None:
    """Record a startup checkpoint with timestamp."""
    _checkpoints.append((name, time.time()))

def get_startup_report() -> dict:
    """Get startup performance report."""
    if not _checkpoints:
        return {}

    phases = {}
    for i, (name, ts) in enumerate(_checkpoints):
        elapsed = (ts - _start_time) * 1000  # ms
        phases[name] = round(elapsed, 1)

    total = phases.get(list(phases.keys())[-1], 0) if phases else 0

    return {
        "checkpoints": phases,
        "total_ms": total,
        "checkpoint_count": len(_checkpoints),
    }

profile_checkpoint("bootstrap_module_loaded")


# == Bootstrap State Singleton ==
# DAG leaf -- imports almost nothing. Every module can import this.
# DO NOT ADD HEAVY IMPORTS HERE.

@dataclass
class BootstrapState:
    """Global session state -- the ONLY place session-wide mutable state lives.

    Design: Claude Code's bootstrap/state.ts pattern.
    - 80+ fields organized by lifetime (session/turn/sticky)
    - DAG leaf: imports nothing heavy
    - Sticky latches: once set, never unset (cache preservation)
    """

    # -- Identity --
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    original_cwd: str = field(default_factory=os.getcwd)
    cwd: str = field(default_factory=os.getcwd)
    project_root: str = ""

    # -- Cost Tracking (session lifetime) --
    total_cost_usd: float = 0.0
    total_api_duration_ms: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_hit_tokens: int = 0
    total_cache_miss_tokens: int = 0

    # -- Turn Metrics (reset each turn) --
    turn_tool_count: int = 0
    turn_tool_duration_ms: float = 0.0
    turn_hook_count: int = 0
    turn_iteration_count: int = 0
    turn_start_time: float = 0.0

    # -- API State (rolling) --
    last_api_request_time: float = 0.0
    last_api_model: str = ""
    last_api_completion_time: float = 0.0
    api_call_count: int = 0
    api_error_count: int = 0

    # -- Cache Latches (sticky-on: once True, never False) --
    # Prevents prompt cache busting from feature toggles mid-session
    cache_control_latched: bool = False
    model_latched: str = ""  # Once set, don't change (cache stability)

    # -- Feature State (session) --
    invoked_skills: list = field(default_factory=list)
    active_plan: str = ""
    plan_mode: bool = False

    # -- Startup State --
    startup_complete: bool = False
    startup_time_ms: float = 0.0
    preconnect_done: bool = False
    settings_loaded: bool = False

    def reset_turn_metrics(self) -> None:
        """Reset per-turn metrics (called at start of each turn)."""
        self.turn_tool_count = 0
        self.turn_tool_duration_ms = 0.0
        self.turn_hook_count = 0
        self.turn_iteration_count = 0
        self.turn_start_time = time.time()

    def add_api_cost(self, input_tokens: int, output_tokens: int,
                      cache_hit: int = 0, cache_miss: int = 0, duration_ms: float = 0) -> None:
        """Track API cost for this session."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cache_hit_tokens += cache_hit
        self.total_cache_miss_tokens += cache_miss
        self.total_api_duration_ms += duration_ms
        self.api_call_count += 1
        self.last_api_request_time = time.time()

        # Calculate cost (DeepSeek pricing)
        input_cost = (cache_hit * 0.028 + cache_miss * 0.28) / 1_000_000
        output_cost = output_tokens * 1.10 / 1_000_000
        self.total_cost_usd += input_cost + output_cost

    def to_dict(self) -> dict:
        """Serialize state for inspection."""
        return {
            "session_id": self.session_id,
            "cwd": self.cwd,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "cache_hit_rate": round(self.total_cache_hit_tokens / max(1, self.total_input_tokens) * 100, 1),
            "api_calls": self.api_call_count,
            "startup_time_ms": self.startup_time_ms,
        }


# Global singleton -- one per process
_state: BootstrapState | None = None

def get_state() -> BootstrapState:
    """Get the global bootstrap state (creates on first access)."""
    global _state
    if _state is None:
        _state = BootstrapState()
    return _state

def reset_state() -> None:
    """Reset global state (for testing or new session)."""
    global _state
    _state = BootstrapState()


# == API Preconnection ==

def preconnect_api() -> None:
    """Fire-and-forget TCP+TLS handshake to DeepSeek API.

    Overlaps with startup work so the connection pool is warm
    by the time the first real API call happens.
    Saves ~100-200ms on first call.
    """
    def _preconnect():
        try:
            from urllib.request import urlopen, Request
            base_url = config.DEEPSEEK_BASE_URL.rstrip("/")
            if not base_url.endswith("/v1"):
                base_url += "/v1"
            req = Request(base_url + "/models", method="HEAD")
            req.add_header("Authorization", f"Bearer {config.DEEPSEEK_API_KEY}")
            urlopen(req, timeout=10)
            get_state().preconnect_done = True
            logger.debug("API preconnect successful")
        except Exception:
            pass  # Fire and forget

    t = threading.Thread(target=_preconnect, daemon=True, name="api-preconnect")
    t.start()


# == Initialization Pipeline ==

_initialized = False

def init() -> None:
    """Phase 2: Trust-independent initialization (runs once).

    Claude Code init.ts equivalent:
    1. Load configs
    2. Setup graceful shutdown
    3. Preconnect API
    4. Detect environment
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    profile_checkpoint("init_start")

    state = get_state()

    # 1. Validate config
    if not config.DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY not configured")

    profile_checkpoint("init_configs_loaded")

    # 2. Graceful shutdown handler
    import signal
    def _shutdown(sig, frame):
        logger.info(f"Received signal {sig}, shutting down")
        state.startup_complete = False

    try:
        signal.signal(signal.SIGTERM, _shutdown)
    except (OSError, ValueError):
        pass  # Windows or non-main thread

    # 3. Preconnect API (fire and forget)
    if config.DEEPSEEK_API_KEY:
        preconnect_api()

    profile_checkpoint("init_preconnect_fired")

    # 4. Detect environment
    state.cwd = os.getcwd()
    state.project_root = _detect_project_root()

    profile_checkpoint("init_environment_detected")

    # 5. Load settings
    try:
        config.load_settings()
        state.settings_loaded = True
    except Exception:
        pass

    profile_checkpoint("init_settings_loaded")

    _initialized = True
    state.startup_complete = True
    state.startup_time_ms = (time.time() - _start_time) * 1000

    profile_checkpoint("init_complete")

    logger.info(f"Bootstrap complete in {state.startup_time_ms:.0f}ms")


def _detect_project_root() -> str:
    """Detect project root by walking up looking for .git or .clow."""
    current = Path(os.getcwd())
    for parent in [current] + list(current.parents):
        if (parent / ".git").exists() or (parent / ".clow").exists():
            return str(parent)
    return str(current)


# == Setup Pipeline ==

def setup() -> None:
    """Phase 3: Post-trust environment setup.

    Claude Code setup.ts equivalent:
    - Background prefetch (commands, hooks)
    - Session memory init
    - Hook snapshot
    """
    profile_checkpoint("setup_start")

    state = get_state()

    # 1. Initialize session memory
    try:
        from .memory import load_memory_context
        load_memory_context()  # Prefetch into cache
    except Exception:
        pass

    profile_checkpoint("setup_memory_loaded")

    # 2. Load project context
    try:
        from .context import load_project_context
        load_project_context(state.cwd)
    except Exception:
        pass

    profile_checkpoint("setup_context_loaded")

    # 3. Background: recover bridge sessions
    try:
        from .bridge import recover_sessions
        recovered = recover_sessions()
        if recovered:
            logger.info(f"Recovered {recovered} bridge sessions")
    except Exception:
        pass

    profile_checkpoint("setup_complete")


# == Fast-Path Detection ==

def is_fast_path(args: list[str]) -> str | None:
    """Detect fast-path commands that skip full startup.

    Returns the fast-path name or None for full startup.
    Claude Code's cli.tsx cascade equivalent.
    """
    if not args:
        return None

    first = args[0].lower().strip()

    # Zero-import fast paths
    if first in ("--version", "-v"):
        return "version"

    # Minimal import fast paths
    if first in ("--help", "-h", "help"):
        return "help"

    if first in ("remote-control", "rc", "remote", "bridge"):
        return "bridge"

    if first in ("--setup", "setup"):
        return "setup"

    # Full startup (default)
    return None


# == Auto-init on import ==
# Like Claude Code: init runs automatically but is memoized
init()
