"""CRM Models — tabelas e CRUD para leads, campanhas, agendamentos.

Usa o mesmo SQLite do Clow via database.get_db().
Todas as operações filtram por tenant_id para isolamento multi-tenant.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .database import get_db


# ── Helpers ──────────────────────────────────────────────────

def _uid() -> str:
    """Gera um UUID curto (12 chars)."""
    return uuid.uuid4().hex[:12]


def _now() -> float:
    return time.time()


def _row_to_dict(row) -> dict | None:
    if row is None:
        return None
    return dict(row)


def _rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ── Init Tables ──────────────────────────────────────────────

CRM_SCHEMA = """
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
    instance_id TEXT DEFAULT '',
    source_phone TEXT DEFAULT '',
    last_contact_at REAL,
    next_followup_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_leads_tenant ON leads(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_leads_instance ON leads(tenant_id, instance_id);
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
"""


def init_crm_tables() -> None:
    """Cria todas as tabelas do CRM se nao existirem."""
    with get_db() as db:
        db.executescript(CRM_SCHEMA)


# ══════════════════════════════════════════════════════════════
# LEADS — CRUD
# ══════════════════════════════════════════════════════════════

def create_lead(tenant_id: str, name: str = "", email: str = "",
                phone: str = "", source: str = "manual",
                notes: str = "", tags: list | None = None,
                custom_fields: dict | None = None,
                instance_id: str = "", source_phone: str = "") -> dict:
    """Cria um novo lead. Retorna o lead criado."""
    lead_id = _uid()
    now = _now()
    with get_db() as db:
        db.execute(
            """INSERT INTO leads (id, tenant_id, name, email, phone, source,
               status, score, notes, tags, custom_fields,
               instance_id, source_phone, created_at, updated_at)
               VALUES (?,?,?,?,?,?, 'novo', 0, ?,?,?, ?,?, ?,?)""",
            (lead_id, tenant_id, name, email, phone, source,
             notes, json.dumps(tags or []), json.dumps(custom_fields or {}),
             instance_id, source_phone, now, now),
        )
        # Registra atividade de criacao
        db.execute(
            "INSERT INTO lead_activities (lead_id, tenant_id, type, content, created_at) VALUES (?,?,?,?,?)",
            (lead_id, tenant_id, "note", f"Lead criado via {source}", now),
        )
    return get_lead(lead_id, tenant_id)


def get_lead(lead_id: str, tenant_id: str) -> dict | None:
    """Retorna um lead pelo ID."""
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM leads WHERE id=? AND tenant_id=?",
            (lead_id, tenant_id),
        ).fetchone()
        return _row_to_dict(row)


def update_lead(lead_id: str, tenant_id: str, **kwargs) -> dict | None:
    """Atualiza campos do lead."""
    allowed = {"name", "email", "phone", "source", "status", "score",
               "assigned_to", "notes", "tags", "custom_fields",
               "instance_id", "source_phone",
               "deal_value", "deal_closed_at", "deal_products", "deal_notes",
               "cost_tokens_used", "cost_estimated_brl",
               "last_contact_at", "next_followup_at"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_lead(lead_id, tenant_id)

    # Serializa listas/dicts
    if "tags" in updates and isinstance(updates["tags"], list):
        updates["tags"] = json.dumps(updates["tags"])
    if "custom_fields" in updates and isinstance(updates["custom_fields"], dict):
        updates["custom_fields"] = json.dumps(updates["custom_fields"])

    updates["updated_at"] = _now()
    # Build SET clause safely — field names from hardcoded whitelist only
    set_parts = []
    values = []
    for field_name in sorted(updates):
        set_parts.append(f"{field_name}=?")
        values.append(updates[field_name])
    values.extend([lead_id, tenant_id])
    sql = "UPDATE leads SET " + ", ".join(set_parts) + " WHERE id=? AND tenant_id=?"
    with get_db() as db:
        db.execute(sql, values)
    return get_lead(lead_id, tenant_id)


def delete_lead(lead_id: str, tenant_id: str) -> bool:
    """Remove um lead e suas atividades."""
    with get_db() as db:
        db.execute("DELETE FROM lead_activities WHERE lead_id=? AND tenant_id=?",
                   (lead_id, tenant_id))
        r = db.execute("DELETE FROM leads WHERE id=? AND tenant_id=?",
                       (lead_id, tenant_id))
        return r.rowcount > 0


def list_leads(tenant_id: str, status: str = "", source: str = "",
               instance_id: str = "",
               page: int = 1, limit: int = 50) -> dict:
    """Lista leads com filtros. Retorna {leads, total, page, pages}."""
    conditions = ["tenant_id=?"]
    params: list[Any] = [tenant_id]

    if instance_id:
        conditions.append("instance_id=?")
        params.append(instance_id)
    if status:
        conditions.append("status=?")
        params.append(status)
    if source:
        conditions.append("source=?")
        params.append(source)

    where = " AND ".join(conditions)
    offset = (page - 1) * limit

    with get_db() as db:
        total = db.execute(f"SELECT COUNT(*) FROM leads WHERE {where}", params).fetchone()[0]
        rows = db.execute(
            f"SELECT * FROM leads WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

    return {
        "leads": _rows_to_list(rows),
        "total": total,
        "page": page,
        "pages": max(1, (total + limit - 1) // limit),
    }


def search_leads(tenant_id: str, query: str) -> list[dict]:
    """Busca leads por nome, email ou telefone."""
    q = f"%{query}%"
    with get_db() as db:
        rows = db.execute(
            """SELECT * FROM leads WHERE tenant_id=?
               AND (name LIKE ? OR email LIKE ? OR phone LIKE ?)
               ORDER BY updated_at DESC LIMIT 50""",
            (tenant_id, q, q, q),
        ).fetchall()
    return _rows_to_list(rows)


def get_lead_by_phone(tenant_id: str, phone: str) -> dict | None:
    """Busca lead por telefone."""
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM leads WHERE tenant_id=? AND phone=? LIMIT 1",
            (tenant_id, phone),
        ).fetchone()
        return _row_to_dict(row)


def get_lead_by_email(tenant_id: str, email: str) -> dict | None:
    """Busca lead por email."""
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM leads WHERE tenant_id=? AND email=? LIMIT 1",
            (tenant_id, email),
        ).fetchone()
        return _row_to_dict(row)


# ══════════════════════════════════════════════════════════════
# LEAD ACTIVITIES (Timeline)
# ══════════════════════════════════════════════════════════════

def add_activity(lead_id: str, tenant_id: str, activity_type: str,
                 content: str = "", metadata: dict | None = None) -> int:
    """Adiciona atividade ao lead e atualiza last_contact_at."""
    now = _now()
    with get_db() as db:
        cursor = db.execute(
            """INSERT INTO lead_activities (lead_id, tenant_id, type, content, metadata, created_at)
               VALUES (?,?,?,?,?,?)""",
            (lead_id, tenant_id, activity_type, content,
             json.dumps(metadata or {}), now),
        )
        # Atualiza last_contact_at
        if activity_type in ("whatsapp", "email", "call", "meeting"):
            db.execute(
                "UPDATE leads SET last_contact_at=?, updated_at=? WHERE id=? AND tenant_id=?",
                (now, now, lead_id, tenant_id),
            )
        return cursor.lastrowid


def get_lead_timeline(lead_id: str, tenant_id: str = "") -> list[dict]:
    """Retorna todas as atividades do lead em ordem cronologica."""
    with get_db() as db:
        if tenant_id:
            rows = db.execute(
                "SELECT * FROM lead_activities WHERE lead_id=? AND tenant_id=? ORDER BY created_at ASC",
                (lead_id, tenant_id),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM lead_activities WHERE lead_id=? ORDER BY created_at ASC",
                (lead_id,),
            ).fetchall()
    return _rows_to_list(rows)


def change_lead_status(lead_id: str, tenant_id: str, new_status: str) -> dict | None:
    """Muda status do lead e registra na timeline."""
    lead = get_lead(lead_id, tenant_id)
    if not lead:
        return None
    old_status = lead.get("status", "")
    update_lead(lead_id, tenant_id, status=new_status)
    add_activity(lead_id, tenant_id, "status_change",
                 f"Status: {old_status} → {new_status}")
    return get_lead(lead_id, tenant_id)


# ══════════════════════════════════════════════════════════════
# EMAIL CAMPAIGNS
# ══════════════════════════════════════════════════════════════

def create_campaign(tenant_id: str, name: str, subject: str,
                    body_html: str, recipient_filter: dict | None = None) -> dict:
    """Cria uma campanha de email."""
    cid = _uid()
    now = _now()
    with get_db() as db:
        db.execute(
            """INSERT INTO email_campaigns (id, tenant_id, name, subject, body_html,
               recipient_filter, created_at) VALUES (?,?,?,?,?,?,?)""",
            (cid, tenant_id, name, subject, body_html,
             json.dumps(recipient_filter or {}), now),
        )
    return get_campaign(cid, tenant_id)


def get_campaign(campaign_id: str, tenant_id: str) -> dict | None:
    """Retorna campanha com metricas."""
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM email_campaigns WHERE id=? AND tenant_id=?",
            (campaign_id, tenant_id),
        ).fetchone()
        return _row_to_dict(row)


def update_campaign(campaign_id: str, tenant_id: str, **kwargs) -> dict | None:
    """Atualiza campanha (so se draft)."""
    campaign = get_campaign(campaign_id, tenant_id)
    if not campaign or campaign["status"] != "draft":
        return None

    allowed = {"name", "subject", "body_html", "recipient_filter", "scheduled_at"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if "recipient_filter" in updates and isinstance(updates["recipient_filter"], dict):
        updates["recipient_filter"] = json.dumps(updates["recipient_filter"])
    if not updates:
        return campaign

    set_parts = []
    values = []
    for field_name in sorted(updates):
        set_parts.append(f"{field_name}=?")
        values.append(updates[field_name])
    values.extend([campaign_id, tenant_id])
    sql = "UPDATE email_campaigns SET " + ", ".join(set_parts) + " WHERE id=? AND tenant_id=?"
    with get_db() as db:
        db.execute(sql, values)
    return get_campaign(campaign_id, tenant_id)


def delete_campaign(campaign_id: str, tenant_id: str) -> bool:
    """Remove campanha e seus envios."""
    with get_db() as db:
        db.execute("DELETE FROM email_sends WHERE campaign_id=?", (campaign_id,))
        r = db.execute("DELETE FROM email_campaigns WHERE id=? AND tenant_id=?",
                       (campaign_id, tenant_id))
        return r.rowcount > 0


def list_campaigns(tenant_id: str, status: str = "") -> list[dict]:
    """Lista campanhas do tenant."""
    with get_db() as db:
        if status:
            rows = db.execute(
                "SELECT * FROM email_campaigns WHERE tenant_id=? AND status=? ORDER BY created_at DESC",
                (tenant_id, status),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM email_campaigns WHERE tenant_id=? ORDER BY created_at DESC",
                (tenant_id,),
            ).fetchall()
    return _rows_to_list(rows)


def update_campaign_status(campaign_id: str, tenant_id: str, status: str, **extra) -> None:
    """Atualiza status da campanha com campos extras (sent_at, sent_count, etc)."""
    _ALLOWED_EXTRA = {"sent_at", "sent_count", "error_count", "failed_count"}
    fields = {"status": status}
    fields.update({k: v for k, v in extra.items() if k in _ALLOWED_EXTRA})
    set_parts = []
    values = []
    for field_name in sorted(fields):
        set_parts.append(f"{field_name}=?")
        values.append(fields[field_name])
    values.extend([campaign_id, tenant_id])
    sql = "UPDATE email_campaigns SET " + ", ".join(set_parts) + " WHERE id=? AND tenant_id=?"
    with get_db() as db:
        db.execute(sql, values)


def create_email_send(campaign_id: str, lead_id: str, email: str) -> int:
    """Registra um envio de email."""
    with get_db() as db:
        c = db.execute(
            "INSERT INTO email_sends (campaign_id, lead_id, email) VALUES (?,?,?)",
            (campaign_id, lead_id, email),
        )
        return c.lastrowid


def update_email_send(send_id: int, **kwargs) -> None:
    """Atualiza status de um envio."""
    _ALLOWED = {"status", "sent_at", "opened_at"}
    updates = {k: v for k, v in kwargs.items() if k in _ALLOWED}
    if not updates:
        return
    set_parts = []
    values = []
    for field_name in sorted(updates):
        set_parts.append(f"{field_name}=?")
        values.append(updates[field_name])
    values.append(send_id)
    sql = "UPDATE email_sends SET " + ", ".join(set_parts) + " WHERE id=?"
    with get_db() as db:
        db.execute(sql, values)


def get_campaign_sends(campaign_id: str) -> list[dict]:
    """Lista envios de uma campanha."""
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM email_sends WHERE campaign_id=? ORDER BY id",
            (campaign_id,),
        ).fetchall()
    return _rows_to_list(rows)


# ══════════════════════════════════════════════════════════════
# APPOINTMENTS (Agendamentos)
# ══════════════════════════════════════════════════════════════

def create_appointment(tenant_id: str, name: str, date: str, time_str: str,
                       email: str = "", phone: str = "", lead_id: str = "",
                       duration: int = 30, notes: str = "",
                       meeting_link: str = "") -> dict:
    """Cria um agendamento."""
    aid = _uid()
    with get_db() as db:
        db.execute(
            """INSERT INTO appointments (id, tenant_id, lead_id, name, email, phone,
               date, time, duration_minutes, notes, meeting_link, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (aid, tenant_id, lead_id, name, email, phone,
             date, time_str, duration, notes, meeting_link, _now()),
        )
    return get_appointment(aid, tenant_id)


def get_appointment(apt_id: str, tenant_id: str) -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM appointments WHERE id=? AND tenant_id=?",
            (apt_id, tenant_id),
        ).fetchone()
        return _row_to_dict(row)


