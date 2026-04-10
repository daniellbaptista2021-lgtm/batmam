"""Testes do sistema de orquestracao inteligente do Clow."""
import sys
import os

os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} — {detail}")


print("=" * 60)
print("TESTES ORQUESTRACAO INTELIGENTE")
print("=" * 60)

from clow import config
from clow.orchestrator import (
    ModelRouter, ToolSelector, AgentSelector, FallbackTracker,
    orchestrate, MASTER_SYSTEM_PROMPT,
    estimate_context_tokens, should_compress,
)

# ═══════════════════════════════════════════════════════════════
# 1. SYSTEM PROMPT MESTRE
# ═══════════════════════════════════════════════════════════════
print("\n[1/7] System Prompt Mestre")

check("Prompt mestre existe", len(MASTER_SYSTEM_PROMPT) > 100)
check("Contem 'agente autonomo'", "agente autonomo" in MASTER_SYSTEM_PROMPT)
check("Contem 'ferramentas'", "ferramentas" in MASTER_SYSTEM_PROMPT)
check("Contem 'ate 3 vezes'", "ate 3 vezes" in MASTER_SYSTEM_PROMPT)
check("Contem 'Nunca abandone'", "Nunca abandone" in MASTER_SYSTEM_PROMPT)

# Testa injecao no agent
from clow.agent import Agent
agent = Agent(cwd="/tmp", auto_approve=True)
system_msg = agent.session.messages[0]["content"]
check("Prompt mestre injetado no agent", "agente autonomo" in system_msg)
check("Prompt de negocios tambem injetado", "Clow" in system_msg)


# ═══════════════════════════════════════════════════════════════
# 2. MODEL ROUTER — deepseek-chat vs deepseek-reasoner
# ═══════════════════════════════════════════════════════════════
print("\n[2/7] Model Router")

# Deve usar reasoner (keywords)
model, reason = ModelRouter.route("Cria um sistema completo de gestao de clientes")
check("'cria' -> reasoner", model == config.DEEPSEEK_REASONER_MODEL, f"got {model}")
check("reason contem keyword", "keyword" in reason, reason)

model, _ = ModelRouter.route("Desenvolve uma API REST com autenticacao")
check("'desenvolve' -> reasoner", model == config.DEEPSEEK_REASONER_MODEL)

model, _ = ModelRouter.route("Refatora o modulo de billing")
check("'refatora' -> reasoner", model == config.DEEPSEEK_REASONER_MODEL)

model, _ = ModelRouter.route("Debug esse erro no servidor")
check("'debug' -> reasoner", model == config.DEEPSEEK_REASONER_MODEL)

model, _ = ModelRouter.route("Analisa o desempenho do banco de dados")
check("'analisa' -> reasoner", model == config.DEEPSEEK_REASONER_MODEL)

model, _ = ModelRouter.route("Planeja a migracao para microservicos")
check("'planeja' -> reasoner", model == config.DEEPSEEK_REASONER_MODEL)

model, _ = ModelRouter.route("Otimiza as queries SQL lentas")
check("'otimiza' -> reasoner", model == config.DEEPSEEK_REASONER_MODEL)

model, _ = ModelRouter.route("Implemente o checkout com Stripe")
check("'implemente' -> reasoner", model == config.DEEPSEEK_REASONER_MODEL)

# Deve usar reasoner (stack trace)
model, reason = ModelRouter.route("Traceback (most recent call last):\n  File \"app.py\", line 42")
check("Stack trace -> reasoner", model == config.DEEPSEEK_REASONER_MODEL)
check("Reason = complex-error", "error" in reason)

# Deve usar reasoner (multi-step)
model, reason = ModelRouter.route("1. Cria o banco\n2. Configura as tabelas\n3. Insere dados\n4. Testa")
check("Multi-step 4 etapas -> reasoner", model == config.DEEPSEEK_REASONER_MODEL)

# Deve usar reasoner (contexto grande)
big_ctx = [{"role": "user", "content": "x" * 40000}]
model, reason = ModelRouter.route("faz isso", context_messages=big_ctx)
check("Contexto >8K tokens -> reasoner", model == config.DEEPSEEK_REASONER_MODEL)
check("Reason indica large-context", "large-context" in reason)

# Deve usar chat (simples)
model, reason = ModelRouter.route("Oi, tudo bem?")
check("Saudacao -> chat", model == config.CLOW_MODEL, f"got {model}")

model, _ = ModelRouter.route("Qual o status do deploy?")
check("Pergunta simples -> chat", model == config.CLOW_MODEL)

model, _ = ModelRouter.route("Sim, pode continuar")
check("Confirmacao -> chat", model == config.CLOW_MODEL)

model, _ = ModelRouter.route("Obrigado!")
check("Agradecimento -> chat", model == config.CLOW_MODEL)

# Deve usar reasoner (error context flag)
model, _ = ModelRouter.route("corrige pra mim", has_error_context=True)
check("has_error_context -> reasoner", model == config.DEEPSEEK_REASONER_MODEL)


# ═══════════════════════════════════════════════════════════════
# 3. TOOL SELECTOR
# ═══════════════════════════════════════════════════════════════
print("\n[3/7] Tool Selector")

domains = ToolSelector.detect_domains("Cria um arquivo HTML com o formulario")
check("'arquivo HTML' -> file domain", "file" in domains, str(domains))

domains = ToolSelector.detect_domains("Integra com a API do Stripe via webhook")
check("'API webhook' -> api domain", "api" in domains, str(domains))

