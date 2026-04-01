"""Ferramenta Read v0.2.0 — lê arquivos, imagens (base64) e PDFs."""

from __future__ import annotations
import base64
import mimetypes
from pathlib import Path
from typing import Any
from .base import BaseTool

# Extensões de imagem suportadas
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"}

# Extensões de PDF
PDF_EXTENSIONS = {".pdf"}


class ReadTool(BaseTool):
    name = "read"
    description = (
        "Lê o conteúdo de um arquivo. Retorna com números de linha. "
        "Suporta offset e limit para arquivos grandes. "
        "Suporta imagens (retorna base64) e PDFs (extrai texto)."
    )
    requires_confirmation = False

    MAX_LINES = 2000

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Caminho absoluto ou relativo do arquivo.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Linha inicial (0-indexed). Padrão: 0.",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Número máximo de linhas. Padrão: {self.MAX_LINES}.",
                },
                "pages": {
                    "type": "string",
                    "description": "Range de páginas para PDFs (ex: '1-5', '3'). Máx 20 páginas.",
                },
            },
            "required": ["file_path"],
        }

    def execute(self, **kwargs: Any) -> str:
        file_path = kwargs.get("file_path", "")
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit", self.MAX_LINES)
        pages = kwargs.get("pages", "")

        if not file_path:
            return "[ERROR] file_path é obrigatório."

        path = Path(file_path).expanduser().resolve()

        if not path.exists():
            return f"[ERROR] Arquivo não encontrado: {path}"

        if not path.is_file():
            return f"[ERROR] Não é um arquivo: {path}"

        suffix = path.suffix.lower()

        # Imagens → base64
        if suffix in IMAGE_EXTENSIONS:
            return self._read_image(path)

        # PDFs → extração de texto
        if suffix in PDF_EXTENSIONS:
            return self._read_pdf(path, pages)

        # Texto normal
        return self._read_text(path, offset, limit)

    def _read_text(self, path: Path, offset: int, limit: int) -> str:
        """Lê arquivo de texto com números de linha."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"[ERROR] Não foi possível ler: {e}"

        lines = text.splitlines()
        total = len(lines)
        selected = lines[offset: offset + limit]

        numbered = []
        for i, line in enumerate(selected, start=offset + 1):
            numbered.append(f"{i:>6}\t{line}")

        result = "\n".join(numbered)

        if offset + limit < total:
            result += f"\n\n... [{total - offset - limit} linhas restantes]"

        return result

    def _read_image(self, path: Path) -> str:
        """Lê imagem e retorna base64 para o modelo processar."""
        try:
            data = path.read_bytes()
            b64 = base64.b64encode(data).decode("ascii")
            mime = mimetypes.guess_type(str(path))[0] or "image/png"
            size_kb = len(data) / 1024

            return (
                f"[IMAGEM] {path.name} ({size_kb:.1f} KB, {mime})\n"
                f"data:{mime};base64,{b64[:100]}...\n"
                f"(Imagem carregada com sucesso — {len(b64)} chars base64)"
            )
        except Exception as e:
            return f"[ERROR] Falha ao ler imagem: {e}"

    def _read_pdf(self, path: Path, pages: str = "") -> str:
        """Lê PDF extraindo texto. Tenta pdfplumber > PyMuPDF > pdftotext."""
        page_range = self._parse_page_range(pages)

        # Tenta pdfplumber
        text = self._try_pdfplumber(path, page_range)
        if text:
            return text

        # Tenta PyMuPDF (fitz)
        text = self._try_pymupdf(path, page_range)
        if text:
            return text

        # Tenta pdftotext (cli)
        text = self._try_pdftotext(path, page_range)
        if text:
            return text

        return (
            "[ERROR] Não foi possível ler o PDF. "
            "Instale: pip install pdfplumber (ou PyMuPDF)"
        )

    def _try_pdfplumber(self, path: Path, page_range: tuple[int, int] | None) -> str:
        """Tenta extrair texto com pdfplumber."""
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                total_pages = len(pdf.pages)
                start, end = self._resolve_range(page_range, total_pages)

                texts = []
                for i in range(start, end):
                    page = pdf.pages[i]
                    text = page.extract_text() or ""
                    if text:
                        texts.append(f"--- Página {i + 1} ---\n{text}")

                if not texts:
                    return f"[PDF] {path.name} ({total_pages} páginas) — sem texto extraível"
                return f"[PDF] {path.name} ({total_pages} páginas, mostrando {start+1}-{end})\n\n" + "\n\n".join(texts)
        except ImportError:
            return ""
        except Exception as e:
            return f"[ERROR] pdfplumber: {e}"

    def _try_pymupdf(self, path: Path, page_range: tuple[int, int] | None) -> str:
        """Tenta extrair texto com PyMuPDF."""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(path))
            total_pages = len(doc)
            start, end = self._resolve_range(page_range, total_pages)

            texts = []
            for i in range(start, end):
                page = doc[i]
                text = page.get_text()
                if text.strip():
                    texts.append(f"--- Página {i + 1} ---\n{text}")
            doc.close()

            if not texts:
                return f"[PDF] {path.name} ({total_pages} páginas) — sem texto extraível"
            return f"[PDF] {path.name} ({total_pages} páginas, mostrando {start+1}-{end})\n\n" + "\n\n".join(texts)
        except ImportError:
            return ""
        except Exception as e:
            return f"[ERROR] PyMuPDF: {e}"

    def _try_pdftotext(self, path: Path, page_range: tuple[int, int] | None) -> str:
        """Tenta extrair texto com pdftotext CLI."""
        try:
            import subprocess
            args = ["pdftotext"]
            if page_range:
                args.extend(["-f", str(page_range[0] + 1), "-l", str(page_range[1])])
            args.extend([str(path), "-"])
            result = subprocess.run(args, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                return f"[PDF] {path.name}\n\n{result.stdout}"
            return ""
        except (FileNotFoundError, Exception):
            return ""

    @staticmethod
    def _parse_page_range(pages: str) -> tuple[int, int] | None:
        """Converte string de range para (start, end) 0-indexed."""
        if not pages:
            return None
        pages = pages.strip()
        if "-" in pages:
            parts = pages.split("-", 1)
            try:
                return (int(parts[0]) - 1, int(parts[1]))
            except ValueError:
                return None
        try:
            p = int(pages)
            return (p - 1, p)
        except ValueError:
            return None

    @staticmethod
    def _resolve_range(
        page_range: tuple[int, int] | None, total: int
    ) -> tuple[int, int]:
        """Resolve range para valores válidos."""
        if page_range:
            start = max(0, page_range[0])
            end = min(total, page_range[1])
            # Limita a 20 páginas
            if end - start > 20:
                end = start + 20
            return (start, end)
        # Default: primeiras 20 páginas
        return (0, min(total, 20))
