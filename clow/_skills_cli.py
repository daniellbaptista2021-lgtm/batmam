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




# ── Skills Avancados (20 novos — inspirados no Claude Code) ────

def _batch_handler(args: str, ctx: dict) -> str:
    return (
        f"Execute os seguintes jobs em sequencia, reportando resultado de cada um:\n{args}\n\n"
        "Para cada job: execute, capture o resultado, e continue para o proximo. "
        "No final, mostre um resumo com status de cada job (ok/erro)."
        if args else
        "Execute multiplos comandos em sequencia. "
        "Forneça os comandos separados por ponto-e-virgula ou um por linha."
    )

def _loop_handler(args: str, ctx: dict) -> str:
    return (
        f"Execute iterativamente ate atingir o objetivo: {args}\n\n"
        "Ciclo: tente → verifique resultado → ajuste → tente novamente. "
        "Maximo 10 iteracoes. Pare quando o objetivo for atingido ou quando "
        "nao houver mais progresso. Reporte cada tentativa."
        if args else
        "Execute um loop iterativo ate atingir um objetivo. "
        "Diga qual o objetivo a atingir."
    )

def _debug_handler(args: str, ctx: dict) -> str:
    target = args or "o erro mais recente"
    return (
        f"Debug inteligente de: {target}\n\n"
        "1) Leia o stacktrace/erro completo\n"
        "2) Identifique o arquivo e linha do problema\n"
        "3) Leia o codigo ao redor para entender o contexto\n"
        "4) Formule hipotese sobre a causa raiz\n"
        "5) Proponha e aplique o fix\n"
        "6) Execute testes para validar\n"
        "Use as tools read, grep, edit, bash conforme necessario."
    )

def _stuck_handler(args: str, ctx: dict) -> str:
    return (
        "O agente esta travado ou em loop. Analise a situacao:\n"
        "1) Revise o historico recente da conversa\n"
        "2) Identifique o que ja foi tentado\n"
        "3) Identifique o que esta bloqueando o progresso\n"
        "4) Proponha uma abordagem completamente diferente\n"
        "5) Se necessario, simplifique o objetivo\n"
        f"Contexto adicional: {args}" if args else
        "O agente esta travado. Analise o historico, identifique o bloqueio, "
        "e proponha abordagem alternativa."
    )

def _remember_handler(args: str, ctx: dict) -> str:
    if args:
        return (
            f"Salve na memoria persistente: {args}\n\n"
            "Use a ferramenta de memoria para salvar esta informacao. "
            "Classifique como user/feedback/project/reference conforme o tipo."
        )
    return (
        "Liste todas as memorias salvas. "
        "Mostre nome, tipo, e um resumo de cada uma."
    )

def _schedule_handler(args: str, ctx: dict) -> str:
    return (
        f"Configure um agente remoto agendado: {args}\n\n"
        "Use o sistema de cron jobs para agendar execucao recorrente. "
        "Defina: intervalo, prompt a executar, e condicoes de parada."
        if args else
        "Configure um agente agendado. "
        "Diga: o que executar, com que frequencia, e quando parar."
    )

def _verify_handler(args: str, ctx: dict) -> str:
    return (
        "Verifique a integridade do projeto:\n"
        "1) Execute todos os testes (pytest/unittest)\n"
        "2) Verifique se o codigo compila sem erros\n"
        "3) Verifique imports quebrados\n"
        "4) Verifique git status (arquivos nao commitados)\n"
        "5) Verifique se o build funciona\n"
        f"Foco em: {args}" if args else
        "Verifique a integridade completa do projeto: testes, build, imports, git status."
    )

def _security_handler(args: str, ctx: dict) -> str:
    target = args or "todo o codigo do projeto"
    return (
        f"Auditoria de seguranca em: {target}\n\n"
        "Verifique OWASP Top 10:\n"
        "1) Injection (SQL, command, XSS)\n"
        "2) Autenticacao quebrada\n"
        "3) Dados sensiveis expostos (.env, keys, tokens no codigo)\n"
        "4) Configuracoes inseguras\n"
        "5) Dependencias com vulnerabilidades conhecidas\n"
        "6) Validacao de input insuficiente\n"
        "Reporte severidade (critica/alta/media/baixa) e sugira fix para cada."
    )

def _perf_handler(args: str, ctx: dict) -> str:
    target = args or "o codigo modificado recentemente"
    return (
        f"Analise de performance de: {target}\n\n"
        "1) Identifique gargalos (loops O(n^2), queries N+1, I/O bloqueante)\n"
        "2) Meca tempo de execucao com benchmarks simples\n"
        "3) Sugira otimizacoes concretas com exemplos\n"
        "4) Priorize por impacto (maior ganho primeiro)\n"
        "Use bash para rodar benchmarks quando possivel."
    )

