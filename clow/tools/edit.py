"""Ferramenta Edit v0.2.0 — edição cirúrgica com diff visual colorido."""

from __future__ import annotations
import difflib
from pathlib import Path
from typing import Any
from .base import BaseTool


class EditTool(BaseTool):
    name = "edit"
    description = (
        "Faz substituição exata de texto em um arquivo. "
        "Encontra old_string e substitui por new_string. "
        "O old_string deve ser único no arquivo para evitar edições ambíguas. "
        "Retorna diff visual colorido mostrando as mudanças."
    )
    requires_confirmation = True

    # Behavioral flags (Claude Code Ep.02)
    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = False
    _search_hint = "file edit replace modify"
    _aliases = ["Edit", "sed"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Caminho absoluto do arquivo a ser editado.",
                },
                "old_string": {
                    "type": "string",
                    "description": "Texto exato a ser encontrado e substituído.",
                },
                "new_string": {
                    "type": "string",
                    "description": "Texto que substituirá o old_string.",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Se true, substitui TODAS as ocorrências. Padrão: false.",
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        }

    def execute(self, **kwargs: Any) -> str:
        file_path = kwargs.get("file_path", "")
        old_string = kwargs.get("old_string", "")
        new_string = kwargs.get("new_string", "")
        replace_all = kwargs.get("replace_all", False)

        if not file_path:
            return "[ERROR] file_path é obrigatório."
        if not old_string:
            return "[ERROR] old_string é obrigatório."
        if old_string == new_string:
            return "[ERROR] old_string e new_string são iguais."

        path = Path(file_path).expanduser().resolve()

        if not path.exists():
            return f"[ERROR] Arquivo não encontrado: {path}"

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return f"[ERROR] Não foi possível ler: {e}"

        count = content.count(old_string)

        if count == 0:
            return "[ERROR] old_string não encontrado no arquivo."

        if count > 1 and not replace_all:
            return (
                f"[ERROR] old_string encontrado {count} vezes. "
                f"Use replace_all=true ou forneça contexto mais específico."
            )

        if replace_all:
            new_content = content.replace(old_string, new_string)
            replaced = count
        else:
            new_content = content.replace(old_string, new_string, 1)
            replaced = 1

        # Gera diff visual antes de escrever
        diff_text = self._generate_diff(content, new_content, str(path))

        try:
            path.write_text(new_content, encoding="utf-8")
            result = f"Editado {path}: {replaced} substituição(ões) feita(s)."
            if diff_text:
                result += f"\n\n{diff_text}"
            return result
        except Exception as e:
            return f"[ERROR] Falha ao escrever: {e}"

    @staticmethod
    def _generate_diff(old_content: str, new_content: str, filepath: str) -> str:
        """Gera unified diff visual das mudanças."""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{filepath}",
            tofile=f"b/{filepath}",
            lineterm="",
        )

        diff_lines = list(diff)
        if not diff_lines:
            return ""

        # Limita o diff para não poluir o contexto
        if len(diff_lines) > 50:
            diff_lines = diff_lines[:50]
            diff_lines.append(f"\n... (diff truncado, {len(diff_lines)} linhas total)")

        return "```diff\n" + "".join(diff_lines) + "\n```"
