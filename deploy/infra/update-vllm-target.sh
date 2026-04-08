#!/bin/bash
NEW_TARGET="$1"
if [ -z "$NEW_TARGET" ]; then
    echo "Usage: update-vllm-target.sh IP:PORT"
    exit 1
fi
echo "server ${NEW_TARGET};" > /etc/nginx/vllm_target
nginx -t && nginx -s reload
echo "vLLM target updated to ${NEW_TARGET}"
