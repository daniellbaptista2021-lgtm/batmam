"""Backup & Export — exportacao e backup dos dados do cliente.

Exporta leads (CSV/JSON), conversas, configs. Importa CSV.
Backup semanal automatico com rotacao de 4 semanas.
"""

from __future__ import annotations

import csv
import io
import json
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config
from .logging import log_action

_BACKUP_DIR = config.CLOW_HOME / "backups"
_BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _tenant_backup_dir(tenant_id: str) -> Path:
    d = _BACKUP_DIR / tenant_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ══════════════════════════════════════════════════════════════
# EXPORT LEADS
# ══════════════════════════════════════════════════════════════

def export_leads_csv(tenant_id: str, instance_id: str = "") -> str:
    """Exporta leads em CSV. Retorna string CSV."""
    from .crm_models import list_leads
    result = list_leads(tenant_id, instance_id=instance_id, limit=10000)
    leads = result.get("leads", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["nome", "telefone", "email", "etapa", "valor", "origem",
                     "data_criacao", "ultima_msg", "instancia", "notas"])
    for l in leads:
        created = datetime.utcfromtimestamp(l.get("created_at", 0)).strftime("%d/%m/%Y %H:%M") if l.get("created_at") else ""
        last = datetime.utcfromtimestamp(l.get("last_contact_at", 0)).strftime("%d/%m/%Y %H:%M") if l.get("last_contact_at") else ""
        writer.writerow([
            l.get("name", ""), l.get("phone", ""), l.get("email", ""),
            l.get("status", ""), l.get("deal_value", 0), l.get("source", ""),
            created, last, l.get("instance_id", ""), l.get("notes", ""),
        ])
    return output.getvalue()


def export_leads_json(tenant_id: str, instance_id: str = "") -> list[dict]:
    """Exporta leads em JSON."""
    from .crm_models import list_leads
    result = list_leads(tenant_id, instance_id=instance_id, limit=10000)
    return result.get("leads", [])


def export_conversations(tenant_id: str, instance_id: str = "") -> dict:
    """Exporta conversas organizadas por telefone."""
    from .whatsapp_agent import get_wa_manager
    manager = get_wa_manager()
    instances = manager.get_instances(tenant_id)
    if instance_id:
        instances = [i for i in instances if i["id"] == instance_id]

    conversations = {}
    for inst_data in instances:
        inst = manager.get_instance(inst_data["id"], tenant_id)
        if not inst:
            continue
        convs = manager.list_conversations(inst)
        for c in convs:
            phone = c.get("phone", "")
            history = manager.get_conversation_history(inst, phone)
            conversations[f"{inst_data['id']}_{phone}"] = {
                "instance": inst_data.get("name", ""),
                "phone": phone,
                "messages": history,
            }
    return conversations


# ══════════════════════════════════════════════════════════════
# EXPORT ALL (ZIP)
# ══════════════════════════════════════════════════════════════

def export_all(tenant_id: str) -> bytes:
    """Gera ZIP completo com todos os dados."""
    buf = io.BytesIO()
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    prefix = f"clow-backup-{date_str}"

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Leads CSV
        csv_data = export_leads_csv(tenant_id)
        zf.writestr(f"{prefix}/leads.csv", csv_data)

        # Leads JSON
        leads = export_leads_json(tenant_id)
        zf.writestr(f"{prefix}/leads_detailed.json",
                     json.dumps(leads, ensure_ascii=False, indent=2))

        # Conversas
        convs = export_conversations(tenant_id)
        for key, data in convs.items():
            zf.writestr(f"{prefix}/conversations/{key}.json",
                         json.dumps(data, ensure_ascii=False, indent=2))

        # Instancias WhatsApp
        from .whatsapp_agent import get_wa_manager
        manager = get_wa_manager()
        instances = manager.get_instances(tenant_id)
        for inst in instances:
            safe = {k: v for k, v in inst.items() if k != "zapi_token"}
            zf.writestr(f"{prefix}/instances/{inst['id']}.json",
                         json.dumps(safe, ensure_ascii=False, indent=2))

        # Agent training
        try:
            from .crm_agent_training import get_corrections
            for inst in instances:
                corrections = get_corrections(tenant_id, inst["id"])
                if corrections:
                    zf.writestr(f"{prefix}/training/{inst['id']}_corrections.json",
                                 json.dumps(corrections, ensure_ascii=False, indent=2))
        except Exception:
            pass

        # Export info
        info = {
            "tenant_id": tenant_id,
            "exported_at": datetime.now().isoformat(),
            "leads_count": len(leads),
            "conversations_count": len(convs),
            "instances_count": len(instances),
        }
        zf.writestr(f"{prefix}/export_info.json",
                     json.dumps(info, ensure_ascii=False, indent=2))

    log_action("data_exported", f"tenant={tenant_id} size={buf.tell()}")
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════
# IMPORT LEADS CSV
# ══════════════════════════════════════════════════════════════

