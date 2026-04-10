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


# PROMPT 100% FIXO — nunca muda entre chamadas = maximiza cache DeepSeek
# Dados dinamicos (nome, telefone) vao na mensagem do usuario, NAO aqui
STATIC_SYSTEM_PROMPT = """Voce e o Daniel, consultor de vendas da NIO Fibra Internet.
Conversa de forma natural e profissional, como um consultor de vendas experiente pelo WhatsApp.

COMO VOCE SE COMPORTA:
- Conversa como gente de verdade, nao como robo
- Nunca pede pro cliente digitar numero de opcao
- Entende respostas naturais: sim, pode ser, aham, minha casa, e pra empresa
- Emojis com moderacao. Respostas curtas, 3-4 frases max
- Se cliente perguntar algo fora do fluxo, responde e volta

INFORMACOES NIO FIBRA:
- Prazo de instalacao: 24 a 48h apos cadastro. Casos complexos: ate 7 dias uteis
- Todos os planos tem instalacao gratis e preco fixo garantido ate janeiro/2028
- Suporte 24h via WhatsApp

PLANOS:
- Essencial: 500 Mega, Wi-Fi 5. R$100/mes. Instalacao gratis.
- Super: 700 Mega, Wi-Fi 6, inclui Globoplay. R$130/mes. Instalacao gratis.
- Ultra: 1 Giga, Wi-Fi 6 + Mesh, Globoplay. R$160/mes. Instalacao gratis.

FLUXO DE ATENDIMENTO:
1. SAUDACAO - Boas-vindas, pergunta casa ou empresa
2. CEP - Pede CEP do endereco de instalacao
3. ENDERECO - Confirma endereco, pede numero e complemento
4. EMAIL - Pede email para contato
5. PLANOS - Apresenta os 3 planos e pergunta qual interessa
6. CPF - Pede CPF para analise cadastral
7. CONFERENCIA - Resume TODOS os dados coletados
8. FINALIZACAO - Cadastro concluido, proximos passos

REGRAS:
- Siga a ordem mas seja flexivel na conversa
- Se cliente pular etapas, processe e avance
- Nunca force formato especifico de resposta
- Nunca mostre dados sigilosos da consulta CPF (score, renda, enderecos antigos)
- O contexto do cliente (nome, telefone, resultados de CEP/CPF) vem na mensagem do usuario"""




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
        data = json.dumps({"email": os.getenv("CPF_API_EMAIL", ""), "senha": os.getenv("CPF_API_SENHA", ""), "cpf": cpf}).encode()
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

    # Cache optimization: system prompt is STATIC, dynamic data goes in user message
    system = STATIC_SYSTEM_PROMPT
    msgs = [{"role": "system", "content": system}]
    for m in state.get("messages", [])[-20:]:
        msgs.append({"role": m["role"], "content": m["content"]})
    # Dynamic context in user message (not system) for cache optimization
    user_context = ""
    if customer_name:
        user_context += f"[Cliente: {customer_name} | Tel: {phone}] "
    if tool_ctx:
        user_context += tool_ctx + "\n"
    msgs.append({"role": "user", "content": user_context + message})

    try:
        from openai import OpenAI
        client = OpenAI(**config.get_deepseek_client_kwargs())
        # Auto-retry: tenta 2x com backoff
        for _attempt in range(2):
            try:
                resp = client.chat.completions.create(model="deepseek-chat", messages=msgs, max_tokens=1024, temperature=0.4)
                reply = resp.choices[0].message.content or ""
                # Log cache performance
                if resp.usage:
                    hit = getattr(resp.usage, 'prompt_cache_hit_tokens', 0) or 0
                    miss = getattr(resp.usage, 'prompt_cache_miss_tokens', 0) or 0
                    out = resp.usage.completion_tokens or 0
                    total_in = resp.usage.prompt_tokens or 0
                    pct = round(hit / total_in * 100) if total_in > 0 else 0
                    cost = (hit / 1e6 * 0.028) + (miss / 1e6 * 0.28) + (out / 1e6 * 0.42)
                    logger.info(f"Cache: {pct}% hit ({hit}/{total_in} tokens) cost=${cost:.5f}")
                break
            except Exception as _retry_err:
                if _attempt == 0:
                    import time as _t
                    _t.sleep(2)
                    continue
                raise _retry_err
    except Exception as e:
        logger.error(f"LLM error after retry: {e}")
        reply = "Desculpa, estou com uma instabilidade temporaria. Pode tentar novamente em alguns segundos?"

    state.setdefault("messages", []).append({"role": "user", "content": message})
    state["messages"].append({"role": "assistant", "content": reply})
    if len(state["messages"]) > 30:
        state["messages"] = state["messages"][-30:]
    _save_conv(phone, state)
    return reply
