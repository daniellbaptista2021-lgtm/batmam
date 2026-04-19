"""Follow-up automatico pos-assinatura.

Thread daemon que roda 1x/dia. Para cada usuario que:
- ja concluiu onboarding (onboarding_completed=1)
- tem plano pago (lite/starter/pro/business)
- ainda NAO conectou WhatsApp (get_whatsapp_credentials retorna None ou status!=connected)
Envia email de lembrete com 1, 3 e 7 dias desde o created_at.

Flags de controle no DB (auto-criadas):
- users.followup_wa_1d_sent (0/1)
- users.followup_wa_3d_sent (0/1)
- users.followup_wa_7d_sent (0/1)

Se SMTP nao estiver configurado, o scheduler continua rodando mas os emails
apenas sao logados (sem envio real).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any

from .logging import log_action

# Periodo do loop (24h) — primeira execucao apos 5min do startup
_LOOP_INTERVAL_SECONDS = 86400
_STARTUP_DELAY_SECONDS = 300

_PAID_PLANS = ("lite", "starter", "pro", "business")

_started = False
_lock = threading.Lock()


def _ensure_columns() -> None:
    from .database import get_db
    with get_db() as db:
        for col in ("followup_wa_1d_sent", "followup_wa_3d_sent", "followup_wa_7d_sent"):
            try:
                db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass


def _build_email_body(plan_label: str, days_since: int) -> tuple[str, str]:
    """Retorna (subject, body_html) para cada estagio."""
    if days_since >= 7:
        subject = "Ultima chamada: conecte seu WhatsApp e ative seu bot"
        headline = "Ultimos dias do seu plano sem resultado"
        message = (
            "Ja faz uma semana que sua assinatura esta ativa e o bot ainda nao "
            "comecou a atender. Cada dia sem conectar e dinheiro perdido em "
            "leads que nao foram respondidos automaticamente."
        )
        cta_label = "Conectar WhatsApp em 2 minutos"
    elif days_since >= 3:
        subject = "Seu bot do Clow ainda esta esperando um numero de WhatsApp"
        headline = "Faltam poucos minutos pra seu bot atender clientes"
        message = (
            "Voce ja tem o plano, o bot ja esta treinado, so falta conectar um "
            "numero de WhatsApp (Z-API ou Meta oficial). Leva menos de 3 minutos."
        )
        cta_label = "Conectar agora"
    else:
        subject = "Vamos conectar seu WhatsApp e ativar seu bot?"
        headline = "Seu bot do Clow esta quase pronto"
        message = (
            "Voce ja assinou, seu acesso esta liberado. Agora falta so conectar "
            "um numero de WhatsApp pro bot comecar a atender seus clientes 24/7."
        )
        cta_label = "Conectar WhatsApp"

    body_html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#050510;font-family:'Segoe UI',Helvetica,Arial,sans-serif;color:#E8E8F0">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#050510;padding:32px 16px">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;background:#0F0F24;border-radius:16px;overflow:hidden;border:1px solid rgba(100,100,180,.15)">
<tr><td style="padding:32px 32px 0;text-align:center">
<img src="https://clow.pvcorretor01.com.br/static/brand/logo.png" alt="Clow" style="height:48px;display:block;margin:0 auto">
</td></tr>
<tr><td style="padding:24px 32px 32px">
<h1 style="font-size:20px;font-weight:700;margin:0 0 12px;color:#E8E8F0;line-height:1.3">{headline}</h1>
<p style="font-size:14px;line-height:1.7;color:#9898B8;margin:0 0 20px">{message}</p>
<div style="background:#14142E;border-left:3px solid #25D366;border-radius:10px;padding:14px 18px;margin:20px 0">
<p style="font-size:12px;color:#9898B8;margin:0 0 6px;letter-spacing:.5px;text-transform:uppercase">O que falta no seu plano {plan_label}</p>
<p style="font-size:14px;color:#E8E8F0;margin:0;font-weight:600">Conectar um numero de WhatsApp</p>
</div>
<ol style="padding-left:20px;font-size:13px;line-height:1.8;color:#9898B8;margin:16px 0">
<li>Va em <b style="color:#E8E8F0">Gerenciar WhatsApp</b> no menu lateral</li>
<li>Escolha <b style="color:#E8E8F0">Z-API</b> (mais rapido) ou <b style="color:#E8E8F0">Meta oficial</b></li>
<li>Cole as credenciais e conecte — pronto, o bot comeca a responder</li>
</ol>
<table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0 8px"><tr><td align="center">
<a href="https://clow.pvcorretor01.com.br/app/whatsapp" style="display:inline-block;background:#25D366;color:#fff;padding:14px 32px;border-radius:10px;font-size:14px;font-weight:600;text-decoration:none">{cta_label} &rarr;</a>
</td></tr></table>
<p style="font-size:12px;color:#585878;text-align:center;margin:20px 0 0">Precisa de ajuda para configurar? Responda este email.</p>
</td></tr>
<tr><td style="padding:16px 32px;background:#0A0A1A;border-top:1px solid rgba(100,100,180,.08);text-align:center">
<p style="font-size:10px;color:#3F3F5F;margin:0">
<a href="https://clow.pvcorretor01.com.br" style="color:#585878;text-decoration:none">clow.pvcorretor01.com.br</a>
</p>
</td></tr>
</table>
</td></tr></table>
</body></html>"""
    return subject, body_html


