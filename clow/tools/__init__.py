"""Ferramentas do Clow — Claude Code Architecture.

15 core tools always available (like Claude Code):
- File Operations: Read, Write, Edit, Glob, Grep
- Execution: Bash
- Agent: Agent, Task management
- Web: WebFetch, WebSearch
- Workflow: Notebook, Skill

Additional tools loaded on-demand via orchestrator.
"""

from .bash import BashTool
from .read import ReadTool
from .write import WriteTool
from .edit import EditTool
from .glob_tool import GlobTool
from .grep import GrepTool
from .agent_tool import AgentTool
from .web_search import WebSearchTool
from .web_fetch import WebFetchTool
from .notebook import NotebookEditTool
from .base import BaseTool, ToolRegistry

# CORE TOOLS — always available (like Claude Code's 15 always-on tools)
CORE_TOOLS = [
    "read", "write", "edit", "glob", "grep",  # File Operations
    "bash",                                      # Execution
    "agent",                                     # Agent Management
    "web_search", "web_fetch",                   # External
]

# ON-DEMAND TOOLS — loaded only when orchestrator detects need
ONDEMAND_TOOLS = [
    "whatsapp_send", "http_request", "supabase_query",
    "n8n_workflow", "docker_manage", "git_advanced",
    "scraper", "pdf_tool", "spreadsheet",
    "ssh_connect", "manage_process", "configure_nginx",
    "manage_ssl", "monitor_resources", "manage_cron",
    "backup_create", "deploy_vercel", "deploy_vps",
    "meta_ads", "image_gen", "design_generate",
    "chatwoot_setup", "chatwoot_list_conversations",
    "chatwoot_search_contact", "chatwoot_create_contact",
    "chatwoot_report", "git_ops",
]

__all__ = [
    "BaseTool",
    "ToolRegistry",
    "BashTool",
    "ReadTool",
    "WriteTool",
    "EditTool",
    "GlobTool",
    "GrepTool",
    "AgentTool",
    "WebSearchTool",
    "WebFetchTool",
    "NotebookEditTool",
    "CORE_TOOLS",
    "ONDEMAND_TOOLS",
]
