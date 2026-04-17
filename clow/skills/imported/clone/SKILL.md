---
name: "clone"
description: "Clona qualquer site/landing page gerando projeto Next.js completo via pipeline 5-fases (deepseek-reasoner)"
license: MIT
metadata:
  version: 1.0.0
  author: Clow
  category: integration
  triggers:
    - /clone
    - clonar site
    - clone site
    - clone website
    - clonar landing
    - clonar pagina
    - website cloner
---

# /clone — Website Cloner

Clona qualquer site, landing page ou hotsite gerando um **projeto Next.js modular completo**, com componentes por seção, design tokens extraídos do original, e validação de build.

## Como usar

```
/clone https://exemplo.com.br
clow clone https://exemplo.com.br --skip-qa
```

A skill é detectada automaticamente quando o usuário escreve algo como:
- "clona esse site: https://..."
- "clonar a landing page X"
- "website cloner para Y"

## Pipeline (5 fases)

1. **Recon** — Playwright abre o site, scrolla até o fim, dispara lazy loading. Tira 2 screenshots (desktop 1440x900 + mobile 390x844). Extrai via `getComputedStyle()` as cores dominantes, fontes, Google Fonts URLs, meta (title/description/lang/favicon) e topologia DOM (header/nav/main/sections/footer com posições).

2. **Foundation** — copia o scaffold `templates/website-cloner-base/` (Next.js 15 + Tailwind v3 + shadcn/ui) pra `~/.clow/clones/<dominio>/`. Reescreve `globals.css` com tokens HSL extraídos. Reescreve `layout.tsx` injetando Google Fonts e meta. Baixa todos os assets (imagens, CSS, fontes, favicons) pra `public/`. Roda `npm install` (se Node disponível).

3. **Specs** — divide a página em seções top-level (filtra contidas/triviais), recorta screenshot por seção, e chama **deepseek-reasoner** com cada recorte + dados do DOM pra gerar um spec markdown estruturado em `docs/research/components/<nome>.spec.md`.

4. **Builder** — pra cada spec, chama **deepseek-reasoner** passando spec + screenshot da seção, gera `src/components/<Nome>.tsx`. Valida com `npx tsc --noEmit`. Em caso de erro, retry até 3x com erro inline. Monta `src/app/page.tsx` importando todos.

5. **QA** — roda `npm run build`. (Iteração 2: side-by-side diff visual com retry de discrepâncias.)

## Princípios não-negociáveis

- **Valores exatos** de `getComputedStyle()`. Nunca estimar cores/tamanhos/espaçamentos.
- **Mobile-first**: Tailwind `base` é mobile, `md:`/`lg:` ajustam desktop.
- **shadcn/ui + Tailwind v3** apenas. Sem CSS modules, sem libs externas.
- **TypeScript strict**. Componentes tipados.
- **Server Components** por padrão (sem `"use client"`), exceto se houver interatividade.
- **Texto exato** do original. Sem reescrever copywriting.

## Output

```
~/.clow/clones/<dominio>/
├── docs/research/
│   ├── RECON.json              ← dados crus extraídos
│   ├── PAGE_TOPOLOGY.md        ← seções detectadas
│   ├── BEHAVIORS.md            ← cores/fontes/Google Fonts
│   ├── screenshots/
│   │   ├── desktop.png + mobile.png
│   │   └── sections/<slug>.png  ← recorte por seção
│   └── components/
│       └── <Nome>.spec.md      ← spec auditável por seção
├── src/
│   ├── app/
│   │   ├── globals.css         ← tokens extraídos
│   │   ├── layout.tsx          ← fontes + meta
│   │   └── page.tsx            ← monta todos os componentes
│   ├── components/
│   │   ├── ui/button.tsx
│   │   └── <Nome>.tsx          ← gerados (1 por seção)
│   └── lib/utils.ts
├── public/                     ← assets baixados
└── package.json + tsconfig.json + tailwind.config.ts ...
```

## Pré-requisitos

- **Playwright** instalado (`pip install playwright && python -m playwright install chromium`)
- **DEEPSEEK_API_KEY** no `.env`
- **Node.js 20+ + npm** (opcional — sem ele, gera os arquivos mas pula `npm install`/`build`)

## Limitações conhecidas

- DeepSeek-reasoner é mais lento que Claude — clone completo leva 5-10 min.
- SPAs com renderização puramente client-side podem ficar incompletas.
- Sites com auth/paywall não funcionam (out of scope).
- Não copia backends/APIs — apenas frontend visual.
- QA visual side-by-side roda em iteração futura.

## Ética

Use apenas para:
- Migrar plataformas legadas (WordPress/Webflow → Next.js)
- Recuperar código-fonte perdido de sites próprios
- Aprender reverse-engineering de UIs reais

**NÃO** use para phishing, impersonação, violação de TOS ou apropriação indevida de design.
