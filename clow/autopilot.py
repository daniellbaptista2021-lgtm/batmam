"""GitHub Issue Autopilot — resolve issues automaticamente.

Quando uma issue recebe label "clow" ou comentario "@clow <instrucao>":
1. Cria branch clow/issue-{number}
2. Clona/indexa o repo
3. Executa Agent com titulo+corpo como prompt
4. Roda testes
5. Faz commit + abre PR linkando a issue
6. Se falhar, comenta diagnostico na issue
"""

from __future__ import annotations
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from . import config
from .logging import log_action

# SQLite para tracking
DB_PATH = config.CLOW_HOME / "autopilot.db"
WORKSPACE_DIR = config.CLOW_HOME / "autopilot_workspaces"
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS autopilot_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_number INTEGER NOT NULL,
            repo_full_name TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            branch_name TEXT DEFAULT '',
            pr_url TEXT DEFAULT '',
            error_message TEXT DEFAULT '',
            tokens_used INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            completed_at REAL DEFAULT 0,
            summary TEXT DEFAULT ''
        )
    """)
    conn.commit()
    return conn


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verifica assinatura HMAC-SHA256 do webhook GitHub."""
    if not config.GITHUB_WEBHOOK_SECRET:
        return True  # Se nao tem secret, aceita tudo (dev mode)
    expected = "sha256=" + hmac.new(
        config.GITHUB_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def handle_webhook(event_type: str, payload: dict) -> dict[str, Any]:
    """Processa webhook do GitHub. Retorna resultado."""
    if not config.CLOW_AUTOPILOT:
        return {"status": "disabled"}

    # Issue labeled com "clow"
    if event_type == "issues" and payload.get("action") == "labeled":
        label = payload.get("label", {}).get("name", "")
        if label.lower() == "clow":
            issue = payload["issue"]
            repo = payload["repository"]
            return _start_autopilot(
                issue_number=issue["number"],
                repo_full_name=repo["full_name"],
                title=issue["title"],
                body=issue.get("body", "") or "",
                trigger_type="label",
            )

    # Comentario com "@clow"
    if event_type == "issue_comment" and payload.get("action") == "created":
        comment = payload.get("comment", {}).get("body", "")
        if "@clow" in comment.lower():
            issue = payload["issue"]
            repo = payload["repository"]
            # Extrai instrucao apos @clow
            instruction = comment.split("@clow", 1)[-1].strip()
            if not instruction:
                instruction = issue["title"]
            return _start_autopilot(
                issue_number=issue["number"],
                repo_full_name=repo["full_name"],
                title=issue["title"],
                body=f"{issue.get('body', '')}\n\nInstrucao adicional: {instruction}",
                trigger_type="comment",
            )

    return {"status": "ignored", "event": event_type}


def _start_autopilot(
    issue_number: int,
    repo_full_name: str,
    title: str,
    body: str,
    trigger_type: str,
) -> dict[str, Any]:
    """Inicia execucao do autopilot em background thread."""
    db = _get_db()
    db.execute(
        "INSERT INTO autopilot_runs (issue_number, repo_full_name, trigger_type, status, created_at) VALUES (?, ?, ?, 'running', ?)",
        (issue_number, repo_full_name, trigger_type, time.time()),
    )
    run_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    db.close()

    log_action("autopilot_start", f"issue #{issue_number} in {repo_full_name}", session_id=str(run_id))

    # Executa em background
    thread = threading.Thread(
        target=_execute_autopilot,
        args=(run_id, issue_number, repo_full_name, title, body),
        daemon=True,
        name=f"autopilot-{run_id}",
    )
    thread.start()

    return {"status": "started", "run_id": run_id, "issue": issue_number}


def _execute_autopilot(
    run_id: int,
    issue_number: int,
    repo_full_name: str,
    title: str,
    body: str,
) -> None:
    """Execucao completa do autopilot (roda em thread)."""
    branch_name = f"clow/issue-{issue_number}"
    workspace = WORKSPACE_DIR / f"{repo_full_name.replace('/', '_')}_{issue_number}"
    token = config.GITHUB_TOKEN

    try:
        # 1. Clone ou pull do repo
        clone_url = f"https://x-access-token:{token}@github.com/{repo_full_name}.git"
        if workspace.exists():
            subprocess.run(["git", "pull"], cwd=str(workspace), capture_output=True, timeout=120)
        else:
            subprocess.run(
                ["git", "clone", "--depth", "50", clone_url, str(workspace)],
                capture_output=True, timeout=300,
            )

        # 2. Cria branch
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=str(workspace), capture_output=True,
        )

        # 3. Executa Agent
        from .agent import Agent
        prompt = (
            f"Resolva a seguinte issue do GitHub:\n\n"
            f"## Issue #{issue_number}: {title}\n\n{body}\n\n"
            f"Repositorio: {repo_full_name}\n"
            f"Diretorio de trabalho: {workspace}\n\n"
            "Instrucoes:\n"
            "1. Leia o codigo relevante\n"
            "2. Implemente a solucao\n"
            "3. Rode os testes se existirem (pytest, npm test, etc)\n"
            "4. Faca commit das mudancas\n"
        )

        agent = Agent(
            cwd=str(workspace),
            auto_approve=True,
            is_subagent=True,
        )
        result = agent.run_turn(prompt)
        tokens_used = agent.session.total_tokens_in + agent.session.total_tokens_out

        # 4. Push da branch
        push_result = subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            cwd=str(workspace), capture_output=True, text=True, timeout=120,
        )

        # 5. Cria PR via API
        pr_url = ""
        if push_result.returncode == 0:
            pr_url = _create_pr(
                repo_full_name, branch_name, issue_number, title, result,
            )

        # 6. Atualiza DB
        _update_run(run_id, "completed", branch_name, pr_url, "", tokens_used, result[:500])
        log_action("autopilot_done", f"PR: {pr_url}", session_id=str(run_id))

    except Exception as e:
        error_msg = str(e)[:500]
        _update_run(run_id, "error", branch_name, "", error_msg, 0, "")

        # Comenta diagnostico na issue
        try:
            _comment_on_issue(repo_full_name, issue_number, error_msg)
        except Exception:
            pass

        log_action("autopilot_error", error_msg, level="error", session_id=str(run_id))


