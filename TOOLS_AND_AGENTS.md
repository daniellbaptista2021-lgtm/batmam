# Clow — Tools & Agentes Especializados

> Powered by DeepSeek (deepseek-chat + deepseek-reasoner)
> 65 tools | 14 agentes | Orquestracao inteligente

---

## Modelo de Roteamento

| Modelo | Quando |
|--------|--------|
| **deepseek-chat** | Respostas rapidas, chatbot, perguntas simples, confirmacoes |
| **deepseek-reasoner** | Keywords complexas (cria, desenvolve, debug, analisa, planeja, otimiza), stack traces, tasks >3 etapas, contexto >8K tokens |
| **Fallback automatico** | Se chat retornar resposta insuficiente → retry com reasoner |

---

## Tools (65 total)

### Core (10)
| Tool | Descricao |
|------|-----------|
| `bash` | Executa comandos bash/shell com sandbox |
| `read` | Le arquivos com suporte a offset/limit, imagens, PDFs |
| `write` | Cria e escreve arquivos |
| `edit` | Edicao precisa com str_replace e diff visual |
| `glob` | Busca arquivos por padrao glob |
| `grep` | Busca regex em conteudo de arquivos |
| `agent` | Lanca sub-agentes especializados |
| `web_search` | Pesquisa web via DuckDuckGo |
| `web_fetch` | Busca conteudo de URL (HTML → markdown) |
| `notebook_edit` | Edita celulas de Jupyter notebooks |

### Task Management (4)
| Tool | Descricao |
|------|-----------|
| `task_create` | Cria tasks com dependencias |
| `task_update` | Atualiza status e output |
| `task_list` | Lista tasks com filtros |
| `task_get` | Detalhes de uma task |

### SSH & VPS (7)
| Tool | Descricao |
|------|-----------|
| `ssh_connect` | Executa comandos em VPS remota via SSH |
| `manage_process` | Gerencia servicos systemd (start/stop/restart/logs) |
| `configure_nginx` | Cria/edita/ativa configs Nginx, proxy_pass automatico |
| `manage_ssl` | Instala/renova certificados SSL Let's Encrypt |
| `monitor_resources` | Monitora CPU, RAM, disco, rede, processos |
| `manage_cron` | Gerencia cron jobs (listar/criar/remover) |
| `backup_create` | Backup/restore de arquivos e bancos (tar, pg_dump, mysqldump) |

### Git (2)
| Tool | Descricao |
|------|-----------|
| `git_ops` | Operacoes completas: init, clone, add, commit, push, pull, branch, checkout, merge, status, log, diff, tag |
| `git_advanced` | Avancado: cherry-pick, rebase, stash, bisect, blame, reflog |

### Database (5)
| Tool | Descricao |
|------|-----------|
| `query_postgres` | SQL no PostgreSQL via psql |
| `query_mysql` | SQL no MySQL/MariaDB via mysql CLI |
| `query_redis` | Comandos Redis via redis-cli |
| `supabase_query` | SQL no Supabase via REST API |
| `manage_migrations` | Migrations: SQL puro, Alembic, Django, Prisma |

### Deploy (2)
| Tool | Descricao |
|------|-----------|
| `deploy_vercel` | Deploy completo Vercel via API REST: login, projetos, deploy, rollback, dominios, env vars. Token criptografado por usuario. |
| `deploy_vps` | Deploy VPS via git pull, Docker Compose ou PM2 |

### Web & APIs (3)
| Tool | Descricao |
|------|-----------|
| `http_request` | GET/POST/PUT/DELETE em qualquer API |
| `scraper` | Web scraping com CSS selectors/regex |
| `web_search` | Pesquisa web |

### WhatsApp (10)
| Tool | Descricao |
|------|-----------|
| `whatsapp_send` | Envia mensagem via Z-API |
| `whatsapp_create_instance` | Cria instancia de bot |
| `whatsapp_connect_test` | Testa conexao Z-API |
| `whatsapp_save_prompt` | Salva prompt do bot |
| `whatsapp_save_rag_text` | Salva base de conhecimento |
| `whatsapp_setup_webhook` | Configura webhook |
| `whatsapp_test_webhook` | Testa webhook |
| `whatsapp_full_test` | Teste completo end-to-end |
| `whatsapp_send_test_message` | Envia mensagem de teste |
| `whatsapp_list_instances` | Lista instancias |

### Chatwoot CRM (15)
| Tool | Descricao |
|------|-----------|
| `chatwoot_setup` | Configura conexao CRM |
| `chatwoot_test_connection` | Testa conexao |
| `chatwoot_list_labels` / `_create_label` | Gerencia etiquetas |
| `chatwoot_search_contact` / `_create_contact` | Gerencia contatos |
| `chatwoot_list_conversations` / `_assign_conversation` / `_label_conversation` | Gerencia conversas |
| `chatwoot_list_inboxes` / `_list_agents` | Canais e agentes |
| `chatwoot_create_team` / `_create_automation` / `_list_automations` | Times e automacoes |
| `chatwoot_report` | Relatorio resumido |

### Meta Ads (1)
| Tool | Descricao |
|------|-----------|
| `meta_ads` | Campanhas, ad sets, insights, pixel, pause/activate via Graph API v21 |

