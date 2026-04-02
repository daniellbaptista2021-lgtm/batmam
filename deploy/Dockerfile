FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml ./
COPY clow/ clow/

RUN pip install --no-cache-dir --prefix=/install ".[web]"

# ── Runtime ──
FROM python:3.12-slim

RUN useradd --create-home --shell /bin/bash clow

COPY --from=builder /install /usr/local
COPY --from=builder /build /app

WORKDIR /app

RUN mkdir -p /home/clow/.clow/sessions /home/clow/.clow/memory /home/clow/.clow/logs \
    && chown -R clow:clow /home/clow/.clow /app

USER clow

ENV PYTHONUNBUFFERED=1 \
    CLOW_PROVIDER=anthropic \
    CLOW_MODEL=claude-sonnet-4-20250514

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["uvicorn", "clow.webapp:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]
