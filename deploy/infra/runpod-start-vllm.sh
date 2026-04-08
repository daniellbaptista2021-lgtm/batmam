#!/bin/bash
source /etc/rp_environment 2>/dev/null

MODEL_PATH="/workspace/models/Llama-3.1-70B-Instruct-AWQ-INT4"
LOG_FILE="/workspace/vllm_server.log"
API_KEY="clow-vllm-sk-8f3a2e7d9b1c4056"

if [ ! -d "$MODEL_PATH" ]; then
    echo "Downloading model..."
    python3 -c "
from huggingface_hub import snapshot_download
snapshot_download(repo_id=\"hugging-quants/Meta-Llama-3.1-70B-Instruct-AWQ-INT4\", local_dir=\"$MODEL_PATH\")
"
fi

if pgrep -f "vllm.entrypoints.openai.api_server" > /dev/null; then
    echo "vLLM already running"
    /workspace/update_clow_proxy.sh
    exit 0
fi

echo "Starting vLLM with max context..."
nohup python3 -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_PATH" \
    --served-model-name llama-3.1-70b \
    --quantization awq \
    --dtype float16 \
    --host 0.0.0.0 \
    --port 8000 \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.95 \
    --api-key "$API_KEY" \
    > "$LOG_FILE" 2>&1 &

echo "Waiting for vLLM to be ready..."
for i in $(seq 1 90); do
    if curl -s -H "Authorization: Bearer $API_KEY" http://localhost:8000/v1/models > /dev/null 2>&1; then
        echo "vLLM ready! Updating clow proxy..."
        /workspace/update_clow_proxy.sh
        exit 0
    fi
    sleep 5
done
echo "WARNING: vLLM did not start in time"
