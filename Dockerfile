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
COPY pyproject.toml uv.lock ./

# Install production dependencies using the locked uv.lock
RUN uv sync --frozen --no-dev

# Copy application code
COPY src/paper_plane_x_backend ./src/paper_plane_x_backend
COPY prompts ./prompts
COPY config ./config

WORKDIR /app

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "paper_plane_x_backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
