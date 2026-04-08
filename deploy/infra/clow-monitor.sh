#!/bin/bash
# Clow Production Monitor + Auto-Failover + Telegram Alerts

ENV_FILE="/root/.clow/app/.env"
DEPLOY_ENV="/root/batmam/deploy/.env"
LOG_FILE="/var/log/clow-monitor.log"
FAIL_COUNT=0
MAX_FAILS=3
CURRENT_MODE=""

# Telegram config (set these to enable alerts)
TG_BOT_TOKEN="${CLOW_TG_BOT_TOKEN:-}"
TG_CHAT_ID="${CLOW_TG_CHAT_ID:-}"

# Read keys from .env files
VLLM_API_KEY=$(grep "^OPENAI_API_KEY=" "$ENV_FILE" 2>/dev/null | cut -d= -f2)
ANTHROPIC_KEY=$(grep "^ANTHROPIC_API_KEY=" "$DEPLOY_ENV" 2>/dev/null | cut -d= -f2)

send_alert() {
    local level="$1" msg="$2"
    echo "$(date) [$level] $msg" >> "$LOG_FILE"
    if [ -n "$TG_BOT_TOKEN" ] && [ -n "$TG_CHAT_ID" ]; then
        local emoji="ℹ️"
        [ "$level" = "ALERT" ] && emoji="🚨"
        [ "$level" = "RECOVERY" ] && emoji="✅"
        [ "$level" = "WARN" ] && emoji="⚠️"
        curl -s --max-time 5 "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
            -d chat_id="$TG_CHAT_ID" \
            -d text="${emoji} *CLOW ${level}*: ${msg}" \
            -d parse_mode="Markdown" > /dev/null 2>&1
    fi
}

detect_mode() {
    if grep -q "CLOW_PROVIDER=openai" "$ENV_FILE"; then
        CURRENT_MODE="vllm"
    else
        CURRENT_MODE="anthropic"
    fi
}

switch_to_anthropic() {
    send_alert "ALERT" "vLLM DOWN! Switching to Anthropic fallback."
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
    send_alert "RECOVERY" "vLLM is back online! Switching back from Anthropic."
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

send_alert "START" "Clow Monitor started (mode: auto-detect)"
detect_mode

# Track clow health separately
CLOW_FAIL=0

while true; do
    # Check vLLM
    if check_vllm; then
        FAIL_COUNT=0
        if [ "$CURRENT_MODE" = "anthropic" ]; then
            switch_to_vllm
        fi
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        if [ $FAIL_COUNT -eq 1 ] || [ $((FAIL_COUNT % 10)) -eq 0 ]; then
            send_alert "WARN" "vLLM check failed ($FAIL_COUNT/$MAX_FAILS)"
        fi
        if [ "$CURRENT_MODE" = "vllm" ] && [ $FAIL_COUNT -ge $MAX_FAILS ]; then
            switch_to_anthropic
        fi
    fi

    # Check clow app health
    if check_clow; then
        CLOW_FAIL=0
    else
        CLOW_FAIL=$((CLOW_FAIL + 1))
        if [ $CLOW_FAIL -ge 3 ]; then
            send_alert "ALERT" "Clow app is DOWN! Restarting..."
            systemctl restart clow
            CLOW_FAIL=0
        fi
    fi

    sleep 60
done
