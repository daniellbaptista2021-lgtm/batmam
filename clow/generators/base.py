"""Base utilities for all generators."""
from __future__ import annotations
import os
import re
import time
import unicodedata
from pathlib import Path

from openai import OpenAI

STATIC_DIR = Path(__file__).parent.parent.parent / "static"
DOMAIN = os.getenv("CLOW_DOMAIN", "clow.pvcorretor01.com.br")


def get_client() -> OpenAI:
    from ..config import get_deepseek_client_kwargs
    return OpenAI(**get_deepseek_client_kwargs())


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
    "default": "deepseek-chat",
    "reasoner": "deepseek-reasoner",
}


def ask_ai(prompt: str, system: str = "", model: str = "", max_tokens: int = 2000, user_id: str = "") -> str:  # DeepSeek max 8192
    from .. import config
    client = get_client()
    model = model or config.CLOW_MODEL
    sys_text = system or "Voce e um assistente especializado. Responda em portugues brasileiro."

    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": sys_text},
            {"role": "user", "content": prompt},
        ],
    )

    # Log usage se tiver user_id
    if user_id and resp.usage:
        try:
            from ..database import log_usage
            inp = resp.usage.prompt_tokens or 0
            out = resp.usage.completion_tokens or 0
            cost = (inp * config.DEEPSEEK_INPUT_PRICE_PER_MTOK + out * config.DEEPSEEK_OUTPUT_PRICE_PER_MTOK) / 1_000_000
            log_usage(user_id, model, inp, out, max(cost, 0), "chat")
        except Exception:
            pass

    return resp.choices[0].message.content or ""
