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
    # WhatsApp (10)
    "whatsapp_send", "whatsapp_create_instance", "whatsapp_list_instances",
    "whatsapp_connect_test", "whatsapp_setup_webhook", "whatsapp_test_webhook",
    "whatsapp_send_test_message", "whatsapp_save_prompt", "whatsapp_save_rag_text",
    "whatsapp_full_test",
    # Chatwoot (15)
    "chatwoot_setup", "chatwoot_list_conversations", "chatwoot_search_contact",
    "chatwoot_create_contact", "chatwoot_report", "chatwoot_list_agents",
    "chatwoot_list_inboxes", "chatwoot_list_labels", "chatwoot_create_label",
    "chatwoot_label_conversation", "chatwoot_assign_conversation",
    "chatwoot_create_automation", "chatwoot_list_automations",
    "chatwoot_create_team", "chatwoot_test_connection",
    # Infrastructure (7)
    "ssh_connect", "manage_process", "configure_nginx", "manage_ssl",
    "monitor_resources", "manage_cron", "backup_create",
    # DevOps (3)
    "docker_manage", "deploy_vercel", "deploy_vps",
    # Data & APIs (5)
    "http_request", "supabase_query", "n8n_workflow",
    "query_mysql", "query_postgres",
    # Content & Media (5)
    "scraper", "pdf_tool", "spreadsheet", "image_gen", "meta_ads",
    # Design (2)
    "canva_template", "design_generate",
    # Git (2)
    "git_advanced", "git_ops",
    # Workflow (5)
    "notebook_edit", "task_create", "task_get", "task_list", "task_update",
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
