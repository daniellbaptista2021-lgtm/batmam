"""Image Generation Tool — DALL-E 3 + Pollinations fallback.

Gera imagens profissionais com DALL-E 3 (OpenAI).
Fallback para Pollinations.ai quando OPENAI_API_KEY nao disponivel.
"""

from __future__ import annotations
import json
import os
import time
import base64
import logging
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
from typing import Any
from .base import BaseTool

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent.parent.parent / "static" / "files"
DOMAIN = os.getenv("CLOW_DOMAIN", "clow.pvcorretor01.com.br")


def _get_openai_key() -> str:
    """Busca OPENAI_API_KEY do env ou credential_manager."""
    key = os.getenv("OPENAI_API_KEY", "")
    if key:
        return key
    try:
        from ..credentials.credential_manager import load_credential
        creds = load_credential("system", "openai")
        if creds:
            return creds.get("api_key", "")
    except Exception:
        pass
    return ""


class ImageGenTool(BaseTool):
    name = "image_gen"
    description = (
        "Gera imagens com IA. Usa DALL-E 3 (HD, multiplas imagens) quando OPENAI_API_KEY "
        "disponivel, senao usa Pollinations.ai (gratuito). "
        "Tamanhos: 1024x1024, 1792x1024 (paisagem), 1024x1792 (retrato)."
    )
    requires_confirmation = False

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Descricao detalhada da imagem em ingles. Inclua estilo, cores, composicao.",
                },
                "size": {
                    "type": "string",
                    "enum": ["1024x1024", "1792x1024", "1024x1792"],
                    "description": "Tamanho: 1024x1024 (quadrado), 1792x1024 (paisagem), 1024x1792 (retrato). Padrao: 1024x1024",
                },
                "quality": {
                    "type": "string",
                    "enum": ["standard", "hd"],
                    "description": "Qualidade: standard (rapido) ou hd (mais detalhe). Padrao: standard",
                },
                "style": {
                    "type": "string",
                    "enum": ["vivid", "natural"],
                    "description": "Estilo: vivid (hiper-realista, dramatico) ou natural (mais sutil). Padrao: vivid",
                },
                "n": {
                    "type": "integer",
                    "description": "Quantidade de imagens (1-4). DALL-E 3: max 1 por chamada, mas gera N chamadas. Padrao: 1",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Diretorio de saida (padrao: static/files/)",
                },
            },
            "required": ["prompt"],
        }

    def execute(self, **kwargs: Any) -> str:
        prompt = kwargs.get("prompt", "").strip()
        if not prompt:
            return "Erro: prompt e obrigatorio."

        size = kwargs.get("size", "1024x1024")
        quality = kwargs.get("quality", "standard")
        style = kwargs.get("style", "vivid")
        n = min(max(kwargs.get("n", 1), 1), 4)
        output_dir = kwargs.get("output_dir", "")

        if not output_dir:
            output_dir = str(STATIC_DIR)
        os.makedirs(output_dir, exist_ok=True)

        api_key = _get_openai_key()

        if api_key:
            return self._generate_dalle(prompt, size, quality, style, n, output_dir, api_key)
        else:
            logger.info("OPENAI_API_KEY nao disponivel, usando Pollinations.ai")
            return self._generate_pollinations(prompt, size, output_dir)

    def _generate_dalle(self, prompt: str, size: str, quality: str, style: str,
                        n: int, output_dir: str, api_key: str) -> str:
        """Gera imagens via DALL-E 3 API."""
        model = os.getenv("DALLE_MODEL", "dall-e-3")
        results = []

        for i in range(n):
            try:
                payload = json.dumps({
                    "model": model,
                    "prompt": prompt,
                    "n": 1,
                    "size": size,
                    "quality": quality,
                    "style": style,
                    "response_format": "b64_json",
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
                resp = urlopen(req, timeout=90)
                result = json.loads(resp.read().decode())

                img_b64 = result["data"][0]["b64_json"]
                revised = result["data"][0].get("revised_prompt", "")

                ts = int(time.time() * 1000)
                suffix = f"_{i+1}" if n > 1 else ""
                filename = f"dalle_{ts}{suffix}.png"
                filepath = os.path.join(output_dir, filename)

                with open(filepath, "wb") as f:
                    f.write(base64.b64decode(img_b64))

                file_size = os.path.getsize(filepath)
                url = f"https://{DOMAIN}/static/files/{filename}"

                results.append({
                    "file": filepath,
                    "filename": filename,
                    "url": url,
                    "size_kb": round(file_size / 1024, 1),
                    "revised_prompt": revised[:150],
                })
                logger.info(f"DALL-E imagem {i+1}/{n} salva: {filepath}")

            except URLError as e:
                err_body = ""
                if hasattr(e, "read"):
                    try:
                        err_body = e.read().decode()[:300]
                    except Exception:
                        pass
                results.append({"error": f"DALL-E erro: {e} {err_body}"})
            except Exception as e:
                results.append({"error": f"Erro: {e}"})

        # Formata resposta
        ok = [r for r in results if "file" in r]
        errs = [r for r in results if "error" in r]

        parts = []
        if ok:
            parts.append(f"{'Imagens geradas' if len(ok) > 1 else 'Imagem gerada'} com DALL-E 3 ({quality}):")
            for r in ok:
                parts.append(f"  {r['filename']} ({r['size_kb']}KB) — {r['url']}")
                if r["revised_prompt"]:
                    parts.append(f"  Prompt: {r['revised_prompt']}")
        if errs:
            for r in errs:
                parts.append(r["error"])

        return "\n".join(parts)

    def _generate_pollinations(self, prompt: str, size: str, output_dir: str) -> str:
        """Fallback: gera via Pollinations.ai (gratuito, sem key)."""
        import urllib.parse
        try:
            w, h = size.split("x")
        except ValueError:
            w, h = "1024", "1024"

        encoded = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width={w}&height={h}&model=flux&nologo=true"

        try:
            img_data = urlopen(url, timeout=120).read()
            ts = int(time.time() * 1000)
            filename = f"pollinations_{ts}.png"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, "wb") as f:
                f.write(img_data)

            file_url = f"https://{DOMAIN}/static/files/{filename}"
            size_kb = round(len(img_data) / 1024, 1)

            return (
                f"Imagem gerada com Pollinations.ai (gratuito):\n"
                f"  {filename} ({size_kb}KB) — {file_url}\n"
                f"  Nota: Para qualidade HD, configure OPENAI_API_KEY para usar DALL-E 3."
            )
        except Exception as e:
            return f"Erro ao gerar imagem: {e}"
