"""Orchestrator — roteamento inteligente de modelos, tools e agentes no Clow.

Decide automaticamente:
- Se a mensagem e conversacional (sem tools, sem reasoner)
- Qual modelo usar (deepseek-chat vs deepseek-reasoner)
- Quais tools sao relevantes para a task
- Se precisa ativar um agente especializado
- Quando fazer fallback de chat -> reasoner
"""

from __future__ import annotations
import re
import time
from typing import Any
from .logging import log_action
from . import config


# ═══════════════════════════════════════════════════════════════
# SYSTEM PROMPT MESTRE — injetado em todas as chamadas
# ═══════════════════════════════════════════════════════════════

MASTER_SYSTEM_PROMPT = """Voce e um agente de terminal que EXECUTA tarefas. Voce NAO e um chatbot.

REGRA #1 — EXECUTE, NAO PERGUNTE:
- Quando o usuario pedir algo, FACA IMEDIATAMENTE usando suas ferramentas.
- NAO fique fazendo perguntas desnecessarias. Use as informacoes que voce ja tem.
- NAO explique o que voce VAI fazer. FACA e depois mostre o resultado.
- Se faltar alguma informacao CRITICA (ex: credencial), pergunte UMA VEZ so.
- NUNCA faca mais de 1 pergunta por turno.

REGRA #2 — COMPLETE A TAREFA:
- Quando pedirem um site/landing page: CRIE os arquivos HTML/CSS/JS completos.
- Quando pedirem um funil: CRIE todos os arquivos e faca deploy.
- Quando pedirem um relatorio: GERE o relatorio com dados reais.
- NAO diga "foi concluido" sem ter REALMENTE criado/entregue os arquivos.
- Inclua SEMPRE o link do resultado final.

REGRA #3 — USO DE FERRAMENTAS:
- Use ferramentas para EXECUTAR, nao para explorar sem rumo.
- Se uma ferramenta falhar 2 vezes: PARE, repense, tente diferente.
- NUNCA chame a mesma ferramenta com os mesmos parametros mais de 1 vez.
- Para saudacoes e perguntas simples: responda DIRETO em texto, sem ferramentas.

REGRA #4 — RESPOSTA FINAL:
- Apos executar ferramentas, de um resumo CURTO do que foi feito.
- Inclua links em formato markdown quando gerar arquivos.
- Se algo falhou, diga O QUE falhou e O QUE voce ja tentou.

REGRA #5 — FOCO:
- Mantenha foco na tarefa ate concluir.
- NAO mude de assunto, NAO faca sugestoes nao solicitadas.
- NAO repita informacoes que o usuario ja sabe."""


# ═══════════════════════════════════════════════════════════════
# CONVERSATIONAL DETECTOR — identifica msgs que NAO precisam de tools
# ═══════════════════════════════════════════════════════════════

CONVERSATIONAL_PATTERNS = re.compile(
    r"^(?:"
    r"(?:oi|ola|ol[aá]|hey|hi|hello|e\s*a[ií]|fala|bom\s*dia|boa\s*(?:tarde|noite)|"
    r"tudo\s*(?:bem|bom|certo|tranquilo)|como\s*(?:vai|esta|ta|vc\s*ta))"
    r"|"
    r"(?:obrigad[oa]|obg|valeu|vlw|tmj|thanks|thank\s*you|"
    r"muito\s*obrigad[oa]|brigadao|brigad[oa]|agradeco|grat[oa])"
    r"|"
    r"(?:ok|okay|certo|entendi|entendido|beleza|blz|pode\s*ser|"
    r"fechou|combinado|perfeito|massa|top|show|dahora|"
    r"sim|nao|s|n|uhum|aham)"
    r"|"
    r"(?:ficou\s*(?:otimo|bom|lindo|perfeito|massa|show|incrivel|top)|"
    r"gostei|adorei|amei|mandou\s*bem|parabens|excelente|sensacional|"
    r"era\s*isso|isso\s*(?:mesmo|ai|a[ií])|muito\s*bom|arrasou)"
    r"|"
    r"(?:tchau|bye|ate\s*(?:mais|logo|amanha)|falou|flw|fui|"
    r"boa\s*noite|bom\s*descanso)"
    r")[\s!.?]*$",
    re.IGNORECASE,
)

