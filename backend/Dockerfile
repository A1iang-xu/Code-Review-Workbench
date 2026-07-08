# Code Review Workbench — Backend Dockerfile
# Multi-stage pattern for smaller production images
FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    git \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies — 先复制 pyproject.toml 并创建最小包结构以利用层缓存
# pip install -e 需要源代码存在，Docker 中改用非可编辑安装
COPY pyproject.toml .
RUN mkdir -p app && touch app/__init__.py && \
    pip install --no-cache-dir . && \
    rm -rf app

# Copy app code
COPY . .

# Create memory data directory
RUN mkdir -p /app/memory_data

# Expose
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
