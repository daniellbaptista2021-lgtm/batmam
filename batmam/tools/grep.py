"""GrepTool avançado — busca com poder de ripgrep.

Features: content/files/count modes, context lines (-A/-B/-C),
multiline, case insensitive, filtro por tipo, paginação.
"""

from __future__ import annotations
import re
import os
import fnmatch
from typing import Any
from .base import BaseTool

FILE_TYPES = {
    "py": ["*.py"], "js": ["*.js", "*.jsx", "*.mjs"], "ts": ["*.ts", "*.tsx"],
    "rust": ["*.rs"], "go": ["*.go"], "java": ["*.java"], "c": ["*.c", "*.h"],
    "cpp": ["*.cpp", "*.cc", "*.cxx", "*.hpp"], "rb": ["*.rb"],
    "php": ["*.php"], "swift": ["*.swift"], "kt": ["*.kt"],
    "sh": ["*.sh", "*.bash"], "yaml": ["*.yml", "*.yaml"],
    "json": ["*.json"], "md": ["*.md"], "html": ["*.html", "*.htm"],
    "css": ["*.css", "*.scss", "*.less"], "sql": ["*.sql"],
    "xml": ["*.xml"], "toml": ["*.toml"],
}

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".next", ".nuxt", "target", "vendor", ".cargo",
    "coverage", ".coverage", ".eggs",
}