SIMPLE_QUESTION_PATTERNS = re.compile(
    r"^(?:"
    r"(?:o\s*que\s*(?:e|eh|é)|como\s*funciona|me\s*explica|"
    r"qual\s*(?:a\s*diferenca|o\s*melhor)|pra\s*que\s*serve|"
    r"quanto\s*custa|quais?\s*(?:sao|são)|por\s*que|"
    r"voce\s*(?:pode|consegue|sabe)|da\s*pra|pode\s*me\s*(?:dizer|falar))"
    r")\s",
    re.IGNORECASE,
)


def is_conversational(message: str) -> bool:
    """Detecta se a mensagem e puramente conversacional (sem necessidade de tools)."""
    msg = message.strip()
    if len(msg) > 200:
        return False
    if CONVERSATIONAL_PATTERNS.match(msg):
        return True
    if len(msg) < 30 and not any(w in msg.lower() for w in [
        "cria", "gera", "faz", "faca", "busca", "mostra",
        "configura", "instala", "deploy", "executa", "roda", "abre",
        "envia", "manda", "deleta", "remove", "atualiza",
    ]):
        return True
    return False


def is_simple_question(message: str) -> bool:
    """Detecta perguntas simples que so precisam de resposta em texto."""
    msg = message.strip()
    if len(msg) > 500:
        return False
    if SIMPLE_QUESTION_PATTERNS.match(msg):
        tech_triggers = [
            "servidor", "banco", "deploy", "whatsapp", "z-api",
            "campanha", "meta ads", "planilha", "landing",
        ]
        if any(t in msg.lower() for t in tech_triggers):
            return False
        return True
    return False


# ═══════════════════════════════════════════════════════════════
# MODEL ROUTER — decide deepseek-chat vs deepseek-reasoner
# ═══════════════════════════════════════════════════════════════

REASONER_TRIGGERS = re.compile(
    r"\b(?:"
    r"(?:cria|crie|desenvolv[aeo]|implement[aeo]|constro[ia])\s+(?:um|uma|o|a)\s+\w+.*"
    r"(?:complet[oa]|do\s+zero|sistema|plataforma|projeto|aplicat)|"
    r"(?:debug|depu[gr]|diagnostica|investiga)\s+|"
    r"(?:refator[aeo]|reescrev|redesign|migra[cgr])\s+|"
    r"(?:planeja|planej[ea]|arquitetur[ao])\s+|"
    r"(?:passo\s+a\s+passo|etapa\s+por\s+etapa|step\s+by\s+step)|"
    r"(?:otimiz[aeo]|melhora|melhore)\s+(?:a\s+performance|o\s+codigo|a\s+arquitetura)"
    r")\b",
    re.IGNORECASE,
)

COMPLEX_ERROR_PATTERN = re.compile(
    r"(?:Traceback|traceback|Error:|ERRO:|Exception|"
    r"at\s+\w+\.\w+\(|File\s+\"[^\"]+\",\s+line\s+\d+|"
    r"panic:|fatal:|FATAL)",
    re.IGNORECASE,
)

CONTEXT_TOKEN_THRESHOLD = 8000
CONTEXT_CHAR_THRESHOLD = CONTEXT_TOKEN_THRESHOLD * 4


class ModelRouter:
    """Decide qual modelo usar baseado na analise da task."""

    @staticmethod
    def route(
        user_message: str,
        context_messages: list[dict] | None = None,
        has_error_context: bool = False,
    ) -> tuple[str, str]:
        if not isinstance(user_message, str):
            return config.CLOW_MODEL, "non-text"

        msg = user_message.strip()

        if is_conversational(msg) or is_simple_question(msg):
            return config.CLOW_MODEL, "conversational"

        if has_error_context or COMPLEX_ERROR_PATTERN.search(msg):
            return config.DEEPSEEK_REASONER_MODEL, "complex-error"

        if REASONER_TRIGGERS.search(msg):
            return config.DEEPSEEK_REASONER_MODEL, "complex-task"

        context_chars = sum(
            len(m.get("content", "") if isinstance(m.get("content"), str) else "")
            for m in (context_messages or [])
        )
        if context_chars > CONTEXT_CHAR_THRESHOLD:
            return config.DEEPSEEK_REASONER_MODEL, "large-context"

        if len(msg) > 2000:
            return config.DEEPSEEK_REASONER_MODEL, "long-message"

        return config.CLOW_MODEL, "default"


