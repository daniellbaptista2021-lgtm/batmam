# Plano de Escalabilidade — Clow + Chatwoot

Arquitetura: **multi-tenant single-tenant-infrastructure**. Um único Chatwoot hospeda todas as subcontas (uma por cliente Clow via `account_id`), e o Clow controla o onboarding automático.

## Modelo atual (até ~50 clientes pagantes)

**Stack:** VPS única (145.223.30.216)
- Clow: FastAPI + SQLite + uvicorn
- Chatwoot: Docker (Rails + Sidekiq + Postgres + Redis)
- nginx: proxy `/cw/` → Chatwoot
- Cada cliente → 1 `account_id` no Chatwoot (subconta isolada)
- n8n, Grafana, Prometheus também no mesmo host

**Recursos atuais:** 7.8 GB RAM, 2 cores (pós upgrade).

## Como o cliente se conecta

Fluxo único (modo A):
1. Cliente clica "Ver CRM" no Clow → modal se não configurou
2. `/app/onboarding` cria automaticamente:
   - Nova `account_id` no Chatwoot (subconta)
   - Usuário com email do cliente + senha random
   - `chatwoot_connections` na base do Clow
3. Wizard mostra credenciais pro cliente copiar
4. Cliente clica "Ver CRM" de novo → iframe `/app/login` → digita email/senha → vê account dele

**Nada de Chatwoot externo.** Tudo no nosso domínio.

## Thresholds de escalabilidade (sinais pra escalar)

Monitorar via Grafana (já instalado):

| Métrica | Limite saudável | Ação |
|---------|-----------------|------|
| Load average | < 2.5 | Se > 4 consistente: upgrade |
| RAM usado | < 6 GB | Se > 7 GB + swap > 500 MB: upgrade |
| Chatwoot p95 response time | < 1.5s | Se > 3s: upgrade |
| SQLite `PRAGMA wal_checkpoint` lock time | < 100ms | Se > 500ms: migrar Postgres |
| Contagem de `account_users` Chatwoot | < 500 | Se > 500: avaliar particionamento |

## Passos de escalabilidade (fase 1 → 3)

### Fase 1 — até ~50 clientes (hoje)

**Infraestrutura:** VPS atual (7.8 GB / 2 cores).

**Ações quando atingir limite:**
- Upgrade VPS Hostinger: **16 GB / 4 cores** (próximo tier)
- Sem mudanças no código

### Fase 2 — 50 a 200 clientes

**Migrar SQLite → Postgres** no Clow (não no Chatwoot, que já usa Postgres).

Passos:
1. Instalar PostgreSQL 16 no host (ou container separado)
2. Migrar schema Clow via Alembic:
   ```bash
   # já existe /root/clow/clow/migrations_pg.py
   python -m clow.migrations_pg --target postgres://user:pw@localhost/clow
   ```
3. Dump SQLite → restore Postgres:
   ```bash
   sqlite3 /root/clow/data/clow.db .dump > dump.sql
   # ajustar sintaxe (AUTOINCREMENT, etc) + restore
   ```
4. Trocar env `DATABASE_URL=postgresql://...` em `/root/.clow/app/.env`
5. `systemctl restart clow`

**Upgrade VPS:** 32 GB / 8 cores.

### Fase 3 — 200 a 1000 clientes

**Separação de serviços** em VPS dedicadas:

| Serviço | VPS |
|---------|-----|
| Clow (app) | VPS 1 (8 GB / 2 cores) |
| Postgres (Clow + Chatwoot) | VPS 2 (16 GB / 4 cores) |
| Chatwoot Rails + Sidekiq | VPS 3 (16 GB / 4 cores) |
| Redis (Chatwoot + cache) | VPS 2 (mesmo do Postgres) |
| nginx / edge | VPS 1 ou Cloudflare |
| n8n / analytics | VPS 4 (separada) |

**Upgrade Chatwoot:** rodar múltiplos workers Sidekiq (WEB_CONCURRENCY=4, SIDEKIQ_CONCURRENCY=20).

### Fase 4 — acima de 1000 clientes

**Horizontal scaling:**
- Load balancer (HAProxy ou Cloudflare) → N Clow workers
- Postgres com replicação (primary + read replica)
- Redis Cluster
- Chatwoot em Kubernetes (gráfico Helm oficial existe)
- Object storage (S3) pra uploads Chatwoot em vez de filesystem

## Backup e disaster recovery

Automatizado (já configurado em `/root/backups/`):
- Backup diário Clow SQLite → `/root/backups/clow/clow-backup-{date}.tar.gz`
- Backup Chatwoot Postgres: usar `pg_dump` via cron (adicionar se não tem)
- Retenção: 7 dias locais + sync pra S3/Backblaze pra 30d+

## Isolamento multi-tenant mantido em todas as fases

Mesmo escalando, cada cliente continua com:
- `account_id` próprio no Chatwoot
- `user_id` próprio no Clow
- `chatwoot_connections.active=1` apenas pro user dono
- Nginx `auth_request` validando ownership antes do proxy
- Path-level `/accounts/{N}/` validation no authz (N deve bater com user)

Nenhuma mudança de arquitetura exigida pra adicionar ou remover clientes — só gerenciar recursos conforme cresce.