class GrepTool(BaseTool):
    name = "grep"
    description = (
        "Busca regex em arquivos. Modos: content (linhas), files_with_matches (paths), count. "
        "Suporta context (-A/-B/-C), case insensitive (-i), filtro por tipo/glob, "
        "multiline, paginação (head_limit/offset), line numbers (-n)."
    )
    requires_confirmation = False

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern para buscar"},
                "path": {"type": "string", "description": "Arquivo ou diretório (padrão: cwd)"},
                "output_mode": {
                    "type": "string", "enum": ["content", "files_with_matches", "count"],
                    "description": "Modo de output. Padrão: files_with_matches",
                },
                "glob": {"type": "string", "description": "Glob pattern para filtrar (ex: '*.py')"},
                "type": {"type": "string", "description": "Tipo de arquivo: py, js, ts, go, rust, etc."},
                "-i": {"type": "boolean", "description": "Case insensitive"},
                "-n": {"type": "boolean", "description": "Mostrar line numbers (padrão: true)"},
                "-A": {"type": "integer", "description": "Linhas depois de cada match"},
                "-B": {"type": "integer", "description": "Linhas antes de cada match"},
                "-C": {"type": "integer", "description": "Context (antes e depois)"},
                "context": {"type": "integer", "description": "Alias para -C"},
                "multiline": {"type": "boolean", "description": "Matching multiline"},
                "head_limit": {"type": "integer", "description": "Limitar a N resultados (padrão: 250)"},
                "offset": {"type": "integer", "description": "Pular N primeiros resultados"},
            },
            "required": ["pattern"],
        }

    def execute(self, **kwargs: Any) -> str:
        pattern_str: str = kwargs.get("pattern", "")
        if not pattern_str:
            return "Erro: pattern é obrigatório."

        path: str = kwargs.get("path", os.getcwd())
        output_mode: str = kwargs.get("output_mode", "files_with_matches")
        glob_pattern: str = kwargs.get("glob", "")
        file_type: str = kwargs.get("type", "")
        case_insensitive: bool = kwargs.get("-i", False)
        show_ln: bool = kwargs.get("-n", True)
        after_ctx: int = kwargs.get("-A", 0)
        before_ctx: int = kwargs.get("-B", 0)
        context: int = kwargs.get("-C", kwargs.get("context", 0))
        multiline: bool = kwargs.get("multiline", False)
        head_limit: int = kwargs.get("head_limit", 250)
        offset: int = kwargs.get("offset", 0)

        if context > 0:
            after_ctx = max(after_ctx, context)
            before_ctx = max(before_ctx, context)

        flags = re.IGNORECASE if case_insensitive else 0
        if multiline:
            flags |= re.DOTALL | re.MULTILINE
        try:
            regex = re.compile(pattern_str, flags)
        except re.error as e:
            return f"Regex inválido: {e}"

        type_exts: set[str] = set()
        if file_type and file_type in FILE_TYPES:
            for ep in FILE_TYPES[file_type]:
                type_exts.add(ep.replace("*", ""))

        target = os.path.abspath(path)
        files: list[str] = []

        if os.path.isfile(target):
            files = [target]
        elif os.path.isdir(target):
            for root, dirs, fnames in os.walk(target):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
                for fname in fnames:
                    if type_exts and not any(fname.endswith(ext) for ext in type_exts):
                        continue
                    if glob_pattern and not fnmatch.fnmatch(fname, glob_pattern):
                        continue
                    files.append(os.path.join(root, fname))
        else:
            return f"Path não encontrado: {path}"

        if output_mode == "files_with_matches":
            return self._files_mode(files, regex, target, head_limit, offset)
        elif output_mode == "count":
            return self._count_mode(files, regex, target, head_limit, offset)
        else:
            return self._content_mode(files, regex, target, show_ln, before_ctx, after_ctx, head_limit, offset, multiline)

    def _files_mode(self, files, regex, base, limit, offset) -> str:
        matched = []
        for fp in sorted(files):
            try:
                content = open(fp, "r", encoding="utf-8", errors="ignore").read()
                if regex.search(content):
                    rel = os.path.relpath(fp, base) if os.path.isdir(base) else fp
                    matched.append(rel)
            except Exception:
                continue
        total = len(matched)
        results = matched[offset:offset + limit]
        out = "\n".join(results)
        if total > offset + limit:
            out += f"\n\n... {total - offset - limit} mais arquivos"
        return out or "Nenhum arquivo encontrado."

    def _count_mode(self, files, regex, base, limit, offset) -> str:
        counts = []
        for fp in sorted(files):
            try:
                content = open(fp, "r", encoding="utf-8", errors="ignore").read()
                n = len(regex.findall(content))
                if n:
                    rel = os.path.relpath(fp, base) if os.path.isdir(base) else fp
                    counts.append((rel, n))
            except Exception:
                continue
        total = len(counts)
        results = counts[offset:offset + limit]
        lines = [f"{p}: {c}" for p, c in results]
        total_m = sum(c for _, c in counts)
        out = "\n".join(lines) + f"\n\nTotal: {total_m} matches em {total} arquivos"
        return out if results else "Nenhum match encontrado."

    def _content_mode(self, files, regex, base, show_ln, before, after, limit, offset, multiline) -> str:
        results: list[str] = []
        total_matches = 0

        for fp in sorted(files):
            try:
                lines = open(fp, "r", encoding="utf-8", errors="ignore").readlines()
            except Exception:
                continue
            rel = os.path.relpath(fp, base) if os.path.isdir(base) else fp
            file_res: list[str] = []

            if multiline:
                content = "".join(lines)
                for m in regex.finditer(content):
                    ln = content[:m.start()].count("\n") + 1
                    txt = m.group()[:200]
                    file_res.append(f"{rel}:{ln}: {txt}" if show_ln else f"{rel}: {txt}")
                    total_matches += 1
            else:
                matched_lines: set[int] = set()
                for i, line in enumerate(lines):
                    if regex.search(line):
                        matched_lines.add(i)
                        total_matches += 1
                ctx_lines: set[int] = set()
                for i in matched_lines:
                    for j in range(max(0, i - before), min(len(lines), i + after + 1)):
                        ctx_lines.add(j)
                prev = -2
                for i in sorted(ctx_lines):
                    if i > prev + 1 and prev >= 0:
                        file_res.append("--")
                    text = lines[i].rstrip("\n")
                    prefix = ">" if i in matched_lines else " "
                    file_res.append(f"{rel}:{i+1}:{prefix} {text}" if show_ln else f"{rel}:{prefix} {text}")
                    prev = i

            if file_res:
                results.extend(file_res)
                results.append("")

        total_lines = len(results)
        results = results[offset:offset + limit]
        out = "\n".join(results).rstrip()
        if not out:
            return "Nenhum match encontrado."
        out += f"\n\n[{total_matches} matches]"
        if total_lines > offset + limit:
            out += f" ({total_lines - offset - limit} linhas omitidas)"
        return out
