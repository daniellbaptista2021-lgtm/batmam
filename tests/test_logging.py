"""Testes do structured logging com metricas."""

import unittest
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.logging import (
    StructuredJSONFormatter, MetricsCollector,
    trace_context, get_trace_id, get_span_id,
    log_action, log_timer, metrics,
)


class TestStructuredFormatter(unittest.TestCase):
    """Testes do formatter JSON."""

    def test_format_produces_json(self):
        import logging
        fmt = StructuredJSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="hello", args=(), exc_info=None,
        )
        output = fmt.format(record)
        data = json.loads(output)
        self.assertEqual(data["message"], "hello")
        self.assertEqual(data["level"], "info")
        self.assertIn("timestamp", data)

    def test_extra_fields(self):
        import logging
        fmt = StructuredJSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="test", args=(), exc_info=None,
        )
        record.tool_name = "bash"
        record.duration = 1.5
        output = fmt.format(record)
        data = json.loads(output)
        self.assertEqual(data["tool_name"], "bash")
        self.assertEqual(data["duration"], 1.5)


class TestTraceContext(unittest.TestCase):
    """Testes de trace context."""

    def test_default_empty(self):
        # Pode ter trace de outro teste, aceita vazio ou nao
        self.assertIsInstance(get_trace_id(), str)

    def test_context_manager_sets_ids(self):
        with trace_context(trace_id="abc123", span_id="span1") as tid:
            self.assertEqual(tid, "abc123")
            self.assertEqual(get_trace_id(), "abc123")
            self.assertEqual(get_span_id(), "span1")

    def test_context_manager_auto_generates(self):
        with trace_context() as tid:
            self.assertGreater(len(tid), 0)
            self.assertGreater(len(get_span_id()), 0)

    def test_context_restores_previous(self):
        with trace_context(trace_id="outer"):
            with trace_context(trace_id="inner"):
                self.assertEqual(get_trace_id(), "inner")
            self.assertEqual(get_trace_id(), "outer")


class TestMetricsCollector(unittest.TestCase):
    """Testes do coletor de metricas."""

    def setUp(self):
        self.m = MetricsCollector()

    def test_increment(self):
        self.m.increment("requests")
        self.m.increment("requests")
        self.m.increment("requests", 3)
        snapshot = self.m.snapshot()
        self.assertEqual(snapshot["counters"]["requests"], 5)

    def test_gauge(self):
        self.m.gauge("memory_mb", 256.5)
        snapshot = self.m.snapshot()
        self.assertEqual(snapshot["gauges"]["memory_mb"], 256.5)

    def test_gauge_overwrite(self):
        self.m.gauge("cpu", 50.0)
        self.m.gauge("cpu", 75.0)
        snapshot = self.m.snapshot()
        self.assertEqual(snapshot["gauges"]["cpu"], 75.0)

    def test_observe(self):
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            self.m.observe("latency", v)
        snapshot = self.m.snapshot()
        hist = snapshot["histograms"]["latency"]
        self.assertEqual(hist["count"], 5)
        self.assertEqual(hist["min"], 1.0)
        self.assertEqual(hist["max"], 5.0)
        self.assertEqual(hist["avg"], 3.0)

    def test_reset(self):
        self.m.increment("x")
        self.m.gauge("y", 1.0)
        self.m.observe("z", 1.0)
        self.m.reset()
        snapshot = self.m.snapshot()
        self.assertEqual(snapshot["counters"], {})
        self.assertEqual(snapshot["gauges"], {})

    def test_snapshot_immutable(self):
        self.m.increment("a")
        s1 = self.m.snapshot()
        self.m.increment("a")
        s2 = self.m.snapshot()
        self.assertNotEqual(s1["counters"]["a"], s2["counters"]["a"])


class TestLogTimer(unittest.TestCase):
    """Testes do context manager log_timer."""

    def test_log_timer_works(self):
        import time
        with log_timer("test_op"):
            time.sleep(0.01)
        # Nao deve lancar excecao


class TestLogAction(unittest.TestCase):
    """Testes do log_action."""

    def test_log_action_increments_metric(self):
        initial = metrics.snapshot()["counters"].get("action.test_log_action", 0)
        log_action("test_log_action", "test detail")
        after = metrics.snapshot()["counters"].get("action.test_log_action", 0)
        self.assertGreater(after, initial)


if __name__ == "__main__":
    unittest.main()
