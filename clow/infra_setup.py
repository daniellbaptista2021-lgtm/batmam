"""Infra Setup — gera scripts de instalacao personalizados.

O Clow NUNCA acessa a maquina do cliente. Gera um script .sh que o
cliente roda na VPS dele. O script instala Docker, Chatwoot, Nginx, SSL.
No final gera um codigo de conexao que o cliente cola no Clow.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from pathlib import Path

from . import config
from .logging import log_action

_SETUP_DIR = config.CLOW_HOME / "infra_setups"
_SETUP_DIR.mkdir(parents=True, exist_ok=True)

# Chave para encode/decode do connection code (nao e criptografia forte,
# e ofuscacao — o token real e o api_token do Chatwoot que so o cliente tem)
_ENCODE_KEY = (config.ANTHROPIC_API_KEY or "clow-default-key")[:32]


# ══════════════════════════════════════════════════════════════
# SETUP TOKENS
# ══════════════════════════════════════════════════════════════

def generate_setup_token(tenant_id: str, setup_config: dict) -> str:
    """Gera token unico e salva config. Expira em 24h."""
    token = uuid.uuid4().hex
    data = {
        "tenant_id": tenant_id,
        "token": token,
        "config": setup_config,
        "created_at": time.time(),
        "expires_at": time.time() + 86400,
        "used": False,
    }
    path = _SETUP_DIR / f"{token}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log_action("setup_token_created", f"tenant={tenant_id} token={token[:8]}...")
    return token


def get_setup_data(token: str) -> dict | None:
    """Busca dados do setup token. Retorna None se expirado/usado."""
    path = _SETUP_DIR / f"{token}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("expires_at", 0) < time.time():
            return None
        if data.get("used"):
            return None
        return data
    except Exception:
        return None


def mark_token_used(token: str) -> None:
    """Marca token como usado (single use)."""
    path = _SETUP_DIR / f"{token}.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["used"] = True
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# CONNECTION CODE (encode/decode)
# ══════════════════════════════════════════════════════════════

def generate_connection_code(chatwoot_url: str, api_token: str) -> str:
    """Gera codigo de conexao a partir da URL e token."""
    data = f"{chatwoot_url}|{api_token}"
    encoded = base64.urlsafe_b64encode(data.encode()).decode()
    return f"clow_conn_{encoded}"


def decode_connection_code(code: str) -> dict | None:
    """Decodifica codigo de conexao."""
    if not code.startswith("clow_conn_"):
        return None
    try:
        encoded = code[len("clow_conn_"):]
        data = base64.urlsafe_b64decode(encoded).decode()
        parts = data.split("|", 1)
        if len(parts) != 2:
            return None
        return {"chatwoot_url": parts[0], "api_token": parts[1]}
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# TEST CONNECTION
# ══════════════════════════════════════════════════════════════

def test_chatwoot_connection(chatwoot_url: str, api_token: str) -> dict:
    """Testa conexao com o Chatwoot do cliente."""
    from urllib.request import urlopen, Request
    from urllib.error import URLError, HTTPError

    url = f"{chatwoot_url.rstrip('/')}/api/v1/profile"
    try:
        req = Request(url, headers={"api_access_token": api_token})
        resp = urlopen(req, timeout=15)
        data = json.loads(resp.read().decode())
        return {
            "ok": True,
            "chatwoot_url": chatwoot_url,
            "name": data.get("name", ""),
            "email": data.get("email", ""),
        }
    except HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}"}
    except URLError as e:
        return {"ok": False, "error": f"Conexao recusada: {str(e.reason)[:100]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ══════════════════════════════════════════════════════════════
# SAVE/GET INFRA CONFIG PER TENANT
# ══════════════════════════════════════════════════════════════

def save_tenant_infra(tenant_id: str, chatwoot_url: str, api_token: str) -> None:
    """Salva conexao do Chatwoot no tenant."""
    d = config.CLOW_HOME / "tenants" / tenant_id
    d.mkdir(parents=True, exist_ok=True)
    data = {
        "chatwoot_url": chatwoot_url,
        "api_token": api_token,
        "connected_at": time.time(),
        "status": "active",
    }
    (d / "infra.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    log_action("infra_connected", f"tenant={tenant_id} url={chatwoot_url}")


def get_tenant_infra(tenant_id: str) -> dict | None:
    """Retorna config de infra do tenant."""
    path = config.CLOW_HOME / "tenants" / tenant_id / "infra.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_infra_status(tenant_id: str) -> dict:
    """Retorna status da infra do tenant."""
    infra = get_tenant_infra(tenant_id)
    if not infra:
        return {"has_infra": False}

    # Testa conexao
    result = test_chatwoot_connection(infra["chatwoot_url"], infra["api_token"])
    return {
        "has_infra": True,
        "chatwoot_url": infra["chatwoot_url"],
        "chatwoot_status": "online" if result.get("ok") else "offline",
        "connected_at": infra.get("connected_at"),
    }


# ══════════════════════════════════════════════════════════════
# SCRIPT GENERATION
# ══════════════════════════════════════════════════════════════

def generate_vps_script(cfg: dict) -> str:
    """Gera script bash para instalacao em VPS Ubuntu."""
    domain = cfg.get("domain", "")
    subdomain = cfg.get("subdomain", "chat")
    email = cfg.get("email", "admin@clow.com")
    password = cfg.get("password", "changeme123")
    port = cfg.get("port", 3000)
    use_ssl = "true" if domain and not domain.replace(".", "").isdigit() else "false"
    chatwoot_domain = f"{subdomain}.{domain}" if subdomain and domain else domain
    zapi_instance = cfg.get("zapi_instance_id", "")
    zapi_token = cfg.get("zapi_token", "")

    return f'''#!/bin/bash
# ============================================================
# Clow — Instalacao automatica de infraestrutura
# Gerado em: {time.strftime("%d/%m/%Y %H:%M")}
# ============================================================
set -e

GREEN='\\033[0;32m'; RED='\\033[0;31m'; YELLOW='\\033[1;33m'; BLUE='\\033[0;34m'; NC='\\033[0m'

echo ""
echo -e "${{BLUE}}==============================================${{NC}}"
echo -e "${{BLUE}}       CLOW — Setup Automatico               ${{NC}}"
echo -e "${{BLUE}}==============================================${{NC}}"
echo ""

CHATWOOT_DOMAIN="{chatwoot_domain}"
CHATWOOT_EMAIL="{email}"
CHATWOOT_PASSWORD="{password}"
CHATWOOT_PORT="{port}"
USE_SSL="{use_ssl}"
INSTALL_DIR="/opt/clow-infra"

# ── Etapa 1: Verificacoes ──
echo -e "${{YELLOW}}[1/6] Verificando sistema...${{NC}}"
if [ "$EUID" -ne 0 ]; then echo -e "${{RED}}Execute como root: sudo bash${{NC}}"; exit 1; fi
TOTAL_RAM=$(free -m | awk '/^Mem/{{print $2}}')
if [ "$TOTAL_RAM" -lt 1800 ]; then echo -e "${{RED}}Minimo 2GB RAM. Detectado: ${{TOTAL_RAM}}MB${{NC}}"; exit 1; fi
echo -e "${{GREEN}}  OK - Sistema verificado (${{TOTAL_RAM}}MB RAM)${{NC}}"

# ── Etapa 2: Docker ──
echo -e "${{YELLOW}}[2/6] Instalando Docker...${{NC}}"
if command -v docker &>/dev/null; then
    echo -e "${{GREEN}}  OK - Docker ja instalado${{NC}}"
else
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker && systemctl start docker
    echo -e "${{GREEN}}  OK - Docker instalado${{NC}}"
fi

# ── Etapa 3: Chatwoot ──
echo -e "${{YELLOW}}[3/6] Configurando Chatwoot...${{NC}}"
mkdir -p $INSTALL_DIR && cd $INSTALL_DIR
SECRET_KEY=$(openssl rand -hex 64)
DB_PASS="cw_$(openssl rand -hex 8)"

cat > docker-compose.yml << 'DEOF'
services:
  chatwoot-rails:
    image: chatwoot/chatwoot:latest
    container_name: clow-chatwoot
    restart: always
    depends_on: [chatwoot-postgres, chatwoot-redis]
    environment:
      RAILS_ENV: production
      NODE_ENV: production
      SECRET_KEY_BASE: __SECRET__
      FRONTEND_URL: __FRONTEND__
      POSTGRES_HOST: chatwoot-postgres
      POSTGRES_USERNAME: chatwoot
      POSTGRES_PASSWORD: __DBPASS__
      POSTGRES_DATABASE: chatwoot_production
      REDIS_URL: redis://chatwoot-redis:6379
      DEFAULT_LOCALE: pt_BR
      ENABLE_ACCOUNT_SIGNUP: "false"
      RAILS_LOG_TO_STDOUT: "true"
    ports: ["__PORT__:3000"]
    volumes: [chatwoot-storage:/app/storage]
    command: sh -c "rm -f /app/tmp/pids/server.pid && bundle exec rails s -p 3000 -b 0.0.0.0"
  chatwoot-sidekiq:
    image: chatwoot/chatwoot:latest
    container_name: clow-chatwoot-worker
    restart: always
    depends_on: [chatwoot-rails]
    environment:
      RAILS_ENV: production
      SECRET_KEY_BASE: __SECRET__
      POSTGRES_HOST: chatwoot-postgres
      POSTGRES_USERNAME: chatwoot
      POSTGRES_PASSWORD: __DBPASS__
      POSTGRES_DATABASE: chatwoot_production
      REDIS_URL: redis://chatwoot-redis:6379
    volumes: [chatwoot-storage:/app/storage]
    command: bundle exec sidekiq -C config/sidekiq.yml
  chatwoot-postgres:
    image: postgres:15
    container_name: clow-chatwoot-db
    restart: always
    environment:
      POSTGRES_USER: chatwoot
      POSTGRES_PASSWORD: __DBPASS__
      POSTGRES_DB: chatwoot_production
    volumes: [chatwoot-pgdata:/var/lib/postgresql/data]
  chatwoot-redis:
    image: redis:7-alpine
    container_name: clow-chatwoot-redis
    restart: always
    volumes: [chatwoot-redis:/data]
volumes:
  chatwoot-storage:
  chatwoot-pgdata:
  chatwoot-redis:
DEOF

if [ "$USE_SSL" = "true" ]; then
    FRONTEND="https://$CHATWOOT_DOMAIN"
else
    FRONTEND="http://$(hostname -I | awk '{{print $1}}'):$CHATWOOT_PORT"
fi
sed -i "s|__SECRET__|$SECRET_KEY|g" docker-compose.yml
sed -i "s|__DBPASS__|$DB_PASS|g" docker-compose.yml
sed -i "s|__FRONTEND__|$FRONTEND|g" docker-compose.yml
sed -i "s|__PORT__|$CHATWOOT_PORT|g" docker-compose.yml
echo -e "${{GREEN}}  OK - docker-compose.yml criado${{NC}}"

# ── Etapa 4: Nginx + SSL ──
echo -e "${{YELLOW}}[4/6] Configurando acesso...${{NC}}"
if [ "$USE_SSL" = "true" ]; then
    apt-get install -y nginx certbot python3-certbot-nginx > /dev/null 2>&1 || true
    cat > /etc/nginx/sites-available/chatwoot << NEOF
server {{
    server_name $CHATWOOT_DOMAIN;
    location / {{
        proxy_pass http://127.0.0.1:$CHATWOOT_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \\$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \\$host;
        proxy_set_header X-Real-IP \\$remote_addr;
        proxy_set_header X-Forwarded-For \\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\$scheme;
    }}
}}
NEOF
    ln -sf /etc/nginx/sites-available/chatwoot /etc/nginx/sites-enabled/
    nginx -t && systemctl restart nginx
    certbot --nginx -d $CHATWOOT_DOMAIN --non-interactive --agree-tos -m $CHATWOOT_EMAIL 2>/dev/null || true
    echo -e "${{GREEN}}  OK - Nginx + SSL${{NC}}"
else
    echo -e "${{GREEN}}  OK - Acessivel via IP:$CHATWOOT_PORT${{NC}}"
fi

# ── Etapa 5: Iniciar ──
echo -e "${{YELLOW}}[5/6] Iniciando Chatwoot (2-5 min)...${{NC}}"
cd $INSTALL_DIR
docker compose pull --quiet 2>/dev/null || docker-compose pull --quiet
docker compose up -d 2>/dev/null || docker-compose up -d

echo -n "  Aguardando"
for i in $(seq 1 90); do
    if curl -sf http://127.0.0.1:$CHATWOOT_PORT > /dev/null 2>&1; then break; fi
    echo -n "."; sleep 3
done
echo ""

# Preparar DB
docker exec clow-chatwoot bundle exec rails db:chatwoot_prepare 2>/dev/null || true
sleep 5

# Criar admin
API_TOKEN=$(docker exec clow-chatwoot sh -c "bundle exec rails runner \\"
  a=Account.find_or_create_by!(name:'Principal') {{ |x| x.locale='pt_BR' }};
  u=User.find_or_create_by!(email:'$CHATWOOT_EMAIL') {{ |x|
    x.name='Admin'; x.password='$CHATWOOT_PASSWORD';
    x.confirmed_at=Time.now; x.type='SuperAdmin'
  }};
  AccountUser.find_or_create_by!(account:a,user:u) {{ |x| x.role=:administrator }};
  t=u.access_token || u.create_access_token;
  puts t.token
\\"" 2>/dev/null | tail -1)

echo -e "${{GREEN}}  OK - Chatwoot rodando${{NC}}"

# ── Etapa 6: Codigo de conexao ──
echo -e "${{YELLOW}}[6/6] Gerando codigo de conexao...${{NC}}"
CONN_DATA="${{FRONTEND}}|${{API_TOKEN}}"
CONN_CODE="clow_conn_$(echo -n "$CONN_DATA" | base64 -w 0 | tr '+/' '-_')"

cat > $INSTALL_DIR/clow-info.txt << IEOF
# Clow Infra — $(date)
# URL: $FRONTEND
# Email: $CHATWOOT_EMAIL
# Token: $API_TOKEN
# Conexao: $CONN_CODE
# Comandos: cd $INSTALL_DIR && docker compose [restart|logs -f|stop]
IEOF

echo ""
echo -e "${{GREEN}}=============================================${{NC}}"
echo -e "${{GREEN}}   INSTALACAO CONCLUIDA COM SUCESSO!         ${{NC}}"
echo -e "${{GREEN}}=============================================${{NC}}"
echo ""
echo -e "  Chatwoot: ${{BLUE}}$FRONTEND${{NC}}"
echo -e "  Email:    $CHATWOOT_EMAIL"
echo ""
echo -e "${{YELLOW}}  CODIGO DE CONEXAO (cole no Clow):${{NC}}"
echo ""
echo -e "  ${{GREEN}}$CONN_CODE${{NC}}"
echo ""
echo -e "  1. Copie o codigo acima"
echo -e "  2. Cole no Clow > WhatsApp Trigger > Conectar infraestrutura"
echo -e "  3. Clique em Testar e Conectar"
echo ""
echo -e "  Info salva em: $INSTALL_DIR/clow-info.txt"
echo ""
'''


def generate_local_script(cfg: dict) -> str:
    """Gera docker-compose.yml para instalacao local."""
    email = cfg.get("email", "admin@clow.com")
    password = cfg.get("password", "changeme123")

    return f'''#!/bin/bash
# Clow — Instalacao local (Docker Desktop)
# Gerado em: {time.strftime("%d/%m/%Y %H:%M")}
set -e
echo "=== Clow — Setup Local ==="
echo "Certifique-se de que o Docker Desktop esta rodando."
echo ""

mkdir -p ~/clow-infra && cd ~/clow-infra
SECRET_KEY=$(openssl rand -hex 64 2>/dev/null || python3 -c "import secrets;print(secrets.token_hex(64))")
DB_PASS="cw_local_$(date +%s | md5sum | head -c 8)"

cat > docker-compose.yml << 'DEOF'
services:
  chatwoot:
    image: chatwoot/chatwoot:latest
    container_name: clow-chatwoot
    restart: unless-stopped
    depends_on: [postgres, redis]
    environment:
      RAILS_ENV: production
      SECRET_KEY_BASE: __SECRET__
      FRONTEND_URL: http://localhost:3000
      POSTGRES_HOST: postgres
      POSTGRES_USERNAME: chatwoot
      POSTGRES_PASSWORD: __DBPASS__
      POSTGRES_DATABASE: chatwoot
      REDIS_URL: redis://redis:6379
      DEFAULT_LOCALE: pt_BR
      ENABLE_ACCOUNT_SIGNUP: "false"
    ports: ["3000:3000"]
    volumes: [storage:/app/storage]
    command: sh -c "rm -f /app/tmp/pids/server.pid && bundle exec rails s -p 3000 -b 0.0.0.0"
  sidekiq:
    image: chatwoot/chatwoot:latest
    depends_on: [chatwoot]
    environment:
      RAILS_ENV: production
      SECRET_KEY_BASE: __SECRET__
      POSTGRES_HOST: postgres
      POSTGRES_USERNAME: chatwoot
      POSTGRES_PASSWORD: __DBPASS__
      POSTGRES_DATABASE: chatwoot
      REDIS_URL: redis://redis:6379
    volumes: [storage:/app/storage]
    command: bundle exec sidekiq -C config/sidekiq.yml
  postgres:
    image: postgres:15
    environment: {{ POSTGRES_USER: chatwoot, POSTGRES_PASSWORD: __DBPASS__, POSTGRES_DB: chatwoot }}
    volumes: [pgdata:/var/lib/postgresql/data]
  redis:
    image: redis:7-alpine
    volumes: [redis:/data]
volumes: {{ storage: , pgdata: , redis:  }}
DEOF

sed -i "s|__SECRET__|$SECRET_KEY|g" docker-compose.yml 2>/dev/null || sed -i '' "s|__SECRET__|$SECRET_KEY|g" docker-compose.yml
sed -i "s|__DBPASS__|$DB_PASS|g" docker-compose.yml 2>/dev/null || sed -i '' "s|__DBPASS__|$DB_PASS|g" docker-compose.yml

echo "Iniciando containers..."
docker compose up -d 2>/dev/null || docker-compose up -d
echo "Aguardando Chatwoot iniciar (2-5 min)..."
for i in $(seq 1 90); do curl -sf http://localhost:3000 >/dev/null 2>&1 && break; sleep 3; done

docker exec clow-chatwoot bundle exec rails db:chatwoot_prepare 2>/dev/null || true
sleep 5

API_TOKEN=$(docker exec clow-chatwoot sh -c "bundle exec rails runner \\"
  a=Account.find_or_create_by!(name:'Principal');
  u=User.find_or_create_by!(email:'{email}'){{|x| x.name='Admin';x.password='{password}';x.confirmed_at=Time.now;x.type='SuperAdmin'}};
  AccountUser.find_or_create_by!(account:a,user:u){{|x| x.role=:administrator}};
  t=u.access_token||u.create_access_token; puts t.token
\\"" 2>/dev/null | tail -1)

CONN_CODE="clow_conn_$(echo -n "http://localhost:3000|$API_TOKEN" | base64 -w 0 2>/dev/null || echo -n "http://localhost:3000|$API_TOKEN" | base64 | tr -d '\\n' | tr '+/' '-_')"

echo ""
echo "=== INSTALACAO CONCLUIDA ==="
echo "Chatwoot: http://localhost:3000"
echo "Email: {email}"
echo ""
echo "CODIGO DE CONEXAO:"
echo "$CONN_CODE"
echo ""
echo "Cole no Clow para conectar."
'''
