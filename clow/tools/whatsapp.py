"""WhatsApp Send Tool — envia mensagens via Z-API."""

from __future__ import annotations
import json
from urllib.request import urlopen, Request
from urllib.error import URLError
from typing import Any
from .base import BaseTool


class WhatsAppSendTool(BaseTool):
    name = "whatsapp_send"
    description = "Envia mensagem WhatsApp via Z-API. Suporta texto, imagem, documento e áudio."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Número do telefone com DDI (ex: 5511999999999)"},
                "message": {"type": "string", "description": "Texto da mensagem"},
                "instance_id": {"type": "string", "description": "ID da instância Z-API (ou usa env ZAPI_INSTANCE_ID)"},
                "token": {"type": "string", "description": "Token Z-API (ou usa env ZAPI_TOKEN)"},
                "media_url": {"type": "string", "description": "URL de mídia para enviar (imagem, doc, áudio)"},
                "media_type": {
                    "type": "string",
                    "enum": ["text", "image", "document", "audio"],
                    "description": "Tipo de mídia (padrão: text)",
                },
                "filename": {"type": "string", "description": "Nome do arquivo para documentos"},
            },
            "required": ["phone", "message"],
        }

    def execute(self, **kwargs: Any) -> str:
        import os
        phone = kwargs.get("phone", "").strip()
        message = kwargs.get("message", "")
        instance_id = kwargs.get("instance_id") or os.getenv("ZAPI_INSTANCE_ID", "")
        token = kwargs.get("token") or os.getenv("ZAPI_TOKEN", "")
        media_type = kwargs.get("media_type", "text")
        media_url = kwargs.get("media_url", "")
        filename = kwargs.get("filename", "")

        if not phone:
            return "Erro: phone é obrigatório."
        if not instance_id or not token:
            return "Erro: instance_id e token Z-API são obrigatórios. Configure ZAPI_INSTANCE_ID e ZAPI_TOKEN no .env"

        # Limpa telefone
        phone = phone.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")

        base_url = f"https://api.z-api.io/instances/{instance_id}/token/{token}"

        try:
            if media_type == "text":
                url = f"{base_url}/send-text"
                payload = {"phone": phone, "message": message}
            elif media_type == "image":
                url = f"{base_url}/send-image"
                payload = {"phone": phone, "image": media_url, "caption": message}
            elif media_type == "document":
                ext = filename.rsplit(".", 1)[-1] if "." in (filename or "") else "pdf"
                url = f"{base_url}/send-document/{ext}"
                payload = {"phone": phone, "document": media_url, "fileName": filename or "documento.pdf", "caption": message}
            elif media_type == "audio":
                url = f"{base_url}/send-audio"
                payload = {"phone": phone, "audio": media_url}
            else:
                return f"Erro: media_type '{media_type}' não suportado."

            data = json.dumps(payload).encode()
            req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            resp = urlopen(req, timeout=30)
            result = json.loads(resp.read().decode())
            return f"Mensagem enviada para {phone}. Status: {result.get('status', 'ok')}"

        except URLError as e:
            return f"Erro ao enviar WhatsApp: {e}"
        except Exception as e:
            return f"Erro: {e}"
