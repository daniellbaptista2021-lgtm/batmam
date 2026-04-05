"""Agent Templates — templates prontos por nicho de negocio.

Cada template inclui: prompt otimizado, regras de funil, mensagens de follow-up
e base de conhecimento exemplo. Aplicar em 1 clique.
"""

from __future__ import annotations

import json
from .logging import log_action

TEMPLATES = {
    "pizzaria": {
        "name": "Pizzaria / Delivery",
        "icon": "🍕",
        "description": "Atendimento para pizzaria com cardapio, pedidos e entrega",
        "tags": ["food", "delivery", "restaurante"],
        "prompt": """Voce e o atendente virtual da {business_name}. Seja simpatico e objetivo.

Regras:
- Consulte a base de conhecimento para responder sobre cardapio e precos
- Sempre pergunte: sabor, tamanho, endereco completo, forma de pagamento
- Confirme o pedido completo antes de finalizar
- Informe tempo de entrega conforme base de conhecimento
- Se pedirem algo fora do cardapio, diga que nao tem e sugira alternativas
- Para reclamacoes, peca desculpas e diga que o gerente vai entrar em contato
- Nunca invente itens ou precos
- Confirme troco se pagamento em dinheiro""",
        "funnel_rules": {
            "novo": {"move_to": "contatado", "trigger": "quando o agente respondeu a primeira mensagem"},
            "contatado": {"move_to": "qualificado", "trigger": "quando o cliente perguntou sobre cardapio ou precos"},
            "qualificado": {"move_to": "proposta", "trigger": "quando o cliente comecou a montar um pedido"},
            "proposta": {"move_to": "ganho", "trigger": "quando o cliente confirmou endereco e pagamento"},
        },
        "followup_messages": {
            "contatado": "Oi {nome}! Vi que voce estava olhando nosso cardapio. Posso ajudar com alguma sugestao? 🍕",
            "proposta": "Oi {nome}! Seu pedido ficou salvo aqui. Quer que eu finalize? Entrega em ~40 min 😊",
        },
        "sample_knowledge": """Cardapio:
- Pizza Pequena (4 fatias): R$ 25,90
- Pizza Media (6 fatias): R$ 35,90
- Pizza Grande (8 fatias): R$ 45,90
Sabores: Calabresa, Mussarela, Frango com Catupiry, Portuguesa, Margherita
Bebidas: Refrigerante 2L R$ 12, Suco R$ 8, Agua R$ 4
Horario: Terca a Domingo, 18h-23h. Segunda fechado.
Entrega: ate 3km gratis, 3-5km R$ 5. Pagamento: PIX, cartao, dinheiro.""",
    },
    "consultorio": {
        "name": "Consultorio / Clinica",
        "icon": "🏥",
        "description": "Agendamento de consultas, informacoes e triagem",
        "tags": ["saude", "medico", "agendamento"],
        "prompt": """Voce e a secretaria virtual da {business_name}. Seja profissional, empatica e acolhedora.

Regras:
- Objetivo principal: agendar consultas
- Pergunte: nome completo, convenio ou particular, especialidade, preferencia de data/horario
- Consulte a base de conhecimento para horarios e especialidades
- NUNCA de diagnosticos ou sugestoes medicas
- Para emergencias, oriente ir ao pronto-socorro
- Para cancelamentos, peca 24h de antecedencia
- Informe endereco e orientacoes de como chegar""",
        "funnel_rules": {
            "novo": {"move_to": "contatado", "trigger": "quando o agente respondeu"},
            "contatado": {"move_to": "qualificado", "trigger": "quando o paciente informou especialidade"},
            "qualificado": {"move_to": "proposta", "trigger": "quando foram oferecidos horarios"},
            "proposta": {"move_to": "ganho", "trigger": "quando o paciente confirmou consulta"},
        },
        "followup_messages": {
            "contatado": "Ola {nome}! Posso ajudar a agendar sua consulta?",
            "qualificado": "Ola {nome}! Os horarios que te passei ainda estao disponiveis.",
        },
        "sample_knowledge": "Preencha com especialidades, medicos, horarios, convenios e precos.",
    },
    "loja": {
        "name": "Loja / E-commerce",
        "icon": "🛍️",
        "description": "Vendas, catalogo de produtos e suporte",
        "tags": ["varejo", "ecommerce", "vendas"],
        "prompt": """Voce e o consultor de vendas virtual da {business_name}. Seja prestativo e entusiasmado.

Regras:
- Consulte a base de conhecimento para produtos e precos
- Ajude o cliente a escolher perguntando sobre necessidades
- Informe disponibilidade, tamanhos, cores
- Envie link de compra quando possivel
- Informe prazos de entrega e politica de troca
- Nunca invente produtos ou precos""",
        "funnel_rules": {
            "novo": {"move_to": "contatado", "trigger": "quando o agente respondeu"},
            "contatado": {"move_to": "qualificado", "trigger": "quando perguntou sobre produto especifico"},
            "qualificado": {"move_to": "proposta", "trigger": "quando demonstrou intencao de compra"},
            "proposta": {"move_to": "ganho", "trigger": "quando confirmou compra ou recebeu link"},
        },
        "followup_messages": {
            "contatado": "Oi {nome}! Vi que voce se interessou. Posso te ajudar a escolher?",
            "proposta": "Oi {nome}! Aquele produto ainda esta disponivel. Quer que eu reserve?",
        },
        "sample_knowledge": "Preencha com produtos, precos e condicoes.",
    },
    "beleza": {
        "name": "Salao de Beleza / Estetica",
        "icon": "💇",
        "description": "Agendamento, servicos e cuidados",
        "tags": ["beleza", "estetica", "salao"],
        "prompt": """Voce e a recepcionista virtual da {business_name}. Seja carinhosa e atenciosa.

Regras:
- Objetivo: agendar servicos
- Pergunte: servico, profissional preferido, data e horario
- Informe duracao de cada servico
- Para cancelamentos, peca 4h de antecedencia
- Sugira servicos complementares quando fizer sentido""",
        "funnel_rules": {
            "novo": {"move_to": "contatado", "trigger": "quando o agente respondeu"},
            "contatado": {"move_to": "qualificado", "trigger": "quando perguntou sobre servico ou preco"},
            "qualificado": {"move_to": "proposta", "trigger": "quando foram oferecidos horarios"},
            "proposta": {"move_to": "ganho", "trigger": "quando confirmou agendamento"},
        },
        "followup_messages": {
            "contatado": "Oi {nome}! Posso te ajudar a agendar? Temos horarios essa semana!",
        },
        "sample_knowledge": "Preencha com servicos, profissionais, precos e horarios.",
    },
    "imobiliaria": {
        "name": "Imobiliaria",
        "icon": "🏠",
        "description": "Imoveis, visitas e negociacao",
        "tags": ["imoveis", "aluguel", "venda"],
        "prompt": """Voce e o corretor virtual da {business_name}. Seja profissional e consultivo.

Regras:
- Pergunte: tipo (compra/aluguel), regiao, quartos, faixa de preco
- Sugira imoveis compativeis da base de conhecimento
- Agende visitas com data, horario e endereco
- Para negociacao de valores, diga que vai consultar proprietario
- Nunca confirme valores finais sem consultar equipe""",
        "funnel_rules": {
            "novo": {"move_to": "contatado", "trigger": "quando o agente respondeu"},
            "contatado": {"move_to": "qualificado", "trigger": "quando informou perfil do imovel"},
            "qualificado": {"move_to": "proposta", "trigger": "quando sugeridos imoveis compativeis"},
            "proposta": {"move_to": "ganho", "trigger": "quando agendou visita ou fez proposta"},
        },
        "followup_messages": {
            "contatado": "Ola {nome}! Tenho opcoes na regiao que mencionou. Quer ver?",
            "proposta": "Oi {nome}! O imovel ainda esta disponivel. Quer agendar visita?",
        },
        "sample_knowledge": "Preencha com imoveis, regioes, precos e condicoes.",
    },
    "seguros": {
        "name": "Seguros / Financeiro",
        "icon": "🛡️",
        "description": "Cotacoes, planos e atendimento",
        "tags": ["seguros", "financeiro", "corretora"],
        "prompt": """Voce e o consultor virtual da {business_name}. Seja profissional e didatico.

Regras:
- Para cotacoes, colete: tipo de seguro, dados do segurado, objeto segurado
- Explique coberturas de forma simples
- Para sinistros, colete dados e encaminhe
- Nunca prometa valores exatos — use "a partir de" ou "cotacao personalizada"
- Informe documentacao necessaria""",
        "funnel_rules": {
            "novo": {"move_to": "contatado", "trigger": "quando o agente respondeu"},
            "contatado": {"move_to": "qualificado", "trigger": "quando informou tipo de seguro"},
            "qualificado": {"move_to": "proposta", "trigger": "quando apresentadas opcoes de planos"},
            "proposta": {"move_to": "ganho", "trigger": "quando aceitou a proposta"},
        },
        "followup_messages": {
            "contatado": "Ola {nome}! Posso te ajudar a encontrar o melhor seguro pro seu perfil?",
            "proposta": "Oi {nome}! A cotacao ainda e valida. Ficou alguma duvida?",
        },
        "sample_knowledge": "Preencha com tipos de seguros, coberturas e faixas de preco.",
    },
    "academia": {
        "name": "Academia / Fitness",
        "icon": "💪",
        "description": "Planos, horarios e matriculas",
        "tags": ["fitness", "academia", "esporte"],
        "prompt": """Voce e o atendente virtual da {business_name}. Seja motivador e informativo.

Regras:
- Informe planos, precos e horarios
- Agende aula experimental gratuita
- Informe modalidades disponiveis
- Para matriculas, colete dados e agende visita
- Motive o cliente quando hesitar""",
        "funnel_rules": {
            "novo": {"move_to": "contatado", "trigger": "quando o agente respondeu"},
            "contatado": {"move_to": "qualificado", "trigger": "quando perguntou sobre planos"},
            "qualificado": {"move_to": "proposta", "trigger": "quando apresentados planos e precos"},
            "proposta": {"move_to": "ganho", "trigger": "quando agendou visita ou aula experimental"},
        },
        "followup_messages": {
            "contatado": "E ai {nome}! Pensando em comecar a treinar? Posso ajudar! 💪",
        },
        "sample_knowledge": "Preencha com planos, precos, horarios e modalidades.",
    },
    "servicos": {
        "name": "Servicos / Consultoria",
        "icon": "🔧",
        "description": "Orcamentos, agendamento e suporte",
        "tags": ["servicos", "consultoria", "orcamento"],
        "prompt": """Voce e o atendente virtual da {business_name}. Seja profissional e objetivo.

Regras:
- Entenda a necessidade antes de oferecer solucao
- Para orcamentos, colete maximo de informacoes
- Informe prazos estimados
- Agende visitas tecnicas quando necessario
- Nunca de orcamentos fechados — depende de avaliacao""",
        "funnel_rules": {
            "novo": {"move_to": "contatado", "trigger": "quando o agente respondeu"},
            "contatado": {"move_to": "qualificado", "trigger": "quando descreveu servico necessario"},
            "qualificado": {"move_to": "proposta", "trigger": "quando enviado orcamento"},
            "proposta": {"move_to": "ganho", "trigger": "quando aprovou orcamento"},
        },
        "followup_messages": {
            "contatado": "Ola {nome}! Posso te ajudar com um orcamento?",
        },
        "sample_knowledge": "Preencha com servicos, precos base e condicoes.",
    },
}


