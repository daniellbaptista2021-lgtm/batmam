"""n8n Workflow Tool — gerencia workflows do n8n via API."""

from __future__ import annotations
import json
import os
from urllib.request import urlopen, Request
from urllib.error import URLError
from typing import Any
from .base import BaseTool


class N8nWorkflowTool(BaseTool):
    name = "n8n_workflow"
    description = "Gerencia workflows do n8n. Ações: list, activate, deactivate, execute, get_status."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "activate", "deactivate", "execute", "get_status", "get"],
                    "description": "Ação a executar",
                },
                "workflow_id": {"type": "string", "description": "ID do workflow (para activate/deactivate/execute/get)"},
                "n8n_url": {"type": "string", "description": "URL do n8n (ou usa env N8N_URL)"},
                "n8n_api_key": {"type": "string", "description": "API key do n8n (ou usa env N8N_API_KEY)"},
                "payload": {"type": "object", "description": "Dados para passar ao executar workflow"},
            },
            "required": ["action"],
        }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "")
        workflow_id = kwargs.get("workflow_id", "")
        n8n_url = (kwargs.get("n8n_url") or os.getenv("N8N_URL", "")).rstrip("/")
        api_key = kwargs.get("n8n_api_key") or os.getenv("N8N_API_KEY", "")
        payload = kwargs.get("payload", {})

        if not n8n_url or not api_key:
            return "Erro: N8N_URL e N8N_API_KEY são obrigatórios. Configure no .env"

        headers = {"Content-Type": "application/json", "X-N8N-API-KEY": api_key}

        try:
            if action == "list":
                return self._api_get(f"{n8n_url}/api/v1/workflows", headers)

            if not workflow_id:
                return "Erro: workflow_id é obrigatório para esta ação."

            if action == "get":
                return self._api_get(f"{n8n_url}/api/v1/workflows/{workflow_id}", headers)

            elif action == "activate":
                return self._api_patch(
                    f"{n8n_url}/api/v1/workflows/{workflow_id}",
                    headers,
                    {"active": True},
                )

            elif action == "deactivate":
                return self._api_patch(
                    f"{n8n_url}/api/v1/workflows/{workflow_id}",
                    headers,
                    {"active": False},
                )

            elif action == "execute":
                data = json.dumps(payload).encode() if payload else None
                req = Request(
                    f"{n8n_url}/api/v1/workflows/{workflow_id}/execute",
                    data=data,
                    headers=headers,
                    method="POST",
                )
                resp = urlopen(req, timeout=60)
                result = json.loads(resp.read().decode())
                return f"Workflow {workflow_id} executado.\n{json.dumps(result, indent=2, ensure_ascii=False)[:3000]}"

            elif action == "get_status":
                return self._api_get(f"{n8n_url}/api/v1/executions?workflowId={workflow_id}&limit=5", headers)

            return f"Ação '{action}' não reconhecida."

        except URLError as e:
            return f"Erro n8n: {e}"
        except Exception as e:
            return f"Erro: {e}"

    @staticmethod
    def _api_get(url: str, headers: dict) -> str:
        req = Request(url, headers=headers, method="GET")
        resp = urlopen(req, timeout=30)
        result = json.loads(resp.read().decode())
        return json.dumps(result, indent=2, ensure_ascii=False)[:5000]

    @staticmethod
    def _api_patch(url: str, headers: dict, data: dict) -> str:
        req = Request(url, data=json.dumps(data).encode(), headers=headers, method="PATCH")
        resp = urlopen(req, timeout=30)
        result = json.loads(resp.read().decode())
        status = "ativado" if data.get("active") else "desativado"
        return f"Workflow {status}. {json.dumps(result, indent=2, ensure_ascii=False)[:1000]}"