# ═══════════════════════════════════════════════════════════════
# TOOL SELECTOR
# ═══════════════════════════════════════════════════════════════

TOOL_DOMAIN_MAP = {
    "file": {
        "tools": {"read", "write", "edit", "glob", "grep"},
        "triggers": re.compile(
            r"\b(?:cri[ae]|edit[ae]|modific|escrev|salv|arqu[iy]v|"
            r"pasta|diretori|codigo|script|html|css|json|yaml)\b",
            re.IGNORECASE,
        ),
    },
    "api": {
        "tools": {"http_request", "web_fetch", "web_search"},
        "triggers": re.compile(
            r"\b(?:api|endpoint|webhook|http|request|fetch|"
            r"integracao|integrar|rest|graphql|curl)\b",
            re.IGNORECASE,
        ),
    },
    "database": {
        "tools": {"supabase_query", "query_postgres", "query_mysql", "query_redis", "manage_migrations"},
        "triggers": re.compile(
            r"\b(?:banco|database|sql|query|tabela|supabase|"
            r"dados|consulta|insert|select|update|delete|postgres|mysql|redis|migration)\b",
            re.IGNORECASE,
        ),
    },
    "whatsapp": {
        "tools": {"whatsapp_send", "whatsapp_create_instance", "whatsapp_save_prompt",
                   "whatsapp_setup_webhook", "whatsapp_full_test"},
        "triggers": re.compile(
            r"\b(?:whatsapp|zap|mensagem|enviar\s+msg|bot|"
            r"atendimento|z-?api)\b",
            re.IGNORECASE,
        ),
    },
    "browser": {
        "tools": {"scraper", "web_fetch"},
        "triggers": re.compile(
            r"\b(?:scraping|scrape|crawler|browser|navegador|"
            r"captura|screenshot|pagina\s+web)\b",
            re.IGNORECASE,
        ),
    },
    "vps": {
        "tools": {"ssh_connect", "manage_process", "configure_nginx", "manage_ssl",
                   "monitor_resources", "manage_cron", "backup_create"},
        "triggers": re.compile(
            r"\b(?:vps|servidor|ssh|nginx|ssl|certbot|cron|backup|"
            r"monitorar|cpu|ram|disco|processo|servico|systemctl)\b",
            re.IGNORECASE,
        ),
    },
    "git": {
        "tools": {"git_ops", "git_advanced"},
        "triggers": re.compile(
            r"\b(?:git|commit|push|pull|branch|merge|clone|deploy|"
            r"repositorio|repo)\b",
            re.IGNORECASE,
        ),
    },
    "deploy": {
        "tools": {"deploy_vercel", "deploy_vps"},
        "triggers": re.compile(
            r"\b(?:deploy|publicar|subir|vercel|producao|staging)\b",
            re.IGNORECASE,
        ),
    },
    "meta_ads": {
        "tools": {"meta_ads"},
        "triggers": re.compile(
            r"\b(?:meta\s*ads|facebook\s*ads|instagram\s*ads|campanha|"
            r"anuncio|pixel|ad\s*set|criativo|trafego\s+pago)\b",
            re.IGNORECASE,
        ),
    },
    "crm": {
        "tools": {"chatwoot_setup", "chatwoot_list_conversations", "chatwoot_search_contact",
                   "chatwoot_create_contact", "chatwoot_report"},
        "triggers": re.compile(
            r"\b(?:crm|chatwoot|lead|cliente|contato|inbox|funil)\b",
            re.IGNORECASE,
        ),
    },
    "documents": {
        "tools": {"pdf_tool", "spreadsheet", "design_generate", "image_gen"},
        "triggers": re.compile(
            r"\b(?:planilha|pdf|documento|apresenta|pptx|docx|xlsx|"
            r"relatorio|export|banner|imagem|design|foto|gerar?\s+imagem|dall-?e|logo)\b",
            re.IGNORECASE,
        ),
    },
}


