# Clow — Inteligência Infinita

**Agente de IA para WhatsApp, CRM, copywriting e automação de negócios.**

Atenda clientes no WhatsApp com IA 24h, gerencie leads no CRM integrado, crie landing pages, gere conteúdo e automatize fluxos — tudo em uma plataforma única.

> *Inteligência Infinita • Possibilidades Premium*

---

## O que o Clow faz

| Funcionalidade | Descrição |
|---|---|
| **WhatsApp com IA** | Agente que responde clientes 24h com persona, base de conhecimento e handoff humano |
| **CRM integrado (Chatwoot)** | Gestão de leads, funil de vendas, histórico de conversas e follow-up |
| **Copywriting** | Textos persuasivos para anúncios, e-mails, propostas e scripts de vendas |
| **Roteiros de vídeo** | Scripts para Reels, TikTok e YouTube Shorts com estrutura de conversão |
| **Landing pages** | Geração automática de páginas de conversão via chat |
| **Automações n8n** | Fluxos prontos de CRM, cobrança, agendamento, relatórios |
| **Planilhas e documentos** | Criação de Excel, Word e apresentações via conversa |
| **Website Cloner** | Clona qualquer site em projeto Next.js 15 modular |
| **Disparos em massa** | Campanhas via templates Meta aprovados, com anti-ban |

---

## Planos

| Plano | Preço/mês | Tokens/dia | WhatsApp | Usuários | Fluxos n8n | CRM |
|---|---|---|---|---|---|---|
| **ONE** | R$ 139,90 | 1M | 1 instância | 1 | — | — |
| **SMART** | R$ 177,90 | 1,8M | 2 instâncias | 3 | 8 | ✓ |
| **PROFISSIONAL** | R$ 289,90 | 2,5M | 3 instâncias | 5 | 2.000 | ✓ |
| **BUSINESS** | R$ 367,90 | 3M | 5 instâncias | 10 | 3.000 | ✓ |

**Pagamento:** cartão de crédito, boleto ou PIX.
**Modelo:** assinatura mensal recorrente. Sem plano gratuito, sem período de teste.

---

## Como acessar

1. **Assine** um plano em [clow.pvcorretor01.com.br](https://clow.pvcorretor01.com.br)
2. **Receba** suas credenciais por e-mail
3. **Faça login** na plataforma web
4. **Configure** seu WhatsApp, base de conhecimento e funil de vendas
5. **Comece** a atender clientes com IA

---

## Funcionalidades detalhadas

### WhatsApp IA
- Integração com **Z-API** e **Meta API Oficial**
- Persona configurável por negócio
- Base de conhecimento (preços, FAQ, regras, serviços)
- Handoff humano: palavra-chave pausa o bot por 2h
- Etiquetas no Chatwoot: `humano` silencia, `bot` reativa, `lead-quente` marca interesse
- Tools automáticas: consulta CEP (ViaCEP) e consulta CPF por regex
- Mensagem de boas-vindas, horário comercial e respostas rápidas

### CRM (Chatwoot integrado)
- Funil kanban com etapas customizáveis
- Importação em massa de leads (CSV)
- Etiquetas: Lead Quente, Frio, VIP, Follow-up
- Timeline de atividades por lead
- Campanhas de e-mail, agendamento e links de reunião
- Auto-assign e auto-label configuráveis

### Automações (n8n)
- Cobrança automática de mensalidades
- Follow-up de leads por WhatsApp
- Relatórios diários
- Integrações: Google Calendar, Supabase, PostgreSQL, webhooks

### Meta API — templates e disparos
- Templates pré-aprovados para iniciar conversas (UTILITY a partir de ~R$0,03/msg)
- CSV com `nome` e `telefone` (DDI+DDD, ex: `5521999999999`)
- Anti-ban: intervalo 3–10s entre mensagens, máx. 1.000/h no início
- Pausa automática se a taxa de erro passar de 5%

### Geração de conteúdo
- Landing pages responsivas (HTML completo)
- Planilhas Excel com dados e fórmulas
- Documentos Word e apresentações
- Imagens via IA (sem custo adicional)
- Copies para anúncios (Facebook/Instagram/Google) e e-mails

### Website Cloner
Clona sites, landing pages ou hotsites gerando um **projeto Next.js 15 modular completo** com pipeline de 5 fases.

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

**Saída em `~/.clow/clones/<dominio>/`:**
- Projeto Next.js 15 + React 19 pronto pra `npm run dev`
- `docs/research/` com specs, screenshots e topology
- Assets baixados (imagens, fontes, ícones) em `public/`

**API REST:** `POST /api/v1/clone` + `GET /api/v1/clone/jobs/{id}`

---

## Segurança

- Autenticação por sessão criptografada
- Dados isolados por usuário e tenant
- Sem armazenamento de chaves de API de terceiros em texto plano
- Logs de auditoria de todas as ações
- Rate limiting por usuário e plano
- Sessões web efêmeras (histórico resetado diariamente); para memória persistente, use Clow via terminal ou VPS própria

---

## Suporte

Dúvidas ou problemas: fale com o suporte pelo WhatsApp ou e-mail informado no painel da sua conta.

---

*Criado por Daniel Baptista — Todos os direitos reservados.*
