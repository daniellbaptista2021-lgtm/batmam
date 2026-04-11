"""Ferramenta NotebookEdit — lê e edita Jupyter notebooks (.ipynb)."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from .base import BaseTool


class NotebookEditTool(BaseTool):
    name = "notebook_edit"
    description = (
        "Lê, edita e cria células em Jupyter notebooks (.ipynb). "
        "Operações: read (ler notebook), edit_cell (editar célula), "
        "insert_cell (inserir nova célula), delete_cell (deletar célula), "
        "create (criar notebook novo)."
    )
    requires_confirmation = True

    # Behavioral flags (Claude Code Ep.02)
    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = False
    _search_hint = "jupyter notebook ipynb cell"
    _aliases = ["NotebookEdit", "jupyter"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Caminho do arquivo .ipynb.",
                },
                "operation": {
                    "type": "string",
                    "enum": ["read", "edit_cell", "insert_cell", "delete_cell", "create"],
                    "description": "Operação a realizar.",
                },
                "cell_index": {
                    "type": "integer",
                    "description": "Índice da célula (0-based). Necessário para edit_cell, delete_cell.",
                },
                "cell_type": {
                    "type": "string",
                    "enum": ["code", "markdown", "raw"],
                    "description": "Tipo da célula. Padrão: code.",
                },
                "content": {
                    "type": "string",
                    "description": "Conteúdo da célula (para edit_cell e insert_cell).",
                },
                "insert_after": {
                    "type": "integer",
                    "description": "Inserir célula após este índice. -1 = início. Padrão: final.",
                },
            },
            "required": ["file_path", "operation"],
        }

    def execute(self, **kwargs: Any) -> str:
        file_path = kwargs.get("file_path", "")
        operation = kwargs.get("operation", "")

        if not file_path:
            return "[ERROR] file_path é obrigatório."

        path = Path(file_path).expanduser().resolve()

        if operation == "create":
            return self._create_notebook(path, kwargs)
        elif operation == "read":
            return self._read_notebook(path)
        elif operation == "edit_cell":
            return self._edit_cell(path, kwargs)
        elif operation == "insert_cell":
            return self._insert_cell(path, kwargs)
        elif operation == "delete_cell":
            return self._delete_cell(path, kwargs)
        else:
            return f"[ERROR] Operação desconhecida: {operation}"

    def _read_notebook(self, path: Path) -> str:
        """Lê e formata um notebook para exibição."""
        if not path.exists():
            return f"[ERROR] Arquivo não encontrado: {path}"

        try:
            nb = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            return f"[ERROR] Não foi possível ler notebook: {e}"

        cells = nb.get("cells", [])
        kernel = nb.get("metadata", {}).get("kernelspec", {}).get("display_name", "unknown")

        output = [f"Notebook: {path.name} ({len(cells)} células, kernel: {kernel})\n"]

        for i, cell in enumerate(cells):
            cell_type = cell.get("cell_type", "unknown")
            source = "".join(cell.get("source", []))

            output.append(f"── Cell [{i}] ({cell_type}) ──")
            output.append(source)

            # Outputs para células de código
            if cell_type == "code":
                exec_count = cell.get("execution_count")
                if exec_count is not None:
                    output.append(f"  [execution_count: {exec_count}]")

                for out in cell.get("outputs", []):
                    out_type = out.get("output_type", "")
                    if out_type == "stream":
                        text = "".join(out.get("text", []))
                        output.append(f"  [output] {text[:500]}")
                    elif out_type in ("execute_result", "display_data"):
                        data = out.get("data", {})
                        if "text/plain" in data:
                            text = "".join(data["text/plain"])
                            output.append(f"  [result] {text[:500]}")
                        if "image/png" in data:
                            output.append("  [image: PNG]")
                    elif out_type == "error":
                        ename = out.get("ename", "")
                        evalue = out.get("evalue", "")
                        output.append(f"  [error] {ename}: {evalue}")

            output.append("")

        return "\n".join(output)

    def _edit_cell(self, path: Path, kwargs: dict) -> str:
        """Edita o conteúdo de uma célula."""
        cell_index = kwargs.get("cell_index")
        content = kwargs.get("content", "")

        if cell_index is None:
            return "[ERROR] cell_index é obrigatório para edit_cell."

        nb = self._load(path)
        if isinstance(nb, str):
            return nb

        cells = nb.get("cells", [])
        if cell_index < 0 or cell_index >= len(cells):
            return f"[ERROR] cell_index {cell_index} fora do range (0-{len(cells)-1})."

        # Atualiza
        cells[cell_index]["source"] = content.splitlines(True)
        if kwargs.get("cell_type"):
            cells[cell_index]["cell_type"] = kwargs["cell_type"]

        return self._save(path, nb, f"Célula [{cell_index}] editada.")

    def _insert_cell(self, path: Path, kwargs: dict) -> str:
        """Insere uma nova célula."""
        content = kwargs.get("content", "")
        cell_type = kwargs.get("cell_type", "code")
        insert_after = kwargs.get("insert_after")

        nb = self._load(path)
        if isinstance(nb, str):
            return nb

        cells = nb.get("cells", [])
        new_cell = self._make_cell(cell_type, content)

        if insert_after is None:
            cells.append(new_cell)
            idx = len(cells) - 1
        elif insert_after == -1:
            cells.insert(0, new_cell)
            idx = 0
        else:
            cells.insert(insert_after + 1, new_cell)
            idx = insert_after + 1

        nb["cells"] = cells
        return self._save(path, nb, f"Célula [{idx}] ({cell_type}) inserida.")

    def _delete_cell(self, path: Path, kwargs: dict) -> str:
        """Deleta uma célula."""
        cell_index = kwargs.get("cell_index")
        if cell_index is None:
            return "[ERROR] cell_index é obrigatório para delete_cell."

        nb = self._load(path)
        if isinstance(nb, str):
            return nb

        cells = nb.get("cells", [])
        if cell_index < 0 or cell_index >= len(cells):
            return f"[ERROR] cell_index {cell_index} fora do range."

        removed = cells.pop(cell_index)
        nb["cells"] = cells
        rtype = removed.get("cell_type", "unknown")
        return self._save(path, nb, f"Célula [{cell_index}] ({rtype}) deletada. {len(cells)} restantes.")

    def _create_notebook(self, path: Path, kwargs: dict) -> str:
        """Cria um notebook novo."""
        content = kwargs.get("content", "")
        cell_type = kwargs.get("cell_type", "code")

        nb = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3",
                },
                "language_info": {
                    "name": "python",
                    "version": "3.12.0",
                },
            },
            "cells": [],
        }

        if content:
            nb["cells"].append(self._make_cell(cell_type, content))

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
            return f"Notebook criado: {path}"
        except Exception as e:
            return f"[ERROR] Falha ao criar: {e}"

    def _make_cell(self, cell_type: str, content: str) -> dict:
        cell: dict[str, Any] = {
            "cell_type": cell_type,
            "metadata": {},
            "source": content.splitlines(True),
        }
        if cell_type == "code":
            cell["execution_count"] = None
            cell["outputs"] = []
        return cell

    def _load(self, path: Path) -> dict | str:
        if not path.exists():
            return f"[ERROR] Arquivo não encontrado: {path}"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            return f"[ERROR] Não foi possível ler: {e}"

    def _save(self, path: Path, nb: dict, msg: str) -> str:
        try:
            path.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
            return msg
        except Exception as e:
            return f"[ERROR] Falha ao salvar: {e}"