class ToolSelector:
    @staticmethod
    def detect_domains(user_message: str) -> list[str]:
        if not isinstance(user_message, str):
            return []
        domains = []
        for domain, info in TOOL_DOMAIN_MAP.items():
            if info["triggers"].search(user_message):
                domains.append(domain)
        return domains

    @staticmethod
    def get_relevant_tools(user_message: str) -> set[str]:
        domains = ToolSelector.detect_domains(user_message)
        tools: set[str] = set()
        for domain in domains:
            tools.update(TOOL_DOMAIN_MAP[domain]["tools"])
        return tools


# ═══════════════════════════════════════════════════════════════
# AGENT SELECTOR
# ═══════════════════════════════════════════════════════════════

AGENT_SPECIALIZATIONS = {
    "fullstack": {
        "description": "Desenvolvimento full-stack: sites, apps, APIs, deploy",
        "triggers": re.compile(
            r"\b(?:site|app|sistema|api\s+rest|frontend|backend|react|next\.?js|"
            r"node|fastapi|laravel|full.?stack|deploy|vercel)\b", re.IGNORECASE),
    },
    "devops": {
        "description": "Infraestrutura: VPS, Docker, Nginx, SSL, DNS, servidor",
        "triggers": re.compile(
            r"\b(?:server|servidor|vps|docker|nginx|traefik|ssl|certbot|"
            r"dns|firewall|ssh|infraestrutura|devops|compose|systemctl)\b", re.IGNORECASE),
    },
    "bot": {
        "description": "Bots WhatsApp: criacao, configuracao, Z-API, fluxos",
        "triggers": re.compile(
            r"\b(?:bot|chatbot|whatsapp|z.?api|atendente\s+virtual|"
            r"atendimento\s+automat|robo|assistente\s+virtual)\b", re.IGNORECASE),
    },
    "automation": {
        "description": "n8n, fluxos, webhooks e automacoes",
        "triggers": re.compile(
            r"\b(?:n8n|automac|fluxo|workflow|webhook|"
            r"trigger|cron|agend|schedul|zapier|integromat)\b", re.IGNORECASE),
    },
    "design": {
        "description": "Design digital: imagens, banners, logos, landing pages visuais",
        "triggers": re.compile(
            r"\b(?:design|banner|logo|criativo|layout|"
            r"mockup|thumbnail|visual|identidade\s+visual|ui|ux)\b", re.IGNORECASE),
    },
    "marketing": {
        "description": "Meta Ads, criativos, copy, campanhas, metricas",
        "triggers": re.compile(
            r"\b(?:anuncio|ads?|meta\s+ads|facebook\s+ads|instagram\s+ads|"
            r"campanha|pixel|capi|trafego\s+pago|gestao\s+de\s+trafego|"
            r"remarketing|publico|audience|roas|cpc|cpm)\b", re.IGNORECASE),
    },
    "data": {
        "description": "Planilhas, analises de dados, SQL, relatorios",
        "triggers": re.compile(
            r"\b(?:planilha|excel|xlsx|csv|dados|data|analise|sql|query|"
            r"relatorio|grafico|chart|metricas|kpi|dashboard|banco\s+de\s+dados)\b", re.IGNORECASE),
    },
    "crm": {
        "description": "Chatwoot, leads, clientes, funil e atendimento",
        "triggers": re.compile(
            r"\b(?:crm|chatwoot|lead|prospect|"
            r"funil|pipeline|inbox|ticket|"
            r"contato|followup|follow.up|gestao\s+de\s+clientes)\b", re.IGNORECASE),
    },
    "code": {
        "description": "Desenvolvimento, debug e refatoracao de codigo puro",
        "triggers": re.compile(
            r"\b(?:codigo|code|bug|debug|refator|function|classe|"
            r"import|compilar|build|test|lint|typescript|python|"
            r"javascript)\b", re.IGNORECASE),
    },
}


class AgentSelector:
    @staticmethod
    def detect(user_message: str) -> str | None:
        if not isinstance(user_message, str):
            return None
        if is_conversational(user_message):
            return None
        scores: dict[str, int] = {}
        for agent_name, info in AGENT_SPECIALIZATIONS.items():
            matches = info["triggers"].findall(user_message)
            if matches:
                scores[agent_name] = len(matches)
        if not scores:
            return None
        return max(scores, key=scores.get)

    @staticmethod
    def get_context_prefix(agent_name: str) -> str:
        info = AGENT_SPECIALIZATIONS.get(agent_name)
        if not info:
            return ""
        return f"\n[Agente ativo: {agent_name}] {info['description']}.\nFoque sua resposta nesta area de especialidade.\n"


