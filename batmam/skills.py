"""Sistema de Skills do Batmam — comandos /slash extensíveis."""

from __future__ import annotations
import os
import importlib.util
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable
from . import config


@dataclass
class Skill:
    """Definição de um skill."""
    name: str
    description: str
    prompt_template: str = ""
    handler: Callable[..., str] | None = None
    aliases: list[str] = field(default_factory=list)
    category: str = "built-in"

    def execute(self, args: str = "", context: dict[str, Any] | None = None) -> str:
        """Executa o skill. Retorna o prompt expandido ou resultado do handler."""
        if self.handler:
            return self.handler(args, context or {})
        if self.prompt_template:
            return self.prompt_template.replace("{args}", args).replace("{context}", str(context or {}))
        return f"Skill {self.name}: {args}"


class SkillRegistry:
    """Registro central de skills."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._aliases: dict[str, str] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill
        for alias in skill.aliases:
            self._aliases[alias] = skill.name

    def get(self, name: str) -> Skill | None:
        if name in self._skills:
            return self._skills[name]
        real_name = self._aliases.get(name)
        return self._skills.get(real_name) if real_name else None

    def list_all(self) -> list[Skill]:
        return sorted(self._skills.values(), key=lambda s: s.name)

    def names(self) -> list[str]:
        return sorted(self._skills.keys())


# ── Built-in Skills ──────────────────────────────────────────

def _commit_handler(args: str, ctx: dict) -> str:
    return (
        "Analise todas as mudanças no repositório git (git status + git diff). "
        "Crie um commit com mensagem clara e concisa em português. "
        "Siga convenções: feat/fix/refactor/docs/style/test/chore. "
        f"Instruções adicionais: {args}" if args else
        "Analise todas as mudanças no repositório git (git status + git diff). "
        "Crie um commit com mensagem clara e concisa em português. "
        "Siga convenções: feat/fix/refactor/docs/style/test/chore."
    )

def _review_handler(args: str, ctx: dict) -> str:
    target = args or "as mudanças atuais (git diff)"
    return (
        f"Faça um code review detalhado de {target}. "
        "Verifique: bugs, segurança (OWASP), performance, legibilidade, testes. "
        "Dê nota de 1-10 e sugira melhorias específicas com exemplos de código."
    )

def _test_handler(args: str, ctx: dict) -> str:
    target = args or "os arquivos modificados recentemente"
    return (
        f"Gere testes unitários para {target}. "
        "Use o framework de teste já existente no projeto (pytest/jest/etc). "
        "Cubra happy path, edge cases e error cases. Execute os testes ao final."
    )

def _refactor_handler(args: str, ctx: dict) -> str:
    target = args or "o código que acabamos de discutir"
    return (
        f"Refatore {target} para melhorar legibilidade e manutenibilidade. "
        "Mantenha o comportamento idêntico. Explique cada mudança."
    )

def _explain_handler(args: str, ctx: dict) -> str:
    target = args or "o código relevante no diretório atual"
    return (
        f"Explique {target} em detalhes. "
        "Descreva: objetivo, fluxo de dados, decisões de design, e possíveis melhorias."
    )

def _fix_handler(args: str, ctx: dict) -> str:
    return (
        f"Encontre e corrija o bug: {args}. " if args else
        "Analise os erros recentes e corrija os bugs encontrados. "
    ) + "Explique a causa raiz e como o fix resolve o problema."

def _init_handler(args: str, ctx: dict) -> str:
    project_type = args or "genérico"
    return (
        f"Inicialize um novo projeto {project_type}. "
        "Crie a estrutura de diretórios, arquivos de configuração, "
        "dependências, README, e um exemplo funcional mínimo."
    )

def _simplify_handler(args: str, ctx: dict) -> str:
    return (
        "Revise o código alterado recentemente buscando oportunidades de: "
        "1) Reutilizar código existente, 2) Melhorar qualidade, "
        "3) Aumentar eficiência. Corrija qualquer problema encontrado."
    )


BUILTIN_SKILLS = [
    Skill(name="commit", description="Commit inteligente com mensagem automática", handler=_commit_handler, aliases=["c", "ci"]),
    Skill(name="review", description="Code review detalhado", handler=_review_handler, aliases=["rev"]),
    Skill(name="test", description="Gera e executa testes", handler=_test_handler, aliases=["t"]),
    Skill(name="refactor", description="Refatora código", handler=_refactor_handler, aliases=["ref"]),
    Skill(name="explain", description="Explica código em detalhes", handler=_explain_handler, aliases=["exp"]),
    Skill(name="fix", description="Encontra e corrige bugs", handler=_fix_handler, aliases=["f"]),
    Skill(name="init", description="Inicializa novo projeto", handler=_init_handler),
    Skill(name="simplify", description="Revisa código para reuso e qualidade", handler=_simplify_handler, aliases=["simp"]),
]


def create_default_skill_registry() -> SkillRegistry:
    """Cria registry com skills built-in + customizados."""
    registry = SkillRegistry()

    for skill in BUILTIN_SKILLS:
        registry.register(skill)

    # Carrega skills customizados de ~/.batmam/skills/
    _load_custom_skills(registry)

    return registry


def _load_custom_skills(registry: SkillRegistry) -> None:
    """Carrega skills de ~/.batmam/skills/*.py"""
    skills_dir = config.BATMAM_HOME / "skills"
    if not skills_dir.exists():
        skills_dir.mkdir(parents=True, exist_ok=True)
        return

    for skill_file in skills_dir.glob("*.py"):
        try:
            spec = importlib.util.spec_from_file_location(skill_file.stem, skill_file)
            if not spec or not spec.loader:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # O módulo deve exportar SKILL ou register(registry)
            if hasattr(module, "SKILL"):
                skill_data = module.SKILL
                skill = Skill(
                    name=skill_data.get("name", skill_file.stem),
                    description=skill_data.get("description", ""),
                    prompt_template=skill_data.get("prompt", ""),
                    handler=skill_data.get("handler"),
                    aliases=skill_data.get("aliases", []),
                    category="custom",
                )
                registry.register(skill)
            elif hasattr(module, "register"):
                module.register(registry)
        except Exception:
            continue
