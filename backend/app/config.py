"""
全局配置模块

使用 pydantic-settings 从环境变量和 .env 文件加载配置，
提供类型安全的全局 Settings 单例。
"""

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局应用配置，自动从 .env 和环境变量加载。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 应用配置 ----
    APP_NAME: str = "code-review-workbench"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    SECRET_KEY: str = "change-me-to-a-random-string"

    # ---- 数据库 ----
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "code_review"
    POSTGRES_USER: str = "crw"
    POSTGRES_PASSWORD: str = "crw_secret"

    @property
    def DATABASE_URL_ASYNC(self) -> str:
        """异步数据库连接串 (asyncpg 驱动)"""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        """同步数据库连接串 (psycopg2 驱动, 供 Alembic 使用)"""
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ---- Redis ----
    REDIS_URL: str = "redis://localhost:6379/0"

    # ---- Milvus 向量数据库 ----
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530

    # ---- LLM 配置 ----
    ZHIPU_API_KEY: str = "your-zhipu-api-key-here"
    ZHIPU_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"

    DEEPSEEK_API_KEY: str = "your-deepseek-api-key-here"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODELS: str = "qwen2.5:7b,deepseek-coder:6.7b"

    LLM_REASONING_MODEL: str = "glm-5.2"
    LLM_UTILITY_MODEL: str = "ollama/qwen2.5:7b"

    # ---- 代码审查配置 ----
    MAX_FILE_SIZE_BYTES: int = 1_048_576       # 1 MB
    MAX_FILES_PER_REVIEW: int = 50
    REVIEW_TIMEOUT_SECONDS: int = 300
    DEFAULT_LANGUAGES: str = "python,go,typescript,javascript"

    # ---- GitHub / GitLab 集成 ----
    GITHUB_TOKEN: str = ""
    GITLAB_TOKEN: str = ""
    WEBHOOK_SECRET: str = "your-webhook-secret"

    # ---- 可观测性 ----
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"
    PROMETHEUS_METRICS_PORT: int = 9090


@lru_cache()
def get_settings() -> Settings:
    """返回全局 Settings 单例（带缓存）。"""
    return Settings()