def _create_pr(
    repo_full_name: str,
    branch_name: str,
    issue_number: int,
    title: str,
    agent_result: str,
) -> str:
    """Cria PR via GitHub API. Retorna URL do PR."""
    import httpx

    pr_body = (
        f"## Resolucao automatica da Issue #{issue_number}\n\n"
        f"**Issue:** {title}\n\n"
        f"### Resumo das mudancas\n{agent_result[:1000]}\n\n"
        f"Closes #{issue_number}\n\n"
        "---\n*Gerado automaticamente pelo Clow Autopilot*"
    )

    response = httpx.post(
        f"https://api.github.com/repos/{repo_full_name}/pulls",
        headers={
            "Authorization": f"token {config.GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "title": f"fix: resolve issue #{issue_number} — {title[:60]}",
            "body": pr_body,
            "head": branch_name,
            "base": "main",
        },
        timeout=30,
    )

    if response.status_code in (201, 200):
        return response.json().get("html_url", "")

    # Tenta base "master" se "main" falhou
    response2 = httpx.post(
        f"https://api.github.com/repos/{repo_full_name}/pulls",
        headers={
            "Authorization": f"token {config.GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "title": f"fix: resolve issue #{issue_number} — {title[:60]}",
            "body": pr_body,
            "head": branch_name,
            "base": "master",
        },
        timeout=30,
    )
    if response2.status_code in (201, 200):
        return response2.json().get("html_url", "")

    return ""


def _comment_on_issue(repo_full_name: str, issue_number: int, error: str) -> None:
    """Comenta diagnostico na issue quando falha."""
    import httpx
    httpx.post(
        f"https://api.github.com/repos/{repo_full_name}/issues/{issue_number}/comments",
        headers={
            "Authorization": f"token {config.GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
        json={"body": f"**Clow Autopilot** — Falha ao resolver esta issue:\n\n```\n{error[:500]}\n```"},
        timeout=30,
    )


def _update_run(run_id: int, status: str, branch: str, pr_url: str, error: str, tokens: int, summary: str) -> None:
    db = _get_db()
    db.execute(
        "UPDATE autopilot_runs SET status=?, branch_name=?, pr_url=?, error_message=?, tokens_used=?, completed_at=?, summary=? WHERE id=?",
        (status, branch, pr_url, error, tokens, time.time(), summary, run_id),
    )
    db.commit()
    db.close()


def list_runs(limit: int = 20) -> list[dict]:
    """Lista execucoes recentes do autopilot."""
    db = _get_db()
    rows = db.execute(
        "SELECT * FROM autopilot_runs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_run(run_id: int) -> dict | None:
    db = _get_db()
    row = db.execute("SELECT * FROM autopilot_runs WHERE id=?", (run_id,)).fetchone()
    db.close()
    return dict(row) if row else None


def get_active_runs() -> list[dict]:
    """Retorna runs em andamento."""
    db = _get_db()
    rows = db.execute(
        "SELECT * FROM autopilot_runs WHERE status='running' ORDER BY created_at DESC"
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]
