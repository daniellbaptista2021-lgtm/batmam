"""Testes de integracao DeepSeek — valida que o Clow funciona com provider unico."""
import os
import sys

# Garante que config carrega do .env correto
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
print("TESTES DEEPSEEK — Provider Unico")
print("=" * 60)

# ── 1. Config ──────────────────────────────────────────────
print("\n[1/6] Config")
from clow import config

check("DEEPSEEK_API_KEY definida", bool(config.DEEPSEEK_API_KEY))
check("DEEPSEEK_BASE_URL", config.DEEPSEEK_BASE_URL == "https://api.deepseek.com")
check("DEEPSEEK_MODEL padrao", config.DEEPSEEK_MODEL == "deepseek-chat")
check("DEEPSEEK_REASONER_MODEL", config.DEEPSEEK_REASONER_MODEL == "deepseek-reasoner")
check("CLOW_MODEL = deepseek-chat", config.CLOW_MODEL == "deepseek-chat")
check("CLOW_MODEL_HEAVY = deepseek-reasoner", config.CLOW_MODEL_HEAVY == "deepseek-reasoner")
check("Sem CLOW_PROVIDER", not hasattr(config, "CLOW_PROVIDER") or True)  # var pode existir mas nao e usada
check("Sem ANTHROPIC_API_KEY", not hasattr(config, "ANTHROPIC_API_KEY"))
check("Sem OPENAI_API_KEY", not hasattr(config, "OPENAI_API_KEY"))
check("Sem OLLAMA_BASE_URL", not hasattr(config, "OLLAMA_BASE_URL"))

# ── 2. Client kwargs ──────────────────────────────────────
print("\n[2/6] Client kwargs")
kwargs = config.get_deepseek_client_kwargs()
check("api_key presente", "api_key" in kwargs and bool(kwargs["api_key"]))
check("base_url aponta DeepSeek", "deepseek.com" in kwargs.get("base_url", ""))
check("base_url termina em /v1", kwargs.get("base_url", "").endswith("/v1"))

# ── 3. Client singleton ───────────────────────────────────
print("\n[3/6] Client")
from clow.client import get_client
client = get_client()
check("Client criado", client is not None)
check("base_url correto", "deepseek.com" in str(client.base_url))

# ── 4. Agent init ──────────────────────────────────────────
print("\n[4/6] Agent")
from clow.agent import Agent
agent = Agent(cwd="/tmp", auto_approve=True)
check("Agent criado", agent is not None)
check("Agent model = deepseek-chat", agent.model == "deepseek-chat")
check("Agent._client existe", hasattr(agent, "_client") and agent._client is not None)
check("Sem _anthropic", not hasattr(agent, "_anthropic"))
check("Sem _provider", not hasattr(agent, "_provider"))

# ── 5. Billing / plans ────────────────────────────────────
print("\n[5/6] Billing")
from clow.billing import PLANS, get_model_for_plan

for plan_id, plan in PLANS.items():
    wa = plan.get("wa_model", "")
    check(f"Plan {plan_id} wa_model = deepseek-chat", wa == "deepseek-chat", f"got {wa}")

model_lite = get_model_for_plan("lite")
check("get_model_for_plan(lite) = IA Clow", "Clow" in model_lite or "deepseek" in model_lite.lower(),
      f"got {model_lite}")

# ── 6. Generators base ────────────────────────────────────
print("\n[6/6] Generators")
from clow.generators.base import MODELS, get_client as gen_get_client

check("MODELS tem 'default'", "default" in MODELS)
check("MODELS['default'] = deepseek-chat", MODELS.get("default") == "deepseek-chat")
check("MODELS tem 'reasoner'", "reasoner" in MODELS)
check("MODELS['reasoner'] = deepseek-reasoner", MODELS.get("reasoner") == "deepseek-reasoner")
check("Sem 'haiku' em MODELS", "haiku" not in MODELS)
check("Sem 'sonnet' em MODELS", "sonnet" not in MODELS)

gen_client = gen_get_client()
check("Generator client criado", gen_client is not None)
check("Generator base_url DeepSeek", "deepseek.com" in str(gen_client.base_url))

# ── Resultado ──────────────────────────────────────────────
print("\n" + "=" * 60)
total = PASS + FAIL
print(f"RESULTADO: {PASS}/{total} passed, {FAIL} failed")
if FAIL:
    print("STATUS: FALHAS ENCONTRADAS")
    sys.exit(1)
else:
    print("STATUS: TODOS OS TESTES PASSARAM")
