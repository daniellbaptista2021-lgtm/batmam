"""Sistema de Skills do Clow — comandos /slash extensíveis."""

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


def _cotacao_handler(args: str, ctx: dict) -> str:
    return (
        "Gere uma cotação de seguro de vida ou plano funerário. "
        "Peça os dados do cliente se não fornecidos: nome completo, idade, CPF, plano desejado. "
        "Use a tool pdf_tool para gerar um PDF formatado profissionalmente com: "
        "logo, dados do cliente, detalhes do plano, valores, benefícios, e condições. "
        "O PDF deve estar pronto para enviar por WhatsApp. "
        f"Dados: {args}" if args else
        "Gere uma cotação de seguro de vida ou plano funerário. "
        "Peça os dados do cliente: nome completo, idade, CPF, plano desejado. "
        "Use a tool pdf_tool para gerar um PDF formatado profissionalmente."
    )


def _proposta_handler(args: str, ctx: dict) -> str:
    return (
        "Gere uma proposta comercial profissional em PDF. "
        "Destinada para funerárias, corretores parceiros, ou clientes finais. "
        "A proposta deve incluir: logo, apresentação da empresa, tabela de preços, "
        "benefícios detalhados, diferenciais competitivos, e dados de contato. "
        "Use a tool pdf_tool com create_from_html para gerar o documento. "
        f"Detalhes: {args}" if args else
        "Gere uma proposta comercial profissional em PDF. "
        "Pergunte: tipo de proposta, público-alvo, produtos/planos a incluir."
    )


def _relatorio_handler(args: str, ctx: dict) -> str:
    periodo = args or "últimos 30 dias"
    return (
        f"Gere um relatório de vendas do período: {periodo}. "
        "Use a tool supabase_query para puxar dados de vendas do banco. "
        "Formate em tabela bonita com totais, médias, e ranking de vendedores. "
        "Se possível, inclua gráficos ASCII. "
        "Exporte em HTML e/ou PDF usando pdf_tool. "
        "Use spreadsheet para criar uma planilha Excel complementar."
    )


def _deploy_handler(args: str, ctx: dict) -> str:
    return (
        "Execute deploy automatizado no servidor: "
        "1) git pull para atualizar código "
        "2) docker-compose restart dos serviços afetados "
        "3) Verifique health checks (curl nos endpoints principais) "
        "4) Se der erro, notifique via whatsapp_send "
        "Use as tools bash, docker_manage, http_request e whatsapp_send. "
        f"Serviço: {args}" if args else
        "Execute deploy automatizado. "
        "Pergunte qual serviço/projeto fazer deploy."
    )


def _backup_handler_skill(args: str, ctx: dict) -> str:
    return (
        "Faça backup completo do VPS: "
        "1) Dump do banco Postgres via bash (pg_dump) "
        "2) Export dos workflows n8n via n8n_workflow "
        "3) Cópia de configs importantes (/etc/nginx, docker-compose, .env) "
        "4) Compacte tudo em um .tar.gz com data no nome "
        "Use as tools bash e n8n_workflow. "
        f"Detalhes: {args}" if args else
        "Faça backup completo do VPS incluindo banco, n8n, e configs."
    )


def _monitor_handler(args: str, ctx: dict) -> str:
    return (
        "Mostre o status completo de todos os serviços: "
        "1) Docker containers (docker_manage ps + stats) "
        "2) Uso de CPU, RAM e disco (bash: top, free, df) "
        "3) Workflows n8n ativos (n8n_workflow list) "
        "4) Health check dos serviços web (http_request GET nos endpoints) "
        "Formate tudo em tabelas organizadas. Destaque problemas em vermelho."
    )


def _ads_handler(args: str, ctx: dict) -> str:
    return (
        "Gerencie campanhas Meta Ads. "
        "Use http_request para conectar na Meta Marketing API. "
        "Ações disponíveis: criar campanha Andromeda, verificar métricas (CPL, CPA, ROAS), "
        "pausar/ativar campanhas, escalar orçamento. "
        "Formate métricas em tabela comparativa. "
        f"Ação: {args}" if args else
        "Gerencie campanhas Meta Ads. "
        "Pergunte: qual ação (métricas, criar, pausar, escalar)?"
    )


def _leads_handler(args: str, ctx: dict) -> str:
    return (
        "Consulte e gerencie leads. "
        "Use supabase_query para listar leads recentes do banco. "
        "Use http_request para consultar Chatwoot API se necessário. "
        "Ações: listar leads por status, filtrar por data/vendedor, "
        "atribuir lead para vendedor, enviar follow-up via whatsapp_send. "
        f"Filtro: {args}" if args else
        "Consulte e gerencie leads. "
        "Pergunte: listar, filtrar, atribuir, ou follow-up?"
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
    # Novas skills (8)
    Skill(name="cotacao", description="Gera cotação de seguro/plano funerário em PDF", handler=_cotacao_handler, aliases=["cot"]),
    Skill(name="proposta", description="Gera proposta comercial profissional em PDF", handler=_proposta_handler, aliases=["prop"]),
    Skill(name="relatorio", description="Relatório de vendas com dados do Supabase", handler=_relatorio_handler, aliases=["rel"]),
    Skill(name="deploy", description="Deploy automatizado com health checks", handler=_deploy_handler, aliases=["dep"]),
    Skill(name="backup", description="Backup completo do VPS (DB, n8n, configs)", handler=_backup_handler_skill, aliases=["bkp"]),
    Skill(name="monitor", description="Status de todos os serviços (Docker, n8n, CPU/RAM)", handler=_monitor_handler, aliases=["mon"]),
    Skill(name="ads", description="Gerencia campanhas Meta Ads", handler=_ads_handler),
    Skill(name="leads", description="Consulta e gerencia leads", handler=_leads_handler),
]


def create_default_skill_registry() -> SkillRegistry:
    """Cria registry com skills built-in + customizados."""
    registry = SkillRegistry()

    for skill in BUILTIN_SKILLS:
        registry.register(skill)

    # Carrega skills customizados de ~/.clow/skills/
    _load_custom_skills(registry)

    return registry


def _load_custom_skills(registry: SkillRegistry) -> None:
    """Carrega skills de ~/.clow/skills/*.py"""
    skills_dir = config.CLOW_HOME / "skills"
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
