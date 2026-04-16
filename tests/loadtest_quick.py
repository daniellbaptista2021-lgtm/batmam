#!/usr/bin/env python3
"""Quick load test — sem dependências externas.

Testa endpoints com concorrência usando ThreadPoolExecutor.
Uso: python3 tests/loadtest_quick.py [users] [requests_per_user]

Default: 10 users, 20 requests each = 200 total requests
"""
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

BASE_URL = os.getenv("CLOW_TEST_URL", "http://localhost:8001")
CONCURRENT_USERS = int(sys.argv[1]) if len(sys.argv) > 1 else 10
REQUESTS_PER_USER = int(sys.argv[2]) if len(sys.argv) > 2 else 20

results = defaultdict(list)
errors = defaultdict(int)


def _request(method: str, path: str, data=None, token=""):
    """Make HTTP request, return (status, duration_ms)."""
    url = f"{BASE_URL}{path}"
    body = json.dumps(data).encode() if data else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Cookie"] = f"clow_session={token}"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    start = time.perf_counter()
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        elapsed = (time.perf_counter() - start) * 1000
        return resp.status, elapsed
    except urllib.error.HTTPError as e:
        elapsed = (time.perf_counter() - start) * 1000
        return e.code, elapsed
    except Exception:
        elapsed = (time.perf_counter() - start) * 1000
        return 0, elapsed


def user_scenario(user_id: int):
    """Simula um usuário fazendo requests."""
    local_results = []

    for i in range(REQUESTS_PER_USER):
        # Mix de endpoints
        endpoints = [
            ("GET", "/health"),
            ("GET", "/login"),
            ("GET", "/static/manifest.json"),
            ("GET", "/static/css/chat.css"),
        ]
        method, path = endpoints[i % len(endpoints)]
        status, duration = _request(method, path)
        local_results.append((path, status, duration))

    return local_results


def main():
    print("=" * 60)
    print(f"LOAD TEST — Clow Platform")
    print(f"Server: {BASE_URL}")
    print(f"Users: {CONCURRENT_USERS}, Requests/user: {REQUESTS_PER_USER}")
    print(f"Total requests: {CONCURRENT_USERS * REQUESTS_PER_USER}")
    print("=" * 60)

    start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=CONCURRENT_USERS) as executor:
        futures = [executor.submit(user_scenario, i) for i in range(CONCURRENT_USERS)]

        for future in as_completed(futures):
            for path, status, duration in future.result():
                results[path].append(duration)
                if status != 200:
                    errors[path] += 1

    total_time = time.perf_counter() - start
    total_requests = sum(len(v) for v in results.values())

    print(f"\nResultados ({total_time:.1f}s total, {total_requests/total_time:.0f} req/s):\n")
    print(f"{'Endpoint':<35} {'Reqs':>5} {'Avg ms':>8} {'P50':>8} {'P95':>8} {'P99':>8} {'Max':>8} {'Err':>5}")
    print("-" * 95)

    all_durations = []
    total_errors = 0

    for path in sorted(results.keys()):
        durations = sorted(results[path])
        all_durations.extend(durations)
        n = len(durations)
        avg = sum(durations) / n
        p50 = durations[int(n * 0.5)]
        p95 = durations[int(n * 0.95)]
        p99 = durations[min(int(n * 0.99), n - 1)]
        mx = durations[-1]
        errs = errors.get(path, 0)
        total_errors += errs

        print(f"{path:<35} {n:>5} {avg:>7.1f} {p50:>7.1f} {p95:>7.1f} {p99:>7.1f} {mx:>7.1f} {errs:>5}")

    # Summary
    all_durations.sort()
    n = len(all_durations)
    print("-" * 95)
    print(f"{'TOTAL':<35} {n:>5} {sum(all_durations)/n:>7.1f} "
          f"{all_durations[int(n*0.5)]:>7.1f} {all_durations[int(n*0.95)]:>7.1f} "
          f"{all_durations[min(int(n*0.99), n-1)]:>7.1f} {all_durations[-1]:>7.1f} {total_errors:>5}")

    print(f"\nThroughput: {total_requests/total_time:.1f} req/s")
    print(f"Error rate: {total_errors/total_requests*100:.1f}%")

    # Pass/Fail criteria
    avg_all = sum(all_durations) / len(all_durations)
    p95_all = all_durations[int(len(all_durations) * 0.95)]
    error_rate = total_errors / total_requests

    print(f"\nCritérios de aceitação:")
    checks = [
        ("Avg < 500ms", avg_all < 500),
        ("P95 < 2000ms", p95_all < 2000),
        ("Error rate < 1%", error_rate < 0.01),
        ("Throughput > 10 req/s", total_requests / total_time > 10),
    ]
    passed = 0
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  {status} {name}")
        if ok:
            passed += 1

    print(f"\n{passed}/{len(checks)} critérios atendidos")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
