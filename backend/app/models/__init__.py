"""
数据库引擎与会话管理

使用 SQLAlchemy 2.0 异步引擎 (asyncpg 驱动)，
通过 FastAPI 依赖注入提供数据库会话。
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

# --- 异步引擎 ---
engine = create_async_engine(
    settings.DATABASE_URL_ASYNC,
    pool_size=10,
    max_overflow=20,
    echo=settings.APP_DEBUG,
)

# --- 会话工厂 ---
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类。"""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入：每次请求生成一个数据库会话。"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# --- 导入所有模型，确保 Base.metadata 包含所有表 ---
from app.models.review import ReviewTask, ReviewStatus  # noqa: E402, F401
from app.models.agent_result import AgentResult  # noqa: E402, F401
from app.models.report import ReviewReport  # noqa: E402, F401
from app.models.memory import EpisodicMemoryRecord, SemanticMemoryRecord  # noqa: E402, F401