def update_appointment(apt_id: str, tenant_id: str, **kwargs) -> dict | None:
    _ALLOWED = {"status", "notes", "meeting_link", "name", "email", "phone"}
    updates = {k: v for k, v in kwargs.items() if k in _ALLOWED}
    if not updates:
        return get_appointment(apt_id, tenant_id)
    set_parts = []
    values = []
    for field_name in sorted(updates):
        set_parts.append(f"{field_name}=?")
        values.append(updates[field_name])
    values.extend([apt_id, tenant_id])
    sql = "UPDATE appointments SET " + ", ".join(set_parts) + " WHERE id=? AND tenant_id=?"
    with get_db() as db:
        db.execute(sql, values)
    return get_appointment(apt_id, tenant_id)


def list_appointments(tenant_id: str, date: str = "", status: str = "") -> list[dict]:
    """Lista agendamentos. Filtros opcionais por data e status."""
    conditions = ["tenant_id=?"]
    params: list[Any] = [tenant_id]
    if date:
        conditions.append("date=?")
        params.append(date)
    if status:
        conditions.append("status=?")
        params.append(status)
    where = " AND ".join(conditions)
    with get_db() as db:
        rows = db.execute(
            f"SELECT * FROM appointments WHERE {where} ORDER BY date, time",
            params,
        ).fetchall()
    return _rows_to_list(rows)


