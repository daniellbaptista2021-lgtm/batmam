#!/usr/bin/env python3
"""
Script para gerar relatório CSV de etiquetas e conversas atribuídas do Chatwoot
Sem dependência de pandas - gera CSV manualmente
"""

import requests
import csv
import json
from datetime import datetime, timedelta
import sys
import os

# Configurações — credenciais lidas de env vars (NUNCA commitar tokens)
_CW_BASE = os.getenv("CHATWOOT_URL", "https://ads.pvcorretor01.com.br").rstrip("/")
_CW_ACCOUNT_ID = os.getenv("CHATWOOT_ADMIN_ACCOUNT_ID", "1")
CHATWOOT_URL = f"{_CW_BASE}/api/v1/accounts/{_CW_ACCOUNT_ID}"
TOKEN = os.getenv("CHATWOOT_ADMIN_TOKEN", "") or os.getenv("CHATWOOT_API_TOKEN", "")
if not TOKEN:
    print("ERRO: defina CHATWOOT_ADMIN_TOKEN no ambiente antes de rodar este script.")
    sys.exit(1)
HEADERS = {"api_access_token": TOKEN}

def fetch_all_conversations():
    """Busca todas as conversas do mês atual"""
    print("Conectando ao Chatwoot...")
    
    # Buscar agentes
    print("Buscando agentes...")
    try:
        agents_r = requests.get(f"{CHATWOOT_URL}/agents", headers=HEADERS, timeout=15)
        agents = agents_r.json() if agents_r.status_code == 200 else []
    except:
        agents = []
    
    agent_map = {}
    for agent in agents:
        agent_map[agent["id"]] = agent.get("name", f"Agente {agent['id']}")
    
    # Data de início (1º do mês atual)
    hoje = datetime.now()
    data_inicio = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    print("Buscando conversas...")
    all_conversations = []
    page = 1
    max_pages = 30  # Limitar páginas
    
    while page <= max_pages:
        sys.stdout.write(f"\rPágina {page}/{max_pages}...")
        sys.stdout.flush()
        
        try:
            params = {"page": page, "per_page": 100}
            r = requests.get(f"{CHATWOOT_URL}/conversations", headers=HEADERS, params=params, timeout=20)
            
            if r.status_code != 200:
                print(f"\nErro HTTP {r.status_code}")
                break
            
            data = r.json()
            payload = data.get("data", {}).get("payload", [])
            if not payload:
                break
            
            for conv in payload:
                # Filtrar por data
                created_at_str = conv.get("created_at")
                if created_at_str:
                    try:
                        # Converter ISO string para datetime
                        created_at_str = created_at_str.replace('Z', '+00:00')
                        created_at = datetime.fromisoformat(created_at_str)
                        if created_at >= data_inicio:
                            all_conversations.append(conv)
                    except Exception as e:
                        # Se falhar, inclui de qualquer forma
                        all_conversations.append(conv)
                else:
                    # Se não tem data, inclui
                    all_conversations.append(conv)
            
            page += 1
            
        except Exception as e:
            print(f"\nErro na página {page}: {e}")
            break
    
    print(f"\nEncontradas {len(all_conversations)} conversas desde 1º do mês")
    return all_conversations, agent_map

def generate_csv_report(conversations, agent_map):
    """Gera arquivo CSV com os dados"""
    if not conversations:
        print("Nenhuma conversa encontrada para gerar relatório.")
        return None
    
    # Nome do arquivo com timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = f"/root/clow/static/files/chatwoot_relatorio_{timestamp}.csv"
    
    # Campos do CSV
    fieldnames = [
        "ID", "Data_Criacao", "Status", "Atribuido_ID", "Atribuido_Nome",
        "Contato", "Telefone", "Inbox", "Etiquetas"
    ]
    
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for conv in conversations:
            conv_id = conv.get("id", "")
            
            # Data
            created_at = conv.get("created_at", "")
            
            # Status
            status = conv.get("status", "unknown")
            
            # Atribuído
            assignee = conv.get("meta", {}).get("assignee", {})
            assignee_id = assignee.get("id") if assignee else ""
            assignee_name = agent_map.get(assignee_id, "Não atribuído") if assignee_id else "Não atribuído"
            
            # Contato
            contact = conv.get("meta", {}).get("sender", {})
            contact_name = contact.get("name", "")
            contact_phone = contact.get("phone_number", "")
            
            # Inbox
            inbox = conv.get("inbox", {})
            inbox_name = inbox.get("name", "")
            
            # Etiquetas
            labels_list = conv.get("labels", [])
            etiquetas_str = ", ".join(labels_list) if labels_list else "Sem etiqueta"
            
            # Escrever linha
            writer.writerow({
                "ID": conv_id,
                "Data_Criacao": created_at,
                "Status": status,
                "Atribuido_ID": assignee_id,
                "Atribuido_Nome": assignee_name,
                "Contato": contact_name,
                "Telefone": contact_phone,
                "Inbox": inbox_name,
                "Etiquetas": etiquetas_str
            })
    
    print(f"CSV gerado: {csv_file}")
    
    # Gerar também um resumo estatístico
    generate_summary(csv_file, conversations, agent_map)
    
    return csv_file

