"""Testes do sistema de contexto com deduplicacao e orcamento."""

import unittest
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.context import (
    load_project_context, MAX_CHARS_PER_FILE, MAX_CHARS_TOTAL,
    INSTRUCTION_FILES, MAX_ANCESTOR_DEPTH,
)


class TestContextLoading(unittest.TestCase):
    """Testes de carregamento de contexto."""

    def test_loads_from_cwd(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            clow_md = Path(tmpdir) / "CLOW.md"
            clow_md.write_text("# Test Project\nInstructions here.", encoding="utf-8")

            ctx = load_project_context(tmpdir)
            self.assertIn("Test Project", ctx)

    def test_loads_claude_md_compat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_md = Path(tmpdir) / "CLAUDE.md"
            claude_md.write_text("# Claude Compat\nWorks.", encoding="utf-8")

            ctx = load_project_context(tmpdir)
            self.assertIn("Claude Compat", ctx)

    def test_loads_from_dot_clow_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            clow_dir = Path(tmpdir) / ".clow"
            clow_dir.mkdir()
            (clow_dir / "CLOW.md").write_text("# Nested Config", encoding="utf-8")

            ctx = load_project_context(tmpdir)
            self.assertIn("Nested Config", ctx)

    def test_ancestor_chain_lookup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Cria CLOW.md no pai
            parent = Path(tmpdir)
            (parent / "CLOW.md").write_text("# Parent Context", encoding="utf-8")

            # Busca do subdiretorio
            child = parent / "sub"
            child.mkdir()

            ctx = load_project_context(str(child))
            self.assertIn("Parent Context", ctx)

    def test_deduplication(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            content = "# Same Content"
            (Path(tmpdir) / "CLOW.md").write_text(content, encoding="utf-8")
            clow_dir = Path(tmpdir) / ".clow"
            clow_dir.mkdir()
            (clow_dir / "CLOW.md").write_text(content, encoding="utf-8")

            ctx = load_project_context(tmpdir)
            # Mesmo conteudo nao deve aparecer 2x
            self.assertEqual(ctx.count("Same Content"), 1)

    def test_per_file_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Arquivo maior que MAX_CHARS_PER_FILE
            big_content = "x" * (MAX_CHARS_PER_FILE + 1000)
            (Path(tmpdir) / "CLOW.md").write_text(big_content, encoding="utf-8")

            ctx = load_project_context(tmpdir)
            self.assertLessEqual(len(ctx), MAX_CHARS_PER_FILE + 100)  # margem para "truncado"
            self.assertIn("truncado", ctx)

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = load_project_context(tmpdir)
            self.assertEqual(ctx, "")

    def test_constants(self):
        self.assertEqual(MAX_CHARS_PER_FILE, 4000)
        self.assertEqual(MAX_CHARS_TOTAL, 12000)
        self.assertEqual(MAX_ANCESTOR_DEPTH, 10)


if __name__ == "__main__":
    unittest.main()
