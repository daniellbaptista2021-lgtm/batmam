"""Plugin System — Full Lifecycle Management (Claude Code Architecture Ep.04).

Discovers, validates, loads, and registers plugins from multiple sources.
Plugins provide: agents, commands, hooks, skills, MCP servers, output styles.

Sources (priority order):
1. Built-in plugins (bundled with Clow)
2. Project plugins (.claude/ in project directory)
3. User plugins (~/.clow/plugins/)
"""

from __future__ import annotations

import json
import os
import time
import logging
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from . import config

logger = logging.getLogger("clow.plugins")

PLUGINS_DIR = config.CLOW_HOME / "plugins"
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

MANIFEST_FILE = ".claude-plugin/plugin.json"
SKILL_FILE = "SKILL.md"


# ══════════════════════════════════════════════════════════════
#  Data classes
# ══════════════════════════════════════════════════════════════

@dataclass
class PluginManifest:
    """Plugin manifest from .claude-plugin/plugin.json."""

    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    commands: list[str] = field(default_factory=list)       # glob: ["commands/*.md"]
    agents: list[str] = field(default_factory=list)          # glob: ["agents/*.md"]
    hooks: dict = field(default_factory=dict)                 # hooks config
    skills: list[str] = field(default_factory=list)           # glob: ["skills/*/SKILL.md"]
    mcp_servers: dict = field(default_factory=dict)            # MCP server declarations
    output_style: str = ""                                     # style markdown
    # Legacy fields (backward compat with old plugin.json)
    entry_point: str = ""
    permissions: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    min_clow_version: str = ""
    source: str = ""
    path: str = ""

    @classmethod
    def from_dict(cls, data: dict, path: str = "") -> PluginManifest:
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            author=data.get("author", ""),
            commands=data.get("commands", []),
            agents=data.get("agents", []),
            hooks=data.get("hooks", {}),
            skills=data.get("skills", []),
            mcp_servers=data.get("mcpServers", data.get("mcp_servers", {})),
            output_style=data.get("outputStyle", data.get("output_style", "")),
            # Legacy
            entry_point=data.get("entry_point", ""),
            permissions=data.get("permissions", []),
            tools=data.get("tools", []),
            min_clow_version=data.get("min_clow_version", ""),
            source=data.get("source", "local"),
            path=path,
        )

    @classmethod
    def from_file(cls, manifest_path: Path) -> PluginManifest:
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data, path=str(manifest_path.parent))

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "commands": self.commands,
            "agents": self.agents,
            "hooks": self.hooks,
            "skills": self.skills,
            "mcpServers": self.mcp_servers,
            "outputStyle": self.output_style,
        }

    def validate(self) -> list[str]:
        """Validate the manifest. Returns list of errors (empty = valid)."""
        errors: list[str] = []
        if not self.name or not self.name.strip():
            errors.append("Missing plugin name")
        return errors


@dataclass
class Plugin:
    """A loaded plugin with its components."""

    manifest: PluginManifest
    source: str = ""          # "built-in", "project", "user"
    path: str = ""            # Filesystem path
    loaded: bool = False
    error: str = ""
    load_time_ms: float = 0

    # Loaded components
    loaded_agents: list[dict] = field(default_factory=list)
    loaded_commands: list[dict] = field(default_factory=list)
    loaded_hooks: list[dict] = field(default_factory=list)
    loaded_skills: list[dict] = field(default_factory=list)
    loaded_mcp_servers: list[dict] = field(default_factory=list)
    loaded_styles: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.manifest.name,
            "version": self.manifest.version,
            "description": self.manifest.description,
            "source": self.source,
            "path": self.path,
            "loaded": self.loaded,
            "error": self.error,
            "load_time_ms": round(self.load_time_ms, 2),
            "components": {
                "agents": len(self.loaded_agents),
                "commands": len(self.loaded_commands),
                "hooks": len(self.loaded_hooks),
                "skills": len(self.loaded_skills),
                "mcp_servers": len(self.loaded_mcp_servers),
                "styles": len(self.loaded_styles),
            },
        }


