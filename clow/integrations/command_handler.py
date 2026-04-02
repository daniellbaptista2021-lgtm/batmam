"""Command handler — processa /connect, /disconnect, /connections e pedidos de integracao."""
from __future__ import annotations
import re
from ..credentials.credential_manager import (
    save_credential, load_credential, delete_credential,
    list_credentials, get_schema, list_services, SCHEMAS,
)


def handle_command(message: str, user_id: str) -> dict | None:
    """Processa comandos / e retorna resposta ou None se nao for comando."""
    text = message.strip()

    if text == "/connections" or text.startswith("/connections "):
        return _handle_list(user_id)
    elif text.startswith("/disconnect"):
        return _handle_disconnect(text, user_id)
    elif text.startswith("/connect"):
        return _handle_connect(text, user_id)

    return None


def _handle_connect(text: str, user_id: str) -> dict:
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        services = list_services()
        return {"response": "## Servicos disponiveis\n\n" + "\n".join(f"- `/connect {s}`" for s in services)}

    service = parts[1].strip().lower()

    # Checa se os dados ja vem inline (formato: /connect meta key1=val1 key2=val2)
    if "=" in service:
        # Parse inline
        service_parts = service.split(maxsplit=1)
        service = service_parts[0]
        if len(service_parts) > 1:
            return _parse_inline_connect(service, service_parts[1], user_id)

    schema = get_schema(service)
    if not schema:
        return {"response": f"Servico `{service}` nao reconhecido. Use `/connect` para ver a lista."}

    # Retorna formulario pedindo os campos
    fields_text = "\n".join(f"- **{f['label']}**" for f in schema)
    return {
        "response": f"## Conectar {service.title()}\n\nEnvie os dados no formato:\n```\n/connect {service} " +
            " ".join(f"{f['key']}=VALOR" for f in schema) +
            f"\n```\n\nCampos necessarios:\n{fields_text}",
        "awaiting_connect": service,
    }


def _parse_inline_connect(service: str, data_str: str, user_id: str) -> dict:
    schema = get_schema(service)
    if not schema:
        return {"response": f"Servico `{service}` nao reconhecido."}

    # Parse key=value pairs
    pairs = {}
    # Suporta key=valor e key="valor com espacos"
    for match in re.finditer(r'(\w+)=(?:"([^"]+)"|(\S+))', data_str):
        key = match.group(1)
        val = match.group(2) or match.group(3)
        pairs[key] = val

    # Valida campos obrigatorios
    required_keys = [f["key"] for f in schema]
    missing = [k for k in required_keys if k not in pairs and not any(f.get("key") == k and "opcional" in f.get("label", "").lower() for f in schema)]

    if missing:
        return {"response": f"Campos faltando: {', '.join(missing)}\n\nUse: `/connect {service} " + " ".join(f"{k}=VALOR" for k in missing) + "`"}

    # Salva
    save_credential(user_id, service, pairs)
    return {"response": f"✅ **{service.title()}** conectado com sucesso!\n\nUse `/connections` para ver suas conexoes."}


def _handle_disconnect(text: str, user_id: str) -> dict:
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return {"response": "Use: `/disconnect nome_do_servico`"}

    service = parts[1].strip().lower()
    if delete_credential(user_id, service):
        return {"response": f"✅ Credencial `{service}` removida."}
    return {"response": f"Nenhuma credencial encontrada para `{service}`."}


def _handle_list(user_id: str) -> dict:
    creds = list_credentials(user_id)
    if not creds:
        return {"response": "Nenhuma conexao configurada.\n\nUse `/connect` para ver os servicos disponiveis."}

    lines = ["## Suas Conexoes\n"]
    for c in sorted(creds):
        lines.append(f"- 🔗 **{c.title()}** — conectado")
    lines.append(f"\nPara remover: `/disconnect nome_do_servico`")
    return {"response": "\n".join(lines)}


