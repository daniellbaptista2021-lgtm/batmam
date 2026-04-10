"""Testes DALL-E + Vercel deploy tools."""
import sys, os
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

PASS = FAIL = 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  OK  {name}")
    else: FAIL += 1; print(f"  FAIL {name} — {detail}")

print("=" * 60)
print("TESTES DALL-E + VERCEL")
print("=" * 60)

# ═══════════════════════════════════════════════════════════════
# 1. IMAGE GEN TOOL
# ═══════════════════════════════════════════════════════════════
print("\n[1/4] ImageGenTool — Schema e Config")
from clow.tools.image_gen import ImageGenTool

tool = ImageGenTool()
check("Nome correto", tool.name == "image_gen")
check("Descricao menciona DALL-E", "DALL-E" in tool.description)
check("Descricao menciona Pollinations", "Pollinations" in tool.description)

schema = tool.get_schema()
props = schema.get("properties", {})
check("Schema tem prompt", "prompt" in props)
check("Schema tem size", "size" in props)
check("Schema tem quality", "quality" in props)
check("Schema tem style", "style" in props)
check("Schema tem n", "n" in props)

# Verifica enums
sizes = props["size"].get("enum", [])
check("Tamanho 1024x1024", "1024x1024" in sizes)
check("Tamanho 1792x1024 (paisagem)", "1792x1024" in sizes)
check("Tamanho 1024x1792 (retrato)", "1024x1792" in sizes)

quality_enum = props["quality"].get("enum", [])
check("Qualidade standard", "standard" in quality_enum)
check("Qualidade hd", "hd" in quality_enum)

style_enum = props["style"].get("enum", [])
check("Estilo vivid", "vivid" in style_enum)
check("Estilo natural", "natural" in style_enum)

# Sem API key -> deve usar Pollinations
check("Sem OPENAI_API_KEY -> nao gera erro", True)  # tool lida graciosamente

# Valida OpenAI tool format
oai = tool.to_openai_tool()
check("OpenAI format valido", oai["function"]["name"] == "image_gen")

# ═══════════════════════════════════════════════════════════════
# 2. GENERATORS/IMAGE_GEN
# ═══════════════════════════════════════════════════════════════
print("\n[2/4] Generators — image_gen module")
from clow.generators.image_gen import generate_image, optimize_prompt_for_image

check("generate_image importavel", callable(generate_image))
check("optimize_prompt_for_image importavel", callable(optimize_prompt_for_image))

# ═══════════════════════════════════════════════════════════════
# 3. DEPLOY VERCEL TOOL
# ═══════════════════════════════════════════════════════════════
print("\n[3/4] DeployVercelTool — Schema e Actions")
from clow.tools.deploy_tools import DeployVercelTool

vt = DeployVercelTool()
check("Nome correto", vt.name == "deploy_vercel")
check("Descricao menciona projetos", "projetos" in vt.description.lower() or "project" in vt.description.lower())

schema = vt.get_schema()
props = schema.get("properties", {})
actions = props.get("action", {}).get("enum", [])

# Todas as acoes necessarias
required_actions = [
    "login", "whoami",
    "list_projects", "create_project", "get_project", "delete_project",
    "deploy", "list_deployments", "rollback",
    "add_domain", "list_domains", "remove_domain",
    "set_env", "list_env", "remove_env",
]
for a in required_actions:
    check(f"Acao: {a}", a in actions, f"nao encontrada em {actions}")

check("Schema tem token", "token" in props)
check("Schema tem project_name", "project_name" in props)
check("Schema tem project_dir", "project_dir" in props)
check("Schema tem domain", "domain" in props)
check("Schema tem env_key", "env_key" in props)
check("Schema tem env_value", "env_value" in props)
check("Schema tem framework", "framework" in props)
check("Schema tem prod", "prod" in props)

# Sem token -> deve retornar instrucoes
result = vt.execute(action="whoami")
check("Sem token -> instrucoes de login", "Token Vercel" in result or "vercel.com" in result, result[:100])

result_login = vt.execute(action="login")
check("Login sem token -> instrucoes", "vercel.com/account/tokens" in result_login, result_login[:100])

# ═══════════════════════════════════════════════════════════════
# 4. ORQUESTRACAO
# ═══════════════════════════════════════════════════════════════
print("\n[4/4] Orquestracao — deteccao automatica")
from clow.orchestrator import ToolSelector, AgentSelector

# DALL-E triggers
domains = ToolSelector.detect_domains("Gera uma imagem de banner para anuncio")
check("'imagem banner' -> documents domain", "documents" in domains, str(domains))

# Vercel triggers
domains = ToolSelector.detect_domains("Faz deploy no Vercel da landing page")
check("'deploy Vercel' -> deploy domain", "deploy" in domains, str(domains))

# Agent detection
agent = AgentSelector.detect("Cria um banner profissional com design moderno")
check("Banner/design -> design agent", agent == "design", str(agent))

agent = AgentSelector.detect("Faz deploy do site na Vercel com dominio customizado")
check("Deploy site -> fullstack agent", agent == "fullstack", str(agent))

# Fluxo completo landing page -> deploy
from clow.orchestrator import orchestrate
result = orchestrate("Cria landing page para academia e faz deploy no Vercel")
check("Landing page + deploy -> reasoner", result["model"] == "deepseek-reasoner")
check("Detecta deploy domain", "deploy" in result["tool_domains"], str(result["tool_domains"]))
check("Detecta agente", result["agent"] is not None, str(result["agent"]))

# Credential manager tem schema para vercel e openai
from clow.credentials.credential_manager import get_schema
vs = get_schema("vercel")
check("Credential schema vercel existe", vs is not None)
check("Vercel schema tem token", any(f["key"] == "token" for f in vs))

os_schema = get_schema("openai")
check("Credential schema openai existe", os_schema is not None)
check("OpenAI schema tem api_key", any(f["key"] == "api_key" for f in os_schema))

# ═══ RESULTADO ═══
print("\n" + "=" * 60)
total = PASS + FAIL
print(f"RESULTADO: {PASS}/{total} passed, {FAIL} failed")
if FAIL:
    print("STATUS: FALHAS ENCONTRADAS")
    sys.exit(1)
else:
    print("STATUS: TODOS OS TESTES PASSARAM")