domains = ToolSelector.detect_domains("Consulta os dados no Supabase")
check("'dados Supabase' -> database", "database" in domains, str(domains))

domains = ToolSelector.detect_domains("Envia mensagem no WhatsApp")
check("'WhatsApp' -> whatsapp", "whatsapp" in domains, str(domains))

domains = ToolSelector.detect_domains("Faz scraping do site concorrente")
check("'scraping' -> browser", "browser" in domains, str(domains))

tools = ToolSelector.get_relevant_tools("Edita o arquivo config.py")
check("'edita arquivo' inclui edit", "edit" in tools, str(tools))

domains = ToolSelector.detect_domains("Oi, como vai?")
check("Saudacao -> sem dominio", len(domains) == 0, str(domains))


# ═══════════════════════════════════════════════════════════════
# 4. AGENT SELECTOR
# ═══════════════════════════════════════════════════════════════
print("\n[4/7] Agent Selector")

agent = AgentSelector.detect("Preciso debugar esse bug no codigo Python")
check("Bug/debug -> code agent", agent == "code", str(agent))

agent = AgentSelector.detect("Cria uma planilha de controle com graficos")
check("Planilha/graficos -> data agent", agent == "data", str(agent))

agent = AgentSelector.detect("Cria um anuncio pra campanha no Instagram")
check("Anuncio/Instagram -> marketing", agent == "marketing", str(agent))

agent = AgentSelector.detect("Configura o workflow no n8n com webhook")
check("n8n/workflow -> automation", agent == "automation", str(agent))

agent = AgentSelector.detect("Organiza os leads no Chatwoot por etiqueta")
check("Leads/Chatwoot -> crm", agent == "crm", str(agent))

agent = AgentSelector.detect("Oi, tudo bem?")
check("Saudacao -> nenhum agente", agent is None, str(agent))

ctx = AgentSelector.get_context_prefix("code")
check("Contexto code tem descricao", "codigo" in ctx.lower() or "debug" in ctx.lower(), ctx)


# ═══════════════════════════════════════════════════════════════
# 5. FALLBACK TRACKER
# ═══════════════════════════════════════════════════════════════
print("\n[5/7] Fallback Tracker")

ft = FallbackTracker()

check("Resposta vazia -> fallback", ft.should_fallback("", config.CLOW_MODEL))
check("Resposta curta -> fallback", ft.should_fallback("ok", config.CLOW_MODEL))
check("'nao consigo' -> fallback", ft.should_fallback("Desculpe, nao consigo fazer isso.", config.CLOW_MODEL))
check("Tool errors -> fallback", ft.should_fallback("resultado parcial", config.CLOW_MODEL, had_tool_errors=True))
check("Resposta boa -> sem fallback", not ft.should_fallback("Aqui esta o resultado completo da analise com todos os detalhes necessarios.", config.CLOW_MODEL))
check("Ja no reasoner -> sem fallback", not ft.should_fallback("", config.DEEPSEEK_REASONER_MODEL))

ft.log_fallback("test-reason", config.CLOW_MODEL, "test-session")
check("Log registrado", len(ft.recent_fallbacks) == 1)
check("Log tem reason", ft.recent_fallbacks[0]["reason"] == "test-reason")


# ═══════════════════════════════════════════════════════════════
# 6. CONTEXT COMPRESSION
# ═══════════════════════════════════════════════════════════════
print("\n[6/7] Context Compression")

small_msgs = [{"role": "user", "content": "oi"}]
check("Contexto pequeno -> sem compressao", not should_compress(small_msgs))

big_msgs = [{"role": "user", "content": "x" * 400_000}]
check("Contexto >80K tokens -> compressao", should_compress(big_msgs))

tokens = estimate_context_tokens([{"role": "user", "content": "a" * 4000}])
check("Estimativa ~1000 tokens", 900 <= tokens <= 1100, f"got {tokens}")


# ═══════════════════════════════════════════════════════════════
# 7. ORCHESTRATE (integracao completa)
# ═══════════════════════════════════════════════════════════════
print("\n[7/7] Orchestrate (integracao)")

result = orchestrate("Cria um sistema de CRM completo para gestao de leads e clientes no Chatwoot")
check("Orchestrate retorna model", "model" in result)
check("Orchestrate retorna reason", "model_reason" in result)
check("Task complexa -> reasoner", result["model"] == config.DEEPSEEK_REASONER_MODEL, result["model"])
check("Detecta agente crm", result["agent"] == "crm", str(result["agent"]))
check("Retorna tool_domains", "tool_domains" in result)
check("Retorna needs_compression", "needs_compression" in result)
check("Retorna estimated_tokens", "estimated_tokens" in result)

result2 = orchestrate("Oi, como vai?")
check("Task simples -> chat", result2["model"] == config.CLOW_MODEL, result2["model"])
check("Sem agente para saudacao", result2["agent"] is None)

result3 = orchestrate("Edita o arquivo main.py e envia no WhatsApp")
check("Multi-domain detectado", len(result3["tool_domains"]) >= 2, str(result3["tool_domains"]))


# ═══════════════════════════════════════════════════════════════
# RESULTADO
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
total = PASS + FAIL
print(f"RESULTADO: {PASS}/{total} passed, {FAIL} failed")
if FAIL:
    print("STATUS: FALHAS ENCONTRADAS")
    sys.exit(1)
else:
    print("STATUS: TODOS OS TESTES PASSARAM")
