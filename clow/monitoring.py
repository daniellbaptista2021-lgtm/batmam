"""Monitoring & APM integration for Clow.

Features:
  - Sentry integration for error tracking (optional, via SENTRY_DSN)
  - Structured JSON logging for production
  - Request performance tracking middleware
  - Health metrics endpoint enrichment

Setup:
  1. Set SENTRY_DSN env var to enable Sentry
  2. Set CLOW_LOG_FORMAT=json for structured logging
  3. Call init_monitoring() at app startup
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

logger = logging.getLogger(__name__)

# ── Sentry ──────────────────────────────────────────────────

_sentry_initialized = False


def init_sentry():
    """Initialize Sentry if SENTRY_DSN is configured."""
    global _sentry_initialized
    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn or _sentry_initialized:
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=dsn,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR),
            ],
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_RATE", "0.1")),
            profiles_sample_rate=float(os.getenv("SENTRY_PROFILES_RATE", "0.1")),
            environment=os.getenv("CLOW_ENV", "production"),
            release=os.getenv("CLOW_VERSION", "1.0.0"),
            send_default_pii=False,
            before_send=_before_send,
        )
        _sentry_initialized = True
        logger.info("Sentry initialized (env=%s)", os.getenv("CLOW_ENV", "production"))
        return True
    except ImportError:
        logger.info("sentry-sdk not installed, skipping Sentry init")
        return False
    except Exception as e:
        logger.warning("Sentry init failed: %s", e)
        return False


def _before_send(event, hint):
    """Filter sensitive data from Sentry events."""
    # Remove API keys, passwords, tokens from breadcrumbs
    if "exception" in event:
        for exc in event.get("exception", {}).get("values", []):
            value = exc.get("value", "")
            if any(s in value.lower() for s in ["api_key", "password", "token", "secret"]):
                exc["value"] = "[FILTERED]"

    # Remove cookies from request
    request = event.get("request", {})
    if "cookies" in request:
        request["cookies"] = "[FILTERED]"
    if "headers" in request:
        filtered = {}
        for k, v in request["headers"].items():
            if k.lower() in ("authorization", "cookie", "x-api-key"):
                filtered[k] = "[FILTERED]"
            else:
                filtered[k] = v
        request["headers"] = filtered

    return event


def capture_exception(exc: Exception, **extra):
    """Capture exception to Sentry (if initialized)."""
    if _sentry_initialized:
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                for k, v in extra.items():
                    scope.set_extra(k, v)
                sentry_sdk.capture_exception(exc)
        except Exception:
            pass
    logger.exception("Exception captured: %s", exc)


def capture_message(msg: str, level: str = "info", **extra):
    """Capture message to Sentry."""
    if _sentry_initialized:
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                for k, v in extra.items():
                    scope.set_extra(k, v)
                sentry_sdk.capture_message(msg, level=level)
        except Exception:
            pass


# ── Structured Logging ──────────────────────────────────────

class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info and record.exc_info[0]:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }

        # Add extra fields
        for key in ("user_id", "request_id", "path", "method", "status_code",
                     "duration_ms", "ip", "action"):
            val = getattr(record, key, None)
            if val is not None:
                log_data[key] = val

        return json.dumps(log_data, ensure_ascii=False)


def setup_structured_logging():
    """Configure structured JSON logging if CLOW_LOG_FORMAT=json."""
    log_format = os.getenv("CLOW_LOG_FORMAT", "text")
    if log_format != "json":
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    logger.info("Structured JSON logging enabled")


# ── Performance Middleware ──────────────────────────────────

class PerformanceMiddleware:
    """ASGI middleware that tracks request duration and logs slow requests."""

    SLOW_THRESHOLD_MS = float(os.getenv("CLOW_SLOW_REQUEST_MS", "5000"))

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 200

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
                # Add Server-Timing header
                elapsed = (time.perf_counter() - start) * 1000
                headers = list(message.get("headers", []))
                headers.append((b"server-timing", f"total;dur={elapsed:.1f}".encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            path = scope.get("path", "")

            # Skip static assets and health checks from logging
            if not path.startswith("/static") and path != "/health":
                if elapsed_ms > self.SLOW_THRESHOLD_MS:
                    logger.warning(
                        "Slow request: %s %s %.0fms (status=%d)",
                        scope.get("method", "?"), path, elapsed_ms, status_code,
                        extra={
                            "path": path,
                            "method": scope.get("method", ""),
                            "duration_ms": round(elapsed_ms),
                            "status_code": status_code,
                        },
                    )

            # Track in Sentry performance
            if _sentry_initialized and elapsed_ms > self.SLOW_THRESHOLD_MS:
                capture_message(
                    f"Slow request: {path} ({elapsed_ms:.0f}ms)",
                    level="warning",
                    path=path,
                    duration_ms=round(elapsed_ms),
                )


# ── Health Metrics ──────────────────────────────────────────

_request_count = 0
_error_count = 0
_start_time = time.time()


def get_health_metrics() -> dict[str, Any]:
    """Return health metrics for /health endpoint enrichment."""
    return {
        "uptime_seconds": round(time.time() - _start_time),
        "total_requests": _request_count,
        "total_errors": _error_count,
        "sentry_enabled": _sentry_initialized,
        "log_format": os.getenv("CLOW_LOG_FORMAT", "text"),
        "db_backend": os.getenv("CLOW_DB_BACKEND", "sqlite"),
    }


# ── Init ────────────────────────────────────────────────────

def init_monitoring():
    """Initialize all monitoring systems."""
    setup_structured_logging()
    init_sentry()
    logger.info("Monitoring initialized")
