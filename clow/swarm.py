"""Agent Swarms -- Multi-Agent Team Coordination (Claude Code Architecture Ep.08).

Spawn parallel teammates coordinated through file-based mailbox system.
Leader-worker hierarchy with permission delegation.

Architecture:
- TeamCreate: creates team config + mailbox directories
- SpawnAgent: spawns workers (in-process for Clow)
- Mailbox: file-based JSON with lockfile concurrency
- SendMessage: DM, broadcast, shutdown, plan approval
- Permission delegation: worker -> leader -> worker
"""

import json
import os
import time
import uuid
import threading
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable
from . import config

logger = logging.getLogger("clow.swarm")

TEAMS_DIR = config.CLOW_HOME / "teams"
TEAMS_DIR.mkdir(parents=True, exist_ok=True)

# == Team Configuration ==

@dataclass
class TeamMember:
    agent_id: str           # "researcher@my-project"
    name: str               # "researcher"
    agent_type: str = ""    # subagent type
    model: str = ""         # model override
    prompt: str = ""        # initial prompt
    color: str = ""         # UI color
    cwd: str = ""
    is_active: bool = True
    plan_mode_required: bool = False
    backend_type: str = "in-process"  # in-process for Clow
    subscriptions: list = field(default_factory=list)

@dataclass
class Team:
    name: str
    description: str = ""
    created_at: float = field(default_factory=time.time)
    lead_agent_id: str = ""
    lead_session_id: str = ""
    members: list[TeamMember] = field(default_factory=list)

    @property
    def team_dir(self) -> Path:
        d = TEAMS_DIR / self.name
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def config_path(self) -> Path:
        return self.team_dir / "config.json"

    @property
    def inbox_dir(self) -> Path:
        d = self.team_dir / "inboxes"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self) -> None:
        data = {
            "name": self.name,
            "description": self.description,
            "createdAt": self.created_at,
            "leadAgentId": self.lead_agent_id,
            "leadSessionId": self.lead_session_id,
            "members": [
                {
                    "agentId": m.agent_id,
                    "name": m.name,
                    "agentType": m.agent_type,
                    "model": m.model,
                    "prompt": m.prompt[:500],
                    "color": m.color,
                    "cwd": m.cwd,
                    "isActive": m.is_active,
                    "planModeRequired": m.plan_mode_required,
                    "backendType": m.backend_type,
                    "subscriptions": m.subscriptions,
                }
                for m in self.members
            ],
        }
        self.config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, team_name: str) -> 'Team | None':
        path = TEAMS_DIR / team_name / "config.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            team = cls(
                name=data["name"],
                description=data.get("description", ""),
                created_at=data.get("createdAt", 0),
                lead_agent_id=data.get("leadAgentId", ""),
                lead_session_id=data.get("leadSessionId", ""),
            )
            for m in data.get("members", []):
                team.members.append(TeamMember(
                    agent_id=m.get("agentId", ""),
                    name=m.get("name", ""),
                    agent_type=m.get("agentType", ""),
                    model=m.get("model", ""),
                    prompt=m.get("prompt", ""),
                    color=m.get("color", ""),
                    cwd=m.get("cwd", ""),
                    is_active=m.get("isActive", True),
                    plan_mode_required=m.get("planModeRequired", False),
                    backend_type=m.get("backendType", "in-process"),
                    subscriptions=m.get("subscriptions", []),
                ))
            return team
        except Exception:
            return None


# == Team Management ==

_active_teams: dict[str, Team] = {}
_lock = threading.Lock()

def create_team(name: str, description: str = "", session_id: str = "") -> Team:
    """Create a new team with leader."""
    with _lock:
        # Generate unique name if collision
        base_name = name
        counter = 1
        while (TEAMS_DIR / name).exists():
            counter += 1
            name = f"{base_name}-{counter}"

        team = Team(name=name, description=description)
        team.lead_agent_id = f"team-lead@{name}"
        team.lead_session_id = session_id
        team.save()

        # Create leader inbox
        (team.inbox_dir / "team-lead.json").write_text("[]")

        _active_teams[name] = team
        logger.info(f"Team created: {name}")
        return team

