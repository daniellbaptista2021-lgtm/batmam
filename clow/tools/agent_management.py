"""Agent Management tools - send messages, stop tasks, create/delete teams, list peers."""

from __future__ import annotations
from typing import Any
from .base import BaseTool


class SendMessageTool(BaseTool):
    """Send a message to a sub-agent or teammate by ID."""

    name = "send_message"
    description = (
        "Send a message to a sub-agent or teammate via the swarm mailbox. "
        "Use for inter-agent communication within a team."
    )
    requires_confirmation = False
    _is_read_only = False
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "message agent send communicate"
    _aliases = ["dm", "send_dm"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "team_name": {
                    "type": "string",
                    "description": "Name of the team.",
                },
                "to_agent": {
                    "type": "string",
                    "description": "Name of the target agent. Use * for broadcast.",
                },
                "content": {
                    "type": "string",
                    "description": "Message content.",
                },
                "from_agent": {
                    "type": "string",
                    "description": "Sender name. Default: team-lead.",
                },
                "msg_type": {
                    "type": "string",
                    "enum": ["text", "shutdown_request", "plan_approval_request"],
                    "description": "Message type. Default: text.",
                },
            },
            "required": ["team_name", "to_agent", "content"],
        }

    def execute(self, **kwargs: Any) -> str:
        team_name = kwargs.get("team_name", "")
        to_agent = kwargs.get("to_agent", "")
        content = kwargs.get("content", "")
        from_agent = kwargs.get("from_agent", "team-lead")
        msg_type = kwargs.get("msg_type", "text")

        if not team_name or not to_agent or not content:
            return "[ERROR] team_name, to_agent, and content are required."

        try:
            from ..swarm import send_message
            msg_id = send_message(
                team_name=team_name,
                from_agent=from_agent,
                to_agent=to_agent,
                content=content,
                msg_type=msg_type,
            )
            return f"Message sent. ID: {msg_id}, To: {to_agent}, Type: {msg_type}"
        except Exception as e:
            return f"[ERROR] Failed to send message: {e}"


class TaskStopTool(BaseTool):
    """Stop/kill a running sub-agent or background task."""

    name = "task_stop"
    description = (
        "Stop a running sub-agent or background task by ID. "
        "Sends shutdown signal to the agent."
    )
    requires_confirmation = True
    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = True
    _search_hint = "stop kill agent task cancel"
    _aliases = ["kill_agent", "stop_agent"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "team_name": {
                    "type": "string",
                    "description": "Name of the team containing the agent.",
                },
                "agent_name": {
                    "type": "string",
                    "description": "Name of the agent to stop.",
                },
            },
            "required": ["team_name", "agent_name"],
        }

    def execute(self, **kwargs: Any) -> str:
        team_name = kwargs.get("team_name", "")
        agent_name = kwargs.get("agent_name", "")

        if not team_name or not agent_name:
            return "[ERROR] team_name and agent_name are required."

        try:
            from ..swarm import shutdown_teammate
            result = shutdown_teammate(team_name, agent_name)
            return result
        except Exception as e:
            return f"[ERROR] Failed to stop agent: {e}"


class TeamCreateTool(BaseTool):
    """Create a multi-agent team."""

    name = "team_create"
    description = (
        "Create a new multi-agent team for collaborative work. "
        "Returns the team name and configuration."
    )
    requires_confirmation = False
    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = False
    _search_hint = "team create multi agent"
    _aliases = ["create_team"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the team.",
                },
                "description": {
                    "type": "string",
                    "description": "Description of the team purpose.",
                },
            },
            "required": ["name"],
        }

    def execute(self, **kwargs: Any) -> str:
        name = kwargs.get("name", "")
        description = kwargs.get("description", "")

        if not name:
            return "[ERROR] name is required."

        try:
            from ..swarm import create_team
            team = create_team(name=name, description=description)
            desc_info = description if description else "(none)"
            return (
                f"Team created successfully.\n"
                f"  Name: {team.name}\n"
                f"  Lead: {team.lead_agent_id}\n"
                f"  Description: {desc_info}"
            )
        except Exception as e:
            return f"[ERROR] Failed to create team: {e}"


class TeamDeleteTool(BaseTool):
    """Delete a team and clean up resources."""

    name = "team_delete"
    description = (
        "Delete a multi-agent team and all its resources. "
        "This is irreversible."
    )
    requires_confirmation = True
    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = True
    _search_hint = "team delete remove"
    _aliases = ["delete_team"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the team to delete.",
                },
            },
            "required": ["name"],
        }

    def execute(self, **kwargs: Any) -> str:
        name = kwargs.get("name", "")

        if not name:
            return "[ERROR] name is required."

        try:
            from ..swarm import delete_team
            success = delete_team(name)
            if success:
                return f"Team '{name}' deleted successfully."
            return f"[ERROR] Team '{name}' not found."
        except Exception as e:
            return f"[ERROR] Failed to delete team: {e}"


class ListPeersTool(BaseTool):
    """List all peer agents in the current team."""

    name = "list_peers"
    description = (
        "List all peer agents in a team. Shows agent names, "
        "types, and status."
    )
    requires_confirmation = False
    _is_read_only = True
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "list peers agents team members"
    _aliases = ["team_members"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "team_name": {
                    "type": "string",
                    "description": "Name of the team. If omitted, lists all teams.",
                },
            },
        }

    def execute(self, **kwargs: Any) -> str:
        team_name = kwargs.get("team_name", "")

        try:
            if team_name:
                from ..swarm import get_team
                team = get_team(team_name)
                if not team:
                    return f"[ERROR] Team '{team_name}' not found."
                lines = [f"Team: {team.name} (Lead: {team.lead_agent_id})"]
                if not team.members:
                    lines.append("  (no members)")
                for m in team.members:
                    status = "active" if m.is_active else "inactive"
                    agent_type = m.agent_type if m.agent_type else "general"
                    lines.append(f"  - {m.name} ({agent_type}) [{status}]")
                return "\n".join(lines)
            else:
                from ..swarm import list_teams
                teams = list_teams()
                if not teams:
                    return "No teams found."
                lines = [f"Teams ({len(teams)}):"]
                for t in teams:
                    lines.append(
                        f"  - {t['name']} (lead: {t['lead']}, members: {t['members']})"
                    )
                return "\n".join(lines)
        except Exception as e:
            return f"[ERROR] Failed to list peers: {e}"
