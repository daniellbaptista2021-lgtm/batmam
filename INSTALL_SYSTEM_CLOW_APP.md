# 📱 Instalar System Clow no iPhone

## URL para Acessar
```
http://SEU-IP-VPS:8001/pwa
```

## Passo a Passo (iPhone)

### 1️⃣ **Abra no Safari**
   - Copie a URL acima
   - Cole na barra de endereços do Safari
   - Pressione "Ir"

### 2️⃣ **Adicione à Tela de Início**
   - Toque no ícone de **Compartilhar** (quadrado com seta)
   - Deslize para esquerda e procure por **"Adicionar à Tela de Início"**
   - Toque em **"Adicionar à Tela de Início"**

### 3️⃣ **Customize o Nome (opcional)**
   - O nome padrão é **"System Clow"**
   - Você pode mudar se quiser
   - Toque **"Adicionar"**

### 4️⃣ **Pronto! 🎉**
   - O app aparecerá na sua tela de início
   - Toque para abrir (sem sair do app)
   - Você pode acessar 24/7 direto da tela inicial

## Características do App

✅ **Ícone roxo do infinito** — visual bonito e moderno  
✅ **PWA Standalone** — abre como app, não como Safari  
✅ **Service Worker** — funciona offline (cache de conteúdo)  
✅ **Conexão 24/7** — sempre ativo na VPS  
✅ **Responsivo** — perfeito para iPhone  
✅ **Status bar roxo** — tema integrado com iOS  

## Se Não Abrir via IP

Se a porta 8001 estiver bloqueada pelo seu ISP, você pode:

1. **Usar um domínio**
   - Compre um domínio (ex: systemclow.com)
   - Aponte para seu IP da VPS (SEU-IP-VPS)
   - Acesse via HTTPS

2. **Usar proxy reverso**
   - Configure Cloudflare com o IP
   - Acesse via HTTPS sem se preocupar com porta

## Manter Sempre Ativo

O servidor está rodando com `nohup`, então:
- ✅ Continua ativo mesmo se sair do SSH
- ✅ Reinicia automaticamente se cair (com supervisor/systemd)
- ✅ Acessa 24 horas por dia

Para parar manualmente:
```bash
pkill -f "uvicorn clow.webapp"
```

Para iniciar novamente:
```bash
cd /root/clow && nohup .venv/bin/uvicorn clow.webapp:app --host 0.0.0.0 --port 8001 > /tmp/uvicorn.log 2>&1 &
```

## Próximos Passos

1. **Teste o app** abrindo no iPhone
2. **Depois** você pode:
   - Comprar um domínio
   - Configurar HTTPS com Let's Encrypt
   - Customizar ainda mais a interface

---

**Versão:** System Clow 1.0  
**Data:** 2026-04-02  
**Status:** Ativo e pronto para usar 🚀
