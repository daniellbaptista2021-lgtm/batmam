"""Tipos especializados de agentes — matching Claude Code capabilities.

Agent types:
- ExploreAgent: Busca rápida no codebase (glob, grep, read)
- PlanAgent: Arquiteto — planeja sem escrever (read-only + analysis)
- GeneralAgent: Propósito geral (todos os tools)
- GuideAgent: Especialista em responder dúvidas sobre o Batmam
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class AgentType:
    """Definição de um tipo de agente."""
    name: str
    description: str
    allowed_tools: set[str] | None  # None = todos
    system_prompt_extra: str = ""
    max_iterations: int = 30
    temperature: float = 0.2


EXPLORE_AGENT = AgentType(
    name="explore",
    description="Agente rápido para explorar codebases. Busca arquivos, pesquisa keywords, responde perguntas sobre arquitetura.",
    allowed_tools={"read", "glob", "grep", "web_search", "web_fetch", "task_list", "task_get"},
    system_prompt_extra=(
        "Você é um agente de exploração rápida. Seu objetivo é encontrar informações "
        "no codebase de forma eficiente. Use glob para encontrar arquivos, grep para "
        "buscar conteúdo, e read para examinar arquivos específicos. "
        "NÃO modifique nenhum arquivo. Apenas pesquise e reporte."
    ),
    max_iterations=15,
    temperature=0.1,
)

PLAN_AGENT = AgentType(
    name="plan",
    description="Arquiteto de software. Planeja implementação sem escrever código.",
    allowed_tools={"read", "glob", "grep", "web_search", "web_fetch", "task_create", "task_list", "task_get"},
    system_prompt_extra=(
        "Você é um arquiteto de software. Seu objetivo é analisar o codebase e criar "
        "planos de implementação detalhados. Para cada tarefa:\n"
        "1. Analise os arquivos existentes relevantes\n"
        "2. Identifique arquivos que precisam ser criados ou modificados\n"
        "3. Considere trade-offs arquiteturais\n"
        "4. Retorne um plano step-by-step com arquivos específicos\n"
        "5. Crie tasks para cada etapa do plano\n\n"
        "NÃO escreva código. NÃO modifique arquivos. Apenas planeje."
    ),
    max_iterations=20,
    temperature=0.2,
)

GENERAL_AGENT = AgentType(
    name="general",
    description="Agente de propósito geral para tarefas complexas multi-step.",
    allowed_tools=None,
    system_prompt_extra="",
    max_iterations=30,
    temperature=0.2,
)

GUIDE_AGENT = AgentType(
    name="guide",
    description="Especialista em responder dúvidas sobre o Batmam — features, comandos, configuração.",
    allowed_tools={"read", "glob", "grep"},
    system_prompt_extra=(
        "Você é um guia especialista do Batmam. Responda perguntas sobre:\n"
        "- Features e capabilities do Batmam\n"
        "- Comandos /slash disponíveis\n"
        "- Configuração e settings\n"
        "- Skills, hooks, plugins, MCP\n"
        "- Troubleshooting\n\n"
        "Busque nos arquivos do Batmam se necessário para dar respostas precisas."
    ),
    max_iterations=10,
    temperature=0.1,
)

AGENT_TYPES: dict[str, AgentType] = {
    "explore": EXPLORE_AGENT,
    "plan": PLAN_AGENT,
    "general": GENERAL_AGENT,
    "guide": GUIDE_AGENT,
}


def get_agent_type(name: str) -> AgentType | None:
    return AGENT_TYPES.get(name.lower())


def list_agent_types() -> list[AgentType]:
    return list(AGENT_TYPES.values())
