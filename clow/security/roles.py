"""Role-based access control: define quais tools cada role pode usar.

Single source of truth: agent.py e qualquer outro modulo importam daqui.
Filosofia:
- ADMIN: acesso total (sem restricao via roles).
- TENANT_USER (cliente do SaaS): allowlist explicita. So tools que sao
  intrinsecamente seguras (nao podem ler filesystem, nao podem fazer HTTP
  arbitrario, nao usam credenciais do admin).

Adicionar tool nova? Decida onde:
- Tool que mexe em arquivo, shell, HTTP, credencial -> ADMIN_ONLY_TOOLS.
- Tool 100% sandboxed (memoria do proprio user, busca web read-only,
  geracao de texto/imagem com chave do proprio user) -> TENANT_USER_TOOLS.
- Em duvida -> NAO adicionar em TENANT_USER_TOOLS. Whitelist por padrao.
"""
from __future__ import annotations


# Tools que SO admin pode usar. Blocklist explicita.
# Qualquer tool que possa ler/escrever no servidor, executar shell, acessar
# credenciais do admin (.env), ou interagir com integracoes do admin.
ADMIN_ONLY_TOOLS: frozenset[str] = frozenset({
    # Filesystem / shell
    "read", "write", "edit", "bash", "glob", "grep", "notebook_edit",
    # HTTP arbitrario (pode extrair credenciais, fazer SSRF)
    "http_request", "web_fetch",
    # Integracoes da conta admin (acessam .env)
    "meta_ads", "canva_tools", "supabase_query",
    # Infra / deploy
    "docker_manage", "ssh_vps", "deploy_tools", "git_ops", "git_advanced",
    "cron_tools", "remote_trigger", "config_tool", "mcp_tools",
    # DB / workflows do admin
    "database_tools", "n8n_workflow",
    # Captura / browser (pode acessar sessoes do admin)
    "snip_tool", "browser", "scraper",
    # Sub-agent (poderia spawnar com outras tools)
    "agent",
})


# Allowlist explicita pra tenant_user. Defesa positiva: se uma tool nova
# aparecer na registry e nao estiver aqui nem em ADMIN_ONLY_TOOLS, o tenant
# nao recebe (default-deny via filter strict_allowlist=True).
TENANT_USER_TOOLS: frozenset[str] = frozenset({
    # Busca web read-only (nao baixa conteudo arbitrario)
    "web_search",
    # Memoria do proprio usuario
    "memory_save", "memory_search", "memory_list", "memory_delete",
    # Tarefas/missoes do proprio usuario
    "task_list", "task_get", "task_create", "task_update",
    # Ferramentas de geracao com chave do proprio user (DeepSeek dele)
    "image_generate",
    # Cotador SulAmerica (logica pura, sem credencial)
    "cotador_sulamerica",
    # WhatsApp do proprio user (Z-API instance dele)
    "whatsapp_send",
})


# Modo strict: True = whitelist (so o que esta em TENANT_USER_TOOLS).
# False = blacklist (qualquer coisa menos ADMIN_ONLY_TOOLS).
# Default False por enquanto pra nao quebrar features. Migrar pra True
# depois de auditar todas as tools que tenant_user usa hoje.
TENANT_USER_STRICT_ALLOWLIST: bool = False


def filter_tools_for_role(tool_names: set[str], is_admin: bool) -> set[str]:
    """Filtra um conjunto de nomes de tools de acordo com a role.

    Admin recebe tudo. Tenant_user recebe (tool_names - ADMIN_ONLY_TOOLS),
    e se TENANT_USER_STRICT_ALLOWLIST entao intersecta com TENANT_USER_TOOLS.
    """
    if is_admin:
        return set(tool_names)
    filtered = set(tool_names) - ADMIN_ONLY_TOOLS
    if TENANT_USER_STRICT_ALLOWLIST:
        filtered = filtered & TENANT_USER_TOOLS
    return filtered


# Helper: is this user_id an admin? Cached per-process.
_admin_cache: dict[str, bool] = {}


def is_user_admin(user_id: str | None) -> bool:
    """Retorna True se o user_id pertence a um admin. Default: False (mais seguro)."""
    if not user_id:
        return False
    if user_id in _admin_cache:
        return _admin_cache[user_id]
    try:
        from ..database import get_db
        with get_db() as _db:
            row = _db.execute("SELECT is_admin FROM users WHERE id=?", (user_id,)).fetchone()
        result = bool(row and row[0])
    except Exception:
        result = False
    _admin_cache[user_id] = result
    return result


def clear_admin_cache(user_id: str | None = None) -> None:
    """Limpa cache. Usar quando promover/demover admin."""
    if user_id is None:
        _admin_cache.clear()
    else:
        _admin_cache.pop(user_id, None)
