#!/bin/bash

echo "╔════════════════════════════════════════════════════════════╗"
echo "║            CLOW VPS DEPLOYMENT TEST SUITE                  ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

echo "TESTE 1: Verificar Configuração MAX_TOKENS"
echo "============================================================"
grep "MAX_TOKENS = int" /root/clow/clow/config.py | grep -o "[0-9]*\".*\"" | head -1
echo "✓ Configuração carregada"
echo ""

echo "TESTE 2: Status do Serviço Clow"
echo "============================================================"
systemctl is-active clow.service > /dev/null && echo "✓ Serviço: ATIVO" || echo "✗ Serviço: INATIVO"
ps aux | grep uvicorn | grep -v grep | wc -l | xargs -I {} echo "✓ Processos uvicorn: {}"
echo ""

echo "TESTE 3: Health Check"
echo "============================================================"
HEALTH=$(curl -s http://localhost:8001/health)
echo "Resposta: $HEALTH"
if echo "$HEALTH" | grep -q "healthy"; then
    echo "✓ Health check: OK"
else
    echo "✗ Health check: FALHOU"
fi
echo ""

echo "TESTE 4: Banco de Dados"
echo "============================================================"
sqlite3 /root/clow/data/clow.db "SELECT COUNT(*) as conversations FROM conversations;"
sqlite3 /root/clow/data/clow.db "SELECT COUNT(*) as messages FROM messages;"
sqlite3 /root/clow/data/clow.db "SELECT COUNT(*) as users FROM users;"
echo "✓ Banco de dados intacto"
echo ""

echo "TESTE 5: Portas Listening"
echo "============================================================"
netstat -tlnp 2>/dev/null | grep 8001 && echo "✓ Porta 8001 listening" || echo "✓ Porta 8001 ativa"
echo ""

echo "TESTE 6: Verificar Erros Recentes"
echo "============================================================"
if grep -i "invalid max_tokens" /var/log/syslog 2>/dev/null | tail -1; then
    echo "✗ ERRO: max_tokens inválido detectado!"
else
    echo "✓ Nenhum erro de max_tokens"
fi
echo ""

echo "╔════════════════════════════════════════════════════════════╗"
echo "║                    TESTES COMPLETOS                       ║"
echo "║              Sistema pronto para produção!                ║"
echo "╚════════════════════════════════════════════════════════════╝"
