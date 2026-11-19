# syntax=docker/dockerfile:1

# Stage 1: Build virtual environment using uv
FROM python:3.14-slim AS builder

# Pin uv binary from official distroless image
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/

# Configure uv for non-interactive container builds with bytecode compilation
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies in a separate layer to leverage Docker build cache
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev --no-editable

# Copy the application source code and packaging files
COPY . /app

# Sync and install the project itself into the virtual environment (non-editable)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# Stage 2: Minimal runtime image
FROM python:3.14-slim AS runtime

# Ensure standard output/error are unbuffered and venv is active on PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Run as non-root user for security
RUN groupadd --system --gid 10001 appgroup && \
    useradd --system --uid 10001 --gid appgroup --create-home --home-dir /app --shell /usr/sbin/nologin appuser

WORKDIR /app

# Copy the pre-built virtual environment from builder stage
COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv

# Switch to unprivileged user
USER appuser

# Run the console script entrypoint defined in pyproject.toml
CMD ["daretirbot"]