def generate_summary(csv_file, conversations, agent_map):
    """Gera um arquivo de resumo estatístico"""
    summary_file = csv_file.replace('.csv', '_resumo.txt')
    
    # Contagens básicas
    total = len(conversations)
    open_count = sum(1 for c in conversations if c.get("status") == "open")
    resolved_count = sum(1 for c in conversations if c.get("status") == "resolved")
    
    # Contagem por agente
    agent_counts = {}
    for conv in conversations:
        assignee = conv.get("meta", {}).get("assignee", {})
        assignee_id = assignee.get("id") if assignee else None
        if assignee_id:
            agent_name = agent_map.get(assignee_id, f"Agente {assignee_id}")
            agent_counts[agent_name] = agent_counts.get(agent_name, 0) + 1
    
    # Contagem por etiqueta
    label_counts = {}
    for conv in conversations:
        labels = conv.get("labels", [])
        for label in labels:
            label_counts[label] = label_counts.get(label, 0) + 1
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write("RESUMO CHATWOOT - MÊS ATUAL\n")
        f.write("=" * 60 + "\n\n")
        
        f.write(f"Período: 1º do mês até {datetime.now().strftime('%d/%m/%Y')}\n")
        f.write(f"Total de conversas: {total}\n")
        f.write(f"Conversas abertas: {open_count}\n")
        f.write(f"Conversas resolvidas: {resolved_count}\n\n")
        
        f.write("-" * 60 + "\n")
        f.write("DISTRIBUIÇÃO POR AGENTE\n")
        f.write("-" * 60 + "\n")
        for agent, count in sorted(agent_counts.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / total * 100) if total > 0 else 0
            f.write(f"{agent}: {count} ({percentage:.1f}%)\n")
        
        f.write("\n" + "-" * 60 + "\n")
        f.write("ETIQUETAS MAIS UTILIZADAS\n")
        f.write("-" * 60 + "\n")
        sorted_labels = sorted(label_counts.items(), key=lambda x: x[1], reverse=True)[:20]  # Top 20
        for label, count in sorted_labels:
            percentage = (count / total * 100) if total > 0 else 0
            f.write(f"{label}: {count} ({percentage:.1f}%)\n")
        
        f.write("\n" + "=" * 60 + "\n")
        f.write(f"Arquivo CSV principal: {csv_file}\n")
        f.write("=" * 60 + "\n")
    
    print(f"Resumo gerado: {summary_file}")

def main():
    """Função principal"""
    try:
        # Buscar dados
        conversations, agent_map = fetch_all_conversations()
        
        if not conversations:
            print("Nenhuma conversa encontrada no período.")
            return
        
        # Gerar CSV
        csv_file = generate_csv_report(conversations, agent_map)
        
        if csv_file:
            # Criar link simbólico com nome fixo para acesso fácil
            fixed_link = "/root/clow/static/files/chatwoot_etiquetas_atribuidas.csv"
            if os.path.exists(fixed_link):
                os.remove(fixed_link)
            os.symlink(csv_file, fixed_link)
            
            print("\n" + "=" * 60)
            print("RELATÓRIO GERADO COM SUCESSO!")
            print("=" * 60)
            print(f"Arquivo CSV: https://clow.pvcorretor01.com.br/static/files/chatwoot_etiquetas_atribuidas.csv")
            print(f"Arquivo original: {os.path.basename(csv_file)}")
            
            # Mostrar estatísticas rápidas
            open_count = sum(1 for c in conversations if c.get("status") == "open")
            resolved_count = sum(1 for c in conversations if c.get("status") == "resolved")
            print(f"\nEstatísticas:")
            print(f"  • Total: {len(conversations)} conversas")
            print(f"  • Abertas: {open_count}")
            print(f"  • Resolvidas: {resolved_count}")
            print(f"  • Agentes ativos: {len(set([c.get('meta', {}).get('assignee', {}).get('id') for c in conversations if c.get('meta', {}).get('assignee', {}).get('id')]))}")
            
    except Exception as e:
        print(f"Erro ao gerar relatório: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()