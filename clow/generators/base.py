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


def ask_ai(prompt: str, system: str = "", model: str = "claude-haiku-4-5-20251001", max_tokens: int = 4096) -> str:
    client = get_client()
    msgs = [{"role": "user", "content": prompt}]
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system or "Voce e um assistente especializado. Responda em portugues brasileiro.",
        messages=msgs,
    )
    return resp.content[0].text
