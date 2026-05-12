# syntax=docker/dockerfile:1.7
#
# x402-cms — Cloud Run image.
#
# Layers are ordered so that dependency install is cached separately
# from the application source, which keeps repeated deploys fast.
# Cloud Run injects $PORT at runtime; we honour it and fall back to
# 8080 for local `docker run` parity.

FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY code ./code
# `config/tracked_handles.yaml` and `config/importance_rules.yaml`
# are excluded by .dockerignore — only the `.example.yaml` template
# rides in. The x_indexer job is started with
# `--handles-config config/tracked_handles.example.yaml`.
COPY config ./config
RUN uv sync --frozen --no-dev

EXPOSE 8080

# `--forwarded-allow-ips="*"` lets uvicorn trust `X-Forwarded-Proto`
# from Cloud Run's front-end so `request.url.scheme` resolves to https
# behind the load balancer. Without it, x402 PaymentRequirements
# advertise `http://...` for an HTTPS-served URL.
CMD ["sh", "-c", "uvicorn code.server.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips=*"]
