"""Canva Design Tools — cria e gerencia designs profissionais via Canva API."""

from __future__ import annotations
import json
import urllib.request
import urllib.error
from typing import Any
from .base import BaseTool

CANVA_API = "https://api.canva.com/rest/v1"


def _canva_request(path: str, method: str = "GET", data: dict = None, token: str = "") -> dict:
    """Request autenticado na Canva Connect API."""
    from .. import config
    api_token = token or getattr(config, "CANVA_API_TOKEN", "")
    if not api_token:
        return {"error": "CANVA_API_TOKEN nao configurado. Adicione no .env"}
    url = f"{CANVA_API}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode() if data else None
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if e.fp else str(e)
        return {"error": f"Canva API {e.code}: {err_body[:200]}"}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════
# DESIGN CREATION
# ═══════════════════════════════════════════════════

class CanvaCreateDesignTool(BaseTool):
    name = "canva_create_design"
    description = "Cria um novo design no Canva a partir de um tipo (poster, presentation, social_media, etc)."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Titulo do design"},
                "design_type": {
                    "type": "string",
                    "enum": ["doc", "whiteboard", "presentation", "instagram_post", "instagram_story",
                             "facebook_post", "poster", "flyer", "logo", "business_card",
                             "youtube_thumbnail", "twitter_post", "linkedin_post", "banner",
                             "a4_document", "custom"],
                    "description": "Tipo de design",
                },
                "width": {"type": "integer", "description": "Largura em px (apenas se custom)"},
                "height": {"type": "integer", "description": "Altura em px (apenas se custom)"},
            },
            "required": ["title", "design_type"],
        }

    def execute(self, **kwargs: Any) -> str:
        dt = kwargs["design_type"]
        data = {"title": kwargs["title"]}
        # Map friendly names to Canva design types
        type_map = {
            "instagram_post": {"width": 1080, "height": 1080},
            "instagram_story": {"width": 1080, "height": 1920},
            "facebook_post": {"width": 1200, "height": 630},
            "poster": {"width": 1080, "height": 1520},
            "flyer": {"width": 1080, "height": 1520},
            "logo": {"width": 500, "height": 500},
            "business_card": {"width": 1050, "height": 600},
            "youtube_thumbnail": {"width": 1280, "height": 720},
            "twitter_post": {"width": 1200, "height": 675},
            "linkedin_post": {"width": 1200, "height": 627},
            "banner": {"width": 1920, "height": 1080},
            "a4_document": {"width": 595, "height": 842},
            "custom": {"width": kwargs.get("width", 1080), "height": kwargs.get("height", 1080)},
        }
        if dt in type_map:
            data["design_type"] = {"type": "custom", **type_map[dt]}
        elif dt in ("doc", "whiteboard", "presentation"):
            data["design_type"] = {"type": dt}
        else:
            data["design_type"] = {"type": "custom", "width": 1080, "height": 1080}

        result = _canva_request("designs", method="POST", data=data)
        if result.get("error"):
            return f"Erro: {result['error']}"
        design = result.get("design", result)
        did = design.get("id", "?")
        url = design.get("urls", {}).get("edit_url", "")
        return f"Design criado! ID: {did}\nEditar: {url}"


class CanvaSearchTemplatesTool(BaseTool):
    name = "canva_search_templates"
    description = "Busca templates prontos no Canva por palavra-chave."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Termo de busca (ex: pizzaria, imobiliaria, fitness)"},
                "limit": {"type": "integer", "description": "Quantidade (default: 5)"},
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> str:
        limit = kwargs.get("limit", 5)
        result = _canva_request(f"designs/search?query={kwargs['query']}&limit={limit}")
        if result.get("error"):
            return f"Erro: {result['error']}"
        items = result.get("items", result.get("data", []))
        if not items:
            return "Nenhum template encontrado."
        lines = []
        for t in items[:limit]:
            lines.append(f"- {t.get('title', '?')} (id: {t.get('id', '?')})")
        return f"Templates ({len(lines)}):\n" + "\n".join(lines)


class CanvaGetDesignTool(BaseTool):
    name = "canva_get_design"
    description = "Obtem detalhes de um design pelo ID."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "design_id": {"type": "string", "description": "ID do design"},
            },
            "required": ["design_id"],
        }

    def execute(self, **kwargs: Any) -> str:
        result = _canva_request(f"designs/{kwargs['design_id']}")
        if result.get("error"):
            return f"Erro: {result['error']}"
        d = result.get("design", result)
        title = d.get("title", "?")
        pages = d.get("page_count", "?")
        url = d.get("urls", {}).get("edit_url", "")
        view = d.get("urls", {}).get("view_url", "")
        return f"Design: {title}\nPaginas: {pages}\nEditar: {url}\nVisualizar: {view}"


