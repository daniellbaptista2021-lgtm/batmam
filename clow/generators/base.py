"""Base utilities for all generators."""
from __future__ import annotations
import os
import re
import time
import unicodedata
from pathlib import Path

import anthropic

STATIC_DIR = Path(__file__).parent.parent.parent / "static"
DOMAIN = os.getenv("CLOW_DOMAIN", "clow.pvcorretor01.com.br")


def get_client() -> anthropic.Anthropic:
    from ..config import ANTHROPIC_API_KEY
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text[:60] or "arquivo"


def unique_name(base: str, ext: str) -> str:
    ts = int(time.time())
    slug = slugify(base)
    return f"{slug}-{ts}{ext}"


def file_url(relative_path: str) -> str:
    return f"https://{DOMAIN}/{relative_path}"


MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-20250514",
}


def ask_ai(prompt: str, system: str = "", model: str = "claude-haiku-4-5-20251001", max_tokens: int = 4096, user_id: str = "") -> str:
    client = get_client()
    msgs = [{"role": "user", "content": prompt}]

    # Prompt caching: system com cache_control
    sys_text = system or "Voce e um assistente especializado. Responda em portugues brasileiro."
    sys_block = [{"type": "text", "text": sys_text, "cache_control": {"type": "ephemeral"}}]

    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=sys_block,
        messages=msgs,
    )

    # Log usage se tiver user_id
    if user_id and resp.usage:
        try:
            from ..database import log_usage
            inp = resp.usage.input_tokens
            out = resp.usage.output_tokens
            cache_read = getattr(resp.usage, 'cache_read_input_tokens', 0) or 0
            # Custo estimado (haiku ~$0.25/1M input, sonnet ~$3/1M input)
            if "haiku" in model:
                cost = (inp * 0.25 + out * 1.25) / 1_000_000
            else:
                cost = (inp * 3.0 + out * 15.0) / 1_000_000
            # Cache read custa 10% do input normal
            if cache_read > 0:
                saved = cache_read * 0.9
                if "haiku" in model:
                    cost -= saved * 0.25 / 1_000_000
                else:
                    cost -= saved * 3.0 / 1_000_000
            log_usage(user_id, model, inp, out, max(cost, 0), "chat")
        except Exception:
            pass

    return resp.content[0].text
