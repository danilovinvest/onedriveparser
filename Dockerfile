FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

RUN pip install --no-cache-dir uv==0.12.5

WORKDIR /app
# Dependencies first so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

# Token cache lives in /data (named volume), owned by an unprivileged user.
RUN useradd --system --uid 10001 --home-dir /app app \
    && mkdir /data && chown app /data
USER app

ENV ONEDRIVE_TOKEN_CACHE=/data/token_cache.json
ENTRYPOINT ["/app/.venv/bin/onedrive-mcp"]
CMD ["serve"]
