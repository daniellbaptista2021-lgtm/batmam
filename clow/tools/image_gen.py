"""Image Generation Tool — gera imagens via DALL-E ou Stability AI."""

from __future__ import annotations
import json
import os
from urllib.request import urlopen, Request
from urllib.error import URLError
from typing import Any
from .base import BaseTool


class ImageGenTool(BaseTool):
    name = "image_gen"
    description = "Gera imagens via API (DALL-E, Stability). Salva no disco."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Descrição da imagem a gerar"},
                "size": {
                    "type": "string",
                    "enum": ["256x256", "512x512", "1024x1024", "1024x1792", "1792x1024"],
                    "description": "Tamanho da imagem (padrão: 1024x1024)",
                },
                "style": {
                    "type": "string",
                    "enum": ["vivid", "natural"],
                    "description": "Estilo (padrão: vivid)",
                },
                "output_path": {"type": "string", "description": "Caminho para salvar (padrão: ./generated_image.png)"},
                "provider": {
                    "type": "string",
                    "enum": ["dalle", "stability"],
                    "description": "Provider (padrão: dalle)",
                },
            },
            "required": ["prompt"],
        }

    def execute(self, **kwargs: Any) -> str:
        prompt = kwargs.get("prompt", "")
        if not prompt:
            return "Erro: prompt é obrigatório."

        provider = kwargs.get("provider", "dalle")
        size = kwargs.get("size", "1024x1024")
        style = kwargs.get("style", "vivid")
        output_path = kwargs.get("output_path", "./generated_image.png")

        if provider == "dalle":
            return self._generate_dalle(prompt, size, style, output_path)
        elif provider == "stability":
            return self._generate_stability(prompt, size, output_path)
        return f"Provider '{provider}' não suportado."

    def _generate_dalle(self, prompt: str, size: str, style: str, output_path: str) -> str:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            return "Erro: OPENAI_API_KEY necessária para DALL-E."

        try:
            payload = json.dumps({
                "model": "dall-e-3",
                "prompt": prompt,
                "n": 1,
                "size": size,
                "style": style,
                "response_format": "url",
            }).encode()

            req = Request(
                "https://api.openai.com/v1/images/generations",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            resp = urlopen(req, timeout=60)
            result = json.loads(resp.read().decode())

            image_url = result["data"][0]["url"]
            revised_prompt = result["data"][0].get("revised_prompt", "")

            # Baixa a imagem
            img_data = urlopen(image_url, timeout=30).read()
            with open(output_path, "wb") as f:
                f.write(img_data)

            return f"Imagem gerada e salva em {output_path}\nPrompt revisado: {revised_prompt[:200]}"

        except URLError as e:
            return f"Erro DALL-E: {e}"
        except Exception as e:
            return f"Erro: {e}"

    def _generate_stability(self, prompt: str, size: str, output_path: str) -> str:
        api_key = os.getenv("STABILITY_API_KEY", "")
        if not api_key:
            return "Erro: STABILITY_API_KEY necessária."

        try:
            w, h = size.split("x")
            payload = json.dumps({
                "text_prompts": [{"text": prompt}],
                "cfg_scale": 7,
                "width": int(w),
                "height": int(h),
                "samples": 1,
            }).encode()

            req = Request(
                "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
                method="POST",
            )
            resp = urlopen(req, timeout=60)
            result = json.loads(resp.read().decode())

            import base64
            img_b64 = result["artifacts"][0]["base64"]
            with open(output_path, "wb") as f:
                f.write(base64.b64decode(img_b64))

            return f"Imagem gerada e salva em {output_path}"

        except URLError as e:
            return f"Erro Stability: {e}"
        except Exception as e:
            return f"Erro: {e}"
