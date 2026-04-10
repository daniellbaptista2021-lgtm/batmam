"""Database migrations for Clow.

Centralizes all table schemas and provides versioned migrations
so that scattered CREATE TABLE IF NOT EXISTS calls can be replaced
with a single ``run_migrations()`` invocation at startup.

Usage:
    from clow.migrations import run_migrations
    run_migrations()          # safe to call on every boot

Each migration is a (version, description, up_sql) tuple.  The helper
``run_migrations`` creates a ``_migrations`` bookkeeping table, then
applies any migrations whose version has not yet been recorded.
Columns are added with ``ADD COLUMN ... DEFAULT`` so existing data is
never lost.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Migration definitions
# Each entry: (version: int, description: str, up_sql: str)
# up_sql may contain multiple statements separated by semicolons.
# ---------------------------------------------------------------------------

MIGRATIONS: list[tuple[int, str, str]] = [
    # ── v1: core tables (users, usage_log, conversations, messages) ──
    (
        1,
        "Create core tables: users, usage_log, conversations, messages",
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT DEFAULT '',
            plan TEXT DEFAULT 'free',
            active INTEGER DEFAULT 1,
            is_admin INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            last_login REAL
        );

        CREATE TABLE IF NOT EXISTS usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0,
            action TEXT DEFAULT 'chat',
            created_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT DEFAULT 'Nova conversa',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            file_data TEXT,
            created_at REAL NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_usage_user_date ON usage_log(user_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, updated_at);
        CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, created_at);
        """,
    ),
    # ── v2: missions tables ──────────────────────────────────────────
    (
        2,
        "Create missions and mission_steps tables",
        """
        CREATE TABLE IF NOT EXISTS missions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT DEFAULT 'planning',
            plan_json TEXT,
            context_json TEXT DEFAULT '{}',
            current_step INTEGER DEFAULT 0,
            total_steps INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            completed_at REAL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS mission_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mission_id TEXT NOT NULL,
            step_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            model TEXT DEFAULT 'haiku',
            result_json TEXT,
            error TEXT,
            attempts INTEGER DEFAULT 0,
            started_at REAL,
            completed_at REAL,
            FOREIGN KEY (mission_id) REFERENCES missions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_missions_user ON missions(user_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_msteps_mission ON mission_steps(mission_id, step_number);
        """,
    ),
    # ── v3: claude_code_log (from claude_code_bridge.py) ─────────────
    (
        3,
        "Create claude_code_log table for CLI usage tracking",
        """
        CREATE TABLE IF NOT EXISTS claude_code_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            prompt_preview TEXT NOT NULL,
            elapsed_seconds REAL NOT NULL,
            created_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cclog_user ON claude_code_log(user_id, created_at);
        """,
    ),
    # ── v4: rate_limit_events (optional audit trail for rate limits) ─
    (
        4,
        "Create rate_limit_events table",
        """
        CREATE TABLE IF NOT EXISTS rate_limit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            user_id TEXT DEFAULT '',
            plan TEXT DEFAULT 'free',
            blocked INTEGER DEFAULT 0,
            created_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_rl_ip ON rate_limit_events(ip, created_at);
        CREATE INDEX IF NOT EXISTS idx_rl_user ON rate_limit_events(user_id, created_at);
        """,
    ),
    # ── v5: CRM tables (leads, activities, campaigns, appointments) ──
    (
        5,
        "Create CRM tables: leads, lead_activities, email_campaigns, email_sends, appointments, scheduling_links",
        """
        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            name TEXT,
            email TEXT,
            phone TEXT,
            source TEXT DEFAULT 'manual',
            status TEXT DEFAULT 'novo',
            score INTEGER DEFAULT 0,
            assigned_to TEXT,
            notes TEXT,
            tags TEXT,
            custom_fields TEXT,
            last_contact_at REAL,
            next_followup_at REAL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_leads_tenant ON leads(tenant_id, status);
        CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);
        CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);

        CREATE TABLE IF NOT EXISTS lead_activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            type TEXT NOT NULL,
            content TEXT,
            metadata TEXT,
            created_at REAL NOT NULL,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        );
        CREATE INDEX IF NOT EXISTS idx_activities_lead ON lead_activities(lead_id, created_at);

        CREATE TABLE IF NOT EXISTS email_campaigns (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            subject TEXT NOT NULL,
            body_html TEXT NOT NULL,
            status TEXT DEFAULT 'draft',
            recipient_filter TEXT,
            total_recipients INTEGER DEFAULT 0,
            sent_count INTEGER DEFAULT 0,
            open_count INTEGER DEFAULT 0,
            click_count INTEGER DEFAULT 0,
            scheduled_at REAL,
            sent_at REAL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_campaigns_tenant ON email_campaigns(tenant_id, status);

        CREATE TABLE IF NOT EXISTS email_sends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id TEXT NOT NULL,
            lead_id TEXT NOT NULL,
            email TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            sent_at REAL,
            opened_at REAL,
            FOREIGN KEY (campaign_id) REFERENCES email_campaigns(id)
        );
        CREATE INDEX IF NOT EXISTS idx_sends_campaign ON email_sends(campaign_id);

        CREATE TABLE IF NOT EXISTS appointments (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            lead_id TEXT,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            duration_minutes INTEGER DEFAULT 30,
            status TEXT DEFAULT 'confirmado',
            notes TEXT,
            meeting_link TEXT,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_appointments_tenant ON appointments(tenant_id, date);

        CREATE TABLE IF NOT EXISTS scheduling_links (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            title TEXT NOT NULL,
            duration_minutes INTEGER DEFAULT 30,
            available_days TEXT DEFAULT '1,2,3,4,5',
            available_start TEXT DEFAULT '09:00',
            available_end TEXT DEFAULT '18:00',
            blocked_times TEXT,
            active INTEGER DEFAULT 1,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_slinks_tenant ON scheduling_links(tenant_id);
        """,
    ),
    # ── v6: CRM leads — instance_id e source_phone ──────────────
    (
        6,
        "Add instance_id and source_phone to leads for per-WhatsApp pipeline",
        """
        ALTER TABLE leads ADD COLUMN instance_id TEXT DEFAULT '';
        ALTER TABLE leads ADD COLUMN source_phone TEXT DEFAULT '';
        CREATE INDEX IF NOT EXISTS idx_leads_instance ON leads(tenant_id, instance_id);
        """,
    ),
    # ── v7: deal/ROI fields on leads ──
    (
        7,
        "Add deal value, cost tracking fields to leads",
        """
        ALTER TABLE leads ADD COLUMN deal_value REAL DEFAULT 0;
        ALTER TABLE leads ADD COLUMN deal_closed_at REAL DEFAULT 0;
        ALTER TABLE leads ADD COLUMN deal_products TEXT DEFAULT '';
        ALTER TABLE leads ADD COLUMN deal_notes TEXT DEFAULT '';
        ALTER TABLE leads ADD COLUMN cost_tokens_used INTEGER DEFAULT 0;
        ALTER TABLE leads ADD COLUMN cost_estimated_brl REAL DEFAULT 0;
        """,
    ),
    # ── v8: Analytics views and daily aggregation ─────────────
    (
        8,
        "Create usage_daily_stats table and analytics views",
        """
        CREATE TABLE IF NOT EXISTS usage_daily_stats (
            date TEXT NOT NULL,
            user_id TEXT NOT NULL,
            plan TEXT DEFAULT 'free',
            total_input_tokens INTEGER DEFAULT 0,
            total_output_tokens INTEGER DEFAULT 0,
            total_cost_usd REAL DEFAULT 0,
            request_count INTEGER DEFAULT 0,
            PRIMARY KEY (date, user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_daily_stats_date ON usage_daily_stats(date);

        -- View: uso diario agregado
        CREATE VIEW IF NOT EXISTS v_daily_usage AS
        SELECT
            date(created_at, 'unixepoch') as date,
            user_id,
            SUM(input_tokens) as total_input,
            SUM(output_tokens) as total_output,
            SUM(cost_usd) as total_cost,
            COUNT(*) as requests
        FROM usage_log
        GROUP BY date(created_at, 'unixepoch'), user_id;

        -- View: comandos populares (WhatsApp vs Chat)
        CREATE VIEW IF NOT EXISTS v_action_distribution AS
        SELECT
            action,
            COUNT(*) as count,
            SUM(input_tokens + output_tokens) as total_tokens,
            SUM(cost_usd) as total_cost
        FROM usage_log
        WHERE created_at >= strftime('%s', 'now', '-30 days')
        GROUP BY action
        ORDER BY count DESC;

        -- View: top users nos ultimos 7 dias
        CREATE VIEW IF NOT EXISTS v_top_users_week AS
        SELECT
            u.email,
            u.plan,
            SUM(l.input_tokens + l.output_tokens) as total_tokens,
            SUM(l.cost_usd) as total_cost,
            COUNT(*) as requests
        FROM usage_log l
        JOIN users u ON l.user_id = u.id
        WHERE l.created_at >= strftime('%s', 'now', '-7 days')
        GROUP BY l.user_id
        ORDER BY total_tokens DESC
        LIMIT 20;
        """,
    ),
    # ── v9: Auto-aggregation tables for dashboard ──────────────
    (
        9,
        "Create daily_stats, weekly_stats, action_distribution, top_users_weekly for auto-aggregation",
        """
        CREATE TABLE IF NOT EXISTS daily_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            date TEXT NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_hits INTEGER DEFAULT 0,
            total_requests INTEGER DEFAULT 0,
            successful_requests INTEGER DEFAULT 0,
            failed_requests INTEGER DEFAULT 0,
            whatsapp_messages_received INTEGER DEFAULT 0,
            whatsapp_messages_sent INTEGER DEFAULT 0,
            whatsapp_auto_replies INTEGER DEFAULT 0,
            leads_created INTEGER DEFAULT 0,
            leads_converted INTEGER DEFAULT 0,
            avg_latency_ms REAL DEFAULT 0,
            max_latency_ms REAL DEFAULT 0,
            estimated_cost_usd REAL DEFAULT 0,
            created_at REAL DEFAULT (strftime('%s','now')),
            updated_at REAL DEFAULT (strftime('%s','now')),
            UNIQUE(tenant_id, date)
        );

        CREATE TABLE IF NOT EXISTS weekly_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            week TEXT NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            total_requests INTEGER DEFAULT 0,
            whatsapp_messages INTEGER DEFAULT 0,
            leads_created INTEGER DEFAULT 0,
            leads_converted INTEGER DEFAULT 0,
            estimated_cost_usd REAL DEFAULT 0,
            created_at REAL DEFAULT (strftime('%s','now')),
            updated_at REAL DEFAULT (strftime('%s','now')),
            UNIQUE(tenant_id, week)
        );

        CREATE TABLE IF NOT EXISTS action_distribution (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            date TEXT NOT NULL,
            action_type TEXT NOT NULL,
            action_name TEXT NOT NULL,
            count INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            UNIQUE(tenant_id, date, action_type, action_name)
        );

        CREATE TABLE IF NOT EXISTS top_users_weekly (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            week TEXT NOT NULL,
            user_id TEXT NOT NULL,
            user_name TEXT DEFAULT '',
            total_requests INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            UNIQUE(tenant_id, week, user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_daily_stats_td ON daily_stats(tenant_id, date);
        CREATE INDEX IF NOT EXISTS idx_weekly_stats_tw ON weekly_stats(tenant_id, week);
        CREATE INDEX IF NOT EXISTS idx_action_dist_td ON action_distribution(tenant_id, date);
        CREATE INDEX IF NOT EXISTS idx_top_users_tw ON top_users_weekly(tenant_id, week);
        """,
    ),

    # -- v10: WhatsApp connections, bot config, message logs, knowledge base, onboarding --
    (
        10,
        "Create WhatsApp connections, bot_configs, wa_message_logs, wa_knowledge_base, onboarding_status tables and add user columns",
        """
        -- WhatsApp connections tracking
        CREATE TABLE IF NOT EXISTS whatsapp_connections (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            plan_slot INTEGER DEFAULT 1,
            instance_id TEXT NOT NULL,
            token TEXT NOT NULL,
            name TEXT DEFAULT 'Meu WhatsApp',
            status TEXT DEFAULT 'disconnected',
            webhook_url TEXT DEFAULT '',
            last_seen REAL DEFAULT 0,
            last_health_check REAL DEFAULT 0,
            created_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- Bot configuration per connection
        CREATE TABLE IF NOT EXISTS bot_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            connection_id TEXT NOT NULL,
            prompt TEXT DEFAULT '',
            personality_name TEXT DEFAULT 'Assistente',
            personality_tone TEXT DEFAULT 'casual',
            language TEXT DEFAULT 'pt-BR',
            business_hours_enabled INTEGER DEFAULT 0,
            business_hours_start TEXT DEFAULT '08:00',
            business_hours_end TEXT DEFAULT '18:00',
            business_days TEXT DEFAULT '1,2,3,4,5',
            out_of_hours_message TEXT DEFAULT 'Estamos fora do horario de atendimento. Retornaremos em breve!',
            welcome_enabled INTEGER DEFAULT 1,
            welcome_message TEXT DEFAULT 'Ola! Como posso ajudar?',
            welcome_delay_seconds INTEGER DEFAULT 2,
            handoff_enabled INTEGER DEFAULT 0,
            handoff_keywords TEXT DEFAULT 'humano,atendente,gerente',
            handoff_number TEXT DEFAULT '',
            handoff_message TEXT DEFAULT 'Transferindo para um atendente humano...',
            quick_replies TEXT DEFAULT '[]',
            typing_delay_ms INTEGER DEFAULT 1500,
            anti_spam_seconds INTEGER DEFAULT 3,
            model TEXT DEFAULT 'deepseek-chat',
            temperature REAL DEFAULT 0.3,
            max_tokens INTEGER DEFAULT 1024,
            FOREIGN KEY (connection_id) REFERENCES whatsapp_connections(id)
        );

        -- Message logs
        CREATE TABLE IF NOT EXISTS wa_message_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            connection_id TEXT NOT NULL,
            phone TEXT NOT NULL,
            direction TEXT NOT NULL CHECK (direction IN ('incoming', 'outgoing')),
            content TEXT NOT NULL,
            tokens_used INTEGER DEFAULT 0,
            resolved_by_ai INTEGER DEFAULT 1,
            transferred_to_human INTEGER DEFAULT 0,
            response_time_ms INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            FOREIGN KEY (connection_id) REFERENCES whatsapp_connections(id)
        );

        CREATE INDEX IF NOT EXISTS idx_wa_logs_connection ON wa_message_logs(connection_id);
        CREATE INDEX IF NOT EXISTS idx_wa_logs_phone ON wa_message_logs(phone);
        CREATE INDEX IF NOT EXISTS idx_wa_logs_date ON wa_message_logs(created_at);

        -- Knowledge base documents
        CREATE TABLE IF NOT EXISTS wa_knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            connection_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            content TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            processed_at REAL,
            created_at REAL NOT NULL,
            FOREIGN KEY (connection_id) REFERENCES whatsapp_connections(id)
        );

        -- Onboarding status
        CREATE TABLE IF NOT EXISTS onboarding_status (
            user_id TEXT PRIMARY KEY,
            completed INTEGER DEFAULT 0,
            step_reached INTEGER DEFAULT 0,
            whatsapp_done INTEGER DEFAULT 0,
            chatwoot_done INTEGER DEFAULT 0,
            skipped INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- Add first_login column to users if not exists
        ALTER TABLE users ADD COLUMN first_login INTEGER DEFAULT 1;
        ALTER TABLE users ADD COLUMN onboarding_completed INTEGER DEFAULT 0;
        """,
    ),
    # ── v11: Meta WhatsApp Business API provider fields ──────
    (
        11,
        "Add Meta WhatsApp Business API provider fields to whatsapp_connections",
        """
        ALTER TABLE whatsapp_connections ADD COLUMN provider TEXT DEFAULT 'zapi';
        ALTER TABLE whatsapp_connections ADD COLUMN meta_phone_number_id TEXT DEFAULT '';
        ALTER TABLE whatsapp_connections ADD COLUMN meta_waba_id TEXT DEFAULT '';
        ALTER TABLE whatsapp_connections ADD COLUMN meta_access_token TEXT DEFAULT '';
        ALTER TABLE whatsapp_connections ADD COLUMN meta_verify_token TEXT DEFAULT '';
        """,
    ),
]


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------

