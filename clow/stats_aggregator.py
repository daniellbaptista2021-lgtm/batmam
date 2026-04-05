"""Agregador de estatisticas com upsert automatico.

Atualiza tabelas de agregacao incrementalmente a cada request.
A dashboard le diretamente das tabelas agregadas — sem recalcular.

Uso:
    from clow.stats_aggregator import stats
    stats.record_request(tenant_id, inp, out, latency, True, model="haiku")
    stats.record_whatsapp(tenant_id, received=True)
    stats.record_lead(tenant_id, created=True)

    daily = stats.get_daily(tenant_id, days=7)
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class StatsAggregator:
    """Atualiza tabelas de agregacao de forma incremental."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path:
            self._db_path = str(db_path)
        else:
            self._db_path = str(Path(__file__).parent.parent / "data" / "clow.db")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Record methods (chamados a cada evento) ───────────────

    def record_request(
        self,
        tenant_id: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        success: bool,
        cache_hit: bool = False,
        model: str = "",
        user_id: str = "",
        user_name: str = "",
    ) -> None:
        """Chamado apos cada request ao LLM. Upsert em daily + weekly."""
        today = time.strftime("%Y-%m-%d")
        week = time.strftime("%Y-W%W")
        cost = self._calculate_cost(input_tokens, output_tokens, model)

        conn = self._conn()
        try:
            # Upsert daily
            conn.execute("""
                INSERT INTO daily_stats (tenant_id, date, input_tokens, output_tokens,
                    cache_hits, total_requests, successful_requests, failed_requests,
                    avg_latency_ms, max_latency_ms, estimated_cost_usd)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, date) DO UPDATE SET
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    cache_hits = cache_hits + excluded.cache_hits,
                    total_requests = total_requests + 1,
                    successful_requests = successful_requests + excluded.successful_requests,
                    failed_requests = failed_requests + excluded.failed_requests,
                    avg_latency_ms = (avg_latency_ms * total_requests + excluded.avg_latency_ms) / (total_requests + 1),
                    max_latency_ms = MAX(max_latency_ms, excluded.max_latency_ms),
                    estimated_cost_usd = estimated_cost_usd + excluded.estimated_cost_usd,
                    updated_at = unixepoch()
            """, (
                tenant_id, today, input_tokens, output_tokens,
                1 if cache_hit else 0,
                1 if success else 0, 0 if success else 1,
                latency_ms, latency_ms, cost,
            ))

            # Upsert weekly
            conn.execute("""
                INSERT INTO weekly_stats (tenant_id, week, input_tokens, output_tokens,
                    total_requests, estimated_cost_usd)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(tenant_id, week) DO UPDATE SET
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    total_requests = total_requests + 1,
                    estimated_cost_usd = estimated_cost_usd + excluded.estimated_cost_usd,
                    updated_at = unixepoch()
            """, (tenant_id, week, input_tokens, output_tokens, cost))

            # Top users
            if user_id:
                conn.execute("""
                    INSERT INTO top_users_weekly (tenant_id, week, user_id, user_name,
                        total_requests, total_tokens)
                    VALUES (?, ?, ?, ?, 1, ?)
                    ON CONFLICT(tenant_id, week, user_id) DO UPDATE SET
                        total_requests = total_requests + 1,
                        total_tokens = total_tokens + excluded.total_tokens,
                        user_name = COALESCE(NULLIF(excluded.user_name, ''), user_name)
                """, (tenant_id, week, user_id, user_name, input_tokens + output_tokens))

            conn.commit()
        except sqlite3.OperationalError as e:
            # Tables may not exist yet (migration not applied)
            logger.debug("Stats aggregation skipped (table missing?): %s", e)
        except Exception as e:
            logger.warning("Stats aggregation error: %s", e)
        finally:
            conn.close()

    def record_action(self, tenant_id: str, action_type: str, action_name: str, tokens: int = 0) -> None:
        """Registra uso de tool/skill/command."""
        today = time.strftime("%Y-%m-%d")
        conn = self._conn()
        try:
            conn.execute("""
                INSERT INTO action_distribution (tenant_id, date, action_type, action_name, count, total_tokens)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(tenant_id, date, action_type, action_name) DO UPDATE SET
                    count = count + 1,
                    total_tokens = total_tokens + excluded.total_tokens
            """, (tenant_id, today, action_type, action_name, tokens))
            conn.commit()
        except sqlite3.OperationalError:
            pass
        except Exception as e:
            logger.debug("Action record error: %s", e)
        finally:
            conn.close()

    def record_whatsapp(self, tenant_id: str, received: bool = False, sent: bool = False, auto_reply: bool = False) -> None:
        """Registra atividade WhatsApp."""
        today = time.strftime("%Y-%m-%d")
        week = time.strftime("%Y-W%W")
        conn = self._conn()
        try:
            conn.execute("""
                INSERT INTO daily_stats (tenant_id, date, whatsapp_messages_received,
                    whatsapp_messages_sent, whatsapp_auto_replies)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, date) DO UPDATE SET
                    whatsapp_messages_received = whatsapp_messages_received + excluded.whatsapp_messages_received,
                    whatsapp_messages_sent = whatsapp_messages_sent + excluded.whatsapp_messages_sent,
                    whatsapp_auto_replies = whatsapp_auto_replies + excluded.whatsapp_auto_replies,
                    updated_at = unixepoch()
            """, (tenant_id, today, 1 if received else 0, 1 if sent else 0, 1 if auto_reply else 0))

            conn.execute("""
                INSERT INTO weekly_stats (tenant_id, week, whatsapp_messages)
                VALUES (?, ?, 1)
                ON CONFLICT(tenant_id, week) DO UPDATE SET
                    whatsapp_messages = whatsapp_messages + 1,
                    updated_at = unixepoch()
            """, (tenant_id, week))
            conn.commit()
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()

    def record_lead(self, tenant_id: str, created: bool = False, converted: bool = False) -> None:
        """Registra atividade de leads."""
        today = time.strftime("%Y-%m-%d")
        conn = self._conn()
        try:
            conn.execute("""
                INSERT INTO daily_stats (tenant_id, date, leads_created, leads_converted)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tenant_id, date) DO UPDATE SET
                    leads_created = leads_created + excluded.leads_created,
                    leads_converted = leads_converted + excluded.leads_converted,
                    updated_at = unixepoch()
            """, (tenant_id, today, 1 if created else 0, 1 if converted else 0))
            conn.commit()
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()

    # ── Query methods (leitura rapida pra dashboard) ──────────

    def get_daily(self, tenant_id: str, days: int = 7) -> list[dict]:
        """Retorna stats diarios dos ultimos N dias."""
        conn = self._conn()
        try:
            cursor = conn.execute("""
                SELECT * FROM daily_stats
                WHERE tenant_id = ? AND date >= date('now', ?)
                ORDER BY date DESC
            """, (tenant_id, f"-{days} days"))
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def get_weekly(self, tenant_id: str, weeks: int = 4) -> list[dict]:
        """Retorna stats semanais."""
        conn = self._conn()
        try:
            cursor = conn.execute("""
                SELECT * FROM weekly_stats
                WHERE tenant_id = ? ORDER BY week DESC LIMIT ?
            """, (tenant_id, weeks))
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def get_top_actions(self, tenant_id: str, days: int = 7, limit: int = 10) -> list[dict]:
        """Retorna acoes mais usadas."""
        conn = self._conn()
        try:
            cursor = conn.execute("""
                SELECT action_type, action_name, SUM(count) as total_count, SUM(total_tokens) as total_tokens
                FROM action_distribution
                WHERE tenant_id = ? AND date >= date('now', ?)
                GROUP BY action_type, action_name
                ORDER BY total_count DESC LIMIT ?
            """, (tenant_id, f"-{days} days", limit))
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def get_top_users(self, tenant_id: str, week: str = "") -> list[dict]:
        """Retorna top usuarios da semana."""
        if not week:
            week = time.strftime("%Y-W%W")
        conn = self._conn()
        try:
            cursor = conn.execute("""
                SELECT * FROM top_users_weekly
                WHERE tenant_id = ? AND week = ?
                ORDER BY total_requests DESC LIMIT 10
            """, (tenant_id, week))
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def get_summary(self, tenant_id: str) -> dict:
        """Resumo rapido: hoje + semana + acoes top."""
        daily = self.get_daily(tenant_id, days=1)
        weekly = self.get_weekly(tenant_id, weeks=1)
        top = self.get_top_actions(tenant_id, days=7, limit=5)
        today = daily[0] if daily else {}
        this_week = weekly[0] if weekly else {}
        return {
            "today": {
                "requests": today.get("total_requests", 0),
                "tokens": today.get("input_tokens", 0) + today.get("output_tokens", 0),
                "cost_usd": today.get("estimated_cost_usd", 0),
                "whatsapp": today.get("whatsapp_messages_received", 0),
                "leads": today.get("leads_created", 0),
            },
            "week": {
                "requests": this_week.get("total_requests", 0),
                "tokens": this_week.get("input_tokens", 0) + this_week.get("output_tokens", 0),
                "cost_usd": this_week.get("estimated_cost_usd", 0),
                "whatsapp": this_week.get("whatsapp_messages", 0),
            },
            "top_actions": top,
        }

    @staticmethod
    def _calculate_cost(input_tokens: int, output_tokens: int, model: str) -> float:
        if "haiku" in model.lower():
            return (input_tokens / 1_000_000 * 1.0) + (output_tokens / 1_000_000 * 5.0)
        return (input_tokens / 1_000_000 * 3.0) + (output_tokens / 1_000_000 * 15.0)


# Instancia global
stats = StatsAggregator()