# ══════════════════════════════════════════════════════════════
# SCHEDULING LINKS
# ══════════════════════════════════════════════════════════════

def create_scheduling_link(tenant_id: str, slug: str, title: str,
                           duration: int = 30, days: str = "1,2,3,4,5",
                           start: str = "09:00", end: str = "18:00") -> dict:
    """Cria um link de agendamento."""
    with get_db() as db:
        db.execute(
            """INSERT INTO scheduling_links (id, tenant_id, title, duration_minutes,
               available_days, available_start, available_end, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (slug, tenant_id, title, duration, days, start, end, _now()),
        )
    return get_scheduling_link(slug)


def get_scheduling_link(slug: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM scheduling_links WHERE id=?", (slug,)).fetchone()
        return _row_to_dict(row)


def update_scheduling_link(slug: str, tenant_id: str, **kwargs) -> dict | None:
    _ALLOWED = {"title", "duration_minutes", "available_days", "available_start",
                "available_end", "blocked_times", "active"}
    updates = {k: v for k, v in kwargs.items() if k in _ALLOWED}
    if not updates:
        return get_scheduling_link(slug)
    set_parts = []
    values = []
    for field_name in sorted(updates):
        set_parts.append(f"{field_name}=?")
        values.append(updates[field_name])
    values.extend([slug, tenant_id])
    sql = "UPDATE scheduling_links SET " + ", ".join(set_parts) + " WHERE id=? AND tenant_id=?"
    with get_db() as db:
        db.execute(sql, values)
    return get_scheduling_link(slug)


def delete_scheduling_link(slug: str, tenant_id: str) -> bool:
    with get_db() as db:
        r = db.execute("DELETE FROM scheduling_links WHERE id=? AND tenant_id=?",
                       (slug, tenant_id))
        return r.rowcount > 0


def list_scheduling_links(tenant_id: str) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM scheduling_links WHERE tenant_id=? ORDER BY created_at DESC",
            (tenant_id,),
        ).fetchall()
    return _rows_to_list(rows)


def get_available_slots(slug: str, date: str) -> list[str]:
    """Retorna horarios disponiveis para uma data em um link de agendamento."""
    link = get_scheduling_link(slug)
    if not link or not link["active"]:
        return []

    # Verifica se o dia da semana esta disponivel
    from datetime import datetime
    dt = datetime.strptime(date, "%Y-%m-%d")
    day_of_week = dt.isoweekday()  # 1=seg, 7=dom
    available_days = [int(d) for d in link["available_days"].split(",") if d.strip()]
    if day_of_week not in available_days:
        return []

    # Gera slots
    start_h, start_m = map(int, link["available_start"].split(":"))
    end_h, end_m = map(int, link["available_end"].split(":"))
    duration = link["duration_minutes"]

    slots = []
    current = start_h * 60 + start_m
    end_min = end_h * 60 + end_m

    while current + duration <= end_min:
        slot_time = f"{current // 60:02d}:{current % 60:02d}"
        slots.append(slot_time)
        current += duration

    # Remove horarios ja agendados
    tenant_id = link["tenant_id"]
    with get_db() as db:
        booked = db.execute(
            "SELECT time FROM appointments WHERE tenant_id=? AND date=? AND status='confirmado'",
            (tenant_id, date),
        ).fetchall()
    booked_times = {r[0] for r in booked}

    # Remove bloqueados
    blocked = []
    if link.get("blocked_times"):
        try:
            blocked = json.loads(link["blocked_times"])
        except (json.JSONDecodeError, TypeError):
            pass

    return [s for s in slots if s not in booked_times and s not in blocked]


# ══════════════════════════════════════════════════════════════
# DASHBOARD & ANALYTICS
# ══════════════════════════════════════════════════════════════

def get_dashboard_stats(tenant_id: str) -> dict:
    """Retorna estatisticas do CRM para o dashboard."""
    now = _now()
    today_start = now - (now % 86400)
    week_start = now - 7 * 86400

    with get_db() as db:
        # Leads por status
        status_rows = db.execute(
            "SELECT status, COUNT(*) as cnt FROM leads WHERE tenant_id=? GROUP BY status",
            (tenant_id,),
        ).fetchall()
        leads_by_status = {r["status"]: r["cnt"] for r in status_rows}

        # Total leads
        total_leads = sum(leads_by_status.values())

        # Leads novos (7 dias)
        new_leads_week = db.execute(
            "SELECT COUNT(*) FROM leads WHERE tenant_id=? AND created_at>=?",
            (tenant_id, week_start),
        ).fetchone()[0]

        # Emails enviados hoje e semana
        emails_today = db.execute(
            """SELECT COUNT(*) FROM email_sends es
               JOIN email_campaigns ec ON es.campaign_id=ec.id
               WHERE ec.tenant_id=? AND es.sent_at>=?""",
            (tenant_id, today_start),
        ).fetchone()[0]

        emails_week = db.execute(
            """SELECT COUNT(*) FROM email_sends es
               JOIN email_campaigns ec ON es.campaign_id=ec.id
               WHERE ec.tenant_id=? AND es.sent_at>=?""",
            (tenant_id, week_start),
        ).fetchone()[0]

        # Agendamentos hoje e semana
        from datetime import datetime, timedelta
        today_str = datetime.utcfromtimestamp(today_start).strftime("%Y-%m-%d")
        week_str = datetime.utcfromtimestamp(week_start).strftime("%Y-%m-%d")

        appointments_today = db.execute(
            "SELECT COUNT(*) FROM appointments WHERE tenant_id=? AND date=?",
            (tenant_id, today_str),
        ).fetchone()[0]

        appointments_week = db.execute(
            "SELECT COUNT(*) FROM appointments WHERE tenant_id=? AND date>=?",
            (tenant_id, week_str),
        ).fetchone()[0]

        # Mensagens WhatsApp hoje
        wa_today = db.execute(
            """SELECT COUNT(*) FROM lead_activities
               WHERE tenant_id=? AND type='whatsapp' AND created_at>=?""",
            (tenant_id, today_start),
        ).fetchone()[0]

    return {
        "total_leads": total_leads,
        "leads_by_status": leads_by_status,
        "new_leads_week": new_leads_week,
        "emails_today": emails_today,
        "emails_week": emails_week,
        "appointments_today": appointments_today,
        "appointments_week": appointments_week,
        "wa_messages_today": wa_today,
    }


def get_stale_leads(tenant_id: str, days: int = 3, instance_id: str = "") -> list[dict]:
    """Retorna leads sem contato ha X dias e com status ativo."""
    cutoff = _now() - (days * 86400)
    conditions = ["tenant_id=?", "status NOT IN ('ganho', 'perdido')",
                  "(last_contact_at IS NULL OR last_contact_at < ?)"]
    params: list[Any] = [tenant_id, cutoff]
    if instance_id:
        conditions.append("instance_id=?")
        params.append(instance_id)
    where = " AND ".join(conditions)
    with get_db() as db:
        rows = db.execute(
            f"SELECT * FROM leads WHERE {where} ORDER BY last_contact_at ASC NULLS FIRST LIMIT 50",
            params,
        ).fetchall()
    return _rows_to_list(rows)


def get_instance_metrics(tenant_id: str, instance_id: str) -> dict:
    """Retorna metricas filtradas por instancia Z-API."""
    now = _now()
    today_start = now - (now % 86400)
    week_start = now - 7 * 86400

    with get_db() as db:
        # Leads total
        total = db.execute(
            "SELECT COUNT(*) FROM leads WHERE tenant_id=? AND instance_id=?",
            (tenant_id, instance_id),
        ).fetchone()[0]

        # Leads hoje
        today = db.execute(
            "SELECT COUNT(*) FROM leads WHERE tenant_id=? AND instance_id=? AND created_at>=?",
            (tenant_id, instance_id, today_start),
        ).fetchone()[0]

        # Leads semana
        week = db.execute(
            "SELECT COUNT(*) FROM leads WHERE tenant_id=? AND instance_id=? AND created_at>=?",
            (tenant_id, instance_id, week_start),
        ).fetchone()[0]

        # Leads por status
        status_rows = db.execute(
            "SELECT status, COUNT(*) as cnt FROM leads WHERE tenant_id=? AND instance_id=? GROUP BY status",
            (tenant_id, instance_id),
        ).fetchall()
        pipeline = {r["status"]: r["cnt"] for r in status_rows}

        # Msgs WhatsApp hoje (filtra por leads da instancia)
        msgs_today = db.execute(
            """SELECT COUNT(*) FROM lead_activities la
               JOIN leads l ON la.lead_id=l.id
               WHERE l.tenant_id=? AND l.instance_id=? AND la.type='whatsapp' AND la.created_at>=?""",
            (tenant_id, instance_id, today_start),
        ).fetchone()[0]

        # Conversoes semana (leads que ficaram 'ganho' esta semana)
        conversions = db.execute(
            """SELECT COUNT(*) FROM lead_activities la
               JOIN leads l ON la.lead_id=l.id
               WHERE l.tenant_id=? AND l.instance_id=? AND la.type='status_change'
               AND la.content LIKE '%ganho%' AND la.created_at>=?""",
            (tenant_id, instance_id, week_start),
        ).fetchone()[0]

    return {
        "instance_id": instance_id,
        "leads_total": total,
        "leads_today": today,
        "leads_this_week": week,
        "messages_today": msgs_today,
        "conversions_this_week": conversions,
        "pipeline": pipeline,
    }


def get_leads_count_by_instance(tenant_id: str) -> dict:
    """Retorna contagem de leads por instance_id."""
    now = _now()
    today_start = now - (now % 86400)
    with get_db() as db:
        rows = db.execute(
            """SELECT instance_id, COUNT(*) as total,
               SUM(CASE WHEN created_at>=? THEN 1 ELSE 0 END) as new_today
               FROM leads WHERE tenant_id=? GROUP BY instance_id""",
            (today_start, tenant_id),
        ).fetchall()
    return {r["instance_id"]: {"total": r["total"], "new_today": r["new_today"]} for r in rows}


def get_results_data(tenant_id: str, instance_id: str = "", period_days: int = 30) -> dict:
    """Retorna metricas de conversao e ROI."""
    now = _now()
    period_start = now - period_days * 86400
    prev_start = period_start - period_days * 86400

    conds = ["tenant_id=?"]
    params: list[Any] = [tenant_id]
    if instance_id:
        conds.append("instance_id=?")
        params.append(instance_id)
    where = " AND ".join(conds)

    with get_db() as db:
        # Receita atual
        rev = db.execute(
            f"SELECT COALESCE(SUM(deal_value),0) FROM leads WHERE {where} AND status='ganho' AND deal_closed_at>=?",
            params + [period_start],
        ).fetchone()[0]

        # Receita periodo anterior
        rev_prev = db.execute(
            f"SELECT COALESCE(SUM(deal_value),0) FROM leads WHERE {where} AND status='ganho' AND deal_closed_at>=? AND deal_closed_at<?",
            params + [prev_start, period_start],
        ).fetchone()[0]

        # Deals fechados
        deals = db.execute(
            f"SELECT COUNT(*) FROM leads WHERE {where} AND status='ganho' AND deal_closed_at>=?",
            params + [period_start],
        ).fetchone()[0]
        deals_prev = db.execute(
            f"SELECT COUNT(*) FROM leads WHERE {where} AND status='ganho' AND deal_closed_at>=? AND deal_closed_at<?",
            params + [prev_start, period_start],
        ).fetchone()[0]

        # Funil
        funnel_rows = db.execute(
            f"SELECT status, COUNT(*) as cnt FROM leads WHERE {where} GROUP BY status",
            params,
        ).fetchall()
        funnel = {r["status"]: r["cnt"] for r in funnel_rows}
        total_leads = sum(funnel.values())

        # Custo tokens
        cost = db.execute(
            f"SELECT COALESCE(SUM(cost_estimated_brl),0) FROM leads WHERE {where} AND created_at>=?",
            params + [period_start],
        ).fetchone()[0]

        # Receita diaria (ultimos N dias)
        daily = []
        for i in range(min(period_days, 30)):
            day_start = now - (i + 1) * 86400
            day_end = now - i * 86400
            day_rev = db.execute(
                f"SELECT COALESCE(SUM(deal_value),0) FROM leads WHERE {where} AND status='ganho' AND deal_closed_at>=? AND deal_closed_at<?",
                params + [day_start, day_end],
            ).fetchone()[0]
            from datetime import datetime
            day_str = datetime.utcfromtimestamp(day_start).strftime("%d/%m")
            daily.append({"date": day_str, "value": day_rev})
        daily.reverse()

        # Ultimas vendas
        sales = db.execute(
            f"SELECT name, deal_value, deal_closed_at, source FROM leads WHERE {where} AND status='ganho' AND deal_value>0 ORDER BY deal_closed_at DESC LIMIT 10",
            params,
        ).fetchall()
        recent_sales = [{"name": r["name"], "value": r["deal_value"],
                         "date": r["deal_closed_at"], "source": r["source"]} for r in sales]

    avg_ticket = rev / deals if deals > 0 else 0
    # ROI: estima custo do plano como R$115 (Starter)
    plan_cost = 115
    total_cost = plan_cost + cost
    roi = ((rev - total_cost) / total_cost * 100) if total_cost > 0 else 0

    return {
        "revenue_total": round(rev, 2),
        "revenue_previous": round(rev_prev, 2),
        "deals_closed": deals,
        "deals_previous": deals_prev,
        "avg_ticket": round(avg_ticket, 2),
        "roi_percent": round(roi, 1),
        "funnel": funnel,
        "total_leads": total_leads,
        "cost_tokens": round(cost, 2),
        "cost_plan": plan_cost,
        "daily_revenue": daily,
        "recent_sales": recent_sales,
    }
