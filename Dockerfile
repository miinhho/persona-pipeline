# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

# Install uv (binary). Pin a known-good version; bump in a follow-up if needed.
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /app

# Resolve and install dependencies first (layer-cache friendly)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra mcp --no-dev --no-install-project

# Now bring in the package source and finalize
COPY persona_mcp_store persona_mcp_store
RUN uv sync --frozen --extra mcp --no-dev


FROM python:3.11-slim AS runtime

# Non-root user for runtime
RUN useradd -u 1000 -m app
WORKDIR /app

# Copy the resolved venv and the application package from builder
COPY --from=builder /app /app

USER app
ENV PATH="/app/.venv/bin:$PATH"
ENV PERSONA_STORE_DATA_DIR=/data
EXPOSE 8080

# Default entrypoint runs the streamable-http server on 0.0.0.0:8080.
# Operator must mount a directory at /data and supply PERSONA_STORE_API_KEYS.
ENTRYPOINT ["python", "-m", "persona_mcp_store.cli", "serve-http"]
CMD ["--host", "0.0.0.0", "--port", "8080"]