def list_templates() -> list[dict]:
    """Lista todos os templates disponiveis."""
    return [
        {"id": tid, "name": t["name"], "icon": t["icon"],
         "description": t["description"], "tags": t.get("tags", [])}
        for tid, t in TEMPLATES.items()
    ]


def get_template(template_id: str) -> dict | None:
    """Retorna template completo."""
    return TEMPLATES.get(template_id)


def search_templates(query: str) -> list[dict]:
    """Busca templates por nome ou tag."""
    q = query.lower()
    results = []
    for tid, t in TEMPLATES.items():
        if q in t["name"].lower() or q in t.get("description", "").lower() or any(q in tag for tag in t.get("tags", [])):
            results.append({"id": tid, "name": t["name"], "icon": t["icon"], "description": t["description"]})
    return results


def apply_template(tenant_id: str, instance_id: str, template_id: str,
                   business_name: str = "") -> dict:
    """Aplica template a uma instancia WhatsApp."""
    template = TEMPLATES.get(template_id)
    if not template:
        return {"error": "Template nao encontrado"}

    name = business_name or "Meu Negocio"
    prompt = template["prompt"].replace("{business_name}", name)

    # Atualiza instancia WhatsApp
    from .whatsapp_agent import get_wa_manager
    manager = get_wa_manager()
    result = manager.update_instance(instance_id, tenant_id,
                                     system_prompt=prompt,
                                     rag_text=template.get("sample_knowledge", ""))

    # Configura funil automatico
    if template.get("funnel_rules"):
        from .crm_auto_funnel import set_rules, set_enabled
        set_rules(tenant_id, instance_id, template["funnel_rules"])
        set_enabled(tenant_id, instance_id, True)

    # Configura follow-up
    if template.get("followup_messages"):
        from .crm_followup import save_followup_config, DEFAULT_RULES, DEFAULT_SCHEDULE
        cfg = {"rules": DEFAULT_RULES, "schedule": DEFAULT_SCHEDULE}
        save_followup_config(tenant_id, instance_id, cfg)

    log_action("template_applied", f"tenant={tenant_id} inst={instance_id} template={template_id}")
    return {"success": True, "template": template_id, "prompt_preview": prompt[:200]}
