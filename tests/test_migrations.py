"""Testes do sistema de migrations."""

import unittest
import sys
import os
import sqlite3
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.migrations import run_migrations, current_version, MIGRATIONS


class TestMigrations(unittest.TestCase):
    """Testes do migration runner."""

    def _make_db(self):
        """Cria um banco temporario para testes."""
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._conn = sqlite3.connect(self._tmp.name)
        self._conn.row_factory = sqlite3.Row

        from contextlib import contextmanager

        path = self._tmp.name

        @contextmanager
        def getter():
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

        return getter

    def tearDown(self):
        if hasattr(self, "_conn"):
            self._conn.close()
        if hasattr(self, "_tmp"):
            os.unlink(self._tmp.name)

    def test_run_creates_tables(self):
        getter = self._make_db()
        applied = run_migrations(db_getter=getter)
        self.assertGreater(len(applied), 0)

    def test_idempotent(self):
        getter = self._make_db()
        first = run_migrations(db_getter=getter)
        second = run_migrations(db_getter=getter)
        self.assertEqual(len(second), 0)  # Nothing new to apply

    def test_version_tracking(self):
        getter = self._make_db()
        run_migrations(db_getter=getter)
        ver = current_version(db_getter=getter)
        self.assertEqual(ver, max(v for v, _, _ in MIGRATIONS))

    def test_tables_exist_after_migration(self):
        getter = self._make_db()
        run_migrations(db_getter=getter)
        with getter() as db:
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        for expected in ("users", "conversations", "messages", "claude_code_log"):
            self.assertIn(expected, tables, f"Table {expected} not found")

    def test_migrations_have_versions(self):
        versions = [v for v, _, _ in MIGRATIONS]
        self.assertEqual(sorted(versions), versions)  # Must be in order
        self.assertEqual(len(set(versions)), len(versions))  # No duplicates


if __name__ == "__main__":
    unittest.main()
