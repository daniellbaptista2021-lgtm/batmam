FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl && rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml poetry.lock* ./
RUN pip install --no-cache-dir -e "." 2>/dev/null || pip install --no-cache-dir fastapi uvicorn httpx anthropic openai

# App code
COPY . .

# Create required directories
RUN mkdir -p /root/.clow/app /root/.clow/memory /root/.clow/logs

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8001/health || exit 1

CMD ["uvicorn", "clow.webapp:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
