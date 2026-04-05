"""Metrics Collector — agrega metricas de uso para admin e Anthropic."""

from __future__ import annotations
import time
from typing import Any

from . import config


def record_request(user_id: str, plan: str, input_tokens: int, output_tokens: int, cache_hit: bool = False, latency_ms: float = 0, source: str = "chat") -> None:
    """Registra uma requisicao no usage_log. source: 'chat' ou 'whatsapp'."""
    from .database import get_db

    # WhatsApp sempre usa Haiku pricing
    if source == "whatsapp" or plan == "lite":
        cost = (input_tokens * config.HAIKU_INPUT_PRICE_PER_MTOK + output_tokens * config.HAIKU_OUTPUT_PRICE_PER_MTOK) / 1_000_000
    else:
        cost = (input_tokens * config.SONNET_INPUT_PRICE_PER_MTOK + output_tokens * config.SONNET_OUTPUT_PRICE_PER_MTOK) / 1_000_000

    with get_db() as db:
        db.execute(
            "INSERT INTO usage_log (user_id, model, input_tokens, output_tokens, cost_usd, action, created_at) VALUES (?,?,?,?,?,?,?)",
            (user_id, plan, input_tokens, output_tokens, cost, source, time.time()),
        )


def get_admin_metrics() -> dict[str, Any]:
    """Retorna metricas agregadas para o admin dashboard."""
    from .database import get_db

    now = time.time()
    today_start = now - (now % 86400)
    week_start = now - 7 * 86400
    month_start = now - 30 * 86400

    with get_db() as db:
        # Total users
        total_users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

        # Ativos hoje/semana
        active_today = db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM usage_log WHERE created_at>=?", (today_start,)
        ).fetchone()[0]
        active_week = db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM usage_log WHERE created_at>=?", (week_start,)
        ).fetchone()[0]

        # Tokens e custo
        def _period_stats(since):
            r = db.execute(
                "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COALESCE(SUM(cost_usd),0), COUNT(*) FROM usage_log WHERE created_at>=?",
                (since,),
            ).fetchone()
            return {"input_tokens": r[0], "output_tokens": r[1], "cost_usd": round(r[2], 4), "requests": r[3]}

        today_stats = _period_stats(today_start)
        week_stats = _period_stats(week_start)
        month_stats = _period_stats(month_start)

        # Por plano
        plan_rows = db.execute(
            "SELECT u.plan, COUNT(DISTINCT ul.user_id) as users, COALESCE(SUM(ul.input_tokens),0) as inp, COALESCE(SUM(ul.output_tokens),0) as out, COALESCE(SUM(ul.cost_usd),0) as cost "
            "FROM usage_log ul JOIN users u ON ul.user_id=u.id WHERE ul.created_at>=? GROUP BY u.plan",
            (month_start,),
        ).fetchall()

        by_plan = {}
        for r in plan_rows:
            by_plan[r[0] or "unknown"] = {"users": r[1], "input_tokens": r[2], "output_tokens": r[3], "cost_usd": round(r[4], 4)}

        # Revenue (conta planos pagos ativos)
        from .billing import PLANS
        revenue = 0
        plan_counts = db.execute(
            "SELECT plan, COUNT(*) FROM users WHERE plan IN ('lite','starter','pro','business') AND active=1 GROUP BY plan"
        ).fetchall()
        for r in plan_counts:
            p = PLANS.get(r[0], {})
            revenue += p.get("price_brl", 0) * r[1]

        # Top consumers
        top = db.execute(
            "SELECT u.email, u.plan, SUM(ul.input_tokens) as inp, SUM(ul.output_tokens) as out, SUM(ul.cost_usd) as cost "
            "FROM usage_log ul JOIN users u ON ul.user_id=u.id WHERE ul.created_at>=? "
            "GROUP BY ul.user_id ORDER BY cost DESC LIMIT 10",
            (month_start,),
        ).fetchall()

        top_consumers = [
            {"email": r[0], "plan": r[1], "input_tokens": r[2], "output_tokens": r[3], "cost_usd": round(r[4], 4)}
            for r in top
        ]

    return {
        "total_users": total_users,
        "active_today": active_today,
        "active_week": active_week,
        "revenue_monthly_brl": revenue,
        "today": today_stats,
        "week": week_stats,
        "month": month_stats,
        "by_plan": by_plan,
        "top_consumers": top_consumers,
    }
