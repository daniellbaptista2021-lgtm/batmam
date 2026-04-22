"""Python logging filter that redacts secrets before emission."""
from __future__ import annotations
import logging
from .redact import redact


class RedactFilter(logging.Filter):
    """Attach to every logger/handler. Redacts formatted message + args."""
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Pre-format the message if it has args, then redact
            if record.args:
                try:
                    record.msg = record.getMessage()
                    record.args = None
                except Exception:
                    pass
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
        except Exception:
            pass
        return True


def install_redact_filter(root_logger: logging.Logger | None = None) -> None:
    """Install RedactFilter on the root logger (applies to all loggers).
    Safe to call multiple times."""
    root = root_logger or logging.getLogger()
    # Avoid duplicate install
    for f in root.filters:
        if isinstance(f, RedactFilter):
            return
    root.addFilter(RedactFilter())
    # Also apply to each existing handler (logging.Filter on logger
    # does not always propagate to handlers in older configs)
    for h in list(root.handlers):
        has = any(isinstance(f, RedactFilter) for f in h.filters)
        if not has:
            h.addFilter(RedactFilter())
