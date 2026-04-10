"""Gerador de imagens — DALL-E 3 (preferencial) + Pollinations.ai (fallback)."""

import os
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_image(prompt: str, width: int = 1024, height: int = 1024,
                   quality: str = "standard", timeout: int = 120) -> tuple[str | None, str | None]:
    """Gera imagem usando DALL-E 3 se OPENAI_API_KEY disponivel, senao Pollinations.

    Returns:
        Tupla (filepath, filename) ou (None, None) em caso de erro
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if api_key:
        return _generate_dalle(prompt, width, height, quality, api_key)
    return _generate_pollinations(prompt, width, height, timeout)


def _generate_dalle(prompt: str, width: int, height: int,
                    quality: str, api_key: str) -> tuple[str | None, str | None]:
    """Gera via DALL-E 3 API."""
    import json
    import base64
    from urllib.request import Request, urlopen

    size = f"{width}x{height}"
    if size not in ("1024x1024", "1792x1024", "1024x1792"):
        size = "1024x1024"

    try:
        payload = json.dumps({
            "model": os.getenv("DALLE_MODEL", "dall-e-3"),
            "prompt": prompt,
            "n": 1,
            "size": size,
            "quality": quality,
            "response_format": "b64_json",
        }).encode()

        req = Request(
            "https://api.openai.com/v1/images/generations",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        resp = urlopen(req, timeout=90)
        result = json.loads(resp.read().decode())

        img_b64 = result["data"][0]["b64_json"]
        file_dir = str(Path(__file__).parent.parent.parent / "static" / "files")
        os.makedirs(file_dir, exist_ok=True)

        filename = f"dalle_{int(time.time() * 1000)}.png"
        filepath = os.path.join(file_dir, filename)
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(img_b64))

        logger.info(f"DALL-E imagem salva: {filepath}")
        return filepath, filename

    except Exception as e:
        logger.error(f"Erro DALL-E: {e}")
        return None, None


def _generate_pollinations(prompt: str, width: int, height: int,
                           timeout: int) -> tuple[str | None, str | None]:
    """Fallback: Pollinations.ai (gratuito)."""
    import urllib.parse
    import urllib.request

    encoded = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&model=flux&nologo=true"

    try:
        img_data = urllib.request.urlopen(url, timeout=timeout).read()
        file_dir = str(Path(__file__).parent.parent.parent / "static" / "files")
        os.makedirs(file_dir, exist_ok=True)

        filename = f"pollinations_{int(time.time() * 1000)}.png"
        filepath = os.path.join(file_dir, filename)
        with open(filepath, "wb") as f:
            f.write(img_data)

        logger.info(f"Pollinations imagem salva: {filepath}")
        return filepath, filename

    except Exception as e:
        logger.error(f"Erro Pollinations: {e}")
        return None, None


def optimize_prompt_for_image(user_prompt: str, llm_client) -> str:
    """Otimiza prompt em portugues para prompt de imagem em ingles via DeepSeek."""
    try:
        system = """Voce e um expert em prompts para geracao de imagens.
Transforme pedidos em portugues em prompts detalhados em ingles para DALL-E/Flux.

Regras:
- Seja descritivo: estilo visual, cores, iluminacao, composicao
- Use termos profissionais (photography, illustration, 3D render, digital art)
- Maximo 150 caracteres
- Retorne APENAS o prompt, sem explicacoes"""

        from .. import config
        response = llm_client.chat.completions.create(
            model=config.CLOW_MODEL,
            max_tokens=200,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Transforme em prompt de imagem em ingles:\n\n{user_prompt}"},
            ],
        )
        optimized = (response.choices[0].message.content or "").strip()
        logger.info(f"Prompt otimizado: {optimized}")
        return optimized

    except Exception as e:
        logger.error(f"Erro ao otimizar prompt: {e}")
        return user_prompt
