"""Chat API route: the main HTTP chat endpoint with commands, skills,
file generation, integrations, and agent interaction."""

from __future__ import annotations
import asyncio
import logging
import os
import time
from typing import Any

from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse

from .auth import _get_user_session, _rate_limit_dependency
from .admin import _mission_progress
from ..webapp import track_action
from ..rate_limit import limiter as user_limiter
from ..rag import get_context_for_prompt as _rag_context
from .. import config
from ..database import (
    check_limit, check_message_limit,
    save_message, get_user_usage_today, PLANS,
)


def _build_multimodal_message(text: str, file_data: dict) -> Any:
    """Monta mensagem multimodal (content blocks) para API Anthropic."""
    ftype = file_data.get("type", "")
    content_blocks = []

    if ftype == "image":
        content_blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": file_data.get("media_type", "image/jpeg"),
                "data": file_data.get("base64", ""),
            },
        })
        if text:
            content_blocks.append({"type": "text", "text": text})
        else:
            content_blocks.append({"type": "text", "text": "Analise esta imagem e descreva o que voce ve."})

    elif ftype == "pdf":
        content_blocks.append({
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": file_data.get("base64", ""),
            },
        })
        if text:
            content_blocks.append({"type": "text", "text": text})
        else:
            content_blocks.append({"type": "text", "text": "Analise este PDF e resuma o conteudo."})

    elif ftype == "audio":
        transcription = file_data.get("transcription", "")
        if transcription and not transcription.startswith("[Erro"):
            prompt = f"[Audio transcrito do usuario]\nTranscricao: {transcription}"
            if text:
                prompt += f"\n\nMensagem adicional: {text}"
            return prompt
        else:
            return text or "[O usuario enviou um audio mas a transcricao nao esta disponivel]"

    elif ftype in ("spreadsheet", "document", "code"):
        extracted = file_data.get("extracted_text", "")
        fname = file_data.get("file_name", "arquivo")
        if ftype == "spreadsheet":
            prefix = f"[Planilha: {fname}]\n\nDados:\n{extracted}"
        elif ftype == "code":
            lang = file_data.get("language", "text")
            prefix = f"[Codigo: {fname}]\n\n```{lang}\n{extracted}\n```"
        else:
            prefix = f"[Documento: {fname}]\n\nConteudo:\n{extracted}"
        if text:
            prefix += f"\n\nPedido do usuario: {text}"
        return prefix

    else:
        return text or f"[O usuario enviou um arquivo: {file_data.get('file_name', 'arquivo')}]"

    return content_blocks


def _should_generate_image(content: str) -> bool:
    """Detecta se o pedido e ESPECIFICAMENTE para gerar imagem."""
    keywords = [
        "gera imagem", "cria imagem", "gerar imagem", "criar imagem",
        "faz uma imagem", "gere uma imagem", "crie uma imagem",
        "gera uma foto", "cria uma foto",
        "gera uma ilustracao", "cria uma ilustracao",
    ]
    content_lower = content.lower()
    # Rejeita se contem palavras que indicam outro tipo de criacao
    reject = ["landing", "page", "site", "app", "planilha", "documento",
              "contrato", "proposta", "codigo", "sistema", "dashboard"]
    if any(r in content_lower for r in reject):
        return False
    return any(kw in content_lower for kw in keywords)


async def _process_image_request(content: str, agent) -> tuple[str | None, str | None, str]:
    """
    Processa pedido de imagem:
    1. Otimiza prompt em ingles via Claude
    2. Gera imagem via Pollinations
    3. Retorna (filepath, filename, resposta_formatada)
    """
    from ..generators.image_gen import optimize_prompt_for_image, generate_image

    # Step 1: Otimiza prompt
    try:
        optimized_prompt = optimize_prompt_for_image(content, agent._client)
        if not optimized_prompt:
            optimized_prompt = content
    except Exception as e:
        optimized_prompt = content
        logging.error(f"Erro ao otimizar prompt: {e}")

    # Step 2: Gera imagem
    try:
        filepath, filename = await asyncio.get_event_loop().run_in_executor(
            None, lambda: generate_image(optimized_prompt, 1024, 1024)
        )

        if filepath and filename:
            html = f'''<div style="margin: 12px 0;">
  <img src="/static/files/{filename}" style="max-width:400px;border-radius:12px;cursor:pointer;border:1px solid #ddd;" onclick="window.open(this.src)">
  <div style="margin-top:12px;display:flex;gap:8px;align-items:center;">
    <a href="/static/files/{filename}" download style="padding:8px 16px;background:#5b5fc7;color:#fff;border-radius:6px;text-decoration:none;font-size:12px;cursor:pointer;">⬇️ Baixar</a>
    <span style="font-size:11px;color:#999;">Prompt: {optimized_prompt[:60]}...</span>
  </div>
</div>'''
            response = f"✨ Pronto! Aqui esta sua imagem.\n\n{html}"
            return filepath, filename, response
        else:
            return None, None, "⏳ A geracao de imagem demorou mais que o esperado. Tente novamente ou peca um briefing visual que eu monto pra voce usar no Canva."
    except Exception as e:
        logging.error(f"Erro ao gerar imagem: {e}")
        return None, None, f"❌ Erro ao gerar imagem: {str(e)}"