def import_leads_csv(tenant_id: str, instance_id: str, csv_content: str) -> dict:
    """Importa leads de CSV. Nao duplica (match por telefone)."""
    from .crm_models import create_lead, get_lead_by_phone, get_lead_by_email

    reader = csv.DictReader(io.StringIO(csv_content))
    imported = 0
    skipped = 0
    errors = []

    for i, row in enumerate(reader):
        try:
            name = row.get("nome") or row.get("name") or row.get("Nome") or ""
            phone = row.get("telefone") or row.get("phone") or row.get("Telefone") or ""
            email = row.get("email") or row.get("Email") or ""

            if not name and not phone and not email:
                continue

            # Check duplicata
            existing = None
            if phone:
                existing = get_lead_by_phone(tenant_id, phone)
            if not existing and email:
                existing = get_lead_by_email(tenant_id, email)
            if existing:
                skipped += 1
                continue

            create_lead(
                tenant_id, name=name, phone=phone, email=email,
                source="import", instance_id=instance_id,
                notes=row.get("notas") or row.get("notes") or "",
            )
            imported += 1
        except Exception as e:
            errors.append(f"Linha {i+2}: {str(e)[:100]}")

    log_action("data_imported", f"tenant={tenant_id} imported={imported} skipped={skipped}")
    return {"imported": imported, "skipped": skipped, "errors": len(errors), "error_details": errors}


# ══════════════════════════════════════════════════════════════
# BACKUPS
# ══════════════════════════════════════════════════════════════

def create_backup(tenant_id: str) -> dict:
    """Cria backup manual."""
    data = export_all(tenant_id)
    backup_id = uuid.uuid4().hex[:10]
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"backup-{date_str}-{backup_id}.zip"
    path = _tenant_backup_dir(tenant_id) / filename
    path.write_bytes(data)
    size_mb = round(len(data) / 1024 / 1024, 1)
    log_action("backup_created", f"tenant={tenant_id} size={size_mb}MB")
    return {"backup_id": backup_id, "filename": filename, "size_mb": size_mb, "created_at": time.time()}


def list_backups(tenant_id: str) -> list[dict]:
    """Lista backups disponiveis."""
    d = _tenant_backup_dir(tenant_id)
    backups = []
    for f in sorted(d.glob("backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        backups.append({
            "filename": f.name,
            "size_mb": round(f.stat().st_size / 1024 / 1024, 1),
            "created_at": f.stat().st_mtime,
        })
    return backups


def get_backup_file(tenant_id: str, filename: str) -> bytes | None:
    """Retorna bytes de um backup."""
    path = _tenant_backup_dir(tenant_id) / filename
    if path.exists() and path.suffix == ".zip":
        return path.read_bytes()
    return None


def delete_old_backups(tenant_id: str, keep: int = 4) -> int:
    """Remove backups antigos, mantendo os ultimos N."""
    d = _tenant_backup_dir(tenant_id)
    files = sorted(d.glob("backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for f in files[keep:]:
        f.unlink()
        removed += 1
    return removed


# ══════════════════════════════════════════════════════════════
# DELETE ALL
# ══════════════════════════════════════════════════════════════

def delete_all_data(tenant_id: str) -> dict:
    """Exclui TODOS os dados do tenant. Gera backup final antes."""
    # Backup final
    backup = create_backup(tenant_id)

    # Contagem
    from .crm_models import list_leads
    result = list_leads(tenant_id, limit=1)
    total_leads = result.get("total", 0)

    # Deleta leads e activities
    from .database import get_db
    with get_db() as db:
        db.execute("DELETE FROM lead_activities WHERE tenant_id=?", (tenant_id,))
        db.execute("DELETE FROM leads WHERE tenant_id=?", (tenant_id,))

    # Deleta instancias WhatsApp
    from .whatsapp_agent import get_wa_manager
    manager = get_wa_manager()
    instances = manager.get_instances(tenant_id)
    for inst in instances:
        manager.delete_instance(inst["id"], tenant_id)

    log_action("data_deleted_all", f"tenant={tenant_id} leads={total_leads}")
    return {
        "deleted": True,
        "backup_filename": backup["filename"],
        "items_deleted": total_leads,
    }
