"""Meta Ads Tool — gerencia campanhas, adsets, anuncios e metricas via Graph API."""

from __future__ import annotations
import json
import os
from typing import Any
from .base import BaseTool

API_BASE = "https://graph.facebook.com/v21.0"


def _get_creds() -> tuple[str, str]:
    """Retorna (access_token, ad_account_id) do env ou credentials."""
    token = os.getenv("META_ADS_TOKEN", "")
    account = os.getenv("META_ADS_ACCOUNT_ID", "")
    if not token:
        try:
            from ..credentials.credential_manager import get_credentials
            creds = get_credentials("meta_ads") or {}
            token = creds.get("access_token", "")
            account = creds.get("ad_account_id", account)
        except Exception:
            pass
    return token, account


class MetaAdsTool(BaseTool):
    name = "meta_ads"
    description = (
        "Gerencia Meta Ads (Facebook/Instagram). Campanhas, ad sets, anuncios, "
        "metricas, pixel. Acoes: list_campaigns, get_insights, create_campaign, "
        "create_adset, create_ad, manage_pixel, pause, activate."
    )
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list_campaigns", "get_insights", "create_campaign",
                        "create_adset", "create_ad", "pause", "activate",
                        "manage_pixel", "account_info",
                    ],
                    "description": "Acao Meta Ads",
                },
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
                "period": {"type": "string", "description": "Periodo de insights (today, last_7d, last_30d)"},
                "targeting": {"type": "object", "description": "Targeting JSON para ad set"},
                "creative": {"type": "object", "description": "Creative JSON para anuncio"},
            },
            "required": ["action"],
        }

    def execute(self, **kwargs: Any) -> str:
        import httpx
        token, account_id = _get_creds()
        if not token:
            return "Erro: META_ADS_TOKEN nao configurado. Use /connect meta_ads ou defina META_ADS_TOKEN no .env."
        if not account_id:
            return "Erro: META_ADS_ACCOUNT_ID nao configurado."

        action = kwargs["action"]
        headers = {"Authorization": f"Bearer {token}"}
        act = f"act_{account_id}" if not account_id.startswith("act_") else account_id

        try:
            if action == "account_info":
                r = httpx.get(f"{API_BASE}/{act}?fields=name,currency,timezone_name,amount_spent,balance", headers=headers, timeout=15)
                return json.dumps(r.json(), indent=2)

            elif action == "list_campaigns":
                r = httpx.get(
                    f"{API_BASE}/{act}/campaigns",
                    params={"fields": "name,status,objective,daily_budget,lifetime_budget", "limit": "25"},
                    headers=headers, timeout=15,
                )
                data = r.json().get("data", [])
                if not data:
                    return "Nenhuma campanha encontrada."
                lines = []
                for c in data:
                    status = {"ACTIVE": "🟢", "PAUSED": "⏸️"}.get(c.get("status", ""), "⚪")
                    budget = int(c.get("daily_budget", 0)) / 100
                    lines.append(f"{status} {c['name']} | {c.get('objective','')} | R${budget:.2f}/dia | ID:{c['id']}")
                return "\n".join(lines)

            elif action == "get_insights":
                period = kwargs.get("period", "last_7d")
                target_id = kwargs.get("campaign_id") or kwargs.get("adset_id") or act
                r = httpx.get(
                    f"{API_BASE}/{target_id}/insights",
                    params={
                        "fields": "spend,impressions,reach,clicks,cpc,cpm,ctr,actions,cost_per_action_type",
                        "date_preset": period,
                    },
                    headers=headers, timeout=15,
                )
                data = r.json().get("data", [])
                if not data:
                    return f"Sem dados para o periodo '{period}'."
                d = data[0]
                return (
                    f"Periodo: {period}\n"
                    f"Gasto: R${float(d.get('spend', 0)):.2f}\n"
                    f"Impressoes: {d.get('impressions', 0)}\n"
                    f"Alcance: {d.get('reach', 0)}\n"
                    f"Cliques: {d.get('clicks', 0)}\n"
                    f"CPC: R${float(d.get('cpc', 0)):.2f}\n"
                    f"CPM: R${float(d.get('cpm', 0)):.2f}\n"
                    f"CTR: {d.get('ctr', '0')}%"
                )

            elif action == "create_campaign":
                name = kwargs.get("name", "Campanha Clow")
                objective = kwargs.get("objective", "OUTCOME_TRAFFIC")
                budget = kwargs.get("daily_budget", 5000)
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
                r = httpx.get(f"{API_BASE}/{act}/adspixels", params={"fields": "name,id,code"}, headers=headers, timeout=15)
                data = r.json().get("data", [])
                if not data:
                    return "Nenhum pixel encontrado. Crie um no Meta Business Suite."
                lines = [f"Pixel: {p['name']} | ID: {p['id']}" for p in data]
                return "\n".join(lines)

            return f"Acao '{action}' nao implementada."

        except httpx.HTTPError as e:
            return f"Erro HTTP Meta Ads: {e}"
        except Exception as e:
            return f"Erro Meta Ads: {e}"
