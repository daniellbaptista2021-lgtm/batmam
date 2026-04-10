"""Daniel NIO Fibra — Agente de vendas WhatsApp para NIO Fibra Internet.

Fluxo: Saudacao > CEP > Endereco > Email > Planos > CPF > Conferencia > Finalizacao
Tools: consulta_cep, consulta_cpf
Modelo: deepseek-chat (obrigatorio, mais barato)
"""

import json
import os
import re
import time
import logging
from pathlib import Path
from urllib.request import urlopen, Request

from . import config

logger = logging.getLogger("clow.daniel_agent")

_CONV_DIR = config.CLOW_HOME / "daniel_nio_conversations"
_CONV_DIR.mkdir(parents=True, exist_ok=True)

CAROL_PROMPT = """Voce e o Daniel, consultor de vendas da NIO Fibra Internet.
Conversa de forma natural e profissional, como um consultor de vendas experiente pelo WhatsApp.

NOME DO CLIENTE: {customer_name}
TELEFONE: {customer_phone}

COMPORTAMENTO:
- Conversa como gente de verdade, nao como robo
- Nunca pede pra digitar numero de opcao
- Entende respostas naturais: sim, pode ser, aham, etc
- Emojis com moderacao. Respostas curtas, 3-4 frases max
- Se cliente perguntar algo fora do fluxo, responde e volta

NIO FIBRA:
- Instalacao: 24-48h apos cadastro. Gratis. Preco fixo ate jan/2028.

FLUXO (siga essa ordem, mas seja flexivel):
1. SAUDACAO - Boas-vindas, pergunta casa ou empresa
2. CEP - Pede CEP. Quando receber 8 digitos, resultado abaixo aparece automaticamente
3. ENDERECO - Confirma endereco, pede numero e complemento
4. EMAIL - Pede email
5. PLANOS - Apresenta: Essencial 500M R$100 | Super 700M R$130 | Ultra 1G R$160
6. CPF - Pede CPF. Quando receber 11 digitos, resultado abaixo aparece automaticamente
   USA APENAS: Nome, DataNascimento, NomeMae. IGNORA score, renda, enderecos antigos
7. CONFERENCIA - Resume TODOS os dados coletados com rotulos claros
8. FINALIZACAO - Cadastro concluido, proximos passos

{context}"""


def consulta_cep(cep):
    cep = re.sub(r'\D', '', str(cep))
    if len(cep) != 8:
        return {"error": "CEP invalido"}
    try:
        resp = urlopen(f"https://viacep.com.br/ws/{cep}/json/", timeout=10)
        data = json.loads(resp.read().decode())
        if data.get("erro"):
            return {"error": "CEP nao encontrado"}
        return {"cep": data.get("cep", ""), "logradouro": data.get("logradouro", ""),
                "bairro": data.get("bairro", ""), "cidade": data.get("localidade", ""), "uf": data.get("uf", "")}
    except Exception as e:
        return {"error": str(e)[:100]}


def consulta_cpf(cpf):
    cpf = re.sub(r'\D', '', str(cpf))
    if len(cpf) != 11:
        return {"error": "CPF invalido"}
    try:
        data = json.dumps({"email": "equipoclass@gmail.com", "senha": "123@Equipoclass", "cpf": cpf}).encode()
        req = Request("https://enriquecimento.interativaviews.com.br/api/consulta-cpf/",
                       data=data, headers={"Content-Type": "application/json"}, method="POST")
        resp = urlopen(req, timeout=15)
        r = json.loads(resp.read().decode())
        return {"nome": r.get("Nome", ""), "data_nascimento": r.get("DataNascimento", ""),
                "nome_mae": r.get("NomeMae", ""), "cpf": r.get("Doc", cpf)}
    except Exception as e:
        return {"error": str(e)[:100]}


def _load_conv(phone):
    p = _CONV_DIR / f"{phone}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except:
            pass
    return {"messages": [], "data": {}, "created_at": time.time()}


def _save_conv(phone, state):
    (_CONV_DIR / f"{phone}.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def process_daniel_message(phone, message, customer_name=""):
    """Process message through Daniel agent. Returns reply string."""
    state = _load_conv(phone)
    if not customer_name:
        customer_name = state.get("data", {}).get("name", phone[-4:])
    else:
        state.setdefault("data", {})["name"] = customer_name

    # Auto-detect CEP and CPF
    tool_ctx = ""
    cep_m = re.search(r'\b(\d{5})-?(\d{3})\b', message)
    cpf_m = re.search(r'\b(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})\b', message)

    if cep_m:
        r = consulta_cep(cep_m.group())
        if "error" not in r:
            state.setdefault("data", {}).update(r)
            tool_ctx += f"\n[RESULTADO CEP]\n{json.dumps(r, ensure_ascii=False)}\nUse para confirmar endereco."
        else:
            tool_ctx += f"\n[CEP NAO ENCONTRADO] Peca para verificar."

    if cpf_m:
        r = consulta_cpf(cpf_m.group())
        if "error" not in r:
            state.setdefault("data", {})["cpf_data"] = r
            tool_ctx += f"\n[RESULTADO CPF]\n{json.dumps(r, ensure_ascii=False)}\nUse APENAS Nome, DataNascimento, NomeMae."
        else:
            tool_ctx += f"\n[ERRO CPF] Peca novamente."

    system = CAROL_PROMPT.format(customer_name=customer_name, customer_phone=phone, context=tool_ctx)
    msgs = [{"role": "system", "content": system}]
    for m in state.get("messages", [])[-20:]:
        msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": message})

    try:
        from openai import OpenAI
        client = OpenAI(**config.get_deepseek_client_kwargs())
        resp = client.chat.completions.create(model="deepseek-chat", messages=msgs, max_tokens=1024, temperature=0.4)
        reply = resp.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"Daniel LLM error: {e}")
        reply = "Desculpa, tive um probleminha tecnico. Pode repetir?"

    state.setdefault("messages", []).append({"role": "user", "content": message})
    state["messages"].append({"role": "assistant", "content": reply})
    if len(state["messages"]) > 30:
        state["messages"] = state["messages"][-30:]
    _save_conv(phone, state)
    return reply
