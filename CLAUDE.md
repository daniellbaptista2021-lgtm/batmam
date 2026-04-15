# Clow - AI Agent Platform

Clow is a WhatsApp AI agent, CRM, and business automation platform built in Python.

## Architecture

- **Backend**: Python (FastAPI/Uvicorn) on port 8001
- **AI Provider**: DeepSeek (OpenAI-compatible SDK)
- **Database**: SurrealDB + SQLite + PostgreSQL (via Docker)
- **Messaging**: WhatsApp via Evolution API + Chatwoot
- **Automation**: n8n workflows
- **Monitoring**: Grafana + Prometheus
- **Reverse Proxy**: Nginx

## Directory Structure

- `clow/` - Main Python package (agent, tools, routes, integrations)
- `clow/tools/` - Agent tools (bash, git, web, whatsapp, etc.)
- `clow/routes/` - FastAPI routes (API, admin, billing, bridge, etc.)
- `clow/integrations/` - External service integrations
- `clow/generators/` - Content generators (landing pages, docs, images)
- `deploy/` - Docker, k8s, systemd configs
- `static/` - Frontend assets (HTML, CSS, JS)
- `tests/` - Test suite

## Running Instance

- Service: `systemctl status clow` (systemd)
- Working dir: `/root/clow` (production)
- Repo: `/root/batmam` (git)
- Virtual env: `/root/clow/.venv`
- Config: `/root/.clow/app/.env`

## Key Services (Docker)

- Chatwoot (port 3000) - Customer messaging
- n8n (port 5678) - Workflow automation
- PostgreSQL (port 5432) - Database
- Redis (port 6379) - Cache
- Grafana (port 3001) - Monitoring
- Prometheus (port 9090) - Metrics

## PM2 Processes

- chatwoot-bridge - Bridge between Chatwoot and Clow

## Development Notes

- Use DeepSeek API (compatible with OpenAI SDK)
- All permissions auto-approved (read, write, bash)
- Extended thinking enabled by default
- Max tokens: 8192 per response
