# Clow

**Agente de IA para WhatsApp, CRM e automação de negócios.**

Atenda clientes no WhatsApp com IA 24h, gerencie leads no CRM integrado, crie landing pages e automatize fluxos — tudo em uma plataforma.

---

## O que o Clow faz

| Funcionalidade | Descrição |
|---|---|
| **WhatsApp com IA** | Agente que responde clientes 24h com persona, base de conhecimento e handoff humano |
| **CRM integrado** | Gestão de leads, funil de vendas, histórico de conversas e follow-up automático |
| **Landing pages** | Geração automática de páginas de conversão via chat |
| **Automações n8n** | Fluxos prontos de CRM, cobrança, agendamento e marketing |
| **Planilhas e documentos** | Criação de Excel, Word e apresentações via conversa |
| **Chat com IA** | Assistente inteligente para tarefas do negócio |

---

## Planos

| Plano | Preço | Modelo | Inclui |
|---|---|---|---|
| **Lite** | R$ 169/mês | Haiku 4.5 | CRM + 8 fluxos n8n + WhatsApp |
| **Starter** | R$ 298/mês | Sonnet 4 | CRM + 8 fluxos + 3 usuários |
| **Pro** | R$ 487/mês | Sonnet 4 | 2.000 fluxos + 5 usuários |
| **Business** | R$ 667/mês | Sonnet 4 | 3.000 fluxos + 10 usuários |

Acesso via assinatura — sem plano gratuito, sem período de teste.

---

## Como acessar

1. **Assine** um plano em [clow.com.br](https://clow.com.br)
2. **Receba** suas credenciais de acesso por email
3. **Faça login** na plataforma web
4. **Configure** seu WhatsApp, base de conhecimento e funil de vendas
5. **Comece** a atender clientes com IA

---

## Funcionalidades detalhadas

### WhatsApp IA
- Responde automaticamente com persona configurável
- Base de conhecimento em texto (preços, FAQ, regras)
- Handoff humano: palavra-chave pausa o bot por 2h
- Histórico completo de conversas no CRM
- Suporte a múltiplas instâncias

### CRM
- Funil kanban com etapas customizáveis
- Importação de leads em massa (CSV)
- Campanhas de email integradas
- Timeline de atividades por lead
- Agendamento e links de reunião

### Automações (n8n)
- 8 fluxos prontos inclusos nos planos Starter+
- Cobrança automática de mensalidades
- Follow-up de leads por WhatsApp
- Relatórios diários automáticos
- Integração com Google Calendar, Supabase, webhooks

### Geração de conteúdo
- Landing pages responsivas (HTML completo)
- Planilhas Excel com dados e fórmulas
- Documentos Word e apresentações
- Imagens via IA (sem custo adicional)
- Copies para anúncios e redes sociais

### Website Cloner
Clona qualquer site, landing page ou hotsite gerando um **projeto Next.js modular completo** com pipeline de 5 fases usando DeepSeek-reasoner.

**Como usar:**
```
clona esse site: https://exemplo.com.br
/clone https://exemplo.com.br
clow clone https://exemplo.com.br
```

**O que faz:**
- Captura screenshots desktop (1440px) e mobile (390px) com Playwright
- Extrai design tokens reais via `getComputedStyle` (cores, fontes, Google Fonts)
- Mapeia topologia DOM e gera spec markdown auditável por seção
- Gera componentes React/TSX (1 por seção) com Tailwind v3 + shadcn/ui
- Valida `npx tsc --noEmit` com retry automático até 3x
- Roda `npm run build` para garantir compilação

**Output em `~/.clow/clones/<dominio>/`:**
- Projeto Next.js 15 + React 19 pronto pra `npm run dev`
- `docs/research/` com specs auditáveis, screenshots e topology
- Assets baixados (imagens, fontes, ícones) em `public/`

**API REST:** `POST /api/v1/clone` + `GET /api/v1/clone/jobs/{id}`

**Pré-requisitos:** Playwright + DEEPSEEK_API_KEY + Node.js 20+ (opcional)

---

## Segurança

- Autenticação por sessão criptografada
- Dados isolados por usuário e tenant
- Sem armazenamento de API keys de terceiros
- Logs de auditoria de todas as ações
- Rate limiting por usuário e plano

---

## Suporte

Em caso de dúvidas ou problemas, entre em contato com o suporte via WhatsApp ou email informado no painel da sua conta.

---

*Criado por Daniel Baptista — Todos os direitos reservados.*
