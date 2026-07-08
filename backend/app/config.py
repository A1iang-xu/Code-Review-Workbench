"""
全局配置模块

使用 pydantic-settings 从环境变量和 .env 文件加载配置，
提供类型安全的全局 Settings 单例。
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# 占位符集合：若敏感字段等于其中任一值，视为"未配置"
_PLACEHOLDER_VALUES = {
    "",
    "change-me-to-a-random-string",
    "your-zhipu-api-key-here",
    "your-deepseek-api-key-here",
    "your-webhook-secret",
    "crw_secret",
}


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

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        """生产环境强制校验敏感字段不能为占位符。

        防止运维忘记配置 .env 导致应用以弱口令/占位符静默启动。
        开发环境仅打印警告，不阻断启动。

        注意：此处用标准 logging 而非 app.utils.logger，
        因为后者在模块级 import 时会反向调用 get_settings()，
        在 Settings 初始化期间形成循环导入。
        """
        import logging

        logger = logging.getLogger(__name__)
        is_prod = self.APP_ENV.lower() in {"production", "prod"}

        checks = {
            "SECRET_KEY": self.SECRET_KEY,
            "POSTGRES_PASSWORD": self.POSTGRES_PASSWORD,
            "WEBHOOK_SECRET": self.WEBHOOK_SECRET,
            "ZHIPU_API_KEY": self.ZHIPU_API_KEY,
            "DEEPSEEK_API_KEY": self.DEEPSEEK_API_KEY,
        }

        offending = [name for name, val in checks.items() if val in _PLACEHOLDER_VALUES]

        if not offending:
            return self

        msg = (
            f"敏感配置使用了占位符或默认值: {offending}. "
            f"请在 .env 中配置真实值。"
        )

        if is_prod:
            raise ValueError(msg)
        logger.warning("[Config] %s (开发环境继续启动，生产环境将拒绝启动)", msg)
        return self

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

    # ---- LLM 配置 ----
    ZHIPU_API_KEY: str = "your-zhipu-api-key-here"
    ZHIPU_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"

    DEEPSEEK_API_KEY: str = "your-deepseek-api-key-here"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODELS: str = "qwen2.5:7b,deepseek-coder:6.7b"

    LLM_REASONING_MODEL: str = "glm-5.2"
    LLM_UTILITY_MODEL: str = "ollama/qwen2.5:7b"
    # Embedding 模型（智谱 embedding-3，默认 2048 维），用于语义记忆向量检索
    LLM_EMBEDDING_MODEL: str = "glm/embedding-3"

    # ---- 代码审查配置 ----
    MAX_FILE_SIZE_BYTES: int = 1_048_576       # 1 MB
    MAX_FILES_PER_REVIEW: int = 50
    REVIEW_TIMEOUT_SECONDS: int = 300

    # ---- Agent 协作配置 ----
    COLLABORATION_ENABLED: bool = True              # 是否启用 Agent 协作
    COLLABORATION_MAX_SIGNALS_PER_AGENT: int = 10   # 单 Agent 信号数上限
    COLLABORATION_MAX_FILES_PER_REVIEW: int = 5     # 单 collab 节点复查文件数上限
    COLLABORATION_TIMEOUT_SECONDS: int = 60         # 协作阶段总超时

    # ---- GitHub / GitLab 集成 ----
    GITHUB_TOKEN: str = ""
    GITLAB_TOKEN: str = ""
    WEBHOOK_SECRET: str = "your-webhook-secret"

    # ---- 可观测性 ----
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"


@lru_cache()
def get_settings() -> Settings:
    """返回全局 Settings 单例（带缓存）。"""
    return Settings()
