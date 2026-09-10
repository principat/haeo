FROM python:3.13-slim

# Build tools for native dependencies (highspy, lru-dict, cryptography, etc.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/*

# uv manages the project's virtualenv (see pyproject.toml / uv.lock)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Keep the venv off the bind-mounted workspace: cross-filesystem hardlinks
# from uv's cache fail silently there, producing a corrupt install.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
