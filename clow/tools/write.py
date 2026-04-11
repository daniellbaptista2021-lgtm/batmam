"""Ferramenta Write - cria/sobrescreve arquivos."""

from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import BaseTool


class WriteTool(BaseTool):
    name = "write"
    description = (
        "Cria um novo arquivo ou sobrescreve um existente com o conteúdo fornecido. "
        "Cria diretórios pai automaticamente se necessário."
    )
    requires_confirmation = True

    # Behavioral flags (Claude Code Ep.02)
    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = True
    _search_hint = "file write create overwrite"
    _aliases = ["Write"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Caminho absoluto do arquivo a ser escrito.",
                },
                "content": {
                    "type": "string",
                    "description": "Conteúdo completo a ser escrito no arquivo.",
                },
            },
            "required": ["file_path", "content"],
        }

    def execute(self, **kwargs: Any) -> str:
        import os
        file_path = kwargs.get("file_path", "")
        content = kwargs.get("content", "")

        if not file_path:
            return "[ERROR] file_path é obrigatório."

        path = Path(file_path).expanduser().resolve()

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)

            # Auto-publish: se for HTML/CSS/JS em /tmp, copia para static/files
            web_url = ""
            suffix = path.suffix.lower()
            if suffix in (".html", ".css", ".js", ".json", ".pdf", ".xlsx"):
                static_dir = Path("/root/clow/static/files")
                static_dir.mkdir(parents=True, exist_ok=True)
                web_path = static_dir / path.name
                if str(path).startswith("/tmp") or not str(path).startswith("/root/clow/static"):
                    import shutil
                    shutil.copy2(str(path), str(web_path))
                domain = os.getenv("CLOW_DOMAIN", "clow.pvcorretor01.com.br")
                web_url = f"\n\nAcessar: https://{domain}/static/files/{path.name}"

            return f"Arquivo escrito: {path} ({lines} linhas){web_url}"
        except Exception as e:
            return f"[ERROR] Falha ao escrever: {e}"