def _whatsapp_connected(uid: str) -> bool:
    from .database import get_whatsapp_credentials
    try:
        creds = get_whatsapp_credentials(uid)
        return bool(creds and creds.get("status") == "connected")
    except Exception:
        return False


def _plan_label(plan_id: str) -> str:
    try:
        from .billing import get_plan
        return get_plan(plan_id).get("name", plan_id.upper())
    except Exception:
        return plan_id.upper()


def _run_once() -> None:
    """Varre users e envia emails pendentes."""
    _ensure_columns()
    from .database import get_db
    from .integrations.email_sender import send_email

    now = int(time.time())
    with get_db() as db:
        rows = db.execute(
            "SELECT id, email, plan, created_at, onboarding_completed, "
            "followup_wa_1d_sent, followup_wa_3d_sent, followup_wa_7d_sent "
            "FROM users WHERE onboarding_completed=1 AND plan IN (?,?,?,?)",
            _PAID_PLANS,
        ).fetchall()

    sent = 0
    skipped = 0
    for r in rows:
        uid = r["id"]
        if _whatsapp_connected(uid):
            continue
        try:
            created = float(r["created_at"] or 0)
        except (TypeError, ValueError):
            continue
        if created <= 0:
            continue
        age_days = (now - created) / 86400.0
        email = r["email"] or ""
        if not email:
            continue
        plan = r["plan"]

        stage = None
        if age_days >= 7 and not r["followup_wa_7d_sent"]:
            stage = 7
        elif age_days >= 3 and not r["followup_wa_3d_sent"]:
            stage = 3
        elif age_days >= 1 and not r["followup_wa_1d_sent"]:
            stage = 1
        if stage is None:
            continue

        subject, body = _build_email_body(_plan_label(plan), stage)
        result = send_email(to=email, subject=subject, body_html=body, from_name="Clow")
        if result.get("success"):
            with get_db() as db:
                db.execute(
                    f"UPDATE users SET followup_wa_{stage}d_sent=1 WHERE id=?",
                    (uid,),
                )
            log_action("followup_wa_sent", f"user={uid} email={email} stage={stage}d")
            sent += 1
        else:
            # Marca como enviado mesmo se SMTP falhou (evita tentar de novo em loop
            # ate SMTP ser configurado). Loga o erro.
            log_action(
                "followup_wa_skipped",
                f"user={uid} stage={stage}d reason={result.get('error','?')[:80]}",
            )
            skipped += 1

    log_action("followup_wa_run_complete", f"sent={sent} skipped={skipped} total={len(rows)}")


def _scheduler_loop() -> None:
    time.sleep(_STARTUP_DELAY_SECONDS)
    while True:
        try:
            _run_once()
        except Exception as e:
            log_action("followup_wa_loop_error", str(e)[:200], level="error")
        time.sleep(_LOOP_INTERVAL_SECONDS)


def start() -> None:
    """Inicia o scheduler (idempotente — safe pra chamar varias vezes)."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="followup-wa")
    t.start()
    log_action("followup_wa_scheduler_started", "interval=24h")