def detect_integration_request(message: str, user_id: str) -> dict | None:
    """Detecta se o usuario esta pedindo algo que requer integracao."""
    text = message.lower()

    # Meta Ads
    meta_kw = ["campanha", "campanhas", "meta ads", "facebook ads", "instagram ads",
               "adset", "anuncios", "cpm", "cpc", "ctr", "cpa", "roas",
               "trafego pago", "metricas ads", "breakdown", "escalar campanha",
               "pausar campanha", "ativar campanha", "orcamento campanha"]
    if any(kw in text for kw in meta_kw):
        return _run_meta(text, user_id)

    # Supabase
    supa_kw = ["supabase", "tabela supabase"]
    if any(kw in text for kw in supa_kw):
        return _run_supabase(text, user_id)

    # n8n
    n8n_kw = ["workflow", "workflows", "n8n", "execucao", "execucoes"]
    if any(kw in text for kw in n8n_kw):
        return _run_n8n(text, user_id)

    # Postgres
    pg_kw = ["postgres", "postgresql", "sql query", "banco de dados"]
    if any(kw in text for kw in pg_kw):
        return _run_postgres(text, user_id)

    # Redis
    redis_kw = ["redis", "cache", "keys redis"]
    if any(kw in text for kw in redis_kw):
        return _run_redis(text, user_id)

    # GitHub
    gh_kw = ["repositorio", "repos github", "issues github", "github"]
    if any(kw in text for kw in gh_kw) and "connect" not in text:
        return _run_github(text, user_id)

    # Stripe
    if "stripe" in text:
        return _run_stripe(text, user_id)

    # Mercado Pago
    mp_kw = ["mercado pago", "mercadopago"]
    if any(kw in text for kw in mp_kw):
        return _run_mp(text, user_id)

    # Vercel
    if "vercel" in text and "connect" not in text:
        return _run_vercel(text, user_id)

    return None


def _need_connect(service: str) -> dict:
    return {"response": f"Voce ainda nao conectou sua conta do **{service.title()}**. Use `/connect {service}` para configurar."}


def _run_meta(text: str, user_id: str) -> dict:
    creds = load_credential(user_id, "meta")
    if not creds:
        return _need_connect("meta")

    from .meta_ads import (list_campaigns, get_account_insights, get_breakdown,
                           pause_campaign, activate_campaign, update_budget)
    try:
        if "pausar campanha" in text or "pause campaign" in text:
            # Extrai ID
            import re
            m = re.search(r'(\d{10,})', text)
            if m:
                return {"response": pause_campaign(creds, m.group(1))}
            return {"response": "Informe o ID da campanha. Ex: `pausar campanha 123456789`"}

        if "ativar campanha" in text or "activate campaign" in text:
            import re
            m = re.search(r'(\d{10,})', text)
            if m:
                return {"response": activate_campaign(creds, m.group(1))}
            return {"response": "Informe o ID da campanha. Ex: `ativar campanha 123456789`"}

        if any(kw in text for kw in ["breakdown", "idade", "genero", "posicionamento"]):
            bd = "age"
            if "genero" in text or "gênero" in text:
                bd = "gender"
            elif "posicionamento" in text or "plataforma" in text:
                bd = "publisher_platform"
            period = _extract_period(text)
            return {"response": get_breakdown(creds, period, bd)}

        if any(kw in text for kw in ["campanhas", "listar campanha", "minhas campanhas"]):
            return {"response": list_campaigns(creds)}

        # Default: metricas da conta
        period = _extract_period(text)
        return {"response": get_account_insights(creds, period)}

    except Exception as e:
        return {"response": f"❌ Erro Meta Ads: {str(e)[:200]}"}


def _run_supabase(text: str, user_id: str) -> dict:
    creds = load_credential(user_id, "supabase")
    if not creds:
        return _need_connect("supabase")

    from .supabase_client import list_tables, query_table
    try:
        if "tabelas" in text or "listar tabelas" in text:
            return {"response": list_tables(creds)}

        # Tenta extrair nome de tabela
        import re
        m = re.search(r'tabela\s+(\w+)', text)
        if m:
            return {"response": query_table(creds, m.group(1))}

        return {"response": list_tables(creds)}
    except Exception as e:
        return {"response": f"❌ Erro Supabase: {str(e)[:200]}"}


