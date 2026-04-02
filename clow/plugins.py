"""Sistema de Plugins do Clow.

Suporta 3 formas de instalacao:
  1. Plugins locais: ~/.clow/plugins/*.py
  2. Plugins com manifesto: ~/.clow/plugins/<dir>/plugin.json
  3. Instalacao via Git: clow plugin install <git-url>

Cada plugin pode declarar um manifesto (plugin.json):

{
  "name": "meu-plugin",
  "version": "1.0.0",
  "description": "Descricao do plugin",
  "author": "Autor",
  "entry_point": "main.py",
  "permissions": ["bash", "write"],
  "hooks": {
    "pre_tool_call": "hooks/validate.sh",
    "post_tool_call": "hooks/log.sh"
  },
  "tools": ["MeuTool"],
  "min_clow_version": "0.2.0"
}

Plugins sem manifesto usam o formato legado (modulo .py com register()).
"""

from __future__ import annotations
import importlib.util
import json
import subprocess
import shutil
import sys
from pathlib import Path
from typing import Any

from .tools.base import ToolRegistry
from . import config

PLUGINS_DIR = config.CLOW_HOME / "plugins"
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

REGISTRY_FILE = config.CLOW_HOME / "plugin_registry.json"


class PluginManifest:
    """Manifesto de um plugin (plugin.json)."""

    def __init__(
        self,
        name: str,
        version: str = "0.0.0",
        description: str = "",
        author: str = "",
        entry_point: str = "main.py",
        permissions: list[str] | None = None,
        hooks: dict[str, str] | None = None,
        tools: list[str] | None = None,
        min_clow_version: str = "",
        source: str = "local",
        path: str = "",
    ):
        self.name = name
        self.version = version
        self.description = description
        self.author = author
        self.entry_point = entry_point
        self.permissions = permissions or []
        self.hooks = hooks or {}
        self.tools = tools or []
        self.min_clow_version = min_clow_version
        self.source = source  # "local", "git"
        self.path = path

    @classmethod
    def from_dict(cls, data: dict, path: str = "") -> PluginManifest:
        return cls(
            name=data.get("name", "unknown"),
            version=data.get("version", "0.0.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            entry_point=data.get("entry_point", "main.py"),
            permissions=data.get("permissions"),
            hooks=data.get("hooks"),
            tools=data.get("tools"),
            min_clow_version=data.get("min_clow_version", ""),
            source=data.get("source", "local"),
            path=path,
        )

    @classmethod
    def from_file(cls, manifest_path: Path) -> PluginManifest:
        with open(manifest_path) as f:
            data = json.load(f)
        return cls.from_dict(data, path=str(manifest_path.parent))

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "entry_point": self.entry_point,
            "permissions": self.permissions,
            "hooks": self.hooks,
            "tools": self.tools,
            "min_clow_version": self.min_clow_version,
            "source": self.source,
            "path": self.path,
        }

    def validate(self) -> list[str]:
        """Valida o manifesto. Retorna lista de erros."""
        errors = []
        if not self.name or not self.name.strip():
            errors.append("Campo 'name' e obrigatorio")
        if not self.entry_point:
            errors.append("Campo 'entry_point' e obrigatorio")
        return errors


