"""Modulo Vercel — projetos e deployments."""
from __future__ import annotations
import requests

API = "https://api.vercel.com"
TIMEOUT = 30


def _get(creds: dict, path: str) -> dict:
    r = requests.get(f"{API}{path}", headers={"Authorization": f"Bearer {creds['token']}"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def list_projects(creds: dict) -> str:
    data = _get(creds, "/v9/projects?limit=20")
    projects = data.get("projects", [])
    if not projects:
        return "Nenhum projeto encontrado."
    lines = ["## Projetos Vercel\n"]
    for p in projects:
        lines.append(f"- **{p['name']}** — {', '.join(d.get('domain','') for d in p.get('targets',{}).get('production',{}).get('alias',[]) if d) or 'sem dominio'}")
    return "\n".join(lines)


def list_deployments(creds: dict, limit: int = 10) -> str:
    data = _get(creds, f"/v6/deployments?limit={limit}")
    deps = data.get("deployments", [])
    if not deps:
        return "Nenhum deployment encontrado."
    lines = ["## Deployments Vercel\n", "| Status | Projeto | URL | Data |", "|--------|---------|-----|------|"]
    for d in deps:
        st = {"READY": "✅", "ERROR": "❌", "BUILDING": "⏳"}.get(d.get("readyState", ""), "⚪")
        from datetime import datetime
        dt = datetime.fromtimestamp(d.get("createdAt", 0)/1000).strftime("%d/%m %H:%M")
        lines.append(f"| {st} | {d.get('name', '-')} | {d.get('url', '-')} | {dt} |")
    return "\n".join(lines)
