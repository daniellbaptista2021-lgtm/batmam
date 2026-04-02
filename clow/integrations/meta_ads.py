"""Modulo Meta Ads — analise, metricas e gestao de campanhas."""
from __future__ import annotations
import requests
from datetime import datetime, timedelta

API_BASE = "https://graph.facebook.com/v21.0"
TIMEOUT = 30


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _get(endpoint: str, token: str, params: dict = None) -> dict:
    url = f"{API_BASE}/{endpoint}"
    p = params or {}
    p["access_token"] = token
    r = requests.get(url, params=p, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _post(endpoint: str, token: str, data: dict = None) -> dict:
    url = f"{API_BASE}/{endpoint}"
    d = data or {}
    d["access_token"] = token
    r = requests.post(url, data=d, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def list_campaigns(creds: dict, status_filter: str = None) -> str:
    acc = creds["ad_account_id"]
    fields = "name,status,daily_budget,lifetime_budget,objective,buying_type,bid_strategy"
    params = {"fields": fields, "limit": 50}
    if status_filter:
        params["effective_status"] = f'["{status_filter.upper()}"]'
    data = _get(f"{acc}/campaigns", creds["access_token"], params)

    campaigns = data.get("data", [])
    if not campaigns:
        return "Nenhuma campanha encontrada."

    lines = ["## Campanhas Meta Ads\n"]
    for c in campaigns:
        budget = ""
        if c.get("daily_budget"):
            budget = f"R${int(c['daily_budget'])/100:.2f}/dia"
        elif c.get("lifetime_budget"):
            budget = f"R${int(c['lifetime_budget'])/100:.2f} total"
        status_icon = {"ACTIVE": "🟢", "PAUSED": "⏸️"}.get(c.get("status", ""), "⚪")
        lines.append(f"- {status_icon} **{c['name']}** | {c.get('objective','-')} | {budget} | `{c['id']}`")

    return "\n".join(lines)


def get_account_insights(creds: dict, period: str = "last_7d") -> str:
    acc = creds["ad_account_id"]
    fields = "spend,impressions,reach,clicks,cpc,cpm,ctr,frequency,actions,cost_per_action_type"

    presets = {
        "hoje": "today", "today": "today",
        "7d": "last_7d", "7dias": "last_7d", "last_7d": "last_7d",
        "14d": "last_14d", "last_14d": "last_14d",
        "30d": "last_30d", "30dias": "last_30d", "last_30d": "last_30d",
        "mes": "this_month", "this_month": "this_month",
    }
    preset = presets.get(period.lower().replace(" ", ""), "last_7d")

    params = {"fields": fields, "date_preset": preset}
    data = _get(f"{acc}/insights", creds["access_token"], params)

    rows = data.get("data", [])
    if not rows:
        return f"Sem dados para o periodo `{preset}`."

    d = rows[0]
    spend = float(d.get("spend", 0))
    impressions = int(d.get("impressions", 0))
    reach = int(d.get("reach", 0))
    clicks = int(d.get("clicks", 0))
    cpc = float(d.get("cpc", 0))
    cpm = float(d.get("cpm", 0))
    ctr = float(d.get("ctr", 0))
    freq = float(d.get("frequency", 0))

    # Extrair acoes
    actions = {a["action_type"]: int(a["value"]) for a in d.get("actions", [])}
    costs = {a["action_type"]: float(a["value"]) for a in d.get("cost_per_action_type", [])}
    leads = actions.get("lead", actions.get("offsite_conversion.fb_pixel_lead", 0))
    purchases = actions.get("purchase", actions.get("offsite_conversion.fb_pixel_purchase", 0))
    cpa_lead = costs.get("lead", costs.get("offsite_conversion.fb_pixel_lead", 0))

    lines = [
        f"## Metricas Meta Ads — {preset}\n",
        f"| Metrica | Valor |",
        f"|---------|-------|",
        f"| Gasto | R${spend:.2f} |",
        f"| Impressoes | {impressions:,} |",
        f"| Alcance | {reach:,} |",
        f"| Cliques | {clicks:,} |",
        f"| CPC | R${cpc:.2f} |",
        f"| CPM | R${cpm:.2f} |",
        f"| CTR | {ctr:.2f}% |",
        f"| Frequencia | {freq:.2f} |",
    ]
    if leads:
        lines.append(f"| Leads | {leads} |")
    if cpa_lead:
        lines.append(f"| CPL | R${cpa_lead:.2f} |")
    if purchases:
        lines.append(f"| Compras | {purchases} |")

    # Analise Andromeda
    lines.append(f"\n### Analise Andromeda\n")
    if freq > 3:
        lines.append(f"⚠️ **Frequencia alta ({freq:.1f})** — possivel fadiga de criativo. Considere renovar os criativos ou pausar adsets com frequencia >4.")
    if ctr < 1:
        lines.append(f"⚠️ **CTR baixo ({ctr:.2f}%)** — criativos podem nao estar ressonando. Teste novos angulos de copy e imagem.")
    if ctr >= 2:
        lines.append(f"✅ **CTR excelente ({ctr:.2f}%)** — criativos performando bem.")
    if cpc > 5:
        lines.append(f"⚠️ **CPC alto (R${cpc:.2f})** — revise segmentacao e criativos.")
    if cpc < 1.5:
        lines.append(f"✅ **CPC otimo (R${cpc:.2f})** — boa eficiencia.")
    if spend > 0 and leads > 0:
        cpl = spend / leads
        if cpl < 15:
            lines.append(f"✅ **CPL bom (R${cpl:.2f})** — considere escalar orçamento +20%.")
        elif cpl > 40:
            lines.append(f"🔴 **CPL alto (R${cpl:.2f})** — revise landing page e criativos.")

    return "\n".join(lines)


def get_campaign_insights(creds: dict, campaign_id: str, period: str = "last_7d") -> str:
    fields = "campaign_name,spend,impressions,clicks,cpc,cpm,ctr,frequency,actions,cost_per_action_type"
    presets = {"7d": "last_7d", "30d": "last_30d", "hoje": "today"}
    preset = presets.get(period, "last_7d")

    params = {"fields": fields, "date_preset": preset}
    data = _get(f"{campaign_id}/insights", creds["access_token"], params)
    rows = data.get("data", [])
    if not rows:
        return "Sem dados para esta campanha neste periodo."

    d = rows[0]
    return (
        f"## {d.get('campaign_name', campaign_id)}\n\n"
        f"- Gasto: R${float(d.get('spend',0)):.2f}\n"
        f"- Impressoes: {int(d.get('impressions',0)):,}\n"
        f"- Cliques: {int(d.get('clicks',0)):,}\n"
        f"- CPC: R${float(d.get('cpc',0)):.2f}\n"
        f"- CTR: {float(d.get('ctr',0)):.2f}%\n"
        f"- Frequencia: {float(d.get('frequency',0)):.1f}"
    )


def get_breakdown(creds: dict, period: str = "last_7d", breakdown: str = "age") -> str:
    acc = creds["ad_account_id"]
    fields = "spend,impressions,clicks,cpc,ctr,actions"
    params = {"fields": fields, "date_preset": period, "breakdowns": breakdown}
    data = _get(f"{acc}/insights", creds["access_token"], params)

    rows = data.get("data", [])
    if not rows:
        return f"Sem dados para breakdown `{breakdown}`."

    lines = [f"## Breakdown por {breakdown}\n", "| Segmento | Gasto | Cliques | CPC | CTR |", "|----------|-------|---------|-----|-----|"]
    for r in rows:
        seg = r.get(breakdown, "-")
        lines.append(f"| {seg} | R${float(r.get('spend',0)):.2f} | {r.get('clicks',0)} | R${float(r.get('cpc',0)):.2f} | {float(r.get('ctr',0)):.2f}% |")

    return "\n".join(lines)


def pause_campaign(creds: dict, campaign_id: str) -> str:
    _post(campaign_id, creds["access_token"], {"status": "PAUSED"})
    return f"✅ Campanha `{campaign_id}` pausada com sucesso."


def activate_campaign(creds: dict, campaign_id: str) -> str:
    _post(campaign_id, creds["access_token"], {"status": "ACTIVE"})
    return f"✅ Campanha `{campaign_id}` ativada com sucesso."


def update_budget(creds: dict, campaign_id: str, daily_budget_reais: float) -> str:
    budget_cents = str(int(daily_budget_reais * 100))
    _post(campaign_id, creds["access_token"], {"daily_budget": budget_cents})
    return f"✅ Orcamento da campanha `{campaign_id}` alterado para R${daily_budget_reais:.2f}/dia."
