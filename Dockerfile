FROM node:24-slim AS console-builder

WORKDIR /repo

RUN corepack enable && corepack prepare pnpm@10 --activate

COPY paper_plane_x_frontend/package.json paper_plane_x_frontend/pnpm-lock.yaml ./paper_plane_x_frontend/
RUN pnpm --dir paper_plane_x_frontend install --frozen-lockfile

COPY VERSION ./VERSION
COPY paper_plane_x_frontend ./paper_plane_x_frontend
RUN pnpm --dir paper_plane_x_frontend build


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON=python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1

WORKDIR /app

# Install uv and keep curl for docker-compose healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://astral.sh/uv/install.sh | sh \
    && rm -rf /var/lib/apt/lists/* /root/.cache

ENV PATH="/root/.local/bin:${PATH}"

# Copy dependency manifests first for layer caching
COPY paper_plane_x_backend/pyproject.toml paper_plane_x_backend/uv.lock paper_plane_x_backend/README.md ./

# Install production dependencies using the locked uv.lock
RUN uv sync --frozen --no-dev

# Copy application code
COPY VERSION ./VERSION
COPY paper_plane_x_backend/src/paper_plane_x_backend ./src/paper_plane_x_backend
COPY paper_plane_x_backend/prompts ./prompts
COPY paper_plane_x_backend/config ./config
COPY --from=console-builder /repo/paper_plane_x_frontend/dist ./data/console

WORKDIR /app

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "paper_plane_x_backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
