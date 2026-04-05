# System Clow

**Agente de código AI no terminal e web** — multi-provider (Anthropic Claude / OpenAI GPT / Ollama), com 33 tools, 108 skills e 5 tipos de agente.

Lê, escreve, edita código, executa comandos, busca na web, gerencia projetos, roda pipelines, agenda cron jobs — tudo direto do terminal ou via web app.

## Instalação

### Rápida

```bash
git clone https://github.com/daniellbaptista2021-lgtm/batmam.git clow
cd clow
./install.sh
```

### Manual

```bash
git clone https://github.com/daniellbaptista2021-lgtm/batmam.git clow
cd clow
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Configuração

```bash
# Anthropic (recomendado)
cat > ~/.clow/app/.env << 'EOF'
CLOW_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
CLOW_MODEL=claude-sonnet-4-20250514
EOF

# Ou OpenAI
cat > ~/.clow/app/.env << 'EOF'
CLOW_PROVIDER=openai
OPENAI_API_KEY=sk-...
CLOW_MODEL=gpt-4.1
EOF
```

## Uso

```bash
clow                              # REPL interativo
clow "crie um servidor Flask"     # Prompt direto
clow -m claude-opus-4-20250514    # Escolher modelo
clow -y                           # Auto-approve
clow -C /caminho/do/projeto       # Diretório específico
clow --web --port 8080            # Web app
```

## Features (25+)

### Core
| Feature | Descrição |
|---------|-----------|
| **24 tools** | bash, read, write, edit, glob, grep, agent, web_search, web_fetch, notebook_edit, task_*, image_gen, pdf_tool, spreadsheet, scraper, docker_manage, git_advanced, http_request, supabase_query, n8n_workflow, whatsapp_send |
| **62 skills** | 36 built-in (/commit, /review, /test, /fix, /deploy, /ads, /leads...) + 26 imported (landing-page-generator, paid-ads, agent-designer...) |
| **8 agent types** | explore, plan, general, guide, devops, sales, data, creative |
| **4 tipos de memória** | user, feedback, project, reference — com frontmatter e stale detection |
| **Multi-provider** | Anthropic (Claude Sonnet/Opus/Haiku) ou OpenAI (GPT-4.1/o3/o4-mini) |

### Segurança
| Feature | Descrição |
|---------|-----------|
| **Sandbox bash** | Timeout 1-600s, background execution, bloqueio de comandos perigosos |
| **Git Safety Protocol** | Bloqueia --no-verify, git config, force push main, amend sem permissão |
| **Permissões granulares** | Classificação safe/write/dangerous/blocked por comando |
| **OWASP** | Validação de segurança no system prompt |

### Automação
| Feature | Descrição |
|---------|-----------|
| **Cron jobs** | `/cron create 5m "prompt"` — agentes agendados |
| **Remote triggers** | API REST com autenticação Bearer token + rate limiting |
| **Pipeline** | `/pipeline "etapa1" -> "etapa2" -> "etapa3"` — multi-agent encadeado |
| **Chatwoot** | Webhook para integração com CRM |
| **Backup** | `.tar.gz` automático de memórias com rotação |

### Interface
| Feature | Descrição |
|---------|-----------|
| **CLI estilo Claude Code** | ⏵ tool calls, ⎿ resultados, compactação, 🃏 spinner |
| **Web app** | FastAPI + WebSocket com UI dark mode |
| **Dashboard** | `/dashboard` — tasks, cron, memórias, ações em tempo real |
| **Health check** | `GET /health` — para monitoring (Uptime Kuma, etc.) |
| **VS Code extension** | 12 commands — inline edit, commit, review, test, diff, plan mode |
| **Streaming** | Respostas em tempo real com compactação automática |
| **Diff visual** | Verde/vermelho nas edições |
| **Logging JSON** | `~/.clow/logs/clow.jsonl` — integra com n8n, Supabase |

## Comandos

| Comando | Descrição |
|---------|-----------|
| `/help` | Ajuda completa |
| `/commit` | Commit inteligente |
| `/review` | Code review com nota 1-10 |
| `/test` | Gera e roda testes |
| `/plan` | Modo somente-leitura |
| `/pipeline "a" -> "b"` | Multi-agent pipeline |
| `/cron create 5m "x"` | Agendar execução |
| `/trigger start` | HTTP endpoint |
| `/backup` | Backup de memórias |
| `/memory` | Gerenciar memórias |
| `/tasks` | Listar tasks |
| `/model [nome]` | Trocar modelo |
| `/agents` | Listar tipos de agent |
| `/tools` | Listar ferramentas |
| `/web [porta]` | Web app + dashboard |
| `/diff` | Git diff colorido |
| `/status` | Git status |
| `!comando` | Bash direto |
| `/exit` | Sair |

## Modelos Suportados

### Anthropic (recomendado)
| Modelo | Uso |
|--------|-----|
| `claude-sonnet-4-20250514` | Equilíbrio (padrão) |
| `claude-opus-4-20250514` | Mais potente |
| `claude-haiku-4-5-20251001` | Mais rápido e barato |

### OpenAI
| Modelo | Uso |
|--------|-----|
| `gpt-4.1` | Melhor para código |
| `gpt-4.1-mini` | Mais rápido |
| `o3` | Reasoning avançado |
| `o4-mini` | Reasoning rápido |

Troque em runtime: `/model claude-opus-4-20250514`

## Web App

```bash
clow --web --port 8080
# Ou diretamente:
uvicorn clow.webapp:app --host 0.0.0.0 --port 8080
```

- Chat: `http://localhost:8080`
- Dashboard: `http://localhost:8080/dashboard`
- Health: `http://localhost:8080/health`