# ══════════════════════════════════════════════════════════════
#  Plugin Manager
# ══════════════════════════════════════════════════════════════

class PluginManager:
    """Manages the full plugin lifecycle.

    Discover → Validate → Load → Register.
    Error isolation: one plugin failure never crashes others.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._loaded: dict[str, Any] = {}       # Legacy: nome -> modulo
        self._manifests: dict[str, PluginManifest] = {}  # Legacy compat
        self._errors: list[tuple[str, str]] = []
        self._discovery_done = False

    # ── Discovery ─────────────────────────────────────────────

    def discover(self, cwd: str = "") -> list[Plugin]:
        """Discover plugins from all 3 sources (priority order).

        1. Built-in plugins (bundled with Clow — skills/imported/)
        2. Project plugins (.claude/ in project directory)
        3. User plugins (~/.clow/plugins/)
        """
        discovered: list[Plugin] = []

        # ── 1. Built-in plugins ──────────────────────────────
        builtin_dir = Path(__file__).parent / "skills" / "imported"
        if builtin_dir.exists():
            for d in sorted(builtin_dir.iterdir()):
                if not d.is_dir():
                    continue
                # Check for full manifest (.claude-plugin/plugin.json)
                manifest_path = d / ".claude-plugin" / "plugin.json"
                if manifest_path.exists():
                    plugin = self._load_manifest(manifest_path, "built-in")
                    if plugin:
                        discovered.append(plugin)
                    continue
                # Fallback: SKILL.md means it's a skill-plugin
                skill_path = d / SKILL_FILE
                if skill_path.exists():
                    plugin = Plugin(
                        manifest=PluginManifest(
                            name=d.name,
                            description=f"Built-in skill: {d.name}",
                        ),
                        source="built-in",
                        path=str(d),
                    )
                    plugin.loaded_skills.append({
                        "name": d.name,
                        "path": str(skill_path),
                    })
                    plugin.loaded = True
                    discovered.append(plugin)

        # ── 2. Project plugins (.claude/ in cwd) ─────────────
        if cwd:
            project_plugin_dir = Path(cwd) / ".claude"
            if project_plugin_dir.exists():
                # Full manifest
                manifest_path = project_plugin_dir / "plugin.json"
                if manifest_path.exists():
                    plugin = self._load_manifest(manifest_path, "project")
                    if plugin:
                        discovered.append(plugin)

                # Project skills (.claude/skills/<name>/SKILL.md)
                skills_dir = project_plugin_dir / "skills"
                if skills_dir.exists():
                    for skill_dir in sorted(skills_dir.iterdir()):
                        if skill_dir.is_dir() and (skill_dir / SKILL_FILE).exists():
                            plugin = Plugin(
                                manifest=PluginManifest(
                                    name=skill_dir.name,
                                    description=f"Project skill: {skill_dir.name}",
                                ),
                                source="project",
                                path=str(skill_dir),
                            )
                            plugin.loaded_skills.append({
                                "name": skill_dir.name,
                                "path": str(skill_dir / SKILL_FILE),
                            })
                            plugin.loaded = True
                            discovered.append(plugin)

                # Project commands (.claude/commands/*.md)
                commands_dir = project_plugin_dir / "commands"
                if commands_dir.exists():
                    for cmd_file in sorted(commands_dir.glob("*.md")):
                        try:
                            content = cmd_file.read_text(encoding="utf-8", errors="replace")
                        except OSError:
                            continue
                        cmd_name = cmd_file.stem
                        plugin = Plugin(
                            manifest=PluginManifest(
                                name=f"cmd-{cmd_name}",
                                description=f"Command: /{cmd_name}",
                            ),
                            source="project",
                            path=str(cmd_file),
                        )
                        plugin.loaded_commands.append({
                            "name": cmd_name,
                            "path": str(cmd_file),
                            "content": content[:5000],
                        })
                        plugin.loaded = True
                        discovered.append(plugin)

        # ── 3. User plugins (~/.clow/plugins/) ───────────────
        if PLUGINS_DIR.exists():
            for d in sorted(PLUGINS_DIR.iterdir()):
                if d.is_dir():
                    # New-style manifest
                    manifest_path = d / ".claude-plugin" / "plugin.json"
                    if manifest_path.exists():
                        plugin = self._load_manifest(manifest_path, "user")
                        if plugin:
                            discovered.append(plugin)
                        continue

                    # Legacy manifest (plugin.json in root)
                    legacy_manifest = d / "plugin.json"
                    if legacy_manifest.exists():
                        plugin = self._load_manifest(legacy_manifest, "user")
                        if plugin:
                            discovered.append(plugin)
                        continue

                    # Legacy: bare __init__.py or main.py
                    for entry in ("__init__.py", "main.py"):
                        if (d / entry).exists():
                            plugin = Plugin(
                                manifest=PluginManifest(
                                    name=d.name,
                                    description=f"Legacy plugin: {d.name}",
                                    entry_point=entry,
                                ),
                                source="user",
                                path=str(d),
                            )
                            discovered.append(plugin)
                            break

            # Legacy: loose .py files
            for py_file in sorted(PLUGINS_DIR.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                plugin = Plugin(
                    manifest=PluginManifest(
                        name=py_file.stem,
                        description=f"Legacy plugin: {py_file.stem}",
                        entry_point=py_file.name,
                    ),
                    source="user",
                    path=str(py_file.parent),
                )
                discovered.append(plugin)

        self._discovery_done = True
        logger.info(f"Discovered {len(discovered)} plugins")
        return discovered

    # ── Loading ───────────────────────────────────────────────

    def load_all(
        self,
        registry: Any = None,
        hook_runner: Any = None,
        cwd: str = "",
    ) -> int:
        """Discover and load all plugins. Returns count of successfully loaded."""
        plugins = self.discover(cwd)
        loaded_count = 0

        for plugin in plugins:
            try:
                start = time.time()
                self._load_plugin(plugin, registry, hook_runner)
                plugin.loaded = True
                plugin.load_time_ms = (time.time() - start) * 1000
                loaded_count += 1
            except Exception as e:
                plugin.error = str(e)[:200]
                self._errors.append((plugin.manifest.name, plugin.error))
                logger.error(f"Plugin load failed: {plugin.manifest.name} — {e}")

            self._plugins[plugin.manifest.name] = plugin

        logger.info(f"Loaded {loaded_count}/{len(plugins)} plugins")
        return loaded_count

    def _load_manifest(self, path: Path, source: str) -> Plugin | None:
        """Load and validate a plugin manifest file."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            manifest = PluginManifest.from_dict(data, path=str(path.parent))

            if not manifest.name:
                # Infer name from directory
                manifest.name = path.parent.parent.name if path.parent.name == ".claude-plugin" else path.parent.name

            # Validate
            errors = self._validate(manifest, path.parent.parent if path.parent.name == ".claude-plugin" else path.parent)
            if errors:
                logger.warning(f"Plugin validation warnings for {manifest.name}: {errors}")

            plugin_dir = path.parent.parent if path.parent.name == ".claude-plugin" else path.parent
            return Plugin(
                manifest=manifest,
                source=source,
                path=str(plugin_dir),
            )
        except Exception as e:
            logger.error(f"Manifest load error {path}: {e}")
            return None

    def _validate(self, manifest: PluginManifest, plugin_dir: Path) -> list[str]:
        """Validate plugin manifest and referenced files."""
        errors: list[str] = []

        if not manifest.name:
            errors.append("Missing plugin name")

        # Check referenced command globs
        for cmd_glob in manifest.commands:
            if not list(plugin_dir.glob(cmd_glob)):
                errors.append(f"Command glob matched no files: {cmd_glob}")

        # Check referenced agent globs
        for agent_glob in manifest.agents:
            if not list(plugin_dir.glob(agent_glob)):
                errors.append(f"Agent glob matched no files: {agent_glob}")

        # Check referenced skill globs
        for skill_glob in manifest.skills:
            if not list(plugin_dir.glob(skill_glob)):
                errors.append(f"Skill glob matched no files: {skill_glob}")

        return errors

    def _load_plugin(
        self,
        plugin: Plugin,
        registry: Any = None,
        hook_runner: Any = None,
    ) -> None:
        """Load a plugin's 6 component types (isolated error handling per type)."""
        plugin_dir = Path(plugin.path)

        # ── 1. Load agents ───────────────────────────────────
        for agent_glob in plugin.manifest.agents:
            for agent_file in plugin_dir.glob(agent_glob):
                try:
                    content = agent_file.read_text(encoding="utf-8", errors="replace")
                    agent_def = {
                        "name": agent_file.stem,
                        "path": str(agent_file),
                        "content": content[:10000],
                        "source": plugin.source,
                    }
                    plugin.loaded_agents.append(agent_def)
                except Exception as e:
                    logger.error(f"[{plugin.manifest.name}] Agent load error {agent_file}: {e}")

        # ── 2. Load commands ─────────────────────────────────
        for cmd_glob in plugin.manifest.commands:
            for cmd_file in plugin_dir.glob(cmd_glob):
                try:
                    content = cmd_file.read_text(encoding="utf-8", errors="replace")
                    frontmatter, body = self._parse_frontmatter(content)
                    cmd_def = {
                        "name": cmd_file.stem,
                        "path": str(cmd_file),
                        "description": frontmatter.get("description", ""),
                        "allowed_tools": frontmatter.get("allowed_tools", []),
                        "model": frontmatter.get("model", ""),
                        "content": body[:5000],
                        "source": plugin.source,
                    }
                    plugin.loaded_commands.append(cmd_def)
                except Exception as e:
                    logger.error(f"[{plugin.manifest.name}] Command load error {cmd_file}: {e}")

        # ── 3. Load hooks ────────────────────────────────────
        if plugin.manifest.hooks and hook_runner:
            for event_name, hook_list in plugin.manifest.hooks.items():
                if not isinstance(hook_list, list):
                    hook_list = [hook_list]
                for hook_def in hook_list:
                    try:
                        if isinstance(hook_def, str):
                            # Simple string: shell command
                            from .hooks import Hook
                            hook = Hook(event=event_name, command=hook_def)
                            hook_runner.add_hook(hook)
                        elif isinstance(hook_def, dict):
                            from .hooks import Hook
                            cmd = hook_def.get("command", "")
                            if cmd:
                                hook = Hook(
                                    event=event_name,
                                    command=cmd,
                                    tool=hook_def.get("tool", ""),
                                    timeout=hook_def.get("timeout", 30),
                                )
                                hook_runner.add_hook(hook)
                        plugin.loaded_hooks.append({
                            "event": event_name,
                            "source": plugin.source,
                        })
                    except Exception as e:
                        logger.error(f"[{plugin.manifest.name}] Hook load error: {e}")

        # ── 4. Load skills ───────────────────────────────────
        for skill_glob in plugin.manifest.skills:
            for skill_file in plugin_dir.glob(skill_glob):
                try:
                    content = skill_file.read_text(encoding="utf-8", errors="replace")
                    skill_def = {
                        "name": skill_file.parent.name,
                        "path": str(skill_file),
                        "content": content[:5000],
                        "source": plugin.source,
                    }
                    plugin.loaded_skills.append(skill_def)
                except Exception as e:
                    logger.error(f"[{plugin.manifest.name}] Skill load error {skill_file}: {e}")

        # ── 5. Load MCP servers (config only — startup is lazy) ──
        for server_name, server_config in plugin.manifest.mcp_servers.items():
            try:
                plugin.loaded_mcp_servers.append({
                    "name": server_name,
                    "config": server_config,
                    "source": plugin.source,
                })
            except Exception as e:
                logger.error(f"[{plugin.manifest.name}] MCP server config error: {e}")

        # ── 6. Load output style ─────────────────────────────
        if plugin.manifest.output_style:
            style_path = plugin_dir / plugin.manifest.output_style
            try:
                if style_path.exists():
                    content = style_path.read_text(encoding="utf-8", errors="replace")
                    plugin.loaded_styles.append({
                        "name": plugin.manifest.name,
                        "path": str(style_path),
                        "content": content[:5000],
                        "source": plugin.source,
                    })
                else:
                    # Inline style string
                    plugin.loaded_styles.append({
                        "name": plugin.manifest.name,
                        "content": plugin.manifest.output_style[:2000],
                        "source": plugin.source,
                    })
            except Exception as e:
                logger.error(f"[{plugin.manifest.name}] Style load error: {e}")

        # ── Legacy: Python entry_point with register() ───────
        if plugin.manifest.entry_point:
            self._load_legacy_entry_point(plugin, registry, hook_runner)

    def _load_legacy_entry_point(
        self,
        plugin: Plugin,
        registry: Any = None,
        hook_runner: Any = None,
    ) -> None:
        """Load a legacy Python plugin (entry_point with register() function)."""
        import importlib.util
        import sys

        name = plugin.manifest.name
        if name in self._loaded:
            return

        plugin_dir = Path(plugin.path)
        entry_file = plugin_dir / plugin.manifest.entry_point

        # Loose .py file: path IS the file
        if plugin_dir.suffix == ".py" or (not entry_file.exists() and plugin_dir.is_file()):
            entry_file = plugin_dir

        if not entry_file.exists():
            logger.warning(f"[{name}] Entry point not found: {plugin.manifest.entry_point}")
            return

        try:
            spec = importlib.util.spec_from_file_location(f"clow_plugin_{name}", entry_file)
            if spec is None or spec.loader is None:
                self._errors.append((name, "Could not create module spec"))
                return

            module = importlib.util.module_from_spec(spec)
            sys.modules[f"clow_plugin_{name}"] = module
            spec.loader.exec_module(module)

            if hasattr(module, "register") and registry is not None:
                module.register(registry, hook_runner)

            self._loaded[name] = module
            self._manifests[name] = plugin.manifest
        except Exception as e:
            self._errors.append((name, str(e)[:200]))
            logger.error(f"[{name}] Legacy plugin load error: {e}")

    # ── Frontmatter parser ────────────────────────────────────

    @staticmethod
    def _parse_frontmatter(content: str) -> tuple[dict, str]:
        """Parse YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return {}, content

        end = content.find("---", 3)
        if end < 0:
            return {}, content

        frontmatter_str = content[3:end].strip()
        body = content[end + 3:].strip()

        # Simple YAML-like key: value parsing
        frontmatter: dict = {}
        for line in frontmatter_str.split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if val.startswith("["):
                    try:
                        val = json.loads(val)
                    except (json.JSONDecodeError, ValueError):
                        pass
                frontmatter[key] = val

        return frontmatter, body

    # ══════════════════════════════════════════════════════════
    #  Public API
    # ══════════════════════════════════════════════════════════

    def get_plugin(self, name: str) -> Plugin | None:
        """Get a loaded plugin by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[dict]:
        """List all plugins (loaded + errored). Backward compatible."""
        plugins = []
        for p in self._plugins.values():
            plugins.append(p.to_dict())

        # Also include legacy errors not already in _plugins
        seen = {p.manifest.name for p in self._plugins.values()}
        for name, error in self._errors:
            if name not in seen:
                plugins.append({
                    "name": name,
                    "status": "error",
                    "description": error,
                })
        return plugins

    def get_all_agents(self) -> list[dict]:
        """Get all agents from all loaded plugins."""
        agents = []
        for p in self._plugins.values():
            if p.loaded:
                agents.extend(p.loaded_agents)
        return agents

    def get_all_commands(self) -> list[dict]:
        """Get all commands from all loaded plugins."""
        commands = []
        for p in self._plugins.values():
            if p.loaded:
                commands.extend(p.loaded_commands)
        return commands

    def get_all_skills(self) -> list[dict]:
        """Get all skills from all loaded plugins."""
        skills = []
        for p in self._plugins.values():
            if p.loaded:
                skills.extend(p.loaded_skills)
        return skills

    def get_all_hooks(self) -> list[dict]:
        """Get all hooks from all loaded plugins."""
        hooks = []
        for p in self._plugins.values():
            if p.loaded:
                hooks.extend(p.loaded_hooks)
        return hooks

    def get_all_mcp_servers(self) -> list[dict]:
        """Get all MCP server configs from all loaded plugins."""
        servers = []
        for p in self._plugins.values():
            if p.loaded:
                servers.extend(p.loaded_mcp_servers)
        return servers

    def get_all_styles(self) -> list[dict]:
        """Get all output styles from all loaded plugins."""
        styles = []
        for p in self._plugins.values():
            if p.loaded:
                styles.extend(p.loaded_styles)
        return styles

    def get_stats(self) -> dict:
        """Get aggregate statistics about loaded plugins."""
        total_agents = sum(len(p.loaded_agents) for p in self._plugins.values())
        total_commands = sum(len(p.loaded_commands) for p in self._plugins.values())
        total_hooks = sum(len(p.loaded_hooks) for p in self._plugins.values())
        total_skills = sum(len(p.loaded_skills) for p in self._plugins.values())
        total_mcp = sum(len(p.loaded_mcp_servers) for p in self._plugins.values())
        total_styles = sum(len(p.loaded_styles) for p in self._plugins.values())

        return {
            "total_plugins": len(self._plugins),
            "loaded": sum(1 for p in self._plugins.values() if p.loaded),
            "failed": sum(1 for p in self._plugins.values() if p.error),
            "components": {
                "agents": total_agents,
                "commands": total_commands,
                "hooks": total_hooks,
                "skills": total_skills,
                "mcp_servers": total_mcp,
                "styles": total_styles,
            },
            "sources": {
                "built-in": sum(1 for p in self._plugins.values() if p.source == "built-in"),
                "project": sum(1 for p in self._plugins.values() if p.source == "project"),
                "user": sum(1 for p in self._plugins.values() if p.source == "user"),
            },
        }

    # Legacy compat properties
    @property
    def loaded_count(self) -> int:
        return sum(1 for p in self._plugins.values() if p.loaded)

    @property
    def error_count(self) -> int:
        return sum(1 for p in self._plugins.values() if p.error) + len(self._errors)

    # ══════════════════════════════════════════════════════════
    #  Install / Uninstall / Update
    # ══════════════════════════════════════════════════════════

    def install_from_git(self, git_url: str) -> tuple[bool, str]:
        """Install a plugin from a Git repository.

        Clones to ~/.clow/plugins/<name>/ and validates.
        Returns (success, message).
        """
        repo_name = git_url.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        target_dir = PLUGINS_DIR / repo_name
        if target_dir.exists():
            return False, f"Plugin '{repo_name}' already installed at {target_dir}"

        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", git_url, str(target_dir)],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                return False, f"Clone error: {result.stderr}"

            # Validate: needs at least one recognized entry
            has_manifest = (target_dir / ".claude-plugin" / "plugin.json").exists()
            has_legacy = (target_dir / "plugin.json").exists()
            has_entry = (target_dir / "__init__.py").exists() or (target_dir / "main.py").exists()
            has_skill = (target_dir / SKILL_FILE).exists()

            if not (has_manifest or has_legacy or has_entry or has_skill):
                shutil.rmtree(target_dir, ignore_errors=True)
                return False, "Repository does not contain a valid plugin (no manifest, entry point, or SKILL.md)"

            self._save_to_registry(repo_name, git_url, str(target_dir))
            return True, f"Plugin '{repo_name}' installed successfully"

        except subprocess.TimeoutExpired:
            shutil.rmtree(target_dir, ignore_errors=True)
            return False, "Timeout cloning repository"
        except FileNotFoundError:
            return False, "Git not found. Install git first."
        except Exception as e:
            shutil.rmtree(target_dir, ignore_errors=True)
            return False, f"Error: {e}"

    def uninstall(self, name: str) -> tuple[bool, str]:
        """Remove an installed plugin."""
        target_dir = PLUGINS_DIR / name
        target_file = PLUGINS_DIR / f"{name}.py"

        if target_dir.exists() and target_dir.is_dir():
            shutil.rmtree(target_dir, ignore_errors=True)
            self._plugins.pop(name, None)
            self._loaded.pop(name, None)
            self._manifests.pop(name, None)
            self._remove_from_registry(name)
            return True, f"Plugin '{name}' removed"

        if target_file.exists():
            target_file.unlink()
            self._plugins.pop(name, None)
            self._loaded.pop(name, None)
            self._remove_from_registry(name)
            return True, f"Plugin '{name}' removed"

        return False, f"Plugin '{name}' not found"

    def update(self, name: str) -> tuple[bool, str]:
        """Update a Git-installed plugin (git pull)."""
        target_dir = PLUGINS_DIR / name
        if not target_dir.exists() or not (target_dir / ".git").exists():
            return False, f"Plugin '{name}' was not installed via git"

        try:
            result = subprocess.run(
                ["git", "pull"],
                capture_output=True, text=True,
                cwd=str(target_dir), timeout=30,
            )
            if result.returncode == 0:
                return True, f"Plugin '{name}' updated: {result.stdout.strip()}"
            return False, f"Update error: {result.stderr}"
        except Exception as e:
            return False, f"Error: {e}"

    # ── Persistent registry ───────────────────────────────────

    _REGISTRY_FILE = config.CLOW_HOME / "plugin_registry.json"

    def _save_to_registry(self, name: str, source_url: str, path: str) -> None:
        """Save install info to persistent registry."""
        registry = self._load_registry()
        registry[name] = {
            "source_url": source_url,
            "path": path,
            "installed_at": time.time(),
        }
        with open(self._REGISTRY_FILE, "w") as f:
            json.dump(registry, f, indent=2)

    def _remove_from_registry(self, name: str) -> None:
        """Remove from persistent registry."""
        registry = self._load_registry()
        registry.pop(name, None)
        with open(self._REGISTRY_FILE, "w") as f:
            json.dump(registry, f, indent=2)

    def _load_registry(self) -> dict:
        """Load persistent plugin registry."""
        if self._REGISTRY_FILE.exists():
            try:
                with open(self._REGISTRY_FILE) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}


# ══════════════════════════════════════════════════════════════
#  Module-level convenience functions
# ══════════════════════════════════════════════════════════════

def install_plugin(source: str, name: str = "") -> dict:
    """Install a plugin from a source (git URL, local path, or marketplace ID)."""
    if source.startswith("http") or source.startswith("git@"):
        return _install_from_git(source)
    elif os.path.isdir(source):
        return _install_from_local(source, name)
    else:
        return {"error": f"Unknown plugin source: {source}"}


def _install_from_git(url: str) -> dict:
    dest = PLUGINS_DIR / url.rstrip("/").split("/")[-1].replace(".git", "")
    try:
        subprocess.run(
            ["git", "clone", url, str(dest)],
            check=True, capture_output=True, timeout=60,
        )
        return {"installed": True, "path": str(dest)}
    except Exception as e:
        return {"error": str(e)}


def _install_from_local(path: str, name: str = "") -> dict:
    src = Path(path)
    dest = PLUGINS_DIR / (name or src.name)
    try:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        return {"installed": True, "path": str(dest)}
    except Exception as e:
        return {"error": str(e)}


def uninstall_plugin(name: str) -> dict:
    path = PLUGINS_DIR / name
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
        return {"uninstalled": True}
    return {"error": "Plugin not found"}
