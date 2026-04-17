"""Ferramentas do Clow -- Claude Code Architecture.

42 Claude Code official tools always available:
- File Operations: Read, Write, Edit, Glob, Grep
- Execution: Bash
- Agent: Agent, SubAgent management, Teams
- Task: Task CRUD, Task Output, Task Stop
- Web: WebFetch, WebSearch
- Workflow: Notebook, Skill, Workflow
- Plan Mode: Enter/Exit Plan Mode, ToolSearch
- Context: Snip, Sleep, Monitor
- Git: Enter/Exit Worktree
- Cron: Create, Delete, List
- MCP: List/Read Resources
- Notification: SendFile, PushNotification
- Config: Config read/write
- Remote: RemoteTrigger

Additional Clow-specific tools loaded on-demand via orchestrator.
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
from .task_tool import TaskCreateTool, TaskUpdateTool, TaskListTool, TaskGetTool

# New Claude Code tools
from .plan_tools import EnterPlanModeTool, ExitPlanModeTool, ToolSearchTool
from .worktree_tools import EnterWorktreeTool, ExitWorktreeTool
from .agent_management import (
    SendMessageTool, TaskStopTool, TeamCreateTool, TeamDeleteTool, ListPeersTool,
)
from .skill_tool import SkillTool
from .snip_tool import SnipTool
from .sleep_tool import SleepTool
from .monitor_tool import MonitorTool
from .cron_tools import CronCreateTool, CronDeleteTool, CronListTool
from .mcp_tools import ListMcpResourcesTool, ReadMcpResourceTool
from .notification_tools import SendUserFileTool, PushNotificationTool
from .remote_trigger import RemoteTriggerTool
from .workflow_tool import WorkflowTool
from .task_output import TaskOutputTool
from .config_tool import ConfigTool
from .memory_tools import MemoryReadTool, MemoryWriteTool, MemoryDeleteTool
from .clone_tool import CloneWebsiteTool

from .base import BaseTool, ToolRegistry

# CLAUDE CODE OFFICIAL TOOLS (42) -- always available
CLAUDE_CODE_TOOLS = [
    # File Operations (5)
    "read", "write", "edit", "glob", "grep",
    # Execution (1)
    "bash",
    # Agent (6)
    "agent", "send_message", "task_stop", "team_create", "team_delete", "list_peers",
    # Task (5)
    "task_create", "task_update", "task_list", "task_get", "task_output",
    # Web (2)
    "web_search", "web_fetch",
    # Workflow (3)
    "notebook_edit", "skill", "workflow",
    # Plan Mode (3)
    "enter_plan_mode", "exit_plan_mode", "tool_search",
    # Context Management (3)
    "snip", "sleep", "monitor",
    # Git Worktree (2)
    "enter_worktree", "exit_worktree",
    # Cron (3)
    "cron_create", "cron_delete", "cron_list",
    # MCP (2)
    "list_mcp_resources", "read_mcp_resource",
    # Notification (2)
    "send_user_file", "push_notification",
    # Config (1)
    "config",
    # Remote (1)
    "remote_trigger",
    # Memory (3)
    "memory_read", "memory_write", "memory_delete",
]

# CORE TOOLS -- always loaded (backward compat alias)
CORE_TOOLS = CLAUDE_CODE_TOOLS

# ON-DEMAND TOOLS -- loaded only when orchestrator detects need (Clow-specific)
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
    # Website Cloner (1)
    "clone_website",
]

# All tool classes for easy import
CLAUDE_CODE_TOOL_CLASSES = [
    # File Operations
    ReadTool, WriteTool, EditTool, GlobTool, GrepTool,
    # Execution
    BashTool,
    # Agent
    AgentTool, SendMessageTool, TaskStopTool, TeamCreateTool, TeamDeleteTool, ListPeersTool,
    # Task
    TaskCreateTool, TaskUpdateTool, TaskListTool, TaskGetTool, TaskOutputTool,
    # Web
    WebSearchTool, WebFetchTool,
    # Workflow
    NotebookEditTool, SkillTool, WorkflowTool,
    # Plan Mode
    EnterPlanModeTool, ExitPlanModeTool, ToolSearchTool,
    # Context
    SnipTool, SleepTool, MonitorTool,
    # Worktree
    EnterWorktreeTool, ExitWorktreeTool,
    # Cron
    CronCreateTool, CronDeleteTool, CronListTool,
    # MCP
    ListMcpResourcesTool, ReadMcpResourceTool,
    # Notification
    SendUserFileTool, PushNotificationTool,
    # Config
    ConfigTool,
    # Remote
    RemoteTriggerTool,
    # Memory
    MemoryReadTool, MemoryWriteTool, MemoryDeleteTool,
    # Website Cloner
    CloneWebsiteTool,
]

__all__ = [
    "BaseTool",
    "ToolRegistry",
    # File Operations
    "BashTool",
    "ReadTool",
    "WriteTool",
    "EditTool",
    "GlobTool",
    "GrepTool",
    # Agent
    "AgentTool",
    "SendMessageTool",
    "TaskStopTool",
    "TeamCreateTool",
    "TeamDeleteTool",
    "ListPeersTool",
    # Task
    "TaskCreateTool",
    "TaskUpdateTool",
    "TaskListTool",
    "TaskGetTool",
    "TaskOutputTool",
    # Web
    "WebSearchTool",
    "WebFetchTool",
    # Workflow
    "NotebookEditTool",
    "SkillTool",
    "WorkflowTool",
    # Plan Mode
    "EnterPlanModeTool",
    "ExitPlanModeTool",
    "ToolSearchTool",
    # Context
    "SnipTool",
    "SleepTool",
    "MonitorTool",
    # Worktree
    "EnterWorktreeTool",
    "ExitWorktreeTool",
    # Cron
    "CronCreateTool",
    "CronDeleteTool",
    "CronListTool",
    # MCP
    "ListMcpResourcesTool",
    "ReadMcpResourceTool",
    # Notification
    "SendUserFileTool",
    "PushNotificationTool",
    # Config
    "ConfigTool",
    # Remote
    "RemoteTriggerTool",
    # Memory
    "MemoryReadTool",
    "MemoryWriteTool",
    "MemoryDeleteTool",
    # Website Cloner
    "CloneWebsiteTool",
    # Lists
    "CORE_TOOLS",
    "CLAUDE_CODE_TOOLS",
    "CLAUDE_CODE_TOOL_CLASSES",
    "ONDEMAND_TOOLS",
]
