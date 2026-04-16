FROM python:3.12-slim AS builder

WORKDIR /build

# Python deps (cached layer)
COPY pyproject.toml poetry.lock* ./
RUN pip install --no-cache-dir --prefix=/install -e '.[web]' 2>/dev/null \
    || pip install --no-cache-dir --prefix=/install \
       fastapi 'uvicorn[standard]' httpx anthropic openai \
       python-multipart stripe pydantic python-dotenv rich

# ── Final image ──
FROM python:3.12-slim

# Create non-root user
RUN groupadd -r clow && useradd -r -g clow -m -d /home/clow -s /bin/bash clow

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# App code
COPY --chown=clow:clow . .

# Create required directories owned by clow user
RUN mkdir -p /home/clow/.clow/app /home/clow/.clow/memory \
             /home/clow/.clow/logs /home/clow/.clow/user_memories \
             /home/clow/.clow/sessions \
    && chown -R clow:clow /home/clow/.clow /app

# Run as non-root
USER clow

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1

CMD ["uvicorn", "clow.webapp:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
