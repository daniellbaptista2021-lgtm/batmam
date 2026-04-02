"""Modulo GitHub — repos, issues, PRs."""
from __future__ import annotations
import requests

API = "https://api.github.com"
TIMEOUT = 30


def _get(creds: dict, path: str) -> dict | list:
    r = requests.get(f"{API}{path}", headers={"Authorization": f"token {creds['token']}", "Accept": "application/vnd.github+json"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _post(creds: dict, path: str, data: dict) -> dict:
    r = requests.post(f"{API}{path}", headers={"Authorization": f"token {creds['token']}", "Accept": "application/vnd.github+json"}, json=data, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def list_repos(creds: dict) -> str:
    repos = _get(creds, "/user/repos?sort=updated&per_page=20")
    if not repos:
        return "Nenhum repositorio encontrado."
    lines = ["## Seus Repositorios\n"]
    for r in repos:
        vis = "🔒" if r.get("private") else "🌐"
        lines.append(f"- {vis} **{r['full_name']}** — {r.get('description', '-')}")
    return "\n".join(lines)


def create_repo(creds: dict, name: str, description: str = "", private: bool = False) -> str:
    data = {"name": name, "description": description, "private": private, "auto_init": True}
    repo = _post(creds, "/user/repos", data)
    return f"✅ Repositorio criado: [{repo['full_name']}]({repo['html_url']})"


def list_issues(creds: dict, owner: str, repo: str) -> str:
    issues = _get(creds, f"/repos/{owner}/{repo}/issues?state=open&per_page=20")
    if not issues:
        return "Nenhuma issue aberta."
    lines = [f"## Issues — {owner}/{repo}\n"]
    for i in issues:
        lines.append(f"- #{i['number']} {i['title']}")
    return "\n".join(lines)
