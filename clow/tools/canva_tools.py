"""Canva Design Tools v2 — sem API token, usa links de templates + gerador HTML."""

from __future__ import annotations
import json
import urllib.request
import urllib.parse
from typing import Any
from .base import BaseTool


class CanvaTemplateTool(BaseTool):
    name = "canva_template"
    description = "Gera link do Canva com templates prontos para o cliente personalizar. Nao precisa de token."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "O que o cliente precisa (ex: post pizzaria, logo barbearia, cartao advogado)"},
                "design_type": {
                    "type": "string",
                    "enum": ["instagram_post", "instagram_story", "facebook_post", "logo",
                             "business_card", "poster", "flyer", "youtube_thumbnail",
                             "presentation", "banner", "menu", "convite", "curriculum"],
                    "description": "Tipo de design",
                },
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> str:
        query = kwargs["query"]
        dtype = kwargs.get("design_type", "")

        # Map design types to Canva search categories
        type_map = {
            "instagram_post": "instagram-posts",
            "instagram_story": "instagram-stories",
            "facebook_post": "facebook-posts",
            "logo": "logos",
            "business_card": "business-cards",
            "poster": "posters",
            "flyer": "flyers",
            "youtube_thumbnail": "youtube-thumbnails",
            "presentation": "presentations",
            "banner": "banners",
            "menu": "menus",
            "convite": "invitations",
            "curriculum": "resumes",
        }

        canva_cat = type_map.get(dtype, "")
        encoded_q = urllib.parse.quote(query)

        if canva_cat:
            url = f"https://www.canva.com/templates/search/{canva_cat}/{encoded_q}/"
            create_url = f"https://www.canva.com/create/{canva_cat.rstrip('s')}/"
        else:
            url = f"https://www.canva.com/templates/?query={encoded_q}"
            create_url = f"https://www.canva.com/create/"

        return (f"Aqui estao templates prontos do Canva para voce personalizar:\n\n"
                f"Buscar templates: {url}\n\n"
                f"Criar do zero: {create_url}\n\n"
                f"Clique no link, escolha um template e personalize com suas cores, textos e fotos. "
                f"E gratis e voce pode baixar como PNG ou PDF.")


