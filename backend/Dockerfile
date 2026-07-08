# Code Review Workbench — Backend Dockerfile
# Multi-stage pattern for smaller production images
# 使用 Python 3.11 而非 3.12：semgrep 的 PyPI wheel 仅支持 cp38-cp311，
# 在 3.12 上 pip 会回退到 sdist 源码构建导致失败
FROM python:3.11-slim

WORKDIR /app

# System dependencies
# libffi-dev/libxml2-dev/libxslt-dev: semgrep & lxml 原生扩展编译所需
# pkg-config: 帮助构建脚本定位系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    git \
    libpq-dev \
    libffi-dev \
    libxml2-dev \
    libxslt-dev \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies — 先复制 pyproject.toml 并创建最小包结构以利用层缓存
# pip install -e 需要源代码存在，Docker 中改用非可编辑安装
# 首次失败时用 -v 重试以在 CI 日志中输出详细错误
COPY pyproject.toml .
RUN mkdir -p app && touch app/__init__.py && \
    (pip install --no-cache-dir . || pip install --no-cache-dir -v .) && \
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