# ═══════════════════════════════════════════════════════════════
# FALLBACK TRACKER
# ═══════════════════════════════════════════════════════════════

class FallbackTracker:
    INSUFFICIENT_PATTERNS = re.compile(
        r"(?:nao\s+(?:consigo|posso|sei)|"
        r"desculpe.*(?:nao|n\xe3o)|"
        r"infelizmente|"
        r"alem\s+d[ao]\s+(?:meu|minha)\s+(?:capacidade|alcance)|"
        r"nao\s+tenho\s+(?:acesso|informacao))",
        re.IGNORECASE,
    )

    def __init__(self):
        self._fallback_log: list[dict] = []

    def should_fallback(self, response_text: str, current_model: str,
                        had_tool_errors: bool = False, was_conversational: bool = False) -> bool:
        if current_model == config.DEEPSEEK_REASONER_MODEL:
            return False
        if was_conversational:
            return False
        if not response_text or len(response_text.strip()) < 20:
            return True
        if self.INSUFFICIENT_PATTERNS.search(response_text):
            return True
        if had_tool_errors:
            return True
        return False

    def log_fallback(self, reason: str, original_model: str, session_id: str = ""):
        entry = {"timestamp": time.time(), "reason": reason,
                 "from_model": original_model, "to_model": config.DEEPSEEK_REASONER_MODEL}
        self._fallback_log.append(entry)
        if len(self._fallback_log) > 100:
            self._fallback_log = self._fallback_log[-100:]
        log_action("model_fallback",
                   f"{original_model}->{config.DEEPSEEK_REASONER_MODEL} reason={reason}",
                   session_id=session_id)

    @property
    def recent_fallbacks(self) -> list[dict]:
        return self._fallback_log[-10:]


# ═══════════════════════════════════════════════════════════════
# CONTEXT COMPRESSOR
# ═══════════════════════════════════════════════════════════════

COMPRESS_CHAR_THRESHOLD = 320_000


def estimate_context_tokens(messages: list[dict]) -> int:
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total_chars += len(block.get("text", ""))
    return total_chars // 4


def should_compress(messages: list[dict]) -> bool:
    total_chars = sum(
        len(m.get("content", "")) if isinstance(m.get("content"), str) else 0
        for m in messages
    )
    return total_chars > COMPRESS_CHAR_THRESHOLD


# ═══════════════════════════════════════════════════════════════
# ORCHESTRATE — funcao principal
# ═══════════════════════════════════════════════════════════════

def orchestrate(
    user_message: str,
    context_messages: list[dict] | None = None,
    has_error_context: bool = False,
    session_id: str = "",
) -> dict[str, Any]:
    conversational = False
    needs_tools = True

    if isinstance(user_message, str):
        if is_conversational(user_message):
            conversational = True
            needs_tools = False
        elif is_simple_question(user_message):
            conversational = True
            needs_tools = False

    model, model_reason = ModelRouter.route(user_message, context_messages, has_error_context)

    agent = None
    agent_context = ""
    if not conversational:
        agent = AgentSelector.detect(user_message)
        agent_context = AgentSelector.get_context_prefix(agent) if agent else ""

    tool_domains = []
    relevant_tools = set()
    if not conversational:
        tool_domains = ToolSelector.detect_domains(user_message)
        relevant_tools = ToolSelector.get_relevant_tools(user_message)
        needs_tools = True

    msgs = context_messages or []
    est_tokens = estimate_context_tokens(msgs)
    needs_compress = should_compress(msgs)

    log_action(
        "orchestrate",
        f"model={model} reason={model_reason} conv={conversational} "
        f"agent={agent} domains={tool_domains} tools={needs_tools} "
        f"tokens~{est_tokens} compress={needs_compress}",
        session_id=session_id,
    )

    return {
        "model": model,
        "model_reason": model_reason,
        "is_conversational": conversational,
        "agent": agent,
        "agent_context": agent_context,
        "tool_domains": tool_domains,
        "relevant_tools": relevant_tools,
        "needs_tools": needs_tools,
        "needs_compression": needs_compress,
        "estimated_tokens": est_tokens,
    }
