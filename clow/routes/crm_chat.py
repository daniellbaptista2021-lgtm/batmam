"""CRM Chat Routes — WhatsApp Web integrado ao CRM Pipeline.

Permite enviar/receber mensagens de texto, imagem, documento e audio
via Z-API diretamente do painel CRM do lead.
"""

from __future__ import annotations

import base64
import json
import time
from urllib.request import urlopen, Request
from urllib.error import HTTPError

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR


def register_crm_chat_routes(app) -> None:

    from .auth import _get_user_session

    def _auth(request: _Req):
        return _get_user_session(request)

    def _tenant(sess: dict) -> str:
        return sess["user_id"]

    def _get_instance(tenant_id: str, instance_id: str = ""):
        """Retorna instancia Z-API do tenant. Se instance_id vazio, pega a primeira ativa."""
        from ..whatsapp_agent import get_wa_manager
        manager = get_wa_manager()
        if instance_id:
            return manager.get_instance(instance_id, tenant_id)
        instances = manager.get_instances(tenant_id)
        if not instances:
            return None
        return manager.get_instance(instances[0]["id"], tenant_id)

    def _zapi_request(inst, endpoint: str, data: dict) -> dict:
        """Faz request pra Z-API."""
        url = f"https://api.z-api.io/instances/{inst.zapi_instance_id}/token/{inst.zapi_token}/{endpoint}"
        body = json.dumps(data).encode()
        req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            resp = urlopen(req, timeout=30)
            return json.loads(resp.read().decode())
        except HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            return {"error": f"Z-API {e.code}: {error_body[:200]}"}
        except Exception as e:
            return {"error": str(e)[:200]}

    # ══════════════════════════════════════════════════════════
    # LISTAR INSTANCIAS DO TENANT (pra seletor no chat)
    # ══════════════════════════════════════════════════════════

    @app.get("/api/v1/crm/chat/instances", tags=["crm-chat"])
    async def crm_chat_instances(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..whatsapp_agent import get_wa_manager
        instances = get_wa_manager().get_instances(_tenant(sess))
        return _JR({"instances": instances})

    # ══════════════════════════════════════════════════════════
    # HISTORICO DE MENSAGENS
    # ══════════════════════════════════════════════════════════

    @app.get("/api/v1/crm/chat/messages/{lead_id}", tags=["crm-chat"])
    async def crm_chat_messages(lead_id: str, request: _Req):
        """Carrega historico de mensagens de um lead."""
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        tid = _tenant(sess)
        phone = request.query_params.get("phone", "")
        instance_id = request.query_params.get("instance_id", "")
        limit = int(request.query_params.get("limit", "50"))
        since = float(request.query_params.get("since", "0"))

        if not phone:
            # Busca phone do lead
            from ..crm_models import get_lead
            lead = get_lead(lead_id, tid)
            if not lead or not lead.get("phone"):
                return _JR({"error": "Lead sem telefone"}, status_code=400)
            phone = lead["phone"]

        # Busca instancia
        inst = _get_instance(tid, instance_id)
        if not inst:
            return _JR({"messages": [], "no_instance": True})

        # Carrega historico do arquivo de conversas
        from ..whatsapp_agent import get_wa_manager
        manager = get_wa_manager()
        raw_history = manager.get_conversation_history(inst, phone)

        # Converte pro formato do chat
        messages = []
        for msg in raw_history:
            ts = msg.get("timestamp", 0)
            if since and ts <= since:
                continue
            messages.append({
                "id": f"{phone}_{ts}",
                "phone": phone,
                "body": msg.get("content", ""),
                "type": "chat",
                "fromMe": msg.get("role") == "assistant",
                "timestamp": ts,
                "media_url": None,
                "status": "read",
            })

        # Limita
        if limit:
            messages = messages[-limit:]

        return _JR({"messages": messages})

    # ══════════════════════════════════════════════════════════
    # ENVIAR MENSAGEM DE TEXTO
    # ══════════════════════════════════════════════════════════

    @app.post("/api/v1/crm/chat/send", tags=["crm-chat"])
    async def crm_chat_send(request: _Req):
        """Envia mensagem de texto via Z-API e registra no CRM."""
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        tid = _tenant(sess)
        body = await request.json()
        lead_id = body.get("lead_id", "")
        phone = body.get("phone", "")
        content = body.get("content", "").strip()
        instance_id = body.get("instance_id", "")

        if not phone or not content:
            return _JR({"error": "phone e content obrigatorios"}, status_code=400)

        inst = _get_instance(tid, instance_id)
        if not inst:
            return _JR({"error": "Nenhuma instancia WhatsApp configurada. Configure em WhatsApp Trigger."}, status_code=400)

        # Envia via Z-API
        result = _zapi_request(inst, "send-text", {"phone": phone, "message": content})
        if "error" in result:
            return _JR({"error": result["error"]}, status_code=502)

        now = time.time()

        # Salva no historico local
        from ..whatsapp_agent import get_wa_manager
        manager = get_wa_manager()
        manager._save_message(inst, phone, "assistant", content)

        # Registra na timeline do lead
        if lead_id:
            try:
                from ..crm_models import add_activity
                add_activity(lead_id, tid, "whatsapp", f"Enviado: {content[:150]}")
            except Exception:
                pass

        return _JR({
            "sent": True,
            "timestamp": now,
            "message_id": result.get("messageId", ""),
        })

    # ══════════════════════════════════════════════════════════
    # ENVIAR MIDIA (imagem, documento, audio)
    # ══════════════════════════════════════════════════════════

    @app.post("/api/v1/crm/chat/send-media", tags=["crm-chat"])
    async def crm_chat_send_media(request: _Req):
        """Envia midia (imagem, documento, audio) via Z-API."""
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        tid = _tenant(sess)
        form = await request.form()
        lead_id = form.get("lead_id", "")
        phone = form.get("phone", "")
        instance_id = form.get("instance_id", "")
        media_type = form.get("type", "image")  # image, document, audio
        caption = form.get("caption", "")
        file = form.get("file")

        if not phone:
            return _JR({"error": "phone obrigatorio"}, status_code=400)
        if not file:
            return _JR({"error": "Arquivo obrigatorio"}, status_code=400)

        inst = _get_instance(tid, instance_id)
        if not inst:
            return _JR({"error": "Nenhuma instancia WhatsApp configurada"}, status_code=400)

        # Le o arquivo e converte pra base64
        file_bytes = await file.read()
        file_b64 = base64.b64encode(file_bytes).decode()
        filename = getattr(file, "filename", "file") or "file"

        # Envia conforme o tipo
        if media_type == "image":
            data_uri = f"data:image/jpeg;base64,{file_b64}"
            result = _zapi_request(inst, "send-image", {
                "phone": phone,
                "image": data_uri,
                "caption": caption,
            })
            timeline_msg = f"Foto enviada" + (f": {caption}" if caption else "")

        elif media_type == "document":
            ext = filename.rsplit(".", 1)[-1] if "." in filename else "pdf"
            data_uri = f"data:application/octet-stream;base64,{file_b64}"
            result = _zapi_request(inst, f"send-document/{ext}", {
                "phone": phone,
                "document": data_uri,
                "fileName": filename,
            })
            timeline_msg = f"Documento enviado: {filename}"

        elif media_type == "audio":
            data_uri = f"data:audio/ogg;base64,{file_b64}"
            result = _zapi_request(inst, "send-audio", {
                "phone": phone,
                "audio": data_uri,
            })
            timeline_msg = "Audio enviado"

        else:
            return _JR({"error": f"Tipo desconhecido: {media_type}"}, status_code=400)

        if "error" in result:
            return _JR({"error": result["error"]}, status_code=502)

        now = time.time()

        # Salva no historico
        from ..whatsapp_agent import get_wa_manager
        manager = get_wa_manager()
        manager._save_message(inst, phone, "assistant", f"[{media_type}] {caption or filename}")

        # Timeline do lead
        if lead_id:
            try:
                from ..crm_models import add_activity
                add_activity(lead_id, tid, "whatsapp", timeline_msg)
            except Exception:
                pass

        return _JR({
            "sent": True,
            "timestamp": now,
            "message_id": result.get("messageId", ""),
            "type": media_type,
        })
