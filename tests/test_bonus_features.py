"""Testes das 3 bonus features: CLOW.md template, Stats Aggregator, Plugin Bundles enhanced."""

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ══════════════════════════════════════════════════════════════
# FEATURE 1: CLOW.md Template
# ══════════════════════════════════════════════════════════════

class TestClowMdDetection(unittest.TestCase):

    def test_detect_python_project(self):
        from clow.clow_md_template import detect_project_type
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "pyproject.toml").write_text("[tool.poetry]")
            self.assertEqual(detect_project_type(d), "python")

    def test_detect_node_project(self):
        from clow.clow_md_template import detect_project_type
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "package.json").write_text('{"name": "test"}')
            self.assertEqual(detect_project_type(d), "node")

    def test_detect_react_project(self):
        from clow.clow_md_template import detect_project_type
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "package.json").write_text('{"dependencies": {"react": "^18"}}')
            self.assertEqual(detect_project_type(d), "react")

    def test_detect_generic_project(self):
        from clow.clow_md_template import detect_project_type
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(detect_project_type(d), "generic")

    def test_detect_requirements_txt(self):
        from clow.clow_md_template import detect_project_type
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "requirements.txt").write_text("flask\nfastapi")
            self.assertEqual(detect_project_type(d), "python")


class TestClowMdGeneration(unittest.TestCase):

    def test_generate_complete(self):
        from clow.clow_md_template import generate_clow_md
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "pyproject.toml").write_text("[tool.poetry]")
            md = generate_clow_md(d, "MeuProjeto")
            self.assertIn("MeuProjeto", md)
            self.assertIn("Python", md)
            self.assertIn("pytest", md)
            self.assertIn("Seguranca", md)
            self.assertIn("Emergency Rollback", md)
            self.assertIn("PEP 8", md)

    def test_generate_includes_structure(self):
        from clow.clow_md_template import generate_clow_md
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "package.json").write_text("{}")
            (Path(d) / "src").mkdir()
            md = generate_clow_md(d)
            self.assertIn("src/", md)

    def test_generate_node_project(self):
        from clow.clow_md_template import generate_clow_md
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "package.json").write_text('{"name":"test"}')
            md = generate_clow_md(d)
            self.assertIn("npm", md)
            self.assertIn("JavaScript", md)

    def test_should_suggest_init_true(self):
        from clow.clow_md_template import should_suggest_init
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "pyproject.toml").write_text("[tool]")
            self.assertTrue(should_suggest_init(d))

    def test_should_suggest_init_false_has_clow_md(self):
        from clow.clow_md_template import should_suggest_init
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "pyproject.toml").write_text("[tool]")
            (Path(d) / "CLOW.md").write_text("# Instructions")
            self.assertFalse(should_suggest_init(d))

    def test_should_suggest_init_false_no_project(self):
        from clow.clow_md_template import should_suggest_init
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(should_suggest_init(d))


# ══════════════════════════════════════════════════════════════
# FEATURE 2: Stats Aggregator
# ══════════════════════════════════════════════════════════════