def _ensure_migrations_table(db) -> None:
    """Create the internal ``_migrations`` bookkeeping table."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at REAL NOT NULL
        )
    """)


def _applied_versions(db) -> set[int]:
    """Return the set of already-applied migration versions."""
    rows = db.execute("SELECT version FROM _migrations").fetchall()
    return {row[0] if isinstance(row, (tuple, list)) else row["version"] for row in rows}


def run_migrations(db_getter=None) -> list[int]:
    """Apply all pending migrations and return the list of newly applied versions.

    Parameters
    ----------
    db_getter:
        A callable that returns a context-manager yielding an ``sqlite3.Connection``.
        When *None*, falls back to ``clow.database.get_db`` (lazy import so the
        module can be used stand-alone for testing).

    Returns
    -------
    list[int]
        Versions that were applied during this call (empty if everything was
        already up-to-date).
    """
    if db_getter is None:
        from .database import get_db
        db_getter = get_db

    applied: list[int] = []

    with db_getter() as db:
        _ensure_migrations_table(db)
        already = _applied_versions(db)

        for version, description, up_sql in sorted(MIGRATIONS, key=lambda m: m[0]):
            if version in already:
                continue
            logger.info("Applying migration v%d: %s", version, description)
            try:
                db.executescript(up_sql)
                db.execute(
                    "INSERT INTO _migrations (version, description, applied_at) VALUES (?, ?, ?)",
                    (version, description, time.time()),
                )
                applied.append(version)
                logger.info("Migration v%d applied successfully.", version)
            except Exception:
                logger.exception("Migration v%d FAILED.", version)
                raise

    return applied