## CLOW.md

Crie um `CLOW.md` na raiz do projeto com instruções. O Clow lê automaticamente:

```markdown
# Instruções do Projeto
- Este projeto usa Django 5.0 com PostgreSQL
- Rode testes com: pytest
```

## Extensões

### Hooks (`~/.clow/settings.json`)
```json
{
  "hooks": {
    "post_tool_call": [
      {"tool": "bash", "command": "echo '$tool_args'", "enabled": true}
    ]
  }
}
```

### Plugins (`~/.clow/plugins/`)
```python
from clow.tools.base import BaseTool

class MeuTool(BaseTool):
    name = "meu_tool"
    description = "Minha ferramenta"
    def get_schema(self):
        return {"type": "object", "properties": {}}
    def execute(self, **kwargs):
        return "Resultado!"

def register(registry, hook_runner):
    registry.register(MeuTool())
```

### Skills customizados (`~/.clow/skills/`)
```python
SKILL = {
    "name": "deploy",
    "description": "Deploy para produção",
    "prompt": "Faça deploy do projeto: {args}",
    "aliases": ["d"],
}
```

## Estrutura

```
~/.clow/
├── app/.env        # API keys
├── sessions/       # Sessões salvas
├── memory/         # Memória persistente
├── logs/           # Logs JSON
├── backups/        # Backups de memória
├── plugins/        # Plugins customizados
├── skills/         # Skills customizados
└── settings.json   # Hooks, permissões, MCP
```

## Contribuindo

### Setup para desenvolvimento

```bash
git clone https://github.com/daniellbaptista2021-lgtm/batmam.git clow
cd clow
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Rodar testes

```bash
python -m pytest tests/ -v
```

### Estrutura do código

```
clow/
├── agent.py            # Agent principal (multi-provider)
├── agent_types.py      # 8 tipos de agent (explore, plan, devops, etc.)
├── cli.py              # CLI interativo
├── config.py           # Configuração (.env, settings.json)
├── _skills_cli.py      # 36 built-in skills
├── routes/             # Webapp routes (modular)
│   ├── auth.py         # Autenticação e sessões
│   ├── pages.py        # Páginas HTML (login, dashboard, admin)
│   ├── api.py          # REST API (conversations, upload, health)
│   ├── admin.py        # Admin + missions
│   ├── chat.py         # Chat HTTP endpoint
│   └── ws.py           # WebSocket real-time
├── tools/              # 24 tools
│   ├── base.py         # Registry e BaseTool
│   ├── bash.py, read.py, write.py, edit.py, ...
│   ├── image_gen.py, pdf_tool.py, spreadsheet.py
│   └── scraper.py, docker_manage.py, git_advanced.py
├── skills/             # Skills importadas (26)
│   └── imported/       # registry.json + prompts
├── templates/          # HTML templates
├── static/             # CSS, JS, assets
├── security.py         # CSP, HSTS, security headers
├── metrics.py          # Prometheus /metrics endpoint
├── error_tracker.py    # Error tracking SQLite
├── rate_limit.py       # Rate limit per-user + Redis optional
├── log_config.py       # Structured JSON logging
├── migrations.py       # Database migrations
└── deploy/             # Systemd, Docker, deploy script
```

### Deploy na VPS

```bash
# Via script (testa antes de reiniciar)
bash deploy/deploy.sh

# Via systemd
sudo systemctl restart clow
sudo journalctl -u clow -f

# Via Docker
cd deploy && docker compose -f docker-compose.prod.yml up -d
```

### Monitoring

- Health: `GET /health`
- Métricas: `GET /metrics` (Prometheus)
- Erros: `GET /api/v1/errors` (admin)
- Grafana: `http://VPS_IP:3001` (admin/clow2026)

## Licença

MIT — Criado por Daniel
