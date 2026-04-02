---
name: clow-design-system
description: Sistema de design obrigatorio para toda geracao visual do Clow. Aplicar automaticamente em landing pages, apps, interfaces, dashboards e qualquer HTML/CSS gerado.
---

# Clow Design System — Skill Permanente

Este documento e a fonte unica de verdade para todo design gerado pelo Clow. NUNCA gerar frontend sem seguir estas regras.

## Regra Zero: Evitar AI Slop
O Clow NUNCA gera interfaces genericas.
- NUNCA usar fonts genericas (Inter, Roboto, Open Sans, Arial, Lato, system fonts)
- NUNCA usar gradientes roxos em fundo branco
- NUNCA usar layouts e patterns previsiveis de IA
- NUNCA distribuir cores igualmente — uma dominante com acentos pontuais
- SEMPRE fazer escolhas criativas e distintas para cada contexto
- SEMPRE variar entre temas claros e escuros conforme o projeto
- SEMPRE pensar fora da caixa em tipografia e cor

## Tipografia

### Fontes Aprovadas (Google Fonts):
**Headlines (escolher UMA por projeto):**
- Clash Display
- Cabinet Grotesk
- Bricolage Grotesque
- Playfair Display
- Fraunces
- Space Grotesk

**Body text (escolher UMA por projeto):**
- Satoshi
- IBM Plex Sans
- Source Sans 3
- Crimson Pro (para projetos editoriais)
- DM Sans

**Code/Monospace:**
- JetBrains Mono
- Fira Code
- IBM Plex Mono

### Regras de Tipografia:
- Usar EXTREMOS de peso: 200 vs 800, nao 400 vs 600
- Saltos de tamanho de 3x+: body 14px, heading 42px
- Pairing principle: alto contraste (display + monospace, serif + geometric sans)
- Carregar do Google Fonts via link no head
- Definir font-family em CSS variables
- line-height: 1.5 para body, 1.2 para headings
- letter-spacing: -0.02em para headings grandes

## Paleta de Cores

### Para interfaces do Clow (webapp, admin, chat):
--bg-deepest: #09090F
--bg-base: #0F0F18
--bg-elevated: #161622
--bg-surface: #1C1C2E
--bg-hover: #252540
--border: #2A2A45
--border-focus: #7C5CFC
--primary: #7C5CFC
--primary-glow: rgba(124,92,252,0.15)
--primary-hover: #6B4FE0
--accent-green: #4ADE80
--accent-amber: #FBBF24
--accent-red: #F87171
--accent-cyan: #22D3EE
--text-primary: #F0F0F5
--text-secondary: #A0A0B8
--text-muted: #606078

### Para projetos de clientes:
- NAO usar a paleta do Clow
- Criar paleta unica baseada no contexto do projeto
- Inspiracao: temas de IDE (Dracula, One Dark, Tokyo Night, Nord, Catppuccin)
- Ou esteticas culturais (japonesa minimalista, brutalismo, art deco, solarpunk)
- Sempre definir em CSS variables
- Sempre commitar numa estetica coesa

### Regras de Cor:
- Uma cor dominante forte, 2-3 acentos complementares
- Backgrounds com profundidade: gradients sutis, nao cores solidas
- Usar opacity e rgba para criar camadas
- Cores de status padronizadas: verde=sucesso, amarelo=atencao, vermelho=erro
- Contraste WCAG AA minimo para texto

## Motion e Animacao

### Regras:
- CSS-only para HTML (sem libs JS pesadas)
- Foco em momentos de alto impacto
- Uma orquestracao no page load > micro-interacoes espalhadas
- Usar animation-delay para staggered reveals

### Duracoes:
- Hover: 150-200ms ease
- Toggle/slide: 250ms ease
- Page load reveals: 300-600ms ease-out com stagger de 50-100ms
- Modais: 200ms ease-out (abrir), 150ms ease-in (fechar)

## Backgrounds e Atmosfera

### Regras:
- NUNCA fundo solido simples para paginas inteiras
- Criar profundidade com camadas:
  1. Base color (solid)
  2. Gradient overlay sutil
  3. Pattern opcional (grid de pontos, linhas, noise)
  4. Glow/light effects contextuais

## Layout

### Espacamento:
- Gap entre elementos: 8px, 12px, 16px, 24px, 32px, 48px (escala de 4)
- Padding de containers: 16px mobile, 24px tablet, 32px desktop
- Border-radius: 6px (botoes), 8px (cards pequenos), 12px (cards grandes), 16px (modais)

### Responsivo:
- Mobile first
- Breakpoints: 640px, 768px, 1024px, 1280px
- Touch targets: minimo 44px height
- Sidebar: overlay no mobile com backdrop blur

## Componentes

### Botoes:
- Primary: background var(--primary), text white, hover var(--primary-hover)
- Secondary: background transparent, border 1px var(--border), hover bg var(--bg-hover)
- Ghost: sem background nem border, hover bg var(--bg-hover)
- Todos: border-radius 8px, padding 10px 20px, font-weight 500, transition 200ms

### Inputs:
- Background: var(--bg-surface)
- Border: 1px var(--border)
- Border-radius: 10px
- Focus: border-color var(--primary), box-shadow 0 0 0 3px var(--primary-glow)

### Cards:
- Background: var(--bg-elevated)
- Border: 1px var(--border)
- Border-radius: 12px
- Hover: border-color var(--primary), translateY(-2px), box-shadow com glow
- Transition: 250ms ease

## Regras de Geracao Para Clientes

Quando gerar landing page, site ou app para um CLIENTE:
1. Perguntar: qual o ramo/nicho?
2. Escolher estetica adequada ao nicho (nao usar a paleta do Clow)
3. Escolher font pairing unico para o projeto
4. Gerar com profundidade visual (backgrounds, shadows, layers)
5. Mobile-first e responsivo
6. Incluir micro-interacoes nos pontos de conversao (CTA, formularios)
7. Usar Tailwind CSS via CDN para utility classes
8. Tudo self-contained em um unico HTML file

## Checklist Antes de Entregar

- Fonts carregadas do Google Fonts (nao genericas)
- CSS variables definidas para cores
- Background com profundidade (nao solido)
- Animacoes de entrada nos elementos
- Hover states em todos elementos interativos
- Responsivo (mobile + desktop)
- Contraste adequado para legibilidade
- Nao parece "feito por IA" — tem personalidade
