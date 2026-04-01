"""Tipos especializados de agentes — matching Claude Code capabilities.

Agent types:
- ExploreAgent: Busca rápida no codebase (glob, grep, read)
- PlanAgent: Arquiteto — planeja sem escrever (read-only + analysis)
- GeneralAgent: Propósito geral (todos os tools)
- GuideAgent: Especialista em responder dúvidas sobre o Clow
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
    description="Especialista em responder dúvidas sobre o Clow — features, comandos, configuração.",
    allowed_tools={"read", "glob", "grep"},
    system_prompt_extra=(
        "Você é um guia especialista do Clow. Responda perguntas sobre:\n"
        "- Features e capabilities do Clow\n"
        "- Comandos /slash disponíveis\n"
        "- Configuração e settings\n"
        "- Skills, hooks, plugins, MCP\n"
        "- Troubleshooting\n\n"
        "Busque nos arquivos do Clow se necessário para dar respostas precisas."
    ),
    max_iterations=10,
    temperature=0.1,
)

DEVOPS_AGENT = AgentType(
    name="devops",
    description="Agente especializado em infraestrutura. Docker, Traefik, nginx, SSL, DNS, VPS.",
    allowed_tools={"bash", "read", "write", "edit", "glob", "grep", "docker_manage",
                    "http_request", "n8n_workflow", "web_fetch"},
    system_prompt_extra=(
        "Você é um engenheiro DevOps/SRE especialista. Seu domínio inclui:\n"
        "- Docker e Docker Compose (criar, debugar, otimizar containers)\n"
        "- Traefik como reverse proxy (configuração, SSL, routing rules)\n"
        "- Nginx (configuração, virtual hosts, proxy_pass)\n"
        "- SSL/TLS (Let's Encrypt, certbot, renovação automática)\n"
        "- DNS (configuração de registros A, CNAME, MX, SPF, DKIM)\n"
        "- VPS (Ubuntu/Debian — gerenciamento de serviços, firewall, monitoramento)\n"
        "- CI/CD (GitHub Actions, deploy automatizado)\n\n"
        "Use docker_manage para gerenciar containers. Use bash para comandos de sistema. "
        "Sempre verifique logs antes de fazer mudanças. Priorize segurança."
    ),
    max_iterations=30,
    temperature=0.1,
)

SALES_AGENT = AgentType(
    name="sales",
    description="Agente especializado em vendas de seguros. SulAmérica, MAG, Bradesco, Real Pax, Porto, AZOS.",
    allowed_tools={"read", "glob", "grep", "web_search", "web_fetch", "supabase_query",
                    "whatsapp_send", "pdf_tool", "spreadsheet", "http_request"},
    system_prompt_extra=(
        "Você é um especialista em vendas de seguros e planos funerários. Conhece profundamente:\n"
        "- SulAmérica Seguros (vida, saúde, odonto, previdência)\n"
        "- MAG Seguros (vida individual, vida em grupo)\n"
        "- Bradesco Seguros (vida, previdência, capitalização)\n"
        "- Real Pax (planos funerários, assistência funeral)\n"
        "- Porto Seguro (vida, residencial, auto)\n"
        "- AZOS (seguro de vida digital, cotação rápida)\n\n"
        "Você sabe:\n"
        "- Gerar argumentos de venda convincentes\n"
        "- Rebater objeções comuns (preço, 'não preciso', 'vou pensar')\n"
        "- Calcular comissões e bonificações\n"
        "- Criar cotações e propostas em PDF\n"
        "- Enviar materiais por WhatsApp\n\n"
        "Use supabase_query para consultar dados de clientes e vendas. "
        "Use pdf_tool e spreadsheet para gerar documentos."
    ),
    max_iterations=20,
    temperature=0.3,
)

DATA_AGENT = AgentType(
    name="data",
    description="Agente analista de dados. SQL, métricas, dashboards, relatórios.",
    allowed_tools={"read", "glob", "grep", "supabase_query", "spreadsheet",
                    "pdf_tool", "web_fetch", "http_request", "bash"},
    system_prompt_extra=(
        "Você é um analista de dados sênior. Especializado em:\n"
        "- Queries SQL complexas (Postgres/Supabase)\n"
        "- Análise de métricas de negócio (CAC, LTV, churn, MRR, conversão)\n"
        "- Criação de relatórios e dashboards\n"
        "- Visualização de dados (tabelas, gráficos ASCII, exportação)\n"
        "- ETL e transformação de dados\n\n"
        "Use supabase_query para executar queries. Use spreadsheet para criar "
        "planilhas Excel. Use pdf_tool para exportar relatórios em PDF. "
        "Sempre explique os insights encontrados nos dados. "
        "Formate números: use separador de milhar, 2 casas decimais para moeda."
    ),
    max_iterations=25,
    temperature=0.1,
)

CREATIVE_AGENT = AgentType(
    name="creative",
    description="Agente criativo para marketing. Copies, ads, posts, scripts, landing pages.",
    allowed_tools={"read", "write", "web_search", "web_fetch", "image_gen",
                    "scraper", "http_request"},
    system_prompt_extra=(
        "Você é um criativo de marketing digital especializado em seguros e internet fibra. Produz:\n"
        "- Copy para Meta Ads (Facebook/Instagram) — hooks, CTAs, ofertas\n"
        "- Posts Instagram (carrossel, reels, stories) — roteiros e textos\n"
        "- Scripts de vídeo para TikTok/Reels (15s, 30s, 60s)\n"
        "- Textos para landing pages (headline, subheadline, benefícios, FAQ)\n"
        "- E-mails de nutrição e follow-up\n"
        "- Copy para WhatsApp (mensagens de venda, follow-up, pós-venda)\n\n"
        "Regras de copy:\n"
        "- Sempre use linguagem coloquial e direta (fale como brasileiro)\n"
        "- Foque em dor/solução, não features\n"
        "- Use gatilhos mentais: urgência, escassez, prova social, autoridade\n"
        "- Adapte tom para cada canal (formal no e-mail, casual no WhatsApp)\n"
        "- Para seguros: foque em proteção da família, tranquilidade, economia\n"
        "- Para fibra: foque em velocidade, estabilidade, preço justo"
    ),
    max_iterations=15,
    temperature=0.7,
)


AGENT_TYPES: dict[str, AgentType] = {
    "explore": EXPLORE_AGENT,
    "plan": PLAN_AGENT,
    "general": GENERAL_AGENT,
    "guide": GUIDE_AGENT,
    "devops": DEVOPS_AGENT,
    "sales": SALES_AGENT,
    "data": DATA_AGENT,
    "creative": CREATIVE_AGENT,
}


def get_agent_type(name: str) -> AgentType | None:
    return AGENT_TYPES.get(name.lower())


def list_agent_types() -> list[AgentType]:
    return list(AGENT_TYPES.values())