class CanvaExportDesignTool(BaseTool):
    name = "canva_export_design"
    description = "Exporta um design como PNG, PDF ou MP4."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "design_id": {"type": "string", "description": "ID do design"},
                "format": {
                    "type": "string",
                    "enum": ["png", "jpg", "pdf", "mp4", "gif", "pptx"],
                    "description": "Formato de exportacao",
                },
                "quality": {"type": "string", "enum": ["low", "medium", "high"], "description": "Qualidade (default: high)"},
            },
            "required": ["design_id", "format"],
        }

    def execute(self, **kwargs: Any) -> str:
        data = {
            "design_id": kwargs["design_id"],
            "format": {"type": kwargs["format"]},
        }
        if kwargs.get("quality"):
            data["format"]["quality"] = kwargs["quality"]
        result = _canva_request("exports", method="POST", data=data)
        if result.get("error"):
            return f"Erro: {result['error']}"
        export = result.get("export", result)
        status = export.get("status", "?")
        eid = export.get("id", "?")
        if status == "completed":
            urls = export.get("urls", [])
            return f"Exportado! URLs:\n" + "\n".join(urls)
        return f"Exportacao iniciada (id: {eid}, status: {status}). Use canva_check_export para verificar."


class CanvaCheckExportTool(BaseTool):
    name = "canva_check_export"
    description = "Verifica status de uma exportacao do Canva."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "export_id": {"type": "string", "description": "ID da exportacao"},
            },
            "required": ["export_id"],
        }

    def execute(self, **kwargs: Any) -> str:
        result = _canva_request(f"exports/{kwargs['export_id']}")
        if result.get("error"):
            return f"Erro: {result['error']}"
        export = result.get("export", result)
        status = export.get("status", "?")
        if status == "completed":
            urls = export.get("urls", [])
            return f"Exportacao concluida! URLs:\n" + "\n".join([u.get("url", u) if isinstance(u, dict) else str(u) for u in urls])
        return f"Status: {status}"


class CanvaListBrandKitsTool(BaseTool):
    name = "canva_list_brand_kits"
    description = "Lista brand kits (cores, fontes, logos da marca) do usuario no Canva."

    def get_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs: Any) -> str:
        result = _canva_request("brand-templates")
        if result.get("error"):
            return f"Erro: {result['error']}"
        items = result.get("items", result.get("data", []))
        if not items:
            return "Nenhum brand kit encontrado."
        lines = [f"- {b.get('title', b.get('name', '?'))} (id: {b.get('id', '?')})" for b in items[:10]]
        return f"Brand Kits ({len(lines)}):\n" + "\n".join(lines)


class CanvaUploadAssetTool(BaseTool):
    name = "canva_upload_asset"
    description = "Faz upload de um asset (imagem, logo) para o Canva via URL."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do asset"},
                "url": {"type": "string", "description": "URL publica da imagem"},
            },
            "required": ["name", "url"],
        }

    def execute(self, **kwargs: Any) -> str:
        data = {
            "name": kwargs["name"],
            "url": kwargs["url"],
        }
        result = _canva_request("assets/upload", method="POST", data=data)
        if result.get("error"):
            return f"Erro: {result['error']}"
        asset = result.get("asset", result)
        return f"Asset '{kwargs['name']}' enviado! ID: {asset.get('id', '?')}"


class CanvaListDesignsTool(BaseTool):
    name = "canva_list_designs"
    description = "Lista designs recentes do usuario no Canva."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Quantidade (default: 10)"},
            },
            "required": [],
        }

    def execute(self, **kwargs: Any) -> str:
        limit = kwargs.get("limit", 10)
        result = _canva_request(f"designs?limit={limit}")
        if result.get("error"):
            return f"Erro: {result['error']}"
        items = result.get("items", result.get("data", []))
        if not items:
            return "Nenhum design encontrado."
        lines = []
        for d in items[:limit]:
            title = d.get("title", "Sem titulo")
            did = d.get("id", "?")
            lines.append(f"- {title} (id: {did})")
        return f"Designs ({len(lines)}):\n" + "\n".join(lines)