# HTTP sessions for chat agent reuse
_http_sessions: dict[str, Any] = {}


def register_chat_routes(app: FastAPI) -> None:

    # ── Audio Transcription (Whisper) ──
    _whisper_model = None

    def _get_whisper():
        nonlocal _whisper_model
        if _whisper_model is None:
            from faster_whisper import WhisperModel
            _whisper_model = WhisperModel("medium", device="cpu", compute_type="int8")
        return _whisper_model

    @app.post("/api/v1/transcribe", tags=["chat"])
    async def transcribe_audio(request: Request):
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)
        import tempfile, os
        form = await request.form()
        audio_file = form.get("audio")
        if not audio_file:
            return JSONResponse({"error": "audio file required"}, status_code=400)
        # Save temp file
        suffix = ".webm"
        if hasattr(audio_file, "filename") and audio_file.filename:
            suffix = "." + audio_file.filename.rsplit(".", 1)[-1] if "." in audio_file.filename else ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await audio_file.read()
            tmp.write(content)
            tmp_path = tmp.name
        try:
            model = _get_whisper()
            segments, info = model.transcribe(tmp_path, language="pt", beam_size=5)
            text = " ".join(seg.text.strip() for seg in segments)
            return JSONResponse({"transcription": text, "language": info.language})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        finally:
            os.unlink(tmp_path)

    """Register the main chat API endpoint."""

    @app.post("/api/v1/chat", dependencies=[Depends(_rate_limit_dependency)])
    async def api_chat(request: Request):
        """Chat HTTP com deteccao automatica de geracao de arquivos."""
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)

        # Checa limite de uso (tokens)
        # Check payment status
        from ..database import get_user_by_id as _get_user
        _u = _get_user(sess["user_id"])
        _pay_status = (_u or {}).get("payment_status", "ok")
        if _pay_status == "cancelled":
            return JSONResponse({
                "session_id": "",
                "response": "Sua assinatura foi cancelada. Renove seu plano em Configuracoes > Meu Plano para continuar usando o Clow.",
                "tools": [], "file": None,
            }, status_code=403)
        if _pay_status == "overdue":
            import time as _time
            _overdue_since = (_u or {}).get("payment_overdue_since", 0)
            try:
                _overdue_since = float(_overdue_since)
            except (ValueError, TypeError):
                _overdue_since = 0
            if _overdue_since and (_time.time() - _overdue_since) > 604800:  # 7 days
                return JSONResponse({
                    "session_id": "",
                    "response": "Seu pagamento esta pendente ha mais de 7 dias. O acesso foi bloqueado. Regularize sua assinatura para continuar.",
                    "tools": [], "file": None,
                }, status_code=403)

        allowed, pct = check_limit(sess["user_id"])
        if not allowed:
            return JSONResponse({
                "session_id": "",
                "response": "Voce atingiu seu limite diario de tokens. Volte amanha ou faca upgrade do seu plano.\n\nUse `/plan` para ver seu plano atual.",
                "tools": [], "file": None,
            })

        # Checa limite de mensagens diário/semanal (admins isentos)
        if not sess.get("is_admin"):
            msg_allowed, msg_reason = check_message_limit(sess["user_id"])
            if not msg_allowed:
                return JSONResponse({
                    "session_id": "",
                    "response": msg_reason,
                    "tools": [], "file": None,
                })

        from ..agent import Agent
        import uuid

        body = await request.json()
        content = body.get("content", "").strip()
        conv_id = body.get("conversation_id", "")
        session_id = body.get("session_id", "")
        chosen_model = body.get("model", "deepseek-chat")
        file_data = body.get("file_data")

        if not content and not file_data:
            return JSONResponse({"error": "content vazio"}, status_code=400)

        user_email = sess["email"]
        user_id = sess["user_id"]
        user_plan = sess.get("plan", "lite")
        is_admin = sess.get("is_admin", False)

        # Rate limit per user (based on plan)
        client_ip = request.client.host if request.client else "unknown"
        rl_ok, rl_rem = user_limiter.check(client_ip, user_id, "admin" if is_admin else user_plan)
        if not rl_ok:
            return JSONResponse({
                "session_id": "",
                "response": "Rate limit atingido. Aguarde alguns minutos antes de enviar mais mensagens.",
                "tools": [], "file": None,
            }, status_code=429)

        # ── Billing: seleciona model pelo plano e verifica franquia ──
        from ..billing import get_model_for_plan, check_quota

        user_api_key = None  # Sempre usa key do servidor

        if is_admin:
            # Admin: Sonnet sem limite
            model_id = config.CLOW_MODEL
            effective_plan = "unlimited"
        else:
            effective_plan = user_plan if user_plan in ("lite", "starter", "pro", "business", "unlimited") else "lite"
            # Verifica franquia do plano pago
            quota_check = check_quota(user_id, effective_plan)
            if not quota_check["allowed"]:
                return JSONResponse({
                    "session_id": "",
                    "response": quota_check.get("reason", "Franquia atingida. Tente novamente mais tarde."),
                    "tools": [], "file": None,
                })
            model_id = get_model_for_plan(effective_plan)
        track_action("user_message_http", content[:60])

        # Salva mensagem do usuario no historico
        if conv_id:
            save_message(conv_id, "user", content)

        # ── Comandos internos ──
        if content.startswith("/"):
            cmd_lower = content.lower().strip()
            cmd_resp = None

            if cmd_lower.startswith("/skills"):
                from ..skills.loader import format_skills_list
                cat = content[7:].strip()
                cmd_resp = format_skills_list(cat)
            elif cmd_lower == "/memories":
                from ..memory_web import format_memories_list
                cmd_resp = format_memories_list(user_id)
            elif cmd_lower.startswith("/forget"):
                from ..memory_web import forget_memory
                kw = content[7:].strip()
                cmd_resp = forget_memory(user_id, kw) if kw else "Use: `/forget palavra-chave`"
            elif cmd_lower.startswith("/mission"):
                mission_desc = content[8:].strip() if len(content) > 8 else ""
                if not mission_desc:
                    cmd_resp = (
                        "## Missoes Autonomas\n\n"
                        "Descreva uma missao complexa e o Clow executa sozinho:\n\n"
                        "**Exemplos:**\n"
                        "- `/mission Cria um site completo para uma pizzaria com cardapio e contato`\n"
                        "- `/mission Campanha de trafego para seguro de vida com landing page e copies`\n"
                        "- `/mission Setup digital completo para barbearia`\n\n"
                        "O Clow vai planejar, mostrar as etapas, e executar tudo automaticamente."
                    )
                else:
                    # Planeja e inicia missao
                    from ..agents.mission_engine import plan_mission
                    loop = asyncio.get_event_loop()
                    try:
                        plan_data = await loop.run_in_executor(None, plan_mission, mission_desc)
                        steps = plan_data.get("steps", [])
                        title = plan_data.get("title", mission_desc[:60])
                        est = plan_data.get("estimated_minutes", 5)

                        # Cria e inicia missao
                        from ..database import create_mission as db_create_mission
                        mid = db_create_mission(user_id, title, mission_desc, steps)
                        _mission_progress[mid] = []

                        async def on_progress(m_id, evt, data):
                            _mission_progress.setdefault(m_id, []).append({"type": evt, "data": data, "time": time.time()})

                        from ..agents.mission_engine import execute_mission
                        asyncio.create_task(execute_mission(mid, user_id, on_progress))

                        # Mostra plano e inicia
                        steps_text = "\n".join(f"{i+1}. {s.get('title', '?')}" for i, s in enumerate(steps))
                        cmd_resp = (
                            f"## Missao Iniciada\n\n"
                            f"**{title}**\n\n"
                            f"### Plano ({len(steps)} etapas, ~{est} min):\n{steps_text}\n\n"
                            f"Executando em background... Acompanhe o progresso abaixo."
                        )

                        # Retorna com mission_id pra frontend fazer polling
                        if conv_id:
                            save_message(conv_id, "assistant", cmd_resp)
                        return JSONResponse({
                            "session_id": session_id or str(uuid.uuid4())[:8],
                            "response": cmd_resp,
                            "tools": [], "file": None,
                            "mission": {"id": mid, "title": title, "total_steps": len(steps)},
                        })
                    except Exception as e:
                        cmd_resp = f"Erro ao planejar missao: {str(e)[:200]}"

            elif cmd_lower == "/help":
                cmd_resp = (
                    "## Comandos Disponiveis\n\n"
                    "| Comando | Descricao |\n|---------|----------|\n"
                    "| `/mission X` | Iniciar missao autonoma |\n"
                    "| `/skills` | Listar skills disponiveis |\n"
                    "| `/memories` | Ver memorias salvas |\n"
                    "| `/forget X` | Esquecer memoria |\n"
                    "| `/connect` | Conectar servico externo |\n"
                    "| `/connections` | Ver conexoes ativas |\n"
                    "| `/disconnect X` | Desconectar servico |\n"
                    "| `/usage` | Ver consumo de tokens hoje |\n"
                    "| `/plan` | Ver plano atual e limites |\n"
                    "| `/help` | Esta lista de comandos |\n\n"
                    "**Missoes:** `/mission cria um site completo para pizzaria`\n\n"
                    "**Geracao de arquivos:** peca naturalmente (ex: 'cria uma planilha de vendas')\n\n"
                    "**Integracoes:** pergunte direto (ex: 'mostra minhas campanhas meta ads')"
                )
            elif cmd_lower == "/usage":
                usage = get_user_usage_today(user_id)
                plan_info = PLANS.get(sess.get("plan", "lite"), PLANS["lite"])
                limit = plan_info["daily_tokens"]
                used = usage["total_tokens"]
                pct_str = f"{(used/limit*100):.0f}%" if limit > 0 else "ilimitado"
                cmd_resp = (
                    f"## Seu Consumo Hoje\n\n"
                    f"- Tokens usados: **{used:,}**\n"
                    f"- Limite diario: **{limit:,}** ({pct_str})\n"
                    f"- Requests: **{usage['requests']}**\n"
                    f"- Custo estimado: **${usage['total_cost']:.4f}**"
                )
            elif cmd_lower == "/plan":
                plan_info = PLANS.get(sess.get("plan", "lite"), PLANS["lite"])
                cmd_resp = (
                    f"## Seu Plano: {plan_info['label']}\n\n"
                    f"- Limite diario: **{plan_info['daily_tokens']:,} tokens**\n\n"
                    "**Planos disponiveis:**\n"
                    "| Plano | Tokens/dia |\n|-------|------------|\n"
                )

            if cmd_resp:
                if conv_id:
                    save_message(conv_id, "assistant", cmd_resp)
                return JSONResponse({
                    "session_id": session_id or str(uuid.uuid4())[:8],
                    "response": cmd_resp, "tools": [], "file": None,
                })

            # /connect, /disconnect, /connections
            from ..integrations.command_handler import handle_command
            cmd_result = handle_command(content, user_email)
            if cmd_result:
                if conv_id:
                    save_message(conv_id, "assistant", cmd_result["response"])
                return JSONResponse({
                    "session_id": session_id or str(uuid.uuid4())[:8],
                    "response": cmd_result["response"],
                    "tools": [], "file": None,
                })

        # ── Detecta pedidos de integracao (meta ads, supabase, etc) ──
        from ..integrations.command_handler import detect_integration_request
        int_result = detect_integration_request(content, user_email)
        if int_result:
            return JSONResponse({
                "session_id": session_id or str(uuid.uuid4())[:8],
                "response": int_result["response"],
                "tools": [],
                "file": None,
            })

        # ── Detecta geracao de arquivo ──
        from ..generators.dispatcher import detect, run_generator
        gen_module, gen_type = detect(content)

        if gen_module:
            loop = asyncio.get_event_loop()
            try:
                result = await loop.run_in_executor(None, run_generator, gen_module, content, model_id, user_id)
                track_action("file_generated", f"{gen_type}: {result.get('name', '')}", "ok")

                if result.get("type") == "text":
                    return JSONResponse({
                        "session_id": session_id or str(uuid.uuid4())[:8],
                        "response": result["content"],
                        "tools": [],
                        "file": None,
                    })

                # Formata tamanho
                size_raw = result.get("size", 0)
                if isinstance(size_raw, str):
                    size_str = size_raw
                elif isinstance(size_raw, (int, float)) and size_raw > 1024 * 1024:
                    size_str = f"{size_raw / (1024*1024):.1f} MB"
                elif isinstance(size_raw, (int, float)) and size_raw > 1024:
                    size_str = f"{size_raw / 1024:.1f} KB"
                else:
                    size_str = f"{size_raw} bytes"

                type_labels = {
                    "landing_page": "Landing Page",
                    "app": "Web App",
                    "xlsx": "Planilha Excel",
                    "docx": "Documento Word",
                    "pptx": "Apresentacao PowerPoint",
                }
                type_label = type_labels.get(result["type"], result["type"])
                msg = f"Pronto! Aqui esta seu arquivo:\n\n**{type_label}** — {result['name']} ({size_str})"

                return JSONResponse({
                    "session_id": session_id or str(uuid.uuid4())[:8],
                    "response": msg,
                    "tools": [],
                    "file": {
                        "type": result["type"],
                        "name": result["name"],
                        "url": result["url"],
                        "size": size_str,
                    },
                })
            except Exception as e:
                track_action("file_gen_error", str(e)[:60], "error")
                return JSONResponse({
                    "session_id": session_id or str(uuid.uuid4())[:8],
                    "response": f"Erro ao gerar arquivo: {str(e)}",
                    "tools": [],
                    "file": None,
                }, status_code=500)

        # ── Injetar skills no prompt ──
        from ..skills.loader import build_skill_prompt
        skill_context = build_skill_prompt(content)
        if skill_context:
            content = f"[CONTEXTO DE SKILLS ATIVAS - siga estas instrucoes]\n{skill_context}\n[FIM DO CONTEXTO]\n\nPedido do usuario: {content}"

        # ── Chat normal via Agent ──
        # session_key inclui user_id para garantir isolamento entre usuarios:
        # dois usuarios com o mesmo session_id nunca compartilham o mesmo agente.
        session_key = f"{user_id}_{session_id}_{chosen_model}"
        if session_id and session_key in _http_sessions:
            agent = _http_sessions[session_key]["agent"]
        else:
            session_id = str(uuid.uuid4())[:8]
            session_key = f"{user_id}_{session_id}_{chosen_model}"
            if is_admin:
                # Admin tem acesso total — auto_approve permite todas as ferramentas
                agent = Agent(cwd=os.getcwd(), model=model_id, api_key=user_api_key or None, auto_approve=True)
            else:
                # Usuarios tem acesso total as ferramentas de criacao
                # (bash, write, edit, deploy, etc) — forca total para produtividade.
                # Sessoes sao efemeras (limpas diariamente).
                agent = Agent(
                    cwd=os.getcwd(), model=model_id, api_key=user_api_key or None,
                    auto_approve=True,
                )
            _http_sessions[session_key] = {"agent": agent, "last_used": time.time()}

        _http_sessions[session_key]["last_used"] = time.time()

        now = time.time()
        stale = [k for k, v in _http_sessions.items() if now - v["last_used"] > 1800]
        for k in stale:
            del _http_sessions[k]

        loop = asyncio.get_event_loop()
        collected_text: list[str] = []
        tools_used: list[dict] = []

        def on_text_delta(delta: str):
            collected_text.append(delta)

        def on_tool_call(name: str, args: dict):
            tools_used.append({"name": name, "args": args, "status": "running", "output": ""})
            track_action("tool_call", name, "running")

        def on_tool_result(name: str, status: str, output: str):
            for t in tools_used:
                if t["name"] == name and t["status"] == "running":
                    t["status"] = status
                    t["output"] = output[:500]
                    break
            track_action("tool_result", f"{name}: {status}", status)

        agent.on_text_delta = on_text_delta
        agent.on_text_done = lambda t: None
        agent.on_tool_call = on_tool_call
        agent.on_tool_result = on_tool_result

        # Monta mensagem multimodal se tem arquivo
        if file_data:
            user_msg = _build_multimodal_message(content, file_data)
        else:
            # Enrich with RAG context (codebase search)
            rag_ctx = ""
            try:
                rag_ctx = _rag_context(content, root=os.getcwd(), max_chars=8000)
            except Exception:
                pass
            user_msg = f"{rag_ctx}\n\n---\n\n{content}" if rag_ctx else content

        try:
            result = await loop.run_in_executor(None, agent.run_turn, user_msg)
        except Exception as e:
            return JSONResponse({
                "session_id": session_id,
                "error": str(e),
            }, status_code=500)

        response_text = "".join(collected_text) if collected_text else (result or "")
        track_action("agent_response_http", response_text[:60] if response_text else "")

        return JSONResponse({
            "session_id": session_id,
            "response": response_text,
            "tools": tools_used,
            "file": None,
        })
