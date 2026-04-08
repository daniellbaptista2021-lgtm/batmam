#!/bin/bash
LOG=/workspace/watchdog.log
API_KEY="clow-vllm-sk-8f3a2e7d9b1c4056"
while true; do
    if ! curl -s --max-time 5 -H "Authorization: Bearer $API_KEY" http://localhost:8000/v1/models > /dev/null 2>&1; then
        echo "$(date) - vLLM DOWN, restarting..." >> $LOG
        kill -9 $(pgrep -f api_server) 2>/dev/null
        kill -9 $(pgrep -f EngineCore) 2>/dev/null
        sleep 10
        /workspace/start_vllm.sh >> $LOG 2>&1
        sleep 300
    fi
    sleep 30
done
