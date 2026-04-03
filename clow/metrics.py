"""Prometheus-compatible metrics collection."""

import time
import threading
from collections import defaultdict


class Metrics:
    """Thread-safe metrics registry with counters, histograms, and gauges."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._gauges: dict[str, float] = defaultdict(float)
        self._start_time = time.time()

    def _key(self, name: str, labels: dict | None = None) -> str:
        if labels:
            lbl = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
            return f"{name}{{{lbl}}}"
        return name

    def _split_key(self, key: str) -> tuple[str, str]:
        """Split 'name{labels}' into ('name', '{labels}') or ('name', '')."""
        if "{" in key:
            idx = key.index("{")
            return key[:idx], key[idx:]
        return key, ""

    def inc(self, name: str, value: int = 1, labels: dict | None = None) -> None:
        """Increment a counter."""
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] += value

    def observe(self, name: str, value: float, labels: dict | None = None) -> None:
        """Record a histogram observation (e.g. latency)."""
        key = self._key(name, labels)
        with self._lock:
            hist = self._histograms[key]
            hist.append(value)
            if len(hist) > 1000:
                self._histograms[key] = hist[-500:]

    def set_gauge(self, name: str, value: float, labels: dict | None = None) -> None:
        """Set a gauge value."""
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = value

    def _percentile(self, values: list[float], p: float) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        idx = int(len(s) * p / 100)
        return s[min(idx, len(s) - 1)]

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = [
            "# HELP clow_uptime_seconds Time since process start",
            f"clow_uptime_seconds {time.time() - self._start_time:.0f}",
        ]
        with self._lock:
            for key, val in sorted(self._counters.items()):
                lines.append(f"clow_{key} {val}")
            for key, vals in sorted(self._histograms.items()):
                if vals:
                    name, lbl = self._split_key(key)
                    lines.append(f"clow_{name}_count{lbl} {len(vals)}")
                    lines.append(f"clow_{name}_sum{lbl} {sum(vals):.3f}")
                    lines.append(f"clow_{name}_p50{lbl} {self._percentile(vals, 50):.3f}")
                    lines.append(f"clow_{name}_p95{lbl} {self._percentile(vals, 95):.3f}")
                    lines.append(f"clow_{name}_p99{lbl} {self._percentile(vals, 99):.3f}")
            for key, val in sorted(self._gauges.items()):
                lines.append(f"clow_{key} {val:.2f}")
        return "\n".join(lines) + "\n"

    def to_json(self) -> dict:
        """Export metrics as JSON dict."""
        with self._lock:
            result = {
                "uptime_seconds": round(time.time() - self._start_time),
                "counters": dict(self._counters),
                "histograms": {},
                "gauges": dict(self._gauges),
            }
            for key, vals in self._histograms.items():
                if vals:
                    result["histograms"][key] = {
                        "count": len(vals),
                        "sum": round(sum(vals), 3),
                        "avg": round(sum(vals) / len(vals), 3),
                        "p50": round(self._percentile(vals, 50), 3),
                        "p95": round(self._percentile(vals, 95), 3),
                        "p99": round(self._percentile(vals, 99), 3),
                    }
        return result


# Global instance
metrics = Metrics()
