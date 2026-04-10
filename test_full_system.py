"""Teste completo do sistema Clow — tools, agentes, orquestracao."""
import sys, os
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

PASS = FAIL = 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  OK  {name}")
    else: FAIL += 1; print(f"  FAIL {name} — {detail}")

print("=" * 60)
print("TESTE COMPLETO DO SISTEMA CLOW")
print("=" * 60)

# ── 1. TOOL REGISTRY ──
print("\n[1/5] Tool Registry (65 tools)")
from clow.tools.base import create_default_registry
reg = create_default_registry()
names = set(reg.names())
total = len(names)
check(f"Total >= 65 tools", total >= 65, f"got {total}")

# Core
for t in ["bash", "read", "write", "edit", "glob", "grep", "agent", "web_search", "web_fetch"]:
    check(f"Core: {t}", t in names)

# Task
for t in ["task_create", "task_update", "task_list", "task_get"]:
    check(f"Task: {t}", t in names)

# SSH/VPS
for t in ["ssh_connect", "manage_process", "configure_nginx", "manage_ssl",
          "monitor_resources", "manage_cron", "backup_create"]:
    check(f"VPS: {t}", t in names)

# Git
check("Git: git_ops", "git_ops" in names)
check("Git: git_advanced", "git_advanced" in names)

# Database
for t in ["query_postgres", "query_mysql", "query_redis", "manage_migrations", "supabase_query"]:
    check(f"DB: {t}", t in names)

# Deploy
check("Deploy: deploy_vercel", "deploy_vercel" in names)
check("Deploy: deploy_vps", "deploy_vps" in names)

# Meta Ads
check("Meta Ads: meta_ads", "meta_ads" in names)

# WhatsApp
wa_tools = [n for n in names if n.startswith("whatsapp_")]
check(f"WhatsApp: {len(wa_tools)} tools", len(wa_tools) >= 9, str(len(wa_tools)))

# Chatwoot
cw_tools = [n for n in names if n.startswith("chatwoot_")]
check(f"Chatwoot: {len(cw_tools)} tools", len(cw_tools) >= 15, str(len(cw_tools)))

# Documents
for t in ["pdf_tool", "spreadsheet", "image_gen"]:
    check(f"Doc: {t}", t in names)

# ── 2. AGENT TYPES ──
print(f"\n[2/5] Agent Types (14 agentes)")
from clow.agent_types import AGENT_TYPES, get_agent_type
check(f"Total >= 14 tipos", len(AGENT_TYPES) >= 14, str(len(AGENT_TYPES)))

expected_agents = ["explore", "plan", "general", "guide", "devops", "sales",
                   "data", "creative", "fullstack", "automation", "design",
                   "marketing", "bot", "crm"]
for a in expected_agents:
    at = get_agent_type(a)
    check(f"Agent: {a}", at is not None)

# Verifica tools dos agentes especializados
bot_agent = get_agent_type("bot")
check("Bot agent tem whatsapp tools", "whatsapp_create_instance" in bot_agent.allowed_tools)

crm_agent = get_agent_type("crm")
check("CRM agent tem chatwoot tools", "chatwoot_setup" in crm_agent.allowed_tools)
check("CRM agent tem ssh_connect", "ssh_connect" in crm_agent.allowed_tools)

marketing_agent = get_agent_type("marketing")
check("Marketing agent tem meta_ads", "meta_ads" in marketing_agent.allowed_tools)

fullstack_agent = get_agent_type("fullstack")
check("Fullstack agent tem all tools", fullstack_agent.allowed_tools is None)

# ── 3. ORCHESTRATOR ──
print(f"\n[3/5] Orchestrator")
from clow.orchestrator import orchestrate, ModelRouter, ToolSelector, AgentSelector
from clow import config

# Model routing
model, _ = ModelRouter.route("Cria um site completo para pizzaria")
check("Site complexo -> reasoner", model == config.DEEPSEEK_REASONER_MODEL)

model, _ = ModelRouter.route("Qual o status?")
check("Pergunta simples -> chat", model == config.CLOW_MODEL)

# Tool domains
domains = ToolSelector.detect_domains("Deploy o app no servidor VPS com Nginx e SSL")
check("VPS domain detectado", "vps" in domains, str(domains))
check("Deploy domain detectado", "deploy" in domains, str(domains))

domains = ToolSelector.detect_domains("Cria campanha no Meta Ads")
check("Meta Ads domain detectado", "meta_ads" in domains, str(domains))

domains = ToolSelector.detect_domains("Faz backup do banco postgres e commit no git")
check("Database + git detectados", "database" in domains and "git" in domains, str(domains))

# Agent selection
agent = AgentSelector.detect("Configura o servidor VPS com Docker e Nginx")
check("VPS task -> devops agent", agent == "devops", str(agent))

agent = AgentSelector.detect("Cria um bot WhatsApp para pizzaria")
check("Bot WhatsApp -> bot agent", agent == "bot", str(agent))

agent = AgentSelector.detect("Deploy o app React na Vercel")
check("Deploy React -> fullstack", agent == "fullstack", str(agent))

agent = AgentSelector.detect("Cria campanha de trafego pago no Meta Ads")
check("Meta Ads -> marketing", agent == "marketing", str(agent))

# Full orchestration
result = orchestrate("Cria e configura Chatwoot na VPS do cliente com Docker, Nginx e SSL")
check("Orchestrate: model -> reasoner", result["model"] == config.DEEPSEEK_REASONER_MODEL)
check("Orchestrate: agent detectado", result["agent"] is not None, str(result["agent"]))
check("Orchestrate: tool_domains", len(result["tool_domains"]) > 0)

# ── 4. AGENT INIT ──
print(f"\n[4/5] Agent Init")
from clow.agent import Agent
agent = Agent(cwd="/tmp", auto_approve=True)
check("Agent criado", agent is not None)
check("Agent tem 65+ tools", len(agent.registry.names()) >= 65, str(len(agent.registry.names())))
check("System prompt tem master prompt", "agente autonomo" in agent.session.messages[0]["content"])
check("FallbackTracker ativo", hasattr(agent, "_fallback"))

# ── 5. TOOL SCHEMAS ──
print(f"\n[5/5] Tool Schemas (validacao)")
errors = []
for tool in reg.all_tools():
    try:
        schema = tool.get_schema()
        oai = tool.to_openai_tool()
        assert isinstance(schema, dict), f"{tool.name}: schema nao e dict"
        assert "type" in schema, f"{tool.name}: schema sem 'type'"
        assert oai["function"]["name"] == tool.name, f"{tool.name}: nome inconsistente"
    except Exception as e:
        errors.append(f"{tool.name}: {e}")
check(f"Todos os schemas validos", len(errors) == 0, "; ".join(errors[:3]))

# ═══ RESULTADO ═══
print("\n" + "=" * 60)
total = PASS + FAIL
print(f"RESULTADO: {PASS}/{total} passed, {FAIL} failed")
print(f"TOOLS: {len(reg.names())} | AGENTS: {len(AGENT_TYPES)}")
if FAIL:
    print("STATUS: FALHAS ENCONTRADAS")
    sys.exit(1)
else:
    print("STATUS: TODOS OS TESTES PASSARAM")