def _docs_handler(args: str, ctx: dict) -> str:
    target = args or "o projeto inteiro"
    return (
        f"Gere documentacao para: {target}\n\n"
        "Inclua: descricao, instalacao, uso, API reference, exemplos. "
        "Formate em Markdown. Se for funcao/classe, gere docstrings. "
        "Se for projeto, gere/atualize README.md."
    )

def _migrate_handler(args: str, ctx: dict) -> str:
    return (
        f"Execute migracao: {args}\n\n"
        "1) Analise o estado atual\n"
        "2) Crie backup antes de migrar\n"
        "3) Execute a migracao passo a passo\n"
        "4) Valide que tudo funciona apos migrar\n"
        "5) Documente o que foi feito"
        if args else
        "Execute uma migracao. Diga: de onde para onde (framework, DB, versao, etc)."
    )

def _pr_handler(args: str, ctx: dict) -> str:
    return (
        "Crie um Pull Request completo:\n"
        "1) git diff para ver todas as mudancas\n"
        "2) Gere titulo conciso (< 70 chars)\n"
        "3) Gere descricao com: ## Summary, ## Changes, ## Test Plan\n"
        "4) Identifique breaking changes\n"
        "5) Sugira reviewers\n"
        f"Branch/contexto: {args}" if args else
        "Crie um Pull Request com titulo, descricao e test plan baseado nas mudancas atuais."
    )

def _changelog_handler(args: str, ctx: dict) -> str:
    range_str = args or "desde o ultimo release"
    return (
        f"Gere changelog para: {range_str}\n\n"
        "Use git log para listar commits. Agrupe por:\n"
        "- Features (feat:)\n"
        "- Bug Fixes (fix:)\n"
        "- Breaking Changes\n"
        "- Other\n"
        "Formate em Markdown no padrao Keep a Changelog."
    )

def _scaffold_handler(args: str, ctx: dict) -> str:
    component = args or "componente"
    return (
        f"Gere scaffold/boilerplate para: {component}\n\n"
        "Crie todos os arquivos necessarios: codigo, testes, types, exports. "
        "Siga os padroes e convencoes ja existentes no projeto. "
        "Registre o novo componente onde necessario (index, registry, etc)."
    )

def _cleanup_handler(args: str, ctx: dict) -> str:
    return (
        "Limpeza do projeto:\n"
        "1) Encontre e remova imports nao usados\n"
        "2) Encontre e remova variaveis/funcoes mortas\n"
        "3) Remova arquivos temporarios e caches\n"
        "4) Organize imports (stdlib, third-party, local)\n"
        "5) Remova comentarios TODO resolvidos\n"
        f"Foco em: {args}" if args else
        "Faca limpeza geral do codigo: imports mortos, variaveis nao usadas, caches."
    )

def _estimate_handler(args: str, ctx: dict) -> str:
    task = args or "a tarefa discutida"
    return (
        f"Estime o esforco para: {task}\n\n"
        "Analise:\n"
        "1) Complexidade tecnica (baixa/media/alta)\n"
        "2) Arquivos que precisam ser modificados\n"
        "3) Riscos e dependencias\n"
        "4) Testes necessarios\n"
        "5) Estimativa em horas (otimista/realista/pessimista)\n"
        "Seja honesto e conservador."
    )

def _plan_handler(args: str, ctx: dict) -> str:
    objective = args or "o objetivo discutido"
    return (
        f"Crie um plano de implementacao para: {objective}\n\n"
        "Estruture em fases:\n"
        "1) Preparacao (pesquisa, design)\n"
        "2) Implementacao (passo a passo detalhado)\n"
        "3) Testes e validacao\n"
        "4) Deploy/entrega\n"
        "Identifique riscos, dependencias e criterios de sucesso. "
        "NAO implemente — apenas planeje."
    )

def _diff_handler(args: str, ctx: dict) -> str:
    return (
        "Mostre e analise todas as mudancas pendentes:\n"
        "1) git status para ver arquivos modificados\n"
        "2) git diff para ver mudancas detalhadas\n"
        "3) Resuma o que mudou em linguagem humana\n"
        "4) Identifique potenciais problemas\n"
        f"Filtro: {args}" if args else
        "Mostre e analise todas as mudancas pendentes no repositorio."
    )

def _undo_handler(args: str, ctx: dict) -> str:
    return (
        f"Desfaca a ultima acao: {args}\n\n"
        "Analise o que foi feito recentemente e reverta de forma segura. "
        "Use git checkout/restore para arquivos, git reset para commits. "
        "NUNCA use --force sem confirmar. Mostre o que sera desfeito antes de agir."
        if args else
        "Desfaca a ultima acao realizada. Mostre o que sera desfeito antes de agir."
    )

