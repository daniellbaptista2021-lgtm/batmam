# Branding Chatwoot (CLOW)

Arquivos montados via Docker bind mount em /app/public/:
- /opt/chatwoot-zapi/custom.js  -> /app/public/pv-custom.js
- /opt/chatwoot-zapi/custom.css -> /app/public/pv-custom.css

Carregados automaticamente via installation_configs.DASHBOARD_SCRIPTS:
  value: <script src="/pv-custom.js"></script>

## Mudancas de branding aplicadas

- users.name + display_name do admin (id=1): CRM CLOW (era Corretor Daniel Baptista)
- users.avatar_url: upload logo do Clow via PUT /api/v1/profile
- installation_configs.INSTALLATION_NAME: CRM CLOW
- installation_configs.BRAND_NAME: CRM CLOW
- custom.js: injeta custom.css, mascara emails no rodape, troca titulo aba
- custom.css: esconde sidebar-profile email via multiplos selectors

## Pra atualizar

1. Editar /opt/chatwoot-zapi/custom.{js,css} na VPS
2. Backup aqui em docs/chatwoot-branding/
3. Forcar reload do cache Chatwoot (DASHBOARD_SCRIPTS ja cachea; basta
   bump do query string ?v=X no custom.js)