def _run_n8n(text: str, user_id: str) -> dict:
    creds = load_credential(user_id, "n8n")
    if not creds:
        return _need_connect("n8n")

    from .n8n_client import list_workflows, get_executions, activate_workflow, deactivate_workflow
    try:
        if any(kw in text for kw in ["execuc", "falharam", "erro", "falha"]):
            status = "error" if any(kw in text for kw in ["falharam", "erro", "falha"]) else None
            return {"response": get_executions(creds, status=status)}

        if "ativar workflow" in text:
            import re
            m = re.search(r'(\w+)$', text.strip())
            if m:
                return {"response": activate_workflow(creds, m.group(1))}

        if "desativar workflow" in text:
            import re
            m = re.search(r'(\w+)$', text.strip())
            if m:
                return {"response": deactivate_workflow(creds, m.group(1))}

        return {"response": list_workflows(creds)}
    except Exception as e:
        return {"response": f"❌ Erro n8n: {str(e)[:200]}"}


def _run_postgres(text: str, user_id: str) -> dict:
    creds = load_credential(user_id, "postgres")
    if not creds:
        return _need_connect("postgres")

    from .postgres_client import execute_sql, list_tables
    try:
        if "tabelas" in text:
            return {"response": list_tables(creds)}

        # Tenta extrair SQL
        import re
        m = re.search(r'(?:sql|query|execute|roda|executa)\s*:?\s*(.+)', text, re.I)
        if m:
            return {"response": execute_sql(creds, m.group(1).strip())}

        return {"response": list_tables(creds)}
    except Exception as e:
        return {"response": f"❌ Erro PostgreSQL: {str(e)[:200]}"}


def _run_redis(text: str, user_id: str) -> dict:
    creds = load_credential(user_id, "redis")
    if not creds:
        return _need_connect("redis")

    from .redis_client import list_keys, memory_info, get_key
    try:
        if "memoria" in text or "memory" in text or "info" in text:
            return {"response": memory_info(creds)}
        if "keys" in text or "chaves" in text:
            import re
            m = re.search(r'(?:keys|chaves)\s+(.+)', text, re.I)
            pattern = m.group(1).strip() if m else "*"
            return {"response": list_keys(creds, pattern)}
        return {"response": memory_info(creds)}
    except Exception as e:
        return {"response": f"❌ Erro Redis: {str(e)[:200]}"}


def _run_github(text: str, user_id: str) -> dict:
    creds = load_credential(user_id, "github")
    if not creds:
        return _need_connect("github")

    from .github_client import list_repos
    try:
        return {"response": list_repos(creds)}
    except Exception as e:
        return {"response": f"❌ Erro GitHub: {str(e)[:200]}"}


def _run_stripe(text: str, user_id: str) -> dict:
    creds = load_credential(user_id, "stripe")
    if not creds:
        return _need_connect("stripe")

    from .payments import stripe_balance, stripe_transactions
    try:
        if any(kw in text for kw in ["transac", "cobranc", "pagamento"]):
            return {"response": stripe_transactions(creds)}
        return {"response": stripe_balance(creds)}
    except Exception as e:
        return {"response": f"❌ Erro Stripe: {str(e)[:200]}"}


def _run_mp(text: str, user_id: str) -> dict:
    creds = load_credential(user_id, "mercadopago")
    if not creds:
        return _need_connect("mercadopago")

    from .payments import mp_balance, mp_payments
    try:
        if any(kw in text for kw in ["transac", "pagamento", "cobranc", "entrou"]):
            return {"response": mp_payments(creds)}
        return {"response": mp_balance(creds)}
    except Exception as e:
        return {"response": f"❌ Erro Mercado Pago: {str(e)[:200]}"}


def _run_vercel(text: str, user_id: str) -> dict:
    creds = load_credential(user_id, "vercel")
    if not creds:
        return _need_connect("vercel")

    from .vercel_client import list_projects, list_deployments
    try:
        if "deploy" in text:
            return {"response": list_deployments(creds)}
        return {"response": list_projects(creds)}
    except Exception as e:
        return {"response": f"❌ Erro Vercel: {str(e)[:200]}"}


def _extract_period(text: str) -> str:
    if "hoje" in text or "today" in text:
        return "today"
    if "30" in text or "mes" in text or "mês" in text:
        return "last_30d"
    if "14" in text:
        return "last_14d"
    return "last_7d"
