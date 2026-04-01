"""Sistema de Plugins do Batmam.

Carrega plugins Python de ~/.batmam/plugins/ automaticamente.
Cada plugin é um módulo Python que pode:
  - Registrar novas ferramentas
  - Registrar hooks
  - Modificar configurações

Exemplo de plugin (~/.batmam/plugins/meu_plugin.py):

    from batmam.tools.base import BaseTool

    class MeuTool(BaseTool):
        name = "meu_tool"
        description = "Faz algo legal"

        def get_schema(self):
            return {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            return "Feito!"

    def register(registry, hook_runner):
        registry.register(MeuTool())
"""

from __future__ import annotations
import importlib.util
import sys
from pathlib import Path
from typing import Any

from .tools.base import ToolRegistry
from . import config


PLUGINS_DIR = config.BATMAM_HOME / "plugins"
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)


class PluginManager:
    """Gerencia carregamento e ciclo de vida dos plugins."""

    def __init__(self) -> None:
        self._loaded: dict[str, Any] = {}  # nome -> módulo
        self._errors: list[tuple[str, str]] = []

    def load_all(self, registry: ToolRegistry, hook_runner: Any = None) -> int:
        """Carrega todos os plugins do diretório de plugins.

        Retorna número de plugins carregados com sucesso.
        """
        if not PLUGINS_DIR.exists():
            return 0

        count = 0
        for plugin_path in sorted(PLUGINS_DIR.glob("*.py")):
            if plugin_path.name.startswith("_"):
                continue
            if self._load_plugin(plugin_path, registry, hook_runner):
                count += 1

        # Também carrega plugins de subdiretórios com __init__.py
        for plugin_dir in sorted(PLUGINS_DIR.iterdir()):
            if plugin_dir.is_dir() and (plugin_dir / "__init__.py").exists():
                if self._load_plugin(plugin_dir / "__init__.py", registry, hook_runner):
                    count += 1

        return count

    def _load_plugin(
        self,
        path: Path,
        registry: ToolRegistry,
        hook_runner: Any,
    ) -> bool:
        """Carrega um plugin individual."""
        name = path.stem if path.name != "__init__.py" else path.parent.name

        if name in self._loaded:
            return True  # Já carregado

        try:
            spec = importlib.util.spec_from_file_location(f"batmam_plugin_{name}", path)
            if spec is None or spec.loader is None:
                self._errors.append((name, "Não foi possível criar spec"))
                return False

            module = importlib.util.module_from_spec(spec)
            sys.modules[f"batmam_plugin_{name}"] = module
            spec.loader.exec_module(module)

            # Chama register() se existir
            if hasattr(module, "register"):
                module.register(registry, hook_runner)

            self._loaded[name] = module
            return True

        except Exception as e:
            self._errors.append((name, str(e)))
            return False

    def list_plugins(self) -> list[dict]:
        """Lista plugins carregados e erros."""
        plugins = []
        for name, module in self._loaded.items():
            desc = getattr(module, "__doc__", "") or ""
            desc = desc.strip().split("\n")[0] if desc else "Sem descrição"
            plugins.append({
                "name": name,
                "status": "loaded",
                "description": desc,
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
