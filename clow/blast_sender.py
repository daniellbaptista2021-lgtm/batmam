"""Blast Campaign Sender — disparo em massa via Meta API com anti-ban."""

import json
import os
import time
import random
import uuid
import threading
import logging
from urllib.request import urlopen, Request
from urllib.error import HTTPError

logger = logging.getLogger("clow.blast")
_active_senders: dict[str, threading.Thread] = {}


def list_templates():
    waba_id = os.getenv("META_WABA_ID", "")
    token = os.getenv("META_ACCESS_TOKEN", "")
    if not waba_id or not token:
        return []
    try:
        url = f"https://graph.facebook.com/v18.0/{waba_id}/message_templates?status=APPROVED&limit=100"
        req = Request(url, headers={"Authorization": f"Bearer {token}"})
        resp = urlopen(req, timeout=15)
        data = json.loads(resp.read().decode())
        return [{"name": t.get("name", ""), "status": t.get("status", ""),
                 "language": t.get("language", ""), "category": t.get("category", ""),
                 "components": t.get("components", [])} for t in data.get("data", [])]
    except Exception as e:
        logger.error(f"List templates error: {e}")
        return []


def create_campaign(user_id, name, template_name, contacts, scheduled_at=0):
    from .database import get_db
    cid = str(uuid.uuid4())[:12]
    now = time.time()
    with get_db() as db:
        db.execute("INSERT INTO blast_campaigns (id,user_id,name,template_name,total_contacts,status,scheduled_at,created_at) VALUES (?,?,?,?,?,?,?,?)",
                   (cid, user_id, name, template_name, len(contacts), "draft", scheduled_at or None, now))
        for c in contacts:
            phone = c.get("phone", "").strip().lstrip("+")
            cname = c.get("name", "").strip()
            if phone:
                db.execute("INSERT INTO blast_contacts (campaign_id,phone,name,status,created_at) VALUES (?,?,?,?,?)",
                           (cid, phone, cname, "pending", now))
    return {"id": cid, "total_contacts": len(contacts), "status": "draft"}


def start_campaign(campaign_id):
    from .database import get_db
    with get_db() as db:
        c = db.execute("SELECT * FROM blast_campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not c:
            return {"error": "Campanha nao encontrada"}
        if c["status"] == "sending":
            return {"error": "Ja em envio"}
        db.execute("UPDATE blast_campaigns SET status='sending', started_at=? WHERE id=?", (time.time(), campaign_id))
    t = threading.Thread(target=_send_campaign, args=(campaign_id,), daemon=True, name=f"blast-{campaign_id}")
    _active_senders[campaign_id] = t
    t.start()
    return {"status": "sending", "campaign_id": campaign_id}


def _send_campaign(campaign_id):
    from .database import get_db
    token = os.getenv("META_ACCESS_TOKEN", "")
    phone_id = os.getenv("META_PHONE_NUMBER_ID", "")
    if not token or not phone_id:
        return

    with get_db() as db:
        campaign = db.execute("SELECT * FROM blast_campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not campaign:
            return
        contacts = db.execute("SELECT * FROM blast_contacts WHERE campaign_id=? AND status='pending' ORDER BY id", (campaign_id,)).fetchall()

    template_name = campaign["template_name"]
    sent = failed = 0

    for contact in contacts:
        from .database import get_db as _gdb
        with _gdb() as db:
            st = db.execute("SELECT status FROM blast_campaigns WHERE id=?", (campaign_id,)).fetchone()
            if st and st["status"] in ("paused", "cancelled"):
                break

        time.sleep(random.uniform(3.0, 10.0))

        try:
            url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
            payload = {"messaging_product": "whatsapp", "to": contact["phone"], "type": "template",
                       "template": {"name": template_name, "language": {"code": "pt_BR"}}}
            if contact["name"]:
                payload["template"]["components"] = [{"type": "body", "parameters": [{"type": "text", "text": contact["name"]}]}]

            data = json.dumps(payload).encode()
            req = Request(url, data=data, headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}, method="POST")
            resp = urlopen(req, timeout=30)
            result = json.loads(resp.read().decode())
            msg_id = result.get("messages", [{}])[0].get("id", "")

            with _gdb() as db:
                db.execute("UPDATE blast_contacts SET status='sent', sent_at=?, meta_message_id=? WHERE id=?", (time.time(), msg_id, contact["id"]))
            sent += 1
        except HTTPError as e:
            err = e.read().decode()[:200] if e.fp else str(e)
            failed += 1
            with _gdb() as db:
                db.execute("UPDATE blast_contacts SET status='failed', error_message=? WHERE id=?", (err, contact["id"]))
        except Exception as e:
            failed += 1
            with _gdb() as db:
                db.execute("UPDATE blast_contacts SET status='failed', error_message=? WHERE id=?", (str(e)[:200], contact["id"]))

        total = sent + failed
        error_rate = (failed / total * 100) if total > 0 else 0
        with _gdb() as db:
            db.execute("UPDATE blast_campaigns SET sent=?, failed=?, error_rate=? WHERE id=?", (sent, failed, error_rate, campaign_id))

        if total >= 10 and error_rate > 5:
            with _gdb() as db:
                db.execute("UPDATE blast_campaigns SET status='paused' WHERE id=?", (campaign_id,))
            break

    from .database import get_db as _gdb
    with _gdb() as db:
        cur = db.execute("SELECT status FROM blast_campaigns WHERE id=?", (campaign_id,)).fetchone()
        if cur and cur["status"] == "sending":
            db.execute("UPDATE blast_campaigns SET status='completed', completed_at=? WHERE id=?", (time.time(), campaign_id))
    _active_senders.pop(campaign_id, None)


def get_campaign_progress(campaign_id):
    from .database import get_db
    with get_db() as db:
        c = db.execute("SELECT * FROM blast_campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not c:
            return {"error": "not found"}
        rows = db.execute("SELECT status, COUNT(*) as count FROM blast_contacts WHERE campaign_id=? GROUP BY status", (campaign_id,)).fetchall()
    sc = {r["status"]: r["count"] for r in rows}
    s = sc.get("sent", 0) + sc.get("delivered", 0)
    return {"id": campaign_id, "name": c["name"], "status": c["status"], "total": c["total_contacts"],
            "sent": s, "failed": sc.get("failed", 0), "pending": sc.get("pending", 0),
            "error_rate": c["error_rate"], "progress_pct": round(s / c["total_contacts"] * 100) if c["total_contacts"] else 0}


def list_campaigns(user_id):
    from .database import get_db
    with get_db() as db:
        return [dict(r) for r in db.execute("SELECT * FROM blast_campaigns WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (user_id,)).fetchall()]


def pause_campaign(campaign_id):
    from .database import get_db
    with get_db() as db:
        db.execute("UPDATE blast_campaigns SET status='paused' WHERE id=? AND status='sending'", (campaign_id,))
    return {"status": "paused"}


def cancel_campaign(campaign_id):
    from .database import get_db
    with get_db() as db:
        db.execute("UPDATE blast_campaigns SET status='cancelled' WHERE id=?", (campaign_id,))
    return {"status": "cancelled"}