### Design & Documentos (5)
| Tool | Descricao |
|------|-----------|
| `image_gen` | Gera imagens com DALL-E 3 (HD, vivid/natural, 3 tamanhos) + fallback Pollinations.ai gratuito |
| `design_generate` | Cria designs profissionais (posts, banners, cards) |
| `canva_template` | Links de templates Canva |
| `pdf_tool` | Cria/le/merge/split PDFs |
| `spreadsheet` | Cria/edita planilhas Excel/CSV |

### Docker (1)
| Tool | Descricao |
|------|-----------|
| `docker_manage` | ps, logs, restart, stop, start, stats, inspect |

### n8n (1)
| Tool | Descricao |
|------|-----------|
| `n8n_workflow` | Lista, ativa, desativa, executa workflows n8n |

---

## Agentes Especializados (14)

| Agente | Ativa quando | Tools principais |
|--------|-------------|-----------------|
| **fullstack** | "cria site", "desenvolve app", "API REST" | Todos (acesso total) |
| **devops** | "configura servidor", "docker", "nginx", "SSL" | bash, docker, nginx, ssl, ssh |
| **bot** | "cria bot", "WhatsApp", "chatbot" | whatsapp_*, n8n, http_request |
| **automation** | "automatiza", "n8n", "workflow", "webhook" | n8n, http_request, bash |
| **design** | "design", "banner", "logo", "mockup" | image_gen, design_generate, write |
| **marketing** | "Meta Ads", "campanha", "trafego pago" | meta_ads, image_gen, spreadsheet |
| **data** | "planilha", "analise", "SQL", "relatorio" | supabase, spreadsheet, pdf, bash |
| **crm** | "Chatwoot", "leads", "funil", "CRM" | chatwoot_*, ssh, nginx, ssl, docker |
| **code** | "debug", "bug", "refatora", "codigo" | bash, read, write, edit, grep |
| **creative** | "copy", "roteiro", "texto", "landing page" | write, image_gen, web_search |
| **explore** | Sub-agente de busca rapida | read, glob, grep (read-only) |
| **plan** | Sub-agente de planejamento | read, glob, grep, task_create |
| **sales** | Vendas de seguros | whatsapp, supabase, pdf, spreadsheet |
| **guide** | Duvidas sobre o Clow | read, glob, grep |

---

## Fluxo de Execucao

```
Task recebida
     │
     ▼
[Orchestrator] ──→ Analisa complexidade
     │              Escolhe modelo (chat/reasoner)
     │              Detecta dominios de tools
     │              Seleciona agente especializado
     │
     ▼
[Agent Loop] ──→ Envia ao DeepSeek com system prompt mestre
     │           + contexto do agente especializado
     │
     ▼
[DeepSeek] ──→ Escolhe tools automaticamente
     │          Executa tool calls
     │
     ▼
[Verificacao] ──→ Resultado OK? → Finaliza
     │              Erro? → Auto-correcao (ate 3x)
     │              Resposta insuficiente? → Fallback → reasoner
     │
     ▼
[Contexto] ──→ >80K tokens? → Comprime automaticamente
                Salva memoria relevante
```

---

## Fluxo Landing Page → Deploy (automatico)

Quando usuario pedir "cria landing page e sobe no Vercel":

```
1. Orquestrador detecta: fullstack agent + reasoner
2. DeepSeek cria HTML/CSS/JS completo
3. Se pediu imagens: DALL-E 3 gera (ou Pollinations se sem key)
4. deploy_vercel(action='deploy') sobe no Vercel
5. Retorna URL publica pronta
```

Exemplo: "Cria landing page para academia com hero e depoimentos"
→ Gera imagens de academia com DALL-E
→ Cria HTML com imagens incorporadas
→ Deploy no Vercel
→ "Sua landing page: https://academia-xyz.vercel.app"

---

## DALL-E 3 — Geracao de Imagens

| Parametro | Opcoes | Padrao |
|-----------|--------|--------|
| Tamanho | 1024x1024, 1792x1024, 1024x1792 | 1024x1024 |
| Qualidade | standard, hd | standard |
| Estilo | vivid, natural | vivid |
| Quantidade | 1-4 | 1 |

Ativa automaticamente quando: "gera imagem", "cria banner", "faz logo",
"cria thumbnail", "gera criativo", "faz arte"

Sem OPENAI_API_KEY → fallback automatico para Pollinations.ai (gratuito).

---

## Vercel Deploy — Acoes Completas

| Acao | Descricao |
|------|-----------|
| `login` | Autentica com token (salva criptografado) |
| `whoami` | Verifica conta |
| `list_projects` | Lista projetos |
| `create_project` | Cria projeto (nextjs, vite, static, etc) |
| `deploy` | Upload de arquivos + build + URL de producao |
| `list_deployments` | Historico de deploys |
| `rollback` | Volta para deploy anterior |
| `add_domain` | Adiciona dominio customizado |
| `set_env` / `list_env` / `remove_env` | Variaveis de ambiente |

Token por usuario: cada usuario salva seu token via
`deploy_vercel(action='login', token='...')` — criptografado no credential_manager.

---

## Configuracao (.env)

```env
DEEPSEEK_API_KEY=sk-sua-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_REASONER_MODEL=deepseek-reasoner

# DALL-E (opcional — sem key usa Pollinations gratuito)
OPENAI_API_KEY=sk-sua-key-openai
DALLE_MODEL=dall-e-3

# Vercel (cada usuario salva o proprio token via /connect vercel)
VERCEL_DEFAULT_TOKEN=
```
