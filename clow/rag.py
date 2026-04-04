"""Codebase RAG — indexes project files for intelligent context retrieval.

Uses TF-IDF for zero-dependency search. No external vector DB needed.
"""
import os
import re
import math
import logging
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)

INDEXABLE_EXT = {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".md", ".json", ".yml", ".yaml", ".toml", ".sh", ".sql"}
IGNORE_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".next", "dist", "build", ".claude"}
IGNORE_PATHS = {"skills/imported", "static/files", "static/pages", "static/apps", "static/brand", "static/uploads", "deploy/monitoring"}
MAX_FILE = 100_000
CHUNK_LINES = 40


class CodebaseIndex:
    def __init__(self, root: str = "."):
        self.root = Path(root).resolve()
        self.chunks: list[dict] = []
        self.tfidf: dict[str, dict[int, float]] = {}
        self.doc_count = 0
        self._indexed = False

    def index(self) -> int:
        self.chunks = []
        for path in self._walk():
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")[:MAX_FILE]
                rel = str(path.relative_to(self.root))
                lines = content.split("\n")
                for i in range(0, len(lines), CHUNK_LINES):
                    chunk = "\n".join(lines[i:i + CHUNK_LINES])
                    if chunk.strip():
                        self.chunks.append({"path": rel, "content": chunk, "line": i + 1})
            except Exception:
                continue
        self.doc_count = len(self.chunks)
        self._build_tfidf()
        self._indexed = True
        logger.info("Indexed %d chunks from %s", self.doc_count, self.root)
        return self.doc_count

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        if not self._indexed:
            self.index()
        scores = defaultdict(float)
        for term in self._tok(query):
            for idx, sc in self.tfidf.get(term, {}).items():
                scores[idx] += sc
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [{"path": self.chunks[i]["path"], "line": self.chunks[i]["line"],
                 "content": self.chunks[i]["content"][:800], "score": round(s, 3)} for i, s in ranked]

    def get_context(self, query: str, max_chars: int = 12000) -> str:
        results = self.search(query, top_k=8)
        if not results:
            return ""
        parts, total = ["[Relevant codebase context]"], 0
        for r in results:
            block = f"\n--- {r['path']}:{r['line']} ---\n{r['content']}"
            if total + len(block) > max_chars:
                break
            parts.append(block)
            total += len(block)
        return "\n".join(parts)

    def _walk(self):
        for dp, dn, fn in os.walk(self.root):
            dn[:] = [d for d in dn if d not in IGNORE_DIRS]
            for f in fn:
                p = Path(dp) / f
                # Skip noise paths (skills docs, static assets, generated files)
                rel = str(p.relative_to(self.root))
                if any(rel.startswith(ip) or f"/{ip}/" in rel for ip in IGNORE_PATHS):
                    continue
                if p.suffix.lower() in INDEXABLE_EXT:
                    yield p

    def _tok(self, text):
        return [w.lower() for w in re.findall(r'[a-zA-Z_]\w{2,}', text)]

    def _build_tfidf(self):
        df = defaultdict(int)
        tf = []
        for c in self.chunks:
            tc = defaultdict(int)
            for t in self._tok(c["content"]):
                tc[t] += 1
            tf.append(tc)
            for t in set(tc):
                df[t] += 1
        self.tfidf = {}
        for i, tc in enumerate(tf):
            for term, cnt in tc.items():
                idf = math.log(self.doc_count / (df[term] + 1))
                sc = cnt * idf
                if sc > 0.1:
                    self.tfidf.setdefault(term, {})[i] = sc

    def stats(self):
        return {"indexed": self._indexed, "root": str(self.root), "chunks": len(self.chunks),
                "terms": len(self.tfidf), "files": len(set(c["path"] for c in self.chunks))}


_cache: dict[str, CodebaseIndex] = {}


def get_index(root: str = ".") -> CodebaseIndex:
    r = str(Path(root).resolve())
    if r not in _cache:
        idx = CodebaseIndex(r)
        idx.index()
        _cache[r] = idx
    return _cache[r]


def search_codebase(query: str, root: str = ".", top_k: int = 5) -> list[dict]:
    return get_index(root).search(query, top_k)


def get_context_for_prompt(query: str, root: str = ".", max_chars: int = 12000) -> str:
    return get_index(root).get_context(query, max_chars)