class PluginManager:
    """Gerencia carregamento, instalacao e ciclo de vida dos plugins."""

    def __init__(self) -> None:
        self._loaded: dict[str, Any] = {}  # nome -> modulo
        self._manifests: dict[str, PluginManifest] = {}  # nome -> manifesto
        self._errors: list[tuple[str, str]] = []

    def load_all(self, registry: ToolRegistry, hook_runner: Any = None) -> int:
        """Carrega todos os plugins do diretorio de plugins.

        Suporta:
        1. Arquivos .py soltos (legado)
        2. Diretorios com plugin.json (manifesto)
        3. Diretorios com __init__.py (legado)
        """
        if not PLUGINS_DIR.exists():
            return 0

        count = 0

        # 1. Plugins com manifesto (diretorios com plugin.json)
        for plugin_dir in sorted(PLUGINS_DIR.iterdir()):
            if plugin_dir.is_dir():
                manifest_file = plugin_dir / "plugin.json"
                if manifest_file.exists():
                    if self._load_plugin_with_manifest(manifest_file, registry, hook_runner):
                        count += 1
                    continue

                # Legado: diretorios com __init__.py
                if (plugin_dir / "__init__.py").exists():
                    if self._load_plugin(plugin_dir / "__init__.py", registry, hook_runner):
                        count += 1

        # 2. Plugins .py soltos (legado)
        for plugin_path in sorted(PLUGINS_DIR.glob("*.py")):
            if plugin_path.name.startswith("_"):
                continue
            if self._load_plugin(plugin_path, registry, hook_runner):
                count += 1

        return count

    def _load_plugin_with_manifest(
        self,
        manifest_path: Path,
        registry: ToolRegistry,
        hook_runner: Any,
    ) -> bool:
        """Carrega um plugin com manifesto (plugin.json)."""
        try:
            manifest = PluginManifest.from_file(manifest_path)

            # Valida manifesto
            errors = manifest.validate()
            if errors:
                self._errors.append((manifest.name, f"Manifesto invalido: {'; '.join(errors)}"))
                return False

            name = manifest.name
            if name in self._loaded:
                return True

            # Carrega entry_point
            plugin_dir = manifest_path.parent
            entry_file = plugin_dir / manifest.entry_point
            if not entry_file.exists():
                self._errors.append((name, f"Entry point nao encontrado: {manifest.entry_point}"))
                return False

            if self._load_plugin(entry_file, registry, hook_runner, name=name):
                self._manifests[name] = manifest

                # Registra hooks declarados no manifesto
                if hook_runner and manifest.hooks:
                    from .hooks import Hook
                    for event, cmd_path in manifest.hooks.items():
                        hook_cmd = str(plugin_dir / cmd_path)
                        hook = Hook(event=event, command=hook_cmd, tool="")
                        hook_runner.add_hook(hook)

                return True
            return False

        except Exception as e:
            self._errors.append(("unknown", f"Erro carregando manifesto: {e}"))
            return False

    def _load_plugin(
        self,
        path: Path,
        registry: ToolRegistry,
        hook_runner: Any,
        name: str | None = None,
    ) -> bool:
        """Carrega um plugin individual (legado ou entry_point)."""
        if name is None:
            name = path.stem if path.name != "__init__.py" else path.parent.name

        if name in self._loaded:
            return True

        try:
            spec = importlib.util.spec_from_file_location(f"clow_plugin_{name}", path)
            if spec is None or spec.loader is None:
                self._errors.append((name, "Nao foi possivel criar spec"))
                return False

            module = importlib.util.module_from_spec(spec)
            sys.modules[f"clow_plugin_{name}"] = module
            spec.loader.exec_module(module)

            if hasattr(module, "register"):
                module.register(registry, hook_runner)

            self._loaded[name] = module
            return True

        except Exception as e:
            self._errors.append((name, str(e)))
            return False

    # ── Instalacao via Git ──────────────────────────────────────

    def install_from_git(self, git_url: str) -> tuple[bool, str]:
        """Instala um plugin de um repositorio Git.

        Clona o repo para ~/.clow/plugins/<nome>/ e carrega.
        Retorna (sucesso, mensagem).
        """
        # Extrai nome do repo
        repo_name = git_url.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        target_dir = PLUGINS_DIR / repo_name

        if target_dir.exists():
            return False, f"Plugin '{repo_name}' ja instalado em {target_dir}"

        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", git_url, str(target_dir)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                return False, f"Erro ao clonar: {result.stderr}"

            # Verifica se tem manifesto
            manifest_file = target_dir / "plugin.json"
            if manifest_file.exists():
                manifest = PluginManifest.from_file(manifest_file)
                manifest.source = "git"
                manifest.path = str(target_dir)
                self._save_to_registry(repo_name, git_url, str(target_dir))
                return True, f"Plugin '{manifest.name}' v{manifest.version} instalado com sucesso"

            # Sem manifesto — verifica se tem __init__.py ou main.py
            if (target_dir / "__init__.py").exists() or (target_dir / "main.py").exists():
                self._save_to_registry(repo_name, git_url, str(target_dir))
                return True, f"Plugin '{repo_name}' instalado (sem manifesto)"

            # Nenhum entry point encontrado
            shutil.rmtree(target_dir, ignore_errors=True)
            return False, "Repositorio nao contem plugin valido (falta plugin.json, __init__.py ou main.py)"

        except subprocess.TimeoutExpired:
            shutil.rmtree(target_dir, ignore_errors=True)
            return False, "Timeout ao clonar repositorio"
        except FileNotFoundError:
            return False, "Git nao encontrado. Instale git primeiro."
        except Exception as e:
            shutil.rmtree(target_dir, ignore_errors=True)
            return False, f"Erro: {e}"

    def uninstall(self, name: str) -> tuple[bool, str]:
        """Remove um plugin instalado."""
        target_dir = PLUGINS_DIR / name
        target_file = PLUGINS_DIR / f"{name}.py"

        if target_dir.exists() and target_dir.is_dir():
            shutil.rmtree(target_dir, ignore_errors=True)
            self._loaded.pop(name, None)
            self._manifests.pop(name, None)
            self._remove_from_registry(name)
            return True, f"Plugin '{name}' removido"

        if target_file.exists():
            target_file.unlink()
            self._loaded.pop(name, None)
            self._remove_from_registry(name)
            return True, f"Plugin '{name}' removido"

        return False, f"Plugin '{name}' nao encontrado"

    def update(self, name: str) -> tuple[bool, str]:
        """Atualiza um plugin instalado via Git (git pull)."""
        target_dir = PLUGINS_DIR / name
        if not target_dir.exists() or not (target_dir / ".git").exists():
            return False, f"Plugin '{name}' nao foi instalado via git"

        try:
            result = subprocess.run(
                ["git", "pull"],
                capture_output=True,
                text=True,
                cwd=str(target_dir),
                timeout=30,
            )
            if result.returncode == 0:
                return True, f"Plugin '{name}' atualizado: {result.stdout.strip()}"
            return False, f"Erro ao atualizar: {result.stderr}"
        except Exception as e:
            return False, f"Erro: {e}"

    # ── Registro persistente ────────────────────────────────────

    def _save_to_registry(self, name: str, source_url: str, path: str) -> None:
        """Salva info de instalacao no registro."""
        registry = self._load_registry()
        import time
        registry[name] = {
            "source_url": source_url,
            "path": path,
            "installed_at": time.time(),
        }
        with open(REGISTRY_FILE, "w") as f:
            json.dump(registry, f, indent=2)

    def _remove_from_registry(self, name: str) -> None:
        """Remove do registro."""
        registry = self._load_registry()
        registry.pop(name, None)
        with open(REGISTRY_FILE, "w") as f:
            json.dump(registry, f, indent=2)

    def _load_registry(self) -> dict:
        """Carrega registro de plugins instalados."""
        if REGISTRY_FILE.exists():
            try:
                with open(REGISTRY_FILE) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    # ── Listagem ────────────────────────────────────────────────

    def list_plugins(self) -> list[dict]:
        """Lista plugins carregados, com manifesto e erros."""
        plugins = []
        for name, module in self._loaded.items():
            manifest = self._manifests.get(name)
            if manifest:
                plugins.append({
                    "name": manifest.name,
                    "version": manifest.version,
                    "status": "loaded",
                    "description": manifest.description,
                    "source": manifest.source,
                    "tools": manifest.tools,
                    "hooks": list(manifest.hooks.keys()) if manifest.hooks else [],
                })
            else:
                desc = getattr(module, "__doc__", "") or ""
                desc = desc.strip().split("\n")[0] if desc else "Sem descricao"
                plugins.append({
                    "name": name,
                    "version": "?",
                    "status": "loaded",
                    "description": desc,
                    "source": "local",
                })
        for name, error in self._errors:
            plugins.append({
                "name": name,
                "status": "error",
                "description": error,
            })
        return plugins

    @property
    def loaded_count(self) -> int:
        return len(self._loaded)

    @property
    def error_count(self) -> int:
        return len(self._errors)