def add_column_safe(db, table: str, column: str, col_type: str, default: str = "") -> bool:
    """Add a column to *table* only if it does not already exist.

    Uses ``PRAGMA table_info`` to detect existing columns, then issues
    ``ALTER TABLE ... ADD COLUMN`` when the column is missing.  This is
    safe for SQLite (the only ALTER TABLE operation it supports without
    recreating the table).

    Returns True if the column was added, False if it already existed.
    """
    existing = {row[1] if isinstance(row, (tuple, list)) else row["name"]
                for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in existing:
        return False

    default_clause = f" DEFAULT {default}" if default else ""
    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}")
    logger.info("Added column %s.%s (%s%s)", table, column, col_type, default_clause)
    return True


def current_version(db_getter=None) -> int:
    """Return the highest migration version that has been applied, or 0."""
    if db_getter is None:
        from .database import get_db
        db_getter = get_db

    with db_getter() as db:
        try:
            row = db.execute("SELECT MAX(version) FROM _migrations").fetchone()
            val = row[0] if isinstance(row, (tuple, list)) else row["MAX(version)"]
            return val or 0
        except Exception:
            return 0


# Appended by automation — do not duplicate
MIGRATIONS.append((
    12,
    "Create blast_campaigns and blast_contacts tables for mass messaging",
    """
    CREATE TABLE IF NOT EXISTS blast_campaigns (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        connection_id TEXT DEFAULT '',
        name TEXT NOT NULL,
        template_name TEXT NOT NULL,
        template_language TEXT DEFAULT ''pt_BR'',
        total_contacts INTEGER DEFAULT 0,
        sent INTEGER DEFAULT 0,
        delivered INTEGER DEFAULT 0,
        failed INTEGER DEFAULT 0,
        status TEXT DEFAULT ''draft'' CHECK (status IN (''draft'', ''sending'', ''paused'', ''completed'', ''cancelled'')),
        error_rate REAL DEFAULT 0,
        scheduled_at REAL,
        started_at REAL,
        completed_at REAL,
        created_at REAL NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS blast_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        phone TEXT NOT NULL,
        name TEXT DEFAULT '',
        status TEXT DEFAULT ''pending'' CHECK (status IN (''pending'', ''sent'', ''delivered'', ''failed'', ''skipped'')),
        sent_at REAL,
        error_message TEXT DEFAULT '',
        meta_message_id TEXT DEFAULT '',
        created_at REAL NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES blast_campaigns(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_blast_contacts_campaign ON blast_contacts(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_blast_contacts_status ON blast_contacts(status);
    """,
))
