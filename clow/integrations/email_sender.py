"""Email Sender — envio de emails via SMTP para campanhas CRM.

Usa smtplib (stdlib). Configuracoes via .env:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM
"""

from __future__ import annotations

import json
import os
import smtplib
import threading
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..logging import log_action

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@clow.com.br")


def send_email(to: str, subject: str, body_html: str,
               from_name: str = "Clow") -> dict:
    """Envia um email via SMTP. Retorna {success, error}."""
    if not SMTP_HOST or not SMTP_USER:
        return {"success": False, "error": "SMTP nao configurado. Defina SMTP_HOST e SMTP_USER no .env"}

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{from_name} <{SMTP_FROM}>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to, msg.as_string())

        log_action("email_sent", f"to={to} subject={subject[:50]}")
        return {"success": True}
    except Exception as e:
        log_action("email_error", f"to={to} error={str(e)[:200]}", level="error")
        return {"success": False, "error": str(e)[:200]}


def send_campaign(campaign_id: str, tenant_id: str) -> None:
    """Dispara campanha de email em background (thread).

    Busca leads conforme filtro da campanha, envia email para cada um,
    atualiza status dos envios e da campanha.
    """
    def _run():
        from ..crm_models import (
            get_campaign, list_leads, update_campaign_status,
            create_email_send, update_email_send, add_activity,
        )

        campaign = get_campaign(campaign_id, tenant_id)
        if not campaign:
            return

        # Marca como enviando
        update_campaign_status(campaign_id, tenant_id, "sending")

        # Busca leads conforme filtro
        recipient_filter = {}
        if campaign.get("recipient_filter"):
            try:
                recipient_filter = json.loads(campaign["recipient_filter"])
            except (json.JSONDecodeError, TypeError):
                pass

        status_filter = recipient_filter.get("status", "")
        result = list_leads(tenant_id, status=status_filter, limit=1000)
        leads = [l for l in result["leads"] if l.get("email")]

        if not leads:
            update_campaign_status(campaign_id, tenant_id, "sent",
                                   total_recipients=0, sent_count=0, sent_at=time.time())
            return

        update_campaign_status(campaign_id, tenant_id, "sending",
                               total_recipients=len(leads))

        sent = 0
        for lead in leads:
            send_id = create_email_send(campaign_id, lead["id"], lead["email"])

            result = send_email(
                to=lead["email"],
                subject=campaign["subject"],
                body_html=campaign["body_html"],
            )

            if result["success"]:
                update_email_send(send_id, status="sent", sent_at=time.time())
                add_activity(lead["id"], tenant_id, "email",
                             f"Email campanha: {campaign['name']}")
                sent += 1
            else:
                update_email_send(send_id, status="bounced")

            # Rate limit: 1 email por segundo
            time.sleep(1)

        update_campaign_status(campaign_id, tenant_id, "sent",
                               sent_count=sent, sent_at=time.time())
        log_action("campaign_sent", f"id={campaign_id} sent={sent}/{len(leads)}")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def send_followup_email(lead_id: str, tenant_id: str, subject: str = "",
                        body: str = "") -> dict:
    """Envia email de follow-up para um lead especifico."""
    from ..crm_models import get_lead, add_activity

    lead = get_lead(lead_id, tenant_id)
    if not lead or not lead.get("email"):
        return {"success": False, "error": "Lead sem email"}

    if not subject:
        subject = f"Ola {lead.get('name', '')}, tudo bem?"
    if not body:
        body = f"""<p>Ola {lead.get('name', '')},</p>
        <p>Estamos entrando em contato para saber se podemos ajudar em algo.</p>
        <p>Ficamos a disposicao!</p>"""

    result = send_email(lead["email"], subject, body)
    if result["success"]:
        add_activity(lead_id, tenant_id, "email", f"Follow-up: {subject}")
    return result