def _search_handler(args: str, ctx: dict) -> str:
    query = args or ""
    return (
        f"Busca profunda no projeto por: {query}\n\n"
        "1) grep no codigo-fonte\n"
        "2) Busca em nomes de arquivos\n"
        "3) Busca em git log (commits)\n"
        "4) Busca em comentarios e docstrings\n"
        "Reporte todos os resultados organizados por relevancia."
        if query else
        "Faca uma busca profunda no projeto. Diga o que procurar."
    )


BUILTIN_SKILLS = [
    # ── Dev Core (8 originais) ──
    Skill(name="commit", description="Commit inteligente com mensagem automatica", handler=_commit_handler, aliases=["c", "ci"]),
    Skill(name="review", description="Code review detalhado com nota 1-10", handler=_review_handler, aliases=["rev"]),
    Skill(name="test", description="Gera e executa testes", handler=_test_handler, aliases=["t"]),
    Skill(name="refactor", description="Refatora codigo mantendo comportamento", handler=_refactor_handler, aliases=["ref"]),
    Skill(name="explain", description="Explica codigo em detalhes", handler=_explain_handler, aliases=["exp"]),
    Skill(name="fix", description="Encontra e corrige bugs", handler=_fix_handler, aliases=["f"]),
    Skill(name="init", description="Inicializa novo projeto", handler=_init_handler),
    Skill(name="simplify", description="Revisa codigo para reuso e qualidade", handler=_simplify_handler, aliases=["simp"]),

    # ── Dev Avancado (12 novos — inspirados no Claude Code) ──
    Skill(name="batch", description="Executa multiplos jobs em sequencia", handler=_batch_handler, aliases=["b"]),
    Skill(name="loop", description="Executa iterativamente ate atingir objetivo", handler=_loop_handler, aliases=["l"]),
    Skill(name="debug", description="Debug inteligente com analise de causa raiz", handler=_debug_handler, aliases=["dbg"]),
    Skill(name="stuck", description="Desbloqueia quando o agente esta travado", handler=_stuck_handler),
    Skill(name="remember", description="Salva/lista memorias persistentes", handler=_remember_handler, aliases=["mem"]),
    Skill(name="schedule", description="Configura agente remoto agendado (cron)", handler=_schedule_handler, aliases=["sched"]),
    Skill(name="verify", description="Verifica integridade do projeto (testes, build, imports)", handler=_verify_handler, aliases=["v"]),
    Skill(name="security", description="Auditoria de seguranca OWASP Top 10", handler=_security_handler, aliases=["sec"]),
    Skill(name="perf", description="Analise de performance e otimizacao", handler=_perf_handler, aliases=["performance"]),
    Skill(name="docs", description="Gera documentacao (README, docstrings, API ref)", handler=_docs_handler, aliases=["doc"]),
    Skill(name="migrate", description="Executa migracoes (DB, framework, versao)", handler=_migrate_handler, aliases=["mig"]),
    Skill(name="pr", description="Cria Pull Request com titulo, descricao e test plan", handler=_pr_handler, aliases=["pull-request"]),

    # ── Workflow (8 novos) ──
    Skill(name="changelog", description="Gera changelog a partir do git log", handler=_changelog_handler, aliases=["cl"]),
    Skill(name="scaffold", description="Gera boilerplate seguindo padroes do projeto", handler=_scaffold_handler, aliases=["new"]),
    Skill(name="cleanup", description="Limpa imports mortos, variaveis e caches", handler=_cleanup_handler, aliases=["clean"]),
    Skill(name="estimate", description="Estima esforco de uma tarefa", handler=_estimate_handler, aliases=["est"]),
    Skill(name="plan", description="Cria plano de implementacao sem executar", handler=_plan_handler),
    Skill(name="diff", description="Mostra e analisa mudancas pendentes", handler=_diff_handler),
    Skill(name="undo", description="Desfaz a ultima acao com seguranca", handler=_undo_handler),
    Skill(name="search", description="Busca profunda no projeto (codigo, git, arquivos)", handler=_search_handler, aliases=["find"]),

    # ── Dominio (8 originais) ──
    Skill(name="cotacao", description="Gera cotacao de seguro/plano funerario em PDF", handler=_cotacao_handler, aliases=["cot"]),
    Skill(name="proposta", description="Gera proposta comercial profissional em PDF", handler=_proposta_handler, aliases=["prop"]),
    Skill(name="relatorio", description="Relatorio de vendas com dados do Supabase", handler=_relatorio_handler, aliases=["rel"]),
    Skill(name="deploy", description="Deploy automatizado com health checks", handler=_deploy_handler, aliases=["dep"]),
    Skill(name="backup", description="Backup completo do VPS (DB, n8n, configs)", handler=_backup_handler_skill, aliases=["bkp"]),
    Skill(name="monitor", description="Status de todos os servicos (Docker, n8n, CPU/RAM)", handler=_monitor_handler, aliases=["mon"]),
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
