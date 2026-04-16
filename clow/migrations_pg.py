"""PostgreSQL migrations for Clow.

Converts the SQLite schema to PostgreSQL-compatible DDL.
Called by db_postgres.init_db().
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

PG_SCHEMA = """
-- Core tables
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT DEFAULT '',
    plan TEXT DEFAULT 'free',
    active INTEGER DEFAULT 1,
    is_admin INTEGER DEFAULT 0,
    created_at DOUBLE PRECISION NOT NULL,
    last_login DOUBLE PRECISION,
    anthropic_api_key TEXT DEFAULT '',
    byok_enabled INTEGER DEFAULT 0,
    api_key_set_at DOUBLE PRECISION DEFAULT 0,
    preferences TEXT DEFAULT '{}',
    payment_status TEXT DEFAULT 'ok',
    payment_overdue_since DOUBLE PRECISION DEFAULT 0,
    stripe_customer_id TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS usage_log (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    model TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd DOUBLE PRECISION DEFAULT 0,
    action TEXT DEFAULT 'chat',
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_user_date ON usage_log(user_id, created_at);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    title TEXT DEFAULT 'Nova conversa',
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    file_data TEXT,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, created_at);

-- Missions
CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT DEFAULT 'planning',
    plan_json TEXT,
    context_json TEXT DEFAULT '{}',
    current_step INTEGER DEFAULT 0,
    total_steps INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    completed_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_missions_user ON missions(user_id, created_at);

CREATE TABLE IF NOT EXISTS mission_steps (
    id SERIAL PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'pending',
    model TEXT DEFAULT 'haiku',
    result_json TEXT,
    error TEXT,
    attempts INTEGER DEFAULT 0,
    started_at DOUBLE PRECISION,
    completed_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_msteps_mission ON mission_steps(mission_id, step_number);

-- CRM
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
    last_contact_at DOUBLE PRECISION,
    next_followup_at DOUBLE PRECISION,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    instance_id TEXT DEFAULT '',
    source_phone TEXT DEFAULT '',
    deal_value DOUBLE PRECISION DEFAULT 0,
    deal_closed_at DOUBLE PRECISION DEFAULT 0,
    deal_products TEXT DEFAULT '',
    deal_notes TEXT DEFAULT '',
    cost_tokens_used INTEGER DEFAULT 0,
    cost_estimated_brl DOUBLE PRECISION DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_leads_tenant ON leads(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);
CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
CREATE INDEX IF NOT EXISTS idx_leads_instance ON leads(tenant_id, instance_id);

CREATE TABLE IF NOT EXISTS lead_activities (
    id SERIAL PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads(id),
    tenant_id TEXT NOT NULL,
    type TEXT NOT NULL,
    content TEXT,
    metadata TEXT,
    created_at DOUBLE PRECISION NOT NULL
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
    scheduled_at DOUBLE PRECISION,
    sent_at DOUBLE PRECISION,
    created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS email_sends (
    id SERIAL PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES email_campaigns(id),
    lead_id TEXT NOT NULL,
    email TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    sent_at DOUBLE PRECISION,
    opened_at DOUBLE PRECISION
);

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
    created_at DOUBLE PRECISION NOT NULL
);

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
    created_at DOUBLE PRECISION NOT NULL
);

-- WhatsApp
CREATE TABLE IF NOT EXISTS whatsapp_connections (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    plan_slot INTEGER DEFAULT 1,
    instance_id TEXT NOT NULL,
    token TEXT NOT NULL,
    name TEXT DEFAULT 'Meu WhatsApp',
    status TEXT DEFAULT 'disconnected',
    webhook_url TEXT DEFAULT '',
    last_seen DOUBLE PRECISION DEFAULT 0,
    last_health_check DOUBLE PRECISION DEFAULT 0,
    created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_configs (
    id SERIAL PRIMARY KEY,
    connection_id TEXT NOT NULL REFERENCES whatsapp_connections(id),
    prompt TEXT DEFAULT '',
    personality_name TEXT DEFAULT 'Assistente',
    personality_tone TEXT DEFAULT 'casual',
    language TEXT DEFAULT 'pt-BR',
    business_hours_enabled INTEGER DEFAULT 0,
    business_hours_start TEXT DEFAULT '08:00',
    business_hours_end TEXT DEFAULT '18:00',
    business_days TEXT DEFAULT '1,2,3,4,5',
    out_of_hours_message TEXT DEFAULT '',
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
    temperature DOUBLE PRECISION DEFAULT 0.3,
    max_tokens INTEGER DEFAULT 1024
);

CREATE TABLE IF NOT EXISTS wa_message_logs (
    id SERIAL PRIMARY KEY,
    connection_id TEXT NOT NULL,
    phone TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('incoming', 'outgoing')),
    content TEXT NOT NULL,
    tokens_used INTEGER DEFAULT 0,
    resolved_by_ai INTEGER DEFAULT 1,
    transferred_to_human INTEGER DEFAULT 0,
    response_time_ms INTEGER DEFAULT 0,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wa_logs_conn ON wa_message_logs(connection_id, created_at);
CREATE INDEX IF NOT EXISTS idx_wa_logs_phone ON wa_message_logs(phone, created_at);

-- Web sessions
CREATE TABLE IF NOT EXISTS web_sessions (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    user_id TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0,
    plan TEXT DEFAULT 'free',
    created DOUBLE PRECISION NOT NULL
);

-- Stats
CREATE TABLE IF NOT EXISTS daily_stats (
    id SERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    date TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_requests INTEGER DEFAULT 0,
    estimated_cost_usd DOUBLE PRECISION DEFAULT 0,
    created_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW()),
    UNIQUE(tenant_id, date)
);

-- Migration tracking
CREATE TABLE IF NOT EXISTS _pg_migrations (
    version INTEGER PRIMARY KEY,
    description TEXT,
    applied_at DOUBLE PRECISION
);
"""


def run_pg_migrations():
    """Apply PostgreSQL schema. Each statement runs in its own transaction."""
    import time
    from .db_postgres import _get_pool

    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = True  # Each statement is its own transaction

    try:
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Remove comment lines before splitting
        clean_schema = "\n".join(
            line for line in PG_SCHEMA.splitlines()
            if not line.strip().startswith("--")
        )
        for stmt in clean_schema.split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                cur.execute(stmt)
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.warning("PG migration: %s — %s", stmt[:80], e)

        # Record migration
        try:
            cur.execute(
                "INSERT INTO _pg_migrations (version, description, applied_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (1, "Full schema", time.time()),
            )
        except Exception:
            pass

        cur.close()
        logger.info("PostgreSQL migrations applied successfully")
    except Exception as e:
        logger.error("PostgreSQL migration failed: %s", e)
        raise
    finally:
        conn.autocommit = False
        pool.putconn(conn)