def get_team(name: str) -> 'Team | None':
    with _lock:
        if name in _active_teams:
            return _active_teams[name]
    return Team.load(name)

def list_teams() -> list[dict]:
    teams = []
    if TEAMS_DIR.exists():
        for d in TEAMS_DIR.iterdir():
            if d.is_dir() and (d / "config.json").exists():
                team = Team.load(d.name)
                if team:
                    teams.append({
                        "name": team.name,
                        "lead": team.lead_agent_id,
                        "members": len(team.members),
                        "created_at": team.created_at,
                    })
    return teams

def delete_team(name: str) -> bool:
    """Delete team and cleanup."""
    with _lock:
        _active_teams.pop(name, None)
    team_dir = TEAMS_DIR / name
    if team_dir.exists():
        import shutil
        shutil.rmtree(team_dir, ignore_errors=True)
        logger.info(f"Team deleted: {name}")
        return True
    return False


# == Spawn Teammates ==

_worker_threads: dict[str, threading.Thread] = {}

def spawn_teammate(
    team_name: str,
    name: str,
    prompt: str,
    agent_type: str = "general-purpose",
    model: str = "",
    plan_mode_required: bool = False,
    on_complete: 'Callable | None' = None,
) -> str:
    """Spawn a teammate as in-process worker thread.

    Returns agent_id.
    """
    team = get_team(team_name)
    if not team:
        raise ValueError(f"Team '{team_name}' not found")

    # Generate unique name
    existing_names = {m.name for m in team.members}
    base = name
    counter = 1
    while name in existing_names:
        counter += 1
        name = f"{base}-{counter}"

    agent_id = f"{name}@{team_name}"

    # Create member
    member = TeamMember(
        agent_id=agent_id,
        name=name,
        agent_type=agent_type,
        model=model or config.CLOW_MODEL,
        prompt=prompt,
        cwd=os.getcwd(),
        plan_mode_required=plan_mode_required,
        backend_type="in-process",
    )
    team.members.append(member)
    team.save()

    # Create inbox
    (team.inbox_dir / f"{name}.json").write_text("[]")

    # Send initial prompt to teammate's inbox
    send_message(team_name, "team-lead", name, prompt)

    # Spawn worker thread
    def _run_worker():
        try:
            logger.info(f"Worker {agent_id} started")
            # Import Agent here to avoid circular
            from .agent import Agent
            agent = Agent(
                cwd=member.cwd,
                model=member.model,
                auto_approve=True,
                is_subagent=True,
            )
            result = agent.run_turn(prompt)

            # Send result back to leader
            send_message(team_name, name, "team-lead", result or "Task completed", msg_type="idle_notification")

            if on_complete:
                on_complete(agent_id, result)

        except Exception as e:
            logger.error(f"Worker {agent_id} error: {e}")
            send_message(team_name, name, "team-lead", f"Error: {e}", msg_type="idle_notification")
        finally:
            # Mark inactive
            for m in team.members:
                if m.agent_id == agent_id:
                    m.is_active = False
            team.save()

    t = threading.Thread(target=_run_worker, daemon=True, name=f"swarm-{agent_id}")
    _worker_threads[agent_id] = t
    t.start()

    logger.info(f"Teammate spawned: {agent_id}")
    return agent_id


# == Mailbox System (File-Based IPC) ==

def _inbox_path(team_name: str, agent_name: str) -> Path:
    return TEAMS_DIR / team_name / "inboxes" / f"{agent_name}.json"

def _read_inbox(team_name: str, agent_name: str) -> list[dict]:
    path = _inbox_path(team_name, agent_name)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []

def _write_inbox(team_name: str, agent_name: str, messages: list[dict]) -> None:
    path = _inbox_path(team_name, agent_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Simple file lock (create .lock file)
    lock_path = Path(str(path) + ".lock")
    max_retries = 10
    for attempt in range(max_retries):
        try:
            # Try to acquire lock
            if lock_path.exists():
                lock_age = time.time() - lock_path.stat().st_mtime
                if lock_age > 30:  # Stale lock
                    lock_path.unlink(missing_ok=True)
                else:
                    time.sleep(0.01 * (attempt + 1))  # Exponential backoff
                    continue
            lock_path.touch()
            try:
                path.write_text(json.dumps(messages, ensure_ascii=False, indent=2))
            finally:
                lock_path.unlink(missing_ok=True)
            return
        except Exception:
            time.sleep(0.01 * (attempt + 1))
    # Last resort: write without lock
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2))


