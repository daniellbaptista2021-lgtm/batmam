#!/bin/bash
# Clow Production Monitor + Auto-Failover + WhatsApp Z-API Alerts

ENV_FILE="/root/.clow/app/.env"
DEPLOY_ENV="/root/batmam/deploy/.env"
LOG_FILE="/var/log/clow-monitor.log"
FAIL_COUNT=0
MAX_FAILS=3
CURRENT_MODE=""

# Z-API WhatsApp config
ZAPI_URL="https://api.z-api.io/instances/3EF47A29C3407180CF13C22309410E11/token/3F58BF302142429BA7FAD499/send-text"
ZAPI_CLIENT_TOKEN="F986fce42e250445fb74cc9ec87593732S"
ALERT_PHONE="5521990423520"

# Read keys from .env files
VLLM_API_KEY=$(grep "^OPENAI_API_KEY=" "$ENV_FILE" 2>/dev/null | cut -d= -f2)
ANTHROPIC_KEY=$(grep "^ANTHROPIC_API_KEY=" "$DEPLOY_ENV" 2>/dev/null | cut -d= -f2)

send_alert() {
    local level="$1" msg="$2"
    echo "$(date) [$level] $msg" >> "$LOG_FILE"
    local emoji="ℹ️"
    [ "$level" = "ALERT" ] && emoji="🚨"
    [ "$level" = "RECOVERY" ] && emoji="✅"
    [ "$level" = "WARN" ] && emoji="⚠️"
    curl -s --max-time 10 -X POST "$ZAPI_URL" \
        -H "Content-Type: application/json" \
        -H "Client-Token: $ZAPI_CLIENT_TOKEN" \
        -d "{\"phone\": \"$ALERT_PHONE\", \"message\": \"${emoji} *CLOW ${level}*\n${msg}\"}" > /dev/null 2>&1
}

detect_mode() {
    if grep -q "CLOW_PROVIDER=openai" "$ENV_FILE"; then
        CURRENT_MODE="vllm"
    else
        CURRENT_MODE="anthropic"
    fi
}

switch_to_anthropic() {
    send_alert "ALERT" "vLLM DOWN! Ativando fallback Anthropic. Seus clientes continuam sendo atendidos."
    sed -i "s|^CLOW_PROVIDER=.*|CLOW_PROVIDER=anthropic|" "$ENV_FILE"
    sed -i "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=${ANTHROPIC_KEY}|" "$ENV_FILE"
    if ! grep -q "^ANTHROPIC_API_KEY=" "$ENV_FILE"; then
        echo "ANTHROPIC_API_KEY=${ANTHROPIC_KEY}" >> "$ENV_FILE"
    fi
    sed -i "s|^CLOW_MODEL=.*|CLOW_MODEL=claude-haiku-4-5-20251001|" "$ENV_FILE"
    sed -i "s|^CLOW_MODEL_HEAVY=.*|CLOW_MODEL_HEAVY=claude-sonnet-4-20250514|" "$ENV_FILE"
    systemctl restart clow
    CURRENT_MODE="anthropic"
}

switch_to_vllm() {
    send_alert "RECOVERY" "vLLM voltou! Retornando para Llama 70B."
    sed -i "s|^CLOW_PROVIDER=.*|CLOW_PROVIDER=openai|" "$ENV_FILE"
    sed -i "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=${VLLM_API_KEY}|" "$ENV_FILE"
    sed -i "s|^OPENAI_BASE_URL=.*|OPENAI_BASE_URL=http://127.0.0.1:8088|" "$ENV_FILE"
    sed -i "s|^CLOW_MODEL=.*|CLOW_MODEL=llama-3.1-70b|" "$ENV_FILE"
    sed -i "s|^CLOW_MODEL_HEAVY=.*|CLOW_MODEL_HEAVY=llama-3.1-70b|" "$ENV_FILE"
    systemctl restart clow
    CURRENT_MODE="vllm"
}

check_vllm() {
    RESPONSE=$(curl -s --max-time 8 -H "Authorization: Bearer ${VLLM_API_KEY}" http://127.0.0.1:8088/v1/models 2>/dev/null)
    echo "$RESPONSE" | grep -q "llama-3.1-70b"
}

check_clow() {
    curl -s --max-time 5 http://localhost:8001/health | grep -q "healthy"
}

echo "$(date) [START] Clow Monitor started" >> "$LOG_FILE"
detect_mode
CLOW_FAIL=0

while true; do
    if check_vllm; then
        FAIL_COUNT=0
        if [ "$CURRENT_MODE" = "anthropic" ]; then
            switch_to_vllm
        fi
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        [ $FAIL_COUNT -eq 1 ] && send_alert "WARN" "vLLM check falhou ($FAIL_COUNT/$MAX_FAILS)"
        if [ "$CURRENT_MODE" = "vllm" ] && [ $FAIL_COUNT -ge $MAX_FAILS ]; then
            switch_to_anthropic
        fi
    fi

    if check_clow; then
        CLOW_FAIL=0
    else
        CLOW_FAIL=$((CLOW_FAIL + 1))
        if [ $CLOW_FAIL -ge 3 ]; then
            send_alert "ALERT" "Clow app caiu! Reiniciando..."
            systemctl restart clow
            CLOW_FAIL=0
        fi
    fi

    sleep 60
done
