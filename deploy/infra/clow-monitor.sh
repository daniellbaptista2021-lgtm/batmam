#!/bin/bash
# Clow vLLM Monitor + Auto-Fallback to Anthropic
# Runs as systemd service, checks vLLM every 60s

ENV_FILE="/root/.clow/app/.env"
DEPLOY_ENV="/root/batmam/deploy/.env"
LOG_FILE="/var/log/clow-monitor.log"
FAIL_COUNT=0
MAX_FAILS=3
CURRENT_MODE=""

# Read keys from deploy .env (fallback config)
VLLM_API_KEY=$(grep "^OPENAI_API_KEY=" "$ENV_FILE" 2>/dev/null | cut -d= -f2)
ANTHROPIC_KEY=$(grep "^ANTHROPIC_API_KEY=" "$DEPLOY_ENV" 2>/dev/null | cut -d= -f2)

detect_mode() {
    if grep -q "CLOW_PROVIDER=openai" "$ENV_FILE"; then
        CURRENT_MODE="vllm"
    else
        CURRENT_MODE="anthropic"
    fi
}

switch_to_anthropic() {
    echo "$(date) [ALERT] Switching to Anthropic fallback!" >> "$LOG_FILE"
    sed -i "s|^CLOW_PROVIDER=.*|CLOW_PROVIDER=anthropic|" "$ENV_FILE"
    sed -i "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=${ANTHROPIC_KEY}|" "$ENV_FILE"
    if ! grep -q "^ANTHROPIC_API_KEY=" "$ENV_FILE"; then
        echo "ANTHROPIC_API_KEY=${ANTHROPIC_KEY}" >> "$ENV_FILE"
    fi
    sed -i "s|^CLOW_MODEL=.*|CLOW_MODEL=claude-haiku-4-5-20251001|" "$ENV_FILE"
    sed -i "s|^CLOW_MODEL_HEAVY=.*|CLOW_MODEL_HEAVY=claude-sonnet-4-20250514|" "$ENV_FILE"
    systemctl restart clow
    CURRENT_MODE="anthropic"
    echo "$(date) [INFO] Clow switched to Anthropic. Service restarted." >> "$LOG_FILE"
}

switch_to_vllm() {
    echo "$(date) [RECOVERY] vLLM is back! Switching back." >> "$LOG_FILE"
    sed -i "s|^CLOW_PROVIDER=.*|CLOW_PROVIDER=openai|" "$ENV_FILE"
    sed -i "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=${VLLM_API_KEY}|" "$ENV_FILE"
    sed -i "s|^OPENAI_BASE_URL=.*|OPENAI_BASE_URL=http://127.0.0.1:8088|" "$ENV_FILE"
    sed -i "s|^CLOW_MODEL=.*|CLOW_MODEL=llama-3.1-70b|" "$ENV_FILE"
    sed -i "s|^CLOW_MODEL_HEAVY=.*|CLOW_MODEL_HEAVY=llama-3.1-70b|" "$ENV_FILE"
    systemctl restart clow
    CURRENT_MODE="vllm"
    echo "$(date) [INFO] Clow switched back to vLLM. Service restarted." >> "$LOG_FILE"
}

check_vllm() {
    RESPONSE=$(curl -s --max-time 8 -H "Authorization: Bearer ${VLLM_API_KEY}" http://127.0.0.1:8088/v1/models 2>/dev/null)
    if echo "$RESPONSE" | grep -q "llama-3.1-70b"; then
        return 0
    fi
    return 1
}

echo "$(date) [START] Clow Monitor started." >> "$LOG_FILE"
detect_mode

while true; do
    if check_vllm; then
        FAIL_COUNT=0
        if [ "$CURRENT_MODE" = "anthropic" ]; then
            switch_to_vllm
        fi
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        echo "$(date) [WARN] vLLM check failed ($FAIL_COUNT/$MAX_FAILS)" >> "$LOG_FILE"
        if [ "$CURRENT_MODE" = "vllm" ] && [ $FAIL_COUNT -ge $MAX_FAILS ]; then
            switch_to_anthropic
        fi
    fi
    sleep 60
done
