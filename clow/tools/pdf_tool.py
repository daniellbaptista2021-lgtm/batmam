"""PDF Tool — cria, lê e manipula PDFs."""

from __future__ import annotations
import os
import subprocess
from typing import Any
from .base import BaseTool


class PdfTool(BaseTool):
    name = "pdf_tool"
    description = "Cria, lê e manipula PDFs. Ações: create_from_html, extract_text, merge, split."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create_from_html", "extract_text", "merge", "split", "info"],
                    "description": "Ação a executar",
                },
                "input_path": {"type": "string", "description": "Caminho do arquivo de entrada (HTML ou PDF)"},
                "output_path": {"type": "string", "description": "Caminho do arquivo de saída"},
                "html_content": {"type": "string", "description": "HTML string para criar PDF (alternativa a input_path)"},
                "pages": {"type": "string", "description": "Range de páginas para split (ex: '1-3,5')"},
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de arquivos PDF para merge",
                },
            },
            "required": ["action"],
        }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "")
        input_path = kwargs.get("input_path", "")
        output_path = kwargs.get("output_path", "")
        html_content = kwargs.get("html_content", "")

        if action == "create_from_html":
            return self._create_from_html(input_path, output_path, html_content)
        elif action == "extract_text":
            return self._extract_text(input_path)
        elif action == "merge":
            files = kwargs.get("files", [])
            return self._merge(files, output_path)
        elif action == "split":
            pages = kwargs.get("pages", "")
            return self._split(input_path, output_path, pages)
        elif action == "info":
            return self._info(input_path)
        return f"Ação '{action}' não reconhecida."

    def _create_from_html(self, input_path: str, output_path: str, html_content: str) -> str:
        output_path = output_path or "output.pdf"

        # Se tem html_content, salva em arquivo temporário
        if html_content:
            tmp_html = "/tmp/clow_pdf_input.html"
            with open(tmp_html, "w", encoding="utf-8") as f:
                f.write(html_content)
            input_path = tmp_html
        elif not input_path:
            return "Erro: input_path ou html_content é obrigatório."

        # Tenta weasyprint primeiro
        try:
            import weasyprint
            doc = weasyprint.HTML(filename=input_path)
            doc.write_pdf(output_path)
            return f"PDF criado: {output_path}"
        except ImportError:
            pass

        # Tenta pdfkit/wkhtmltopdf
        try:
            result = subprocess.run(
                f"wkhtmltopdf {input_path} {output_path}",
                shell=True, capture_output=True, text=True, timeout=30,
            )
            if os.path.exists(output_path):
                size = os.path.getsize(output_path)
                return f"PDF criado: {output_path} ({size} bytes)"
            return f"Erro wkhtmltopdf: {result.stderr[:500]}"
        except FileNotFoundError:
            pass

        return "Erro: instale weasyprint ou wkhtmltopdf para criar PDFs."

    def _extract_text(self, input_path: str) -> str:
        if not input_path:
            return "Erro: input_path é obrigatório."

        # Tenta pdfplumber
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(input_path) as pdf:
                for i, page in enumerate(pdf.pages[:50], 1):
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        text_parts.append(f"--- Página {i} ---\n{page_text}")
            return "\n\n".join(text_parts) if text_parts else "(PDF sem texto extraível)"
        except ImportError:
            pass

        # Fallback: pdftotext CLI
        try:
            result = subprocess.run(
                f"pdftotext {input_path} -", shell=True, capture_output=True, text=True, timeout=30,
            )
            return result.stdout[:10000] if result.stdout else "(sem texto)"
        except Exception:
            pass

        return "Erro: instale pdfplumber (pip install pdfplumber) para extrair texto."

    def _merge(self, files: list[str], output_path: str) -> str:
        if len(files) < 2:
            return "Erro: precisa de pelo menos 2 arquivos para merge."
        output_path = output_path or "merged.pdf"

        # Tenta pypdf
        try:
            from pypdf import PdfMerger
            merger = PdfMerger()
            for f in files:
                merger.append(f)
            merger.write(output_path)
            merger.close()
            return f"PDFs merged: {output_path}"
        except ImportError:
            pass

        # Fallback: pdftk ou ghostscript
        files_str = " ".join(files)
        try:
            result = subprocess.run(
                f"pdfunite {files_str} {output_path}",
                shell=True, capture_output=True, text=True, timeout=30,
            )
            if os.path.exists(output_path):
                return f"PDFs merged: {output_path}"
            return f"Erro: {result.stderr[:500]}"
        except Exception as e:
            return f"Erro merge: {e}"

    def _split(self, input_path: str, output_path: str, pages: str) -> str:
        if not input_path or not pages:
            return "Erro: input_path e pages são obrigatórios."
        output_path = output_path or "split.pdf"

        try:
            from pypdf import PdfReader, PdfWriter
            reader = PdfReader(input_path)
            writer = PdfWriter()

            for part in pages.split(","):
                part = part.strip()
                if "-" in part:
                    start, end = part.split("-")
                    for i in range(int(start) - 1, min(int(end), len(reader.pages))):
                        writer.add_page(reader.pages[i])
                else:
                    idx = int(part) - 1
                    if 0 <= idx < len(reader.pages):
                        writer.add_page(reader.pages[idx])

            writer.write(output_path)
            return f"PDF split: {output_path} ({len(writer.pages)} páginas)"
        except ImportError:
            return "Erro: instale pypdf (pip install pypdf) para split."
        except Exception as e:
            return f"Erro split: {e}"

    def _info(self, input_path: str) -> str:
        if not input_path:
            return "Erro: input_path é obrigatório."
        try:
            from pypdf import PdfReader
            reader = PdfReader(input_path)
            info = reader.metadata
            return (
                f"Arquivo: {input_path}\n"
                f"Páginas: {len(reader.pages)}\n"
                f"Título: {info.title if info else 'N/A'}\n"
                f"Autor: {info.author if info else 'N/A'}"
            )
        except ImportError:
            return "Erro: instale pypdf."
        except Exception as e:
            return f"Erro: {e}"
