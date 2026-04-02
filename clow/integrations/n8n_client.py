"""Modulo n8n — gestao de workflows."""
from __future__ import annotations
import requests

TIMEOUT = 30


def _get(creds: dict, path: str) -> dict:
    url = f"{creds['url'].rstrip('/')}/api/v1{path}"
    headers = {"X-N8N-API-KEY": creds["api_key"]}
    r = requests.get(url, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _post(creds: dict, path: str, data: dict = None) -> dict:
    url = f"{creds['url'].rstrip('/')}/api/v1{path}"
    headers = {"X-N8N-API-KEY": creds["api_key"], "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=data or {}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _patch(creds: dict, path: str, data: dict) -> dict:
    url = f"{creds['url'].rstrip('/')}/api/v1{path}"
    headers = {"X-N8N-API-KEY": creds["api_key"], "Content-Type": "application/json"}
    r = requests.patch(url, headers=headers, json=data, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def list_workflows(creds: dict, active_only: bool = False) -> str:
    data = _get(creds, "/workflows?limit=100")
    wfs = data.get("data", data) if isinstance(data, dict) else data

    if isinstance(wfs, dict) and "data" in wfs:
        wfs = wfs["data"]

    if not wfs:
        return "Nenhum workflow encontrado."

    if active_only:
        wfs = [w for w in wfs if w.get("active")]

    lines = ["## Workflows n8n\n", "| Status | Nome | ID |", "|--------|------|----|"]
    for w in wfs:
        status = "🟢" if w.get("active") else "⚪"
        lines.append(f"| {status} | {w.get('name', '-')} | `{w.get('id', '-')}` |")

    return "\n".join(lines)


def get_executions(creds: dict, limit: int = 20, status: str = None) -> str:
    path = f"/executions?limit={limit}"
    if status:
        path += f"&status={status}"
    data = _get(creds, path)
    execs = data.get("data", data) if isinstance(data, dict) else data

    if isinstance(execs, dict) and "data" in execs:
        execs = execs["data"]

    if not execs:
        return "Nenhuma execucao encontrada."

    lines = ["## Execucoes Recentes\n", "| Status | Workflow | Inicio | Modo |", "|--------|----------|--------|------|"]
    for e in execs[:limit]:
        st = {"success": "✅", "error": "❌", "running": "⏳"}.get(e.get("status", ""), "⚪")
        wf_name = e.get("workflowData", {}).get("name", e.get("workflowId", "-"))
        started = str(e.get("startedAt", "-"))[:19]
        mode = e.get("mode", "-")
        lines.append(f"| {st} | {wf_name} | {started} | {mode} |")

    return "\n".join(lines)


def activate_workflow(creds: dict, wf_id: str) -> str:
    _patch(creds, f"/workflows/{wf_id}", {"active": True})
    return f"✅ Workflow `{wf_id}` ativado."


def deactivate_workflow(creds: dict, wf_id: str) -> str:
    _patch(creds, f"/workflows/{wf_id}", {"active": False})
    return f"✅ Workflow `{wf_id}` desativado."