def send_message(
    team_name: str,
    from_agent: str,
    to_agent: str,
    content: str,
    msg_type: str = "text",
    data: 'dict | None' = None,
) -> str:
    """Send message from one agent to another via mailbox.

    Supports: text DM, broadcast (to="*"), idle_notification,
    permission_request/response, shutdown_request/approved/rejected,
    plan_approval_request/response.
    """
    msg_id = uuid.uuid4().hex[:12]
    message = {
        "id": msg_id,
        "from": from_agent,
        "to": to_agent,
        "type": msg_type,
        "content": content,
        "data": data or {},
        "timestamp": time.time(),
        "read": False,
    }

    if to_agent == "*":
        # Broadcast to all members
        team = get_team(team_name)
        if team:
            for m in team.members:
                if m.name != from_agent:
                    msgs = _read_inbox(team_name, m.name)
                    msgs.append(message)
                    _write_inbox(team_name, m.name, msgs)
    else:
        msgs = _read_inbox(team_name, to_agent)
        msgs.append(message)
        _write_inbox(team_name, to_agent, msgs)

    return msg_id


def poll_inbox(team_name: str, agent_name: str, mark_read: bool = True) -> list[dict]:
    """Poll inbox for unread messages."""
    messages = _read_inbox(team_name, agent_name)
    unread = [m for m in messages if not m.get("read")]

    if mark_read and unread:
        for m in messages:
            m["read"] = True
        _write_inbox(team_name, agent_name, messages)

    return unread


def get_inbox(team_name: str, agent_name: str) -> list[dict]:
    """Get all messages (read and unread)."""
    return _read_inbox(team_name, agent_name)


# == Permission Delegation ==

def request_permission(team_name: str, worker_name: str, tool_name: str, tool_input: dict) -> str:
    """Worker requests permission from leader."""
    return send_message(
        team_name, worker_name, "team-lead",
        f"Permission request: {tool_name}",
        msg_type="permission_request",
        data={"tool_name": tool_name, "tool_input": tool_input},
    )

def respond_permission(team_name: str, worker_name: str, approved: bool, reason: str = "") -> str:
    """Leader responds to permission request."""
    return send_message(
        team_name, "team-lead", worker_name,
        "approved" if approved else "denied",
        msg_type="permission_response",
        data={"approved": approved, "reason": reason},
    )


# == Shutdown ==

def shutdown_teammate(team_name: str, agent_name: str) -> str:
    """Request graceful shutdown of a teammate."""
    return send_message(
        team_name, "team-lead", agent_name,
        "Shutdown requested",
        msg_type="shutdown_request",
    )

def shutdown_team(team_name: str) -> int:
    """Shutdown all teammates in a team."""
    team = get_team(team_name)
    if not team:
        return 0

    count = 0
    for m in team.members:
        if m.is_active:
            shutdown_teammate(team_name, m.name)
            count += 1

    return count


# == Cleanup ==

def cleanup_session_teams(session_id: str = "") -> int:
    """Cleanup teams created by this session."""
    cleaned = 0
    for team_name in list(_active_teams.keys()):
        team = _active_teams.get(team_name)
        if team and (not session_id or team.lead_session_id == session_id):
            # Kill worker threads
            for m in team.members:
                _worker_threads.pop(m.agent_id, None)
                # Threads are daemon, will die with process

            delete_team(team_name)
            cleaned += 1

    return cleaned


# == API ==

def get_swarm_status() -> dict:
    """Get status of all active swarms."""
    teams = list_teams()
    workers = {aid: t.is_alive() for aid, t in _worker_threads.items()}
    return {
        "teams": teams,
        "active_workers": sum(1 for v in workers.values() if v),
        "total_workers": len(workers),
    }