class DesignGeneratorTool(BaseTool):
    name = "design_generate"
    description = "Gera uma arte/design profissional como HTML. Cria posts, banners, cartoes, flyers como arquivo HTML estilizado que pode ser baixado como imagem."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "design_type": {
                    "type": "string",
                    "enum": ["instagram_post", "instagram_story", "facebook_post",
                             "banner", "business_card", "flyer", "menu", "poster"],
                    "description": "Tipo de design",
                },
                "title": {"type": "string", "description": "Titulo/headline principal"},
                "subtitle": {"type": "string", "description": "Subtitulo ou descricao"},
                "business_name": {"type": "string", "description": "Nome do negocio"},
                "phone": {"type": "string", "description": "Telefone (opcional)"},
                "colors": {"type": "string", "description": "Cores principais (ex: #FF6B00, #1a1a2e). Opcional."},
                "style": {
                    "type": "string",
                    "enum": ["moderno", "elegante", "minimalista", "bold", "tech", "organico", "luxo"],
                    "description": "Estilo visual",
                },
                "items": {"type": "array", "items": {"type": "string"}, "description": "Lista de itens (ex: pratos do menu, servicos)"},
                "cta": {"type": "string", "description": "Call to action (ex: Peca agora!, Saiba mais)"},
            },
            "required": ["design_type", "title", "business_name"],
        }

    def execute(self, **kwargs: Any) -> str:
        import os, time, hashlib
        dtype = kwargs["design_type"]
        title = kwargs["title"]
        subtitle = kwargs.get("subtitle", "")
        biz = kwargs["business_name"]
        phone = kwargs.get("phone", "")
        colors = kwargs.get("colors", "").split(",") if kwargs.get("colors") else []
        style = kwargs.get("style", "moderno")
        items = kwargs.get("items", [])
        cta = kwargs.get("cta", "")

        # Size configs
        sizes = {
            "instagram_post": ("1080px", "1080px"),
            "instagram_story": ("1080px", "1920px"),
            "facebook_post": ("1200px", "630px"),
            "banner": ("1920px", "600px"),
            "business_card": ("1050px", "600px"),
            "flyer": ("1080px", "1520px"),
            "menu": ("1080px", "1520px"),
            "poster": ("1080px", "1520px"),
        }
        w, h = sizes.get(dtype, ("1080px", "1080px"))

        # Color schemes
        schemes = {
            "moderno": ("#6C5CE7", "#0D0D1A", "#FFFFFF", "#A29BFE"),
            "elegante": ("#C9A84C", "#1A1A1A", "#FFFFFF", "#E8D9A0"),
            "minimalista": ("#333333", "#FFFFFF", "#000000", "#999999"),
            "bold": ("#FF6B35", "#1A1A2E", "#FFFFFF", "#FF9F1C"),
            "tech": ("#00D2FF", "#0A0A1A", "#FFFFFF", "#7B2FF7"),
            "organico": ("#2D6A4F", "#FEFAE0", "#1B4332", "#95D5B2"),
            "luxo": ("#D4AF37", "#0D0D0D", "#FFFFFF", "#B8860B"),
        }
        c1, c2, c3, c4 = schemes.get(style, schemes["moderno"])
        if len(colors) >= 2:
            c1, c2 = colors[0].strip(), colors[1].strip()

        items_html = ""
        if items:
            items_html = "".join([f'<div style="padding:8px 0;border-bottom:1px solid {c1}33;font-size:18px">{it}</div>' for it in items])

        phone_html = f'<div style="margin-top:12px;font-size:16px;opacity:.8">{phone}</div>' if phone else ""
        cta_html = f'<div style="margin-top:20px;display:inline-block;padding:14px 32px;background:{c1};color:{c3};border-radius:30px;font-weight:700;font-size:18px">{cta}</div>' if cta else ""
        sub_html = f'<div style="font-size:20px;opacity:.85;margin-top:8px;max-width:80%">{subtitle}</div>' if subtitle else ""

        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:{w};height:{h};background:{c2};color:{c3};font-family:'Inter',sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:60px;overflow:hidden;position:relative}}
body::before{{content:'';position:absolute;top:-50%;right:-50%;width:100%;height:100%;background:radial-gradient(circle,{c1}22 0%,transparent 70%);pointer-events:none}}
body::after{{content:'';position:absolute;bottom:-30%;left:-30%;width:80%;height:80%;background:radial-gradient(circle,{c4}15 0%,transparent 60%);pointer-events:none}}
h1{{font-size:48px;font-weight:800;line-height:1.1;position:relative;z-index:1}}
.biz{{font-size:14px;letter-spacing:4px;text-transform:uppercase;opacity:.6;margin-bottom:20px;position:relative;z-index:1}}
.accent{{color:{c1}}}
.items{{text-align:left;width:80%;margin:20px auto;position:relative;z-index:1}}
</style></head><body>
<div class="biz">{biz}</div>
<h1>{title.replace(' ', ' <span class="accent">',1).replace(' ', '</span> ',1) if ' ' in title else f'<span class="accent">{title}</span>'}</h1>
{sub_html}
<div class="items">{items_html}</div>
{cta_html}
{phone_html}
</body></html>"""

        # Save to static/files
        static_dir = "/root/clow/static/files"
        os.makedirs(static_dir, exist_ok=True)
        fname = f"design_{dtype}_{int(time.time())}.html"
        fpath = os.path.join(static_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(html)

        url = f"https://clow.pvcorretor01.com.br/static/files/{fname}"
        return (f"Design criado!\n\n"
                f"Abrir: {url}\n\n"
                f"Tipo: {dtype} ({w} x {h})\n"
                f"Estilo: {style}\n\n"
                f"Clique em 'Abrir' para visualizar. Para salvar como imagem:\n"
                f"1. Abra o link\n"
                f"2. Clique com botao direito > Salvar como imagem\n"
                f"3. Ou use Print Screen / screenshot\n\n"
                f"Quer que eu ajuste cores, textos ou crie mais materiais?")
