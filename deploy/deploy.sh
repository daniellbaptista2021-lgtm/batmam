#!/bin/bash
set -euo pipefail

echo "=== Clow Deploy ==="

cd /root/clow

# Pull latest
git pull origin main

# Update deps
source .venv/bin/activate
pip install -e "." -q

# Run tests
python -m pytest tests/ -v --tb=short || { echo "Tests failed! Aborting."; exit 1; }

# Restart service
sudo systemctl restart clow
sleep 3

# Verify
if curl -sf http://localhost:8001/health > /dev/null; then
    echo "✓ Deploy successful — Clow is healthy"
else
    echo "✗ Deploy failed — checking logs..."
    journalctl -u clow --no-pager -n 20
    exit 1
fi
# Deploy automático ativo
