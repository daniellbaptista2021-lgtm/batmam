#!/bin/bash
source /etc/rp_environment 2>/dev/null
CLOW_VPS="145.223.30.216"
SSH_KEY="/root/.ssh/runpod_to_clow"
TARGET="${RUNPOD_PUBLIC_IP}:${RUNPOD_TCP_PORT_8000}"
if [ -z "$RUNPOD_PUBLIC_IP" ] || [ -z "$RUNPOD_TCP_PORT_8000" ]; then
    echo "ERROR: RunPod env vars not found"; exit 1
fi
cp /workspace/.ssh/id_ed25519 "$SSH_KEY" 2>/dev/null
chmod 600 "$SSH_KEY"
echo "Updating clow VPS proxy target to: $TARGET"
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -i "$SSH_KEY" root@${CLOW_VPS} \
    "/usr/local/bin/update-vllm-target.sh ${TARGET}"
