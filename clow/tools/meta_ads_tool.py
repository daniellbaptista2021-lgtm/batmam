"""Meta Ads Tool — gerencia campanhas, adsets, anuncios e metricas via Graph API."""

from __future__ import annotations
import json
import os
from typing import Any
from .base import BaseTool

API_BASE = "https://graph.facebook.com/v21.0"


def _get_creds(kwargs: dict) -> tuple[str, str]:
    """Retorna (access_token, ad_account_id).

    Prioridade:
    1. Parametros diretos (access_token, ad_account_id)
    2. Env vars (META_ADS_TOKEN, META_ADS_ACCOUNT_ID / META_ACCESS_TOKEN)
    3. Credential manager
    """
    token = kwargs.get("access_token", "")
    account = kwargs.get("ad_account_id", "")

    if not token:
        token = os.getenv("META_ADS_TOKEN", "") or os.getenv("META_ACCESS_TOKEN", "")
    if not account:
        account = os.getenv("META_ADS_ACCOUNT_ID", "")

    if not token:
        try:
            from ..credentials.credential_manager import load_credential
            creds = load_credential("system", "meta") or {}
            token = creds.get("access_token", "")
            account = account or creds.get("ad_account_id", "")
        except Exception:
            pass

    return token, account


class MetaAdsTool(BaseTool):
    name = "meta_ads"
    description = (
        "Gerencia Meta Ads (Facebook/Instagram). Campanhas, ad sets, anuncios, "
        "metricas, pixel. Acoes: list_campaigns, get_insights, get_ads, "
        "create_campaign, create_adset, create_ad, manage_pixel, pause, activate, account_info. "
        "Aceita access_token e ad_account_id como parametros diretos."
    )
    requires_confirmation = False

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list_campaigns", "get_insights", "get_ads", "get_adsets",
                        "create_campaign", "create_adset", "create_ad",
                        "pause", "activate", "manage_pixel", "account_info",
                    ],
                    "description": "Acao Meta Ads",
                },
                "access_token": {"type": "string", "description": "Token de acesso Meta (se nao estiver no .env)"},
                "ad_account_id": {"type": "string", "description": "ID da conta (ex: act_123456)"},
                "campaign_id": {"type": "string", "description": "ID da campanha"},
                "adset_id": {"type": "string", "description": "ID do ad set"},
                "ad_id": {"type": "string", "description": "ID do anuncio"},
                "name": {"type": "string", "description": "Nome (campanha/adset/ad)"},
                "objective": {
                    "type": "string",
                    "enum": ["OUTCOME_TRAFFIC", "OUTCOME_LEADS", "OUTCOME_SALES", "OUTCOME_ENGAGEMENT", "OUTCOME_AWARENESS"],
                    "description": "Objetivo da campanha",
                },
                "daily_budget": {"type": "integer", "description": "Orcamento diario em centavos (ex: 5000 = R$50)"},
                "period": {"type": "string", "description": "Periodo de insights (today, yesterday, last_7d, last_14d, last_30d, this_month)"},
                "targeting": {"type": "object", "description": "Targeting JSON para ad set"},
                "creative": {"type": "object", "description": "Creative JSON para anuncio"},
                "fields": {"type": "string", "description": "Campos extras para a query (comma-separated)"},
            },
            "required": ["action"],
        }

    def execute(self, **kwargs: Any) -> str:
        import httpx
        token, account_id = _get_creds(kwargs)
        if not token:
            return (
                "Erro: Token Meta Ads nao encontrado. Passe o access_token como parametro "
                "ou defina META_ADS_TOKEN / META_ACCESS_TOKEN no .env."
            )

        action = kwargs["action"]
        headers = {"Authorization": f"Bearer {token}"}
        act = f"act_{account_id}" if account_id and not account_id.startswith("act_") else account_id

        try:
            if action == "account_info":
                if not act:
                    return "Erro: ad_account_id obrigatorio."
                r = httpx.get(
                    f"{API_BASE}/{act}",
                    params={"fields": "name,currency,timezone_name,account_status,amount_spent,balance,spend_cap"},
                    headers=headers, timeout=15,
                )
                return json.dumps(r.json(), indent=2, ensure_ascii=False)

            elif action == "list_campaigns":
                if not act:
                    return "Erro: ad_account_id obrigatorio."
                r = httpx.get(
                    f"{API_BASE}/{act}/campaigns",
                    params={
                        "fields": "id,name,status,effective_status,objective,daily_budget,lifetime_budget,start_time,stop_time",
                        "limit": "50",
                    },
                    headers=headers, timeout=15,
                )
                data = r.json()
                if "error" in data:
                    return f"Erro API: {json.dumps(data['error'], indent=2, ensure_ascii=False)}"
                campaigns = data.get("data", [])
                if not campaigns:
                    return "Nenhuma campanha encontrada."
                lines = []
                for c in campaigns:
                    status_icon = {"ACTIVE": "ATIVA", "PAUSED": "PAUSADA"}.get(c.get("effective_status", ""), c.get("effective_status", ""))
                    budget = int(c.get("daily_budget", 0)) / 100
                    lines.append(
                        f"[{status_icon}] {c['name']}\n"
                        f"  ID: {c['id']} | Objetivo: {c.get('objective','-')} | Orcamento: R${budget:.2f}/dia"
                    )
                return "\n\n".join(lines)

            elif action == "get_insights":
                period = kwargs.get("period", "last_7d")
                target_id = kwargs.get("campaign_id") or kwargs.get("adset_id") or act
                if not target_id:
                    return "Erro: campaign_id, adset_id ou ad_account_id obrigatorio."
                r = httpx.get(
                    f"{API_BASE}/{target_id}/insights",
                    params={
                        "fields": "spend,impressions,reach,frequency,clicks,unique_clicks,cpc,cpm,ctr,actions,cost_per_action_type,date_start,date_stop",
                        "date_preset": period,
                    },
                    headers=headers, timeout=15,
                )
                data = r.json()
                if "error" in data:
                    return f"Erro API: {json.dumps(data['error'], indent=2, ensure_ascii=False)}"
                insights = data.get("data", [])
                if not insights:
                    return f"Sem dados de insights para o periodo '{period}'."
                d = insights[0]

                # Extrai acoes relevantes
                actions_text = ""
                for a in d.get("actions", []):
                    atype = a.get("action_type", "")
                    val = a.get("value", "0")
                    if atype in ("link_click", "landing_page_view", "lead", "purchase", "omni_purchase", "onsite_conversion.messaging_conversation_started_7d"):
                        label = {
                            "link_click": "Cliques no link",
                            "landing_page_view": "Visualizacoes LP",
                            "lead": "Leads",
                            "purchase": "Compras",
                            "omni_purchase": "Compras",
                            "onsite_conversion.messaging_conversation_started_7d": "Conversas iniciadas",
                        }.get(atype, atype)
                        actions_text += f"\n  {label}: {val}"

                # Extrai custo por acao
                costs_text = ""
                for c in d.get("cost_per_action_type", []):
                    atype = c.get("action_type", "")
                    val = c.get("value", "0")
                    if atype in ("link_click", "landing_page_view", "lead", "purchase", "onsite_conversion.messaging_conversation_started_7d"):
                        label = {
                            "link_click": "Custo/clique",
                            "landing_page_view": "Custo/visualizacao LP",
                            "lead": "Custo/lead",
                            "purchase": "Custo/compra",
                            "onsite_conversion.messaging_conversation_started_7d": "Custo/conversa",
                        }.get(atype, atype)
                        costs_text += f"\n  {label}: R${float(val):.2f}"

                report = (
                    f"RELATORIO META ADS — {d.get('date_start', '')} a {d.get('date_stop', '')}\n"
                    f"{'='*50}\n"
                    f"Gasto total: R${float(d.get('spend', 0)):.2f}\n"
                    f"Impressoes: {d.get('impressions', 0)}\n"
                    f"Alcance: {d.get('reach', 0)}\n"
                    f"Frequencia: {d.get('frequency', '-')}\n"
                    f"Cliques: {d.get('clicks', 0)}\n"
                    f"Cliques unicos: {d.get('unique_clicks', '-')}\n"
                    f"CPC: R${float(d.get('cpc', 0)):.2f}\n"
                    f"CPM: R${float(d.get('cpm', 0)):.2f}\n"
                    f"CTR: {d.get('ctr', '0')}%"
                )
                if actions_text:
                    report += f"\n\nCONVERSOES:{actions_text}"
                if costs_text:
                    report += f"\n\nCUSTO POR ACAO:{costs_text}"

                return report

            elif action == "get_adsets":
                campaign_id = kwargs.get("campaign_id", "")
                target = campaign_id or act
                if not target:
                    return "Erro: campaign_id ou ad_account_id obrigatorio."
                r = httpx.get(
                    f"{API_BASE}/{target}/adsets",
                    params={
                        "fields": "id,name,status,effective_status,daily_budget,lifetime_budget,billing_event,optimization_goal,targeting,bid_strategy",
                        "limit": "50",
                    },
                    headers=headers, timeout=15,
                )
                data = r.json()
                if "error" in data:
                    return f"Erro API: {json.dumps(data['error'], indent=2, ensure_ascii=False)}"
                return json.dumps(data.get("data", []), indent=2, ensure_ascii=False)

            elif action == "get_ads":
                adset_id = kwargs.get("adset_id", "")
                campaign_id = kwargs.get("campaign_id", "")
                target = adset_id or campaign_id or act
                if not target:
                    return "Erro: adset_id, campaign_id ou ad_account_id obrigatorio."
                r = httpx.get(
                    f"{API_BASE}/{target}/ads",
                    params={
                        "fields": "id,name,status,effective_status,creative{id,name,body,title,image_url,thumbnail_url,object_story_spec}",
                        "limit": "50",
                    },
                    headers=headers, timeout=15,
                )
                data = r.json()
                if "error" in data:
                    return f"Erro API: {json.dumps(data['error'], indent=2, ensure_ascii=False)}"
                return json.dumps(data.get("data", []), indent=2, ensure_ascii=False)

            elif action == "create_campaign":
                name = kwargs.get("name", "Campanha Clow")
                objective = kwargs.get("objective", "OUTCOME_TRAFFIC")
                budget = kwargs.get("daily_budget", 5000)
                if not act:
                    return "Erro: ad_account_id obrigatorio."
                r = httpx.post(
                    f"{API_BASE}/{act}/campaigns",
                    headers=headers, timeout=15,
                    data={
                        "name": name,
                        "objective": objective,
                        "status": "PAUSED",
                        "special_ad_categories": "[]",
                        "daily_budget": str(budget),
                    },
                )
                return f"Campanha criada (PAUSED): {json.dumps(r.json(), indent=2)}"

            elif action in ("pause", "activate"):
                obj_id = kwargs.get("campaign_id") or kwargs.get("adset_id") or kwargs.get("ad_id")
                if not obj_id:
                    return "Erro: campaign_id, adset_id ou ad_id obrigatorio."
                status = "PAUSED" if action == "pause" else "ACTIVE"
                r = httpx.post(f"{API_BASE}/{obj_id}", headers=headers, data={"status": status}, timeout=15)
                return f"Status alterado para {status}: {r.json()}"

            elif action == "manage_pixel":
                if not act:
                    return "Erro: ad_account_id obrigatorio."
                r = httpx.get(f"{API_BASE}/{act}/adspixels", params={"fields": "name,id,code"}, headers=headers, timeout=15)
                data = r.json()
                if "error" in data:
                    return f"Erro API: {json.dumps(data['error'], indent=2, ensure_ascii=False)}"
                pixels = data.get("data", [])
                if not pixels:
                    return "Nenhum pixel encontrado. Crie um no Meta Business Suite."
                lines = [f"Pixel: {p['name']} | ID: {p['id']}" for p in pixels]
                return "\n".join(lines)

            return f"Acao '{action}' nao implementada."

        except httpx.HTTPError as e:
            return f"Erro HTTP Meta Ads: {e}"
        except Exception as e:
            return f"Erro Meta Ads: {e}"