class TestStatsAggregator(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test_stats.db")
        # Create tables
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL, date TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
                cache_hits INTEGER DEFAULT 0, total_requests INTEGER DEFAULT 0,
                successful_requests INTEGER DEFAULT 0, failed_requests INTEGER DEFAULT 0,
                whatsapp_messages_received INTEGER DEFAULT 0, whatsapp_messages_sent INTEGER DEFAULT 0,
                whatsapp_auto_replies INTEGER DEFAULT 0, leads_created INTEGER DEFAULT 0,
                leads_converted INTEGER DEFAULT 0, avg_latency_ms REAL DEFAULT 0,
                max_latency_ms REAL DEFAULT 0, estimated_cost_usd REAL DEFAULT 0,
                created_at REAL, updated_at REAL,
                UNIQUE(tenant_id, date)
            );
            CREATE TABLE IF NOT EXISTS weekly_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL, week TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
                total_requests INTEGER DEFAULT 0, whatsapp_messages INTEGER DEFAULT 0,
                leads_created INTEGER DEFAULT 0, leads_converted INTEGER DEFAULT 0,
                estimated_cost_usd REAL DEFAULT 0,
                created_at REAL, updated_at REAL,
                UNIQUE(tenant_id, week)
            );
            CREATE TABLE IF NOT EXISTS action_distribution (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL, date TEXT NOT NULL,
                action_type TEXT NOT NULL, action_name TEXT NOT NULL,
                count INTEGER DEFAULT 0, total_tokens INTEGER DEFAULT 0,
                UNIQUE(tenant_id, date, action_type, action_name)
            );
            CREATE TABLE IF NOT EXISTS top_users_weekly (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL, week TEXT NOT NULL,
                user_id TEXT NOT NULL, user_name TEXT DEFAULT '',
                total_requests INTEGER DEFAULT 0, total_tokens INTEGER DEFAULT 0,
                UNIQUE(tenant_id, week, user_id)
            );
        """)
        conn.commit()
        conn.close()

        from clow.stats_aggregator import StatsAggregator
        self.stats = StatsAggregator(db_path=self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_record_request_upsert(self):
        self.stats.record_request("t1", 1000, 500, 120.0, True, model="haiku")
        self.stats.record_request("t1", 2000, 1000, 80.0, True, model="haiku")
        daily = self.stats.get_daily("t1", days=1)
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]["total_requests"], 2)
        self.assertEqual(daily[0]["input_tokens"], 3000)
        self.assertEqual(daily[0]["output_tokens"], 1500)

    def test_record_request_weekly(self):
        self.stats.record_request("t1", 1000, 500, 100.0, True, model="sonnet")
        weekly = self.stats.get_weekly("t1", weeks=1)
        self.assertEqual(len(weekly), 1)
        self.assertEqual(weekly[0]["total_requests"], 1)

    def test_record_whatsapp(self):
        self.stats.record_whatsapp("t1", received=True)
        self.stats.record_whatsapp("t1", sent=True, auto_reply=True)
        daily = self.stats.get_daily("t1", days=1)
        self.assertEqual(daily[0]["whatsapp_messages_received"], 1)
        self.assertEqual(daily[0]["whatsapp_messages_sent"], 1)
        self.assertEqual(daily[0]["whatsapp_auto_replies"], 1)

    def test_record_action(self):
        self.stats.record_action("t1", "tool", "bash", 500)
        self.stats.record_action("t1", "tool", "bash", 300)
        self.stats.record_action("t1", "skill", "commit", 100)
        top = self.stats.get_top_actions("t1", days=1)
        self.assertEqual(len(top), 2)
        bash_action = next(a for a in top if a["action_name"] == "bash")
        self.assertEqual(bash_action["total_count"], 2)
        self.assertEqual(bash_action["total_tokens"], 800)

    def test_record_lead(self):
        self.stats.record_lead("t1", created=True)
        self.stats.record_lead("t1", created=True)
        self.stats.record_lead("t1", converted=True)
        daily = self.stats.get_daily("t1", days=1)
        self.assertEqual(daily[0]["leads_created"], 2)
        self.assertEqual(daily[0]["leads_converted"], 1)

    def test_get_daily_empty(self):
        daily = self.stats.get_daily("nonexistent", days=7)
        self.assertEqual(daily, [])

    def test_cost_calculation_haiku(self):
        cost = self.stats._calculate_cost(1_000_000, 1_000_000, "claude-haiku-4-5")
        self.assertAlmostEqual(cost, 6.0)  # 1*1 + 1*5

    def test_cost_calculation_sonnet(self):
        cost = self.stats._calculate_cost(1_000_000, 1_000_000, "claude-sonnet-4")
        self.assertAlmostEqual(cost, 18.0)  # 1*3 + 1*15

    def test_top_users(self):
        self.stats.record_request("t1", 1000, 500, 100.0, True,
                                  model="haiku", user_id="u1", user_name="Alice")
        self.stats.record_request("t1", 2000, 1000, 100.0, True,
                                  model="haiku", user_id="u2", user_name="Bob")
        self.stats.record_request("t1", 500, 200, 100.0, True,
                                  model="haiku", user_id="u1", user_name="Alice")
        users = self.stats.get_top_users("t1")
        self.assertEqual(len(users), 2)
        self.assertEqual(users[0]["user_id"], "u1")  # Alice tem mais requests
        self.assertEqual(users[0]["total_requests"], 2)

    def test_get_summary(self):
        self.stats.record_request("t1", 1000, 500, 100.0, True, model="haiku")
        summary = self.stats.get_summary("t1")
        self.assertIn("today", summary)
        self.assertIn("week", summary)
        self.assertEqual(summary["today"]["requests"], 1)


# ══════════════════════════════════════════════════════════════
# FEATURE 3: Plugin Bundles Enhanced
# ══════════════════════════════════════════════════════════════

class TestBundleEnhanced(unittest.TestCase):

    def test_bundles_have_plan_required(self):
        from clow.plugin_bundles import BUNDLES
        for bid, b in BUNDLES.items():
            self.assertIn("plan_required", b, f"Bundle {bid} sem plan_required")

    def test_bundles_have_tags(self):
        from clow.plugin_bundles import BUNDLES
        for bid, b in BUNDLES.items():
            self.assertIn("tags", b, f"Bundle {bid} sem tags")
            self.assertIsInstance(b["tags"], list)
            self.assertGreater(len(b["tags"]), 0, f"Bundle {bid} sem tags")

    def test_search_by_tag(self):
        from clow.plugin_bundles import BundleManager
        with tempfile.TemporaryDirectory() as d:
            mgr = BundleManager(d)
            results = mgr.search("security")
            self.assertGreater(len(results), 0)
            self.assertTrue(any(r["id"] == "security-pro" for r in results))

    def test_search_by_name(self):
        from clow.plugin_bundles import BundleManager
        with tempfile.TemporaryDirectory() as d:
            mgr = BundleManager(d)
            results = mgr.search("whatsapp")
            self.assertTrue(any(r["id"] == "whatsapp-pro" for r in results))

    def test_search_no_results(self):
        from clow.plugin_bundles import BundleManager
        with tempfile.TemporaryDirectory() as d:
            mgr = BundleManager(d)
            results = mgr.search("xyznonexistent")
            self.assertEqual(results, [])

    def test_install_and_uninstall_bundle(self):
        from clow.plugin_bundles import BundleManager
        with tempfile.TemporaryDirectory() as d:
            mgr = BundleManager(d)
            result = mgr.install_bundle("quality-gates")
            self.assertEqual(result["status"], "installed")
            self.assertIn("quality-gates", mgr.get_installed())

            result = mgr.uninstall_bundle("quality-gates")
            self.assertEqual(result["status"], "uninstalled")
            self.assertNotIn("quality-gates", mgr.get_installed())

    def test_all_10_bundles_exist(self):
        from clow.plugin_bundles import BUNDLES
        self.assertEqual(len(BUNDLES), 10)
        expected = {"security-pro", "git-workflow", "crm-suite", "whatsapp-pro",
                    "devops", "quality-gates", "content-creator", "data-analytics",
                    "automation", "full-stack"}
        self.assertEqual(set(BUNDLES.keys()), expected)


if __name__ == "__main__":
    unittest.main()
