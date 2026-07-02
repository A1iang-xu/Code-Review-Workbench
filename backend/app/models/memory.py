"""
记忆系统数据库模型

- EpisodicMemoryRecord: 跨会话审查历史（PostgreSQL）
- SemanticMemoryRecord: 审查规则与最佳实践（pgvector 向量检索）

替代原有的 JSON 文件持久化，支持跨进程共享和语义检索。
"""

import uuid
import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

# pgvector 向量类型 — 作为强依赖
# 原实现根据是否安装 pgvector 在 Vector / JSONB 之间漂移，导致开发与生产
# schema 不一致、Alembic 持续产生假迁移。统一为 Vector 类型，由依赖管理保证安装。
from pgvector.sqlalchemy import Vector


# ============================================================
# 情节记忆 — 审查历史记录
# ============================================================

class EpisodicMemoryRecord(Base):
    """情节记忆记录表。

    每次审查完成后保存一条记录，包含摘要、评分、关键事实等。
    替代原有的 episodic_memory.json 文件。
    """
    __tablename__ = "episodic_memories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        nullable=False,
        index=True,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    key_facts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    top_categories: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    severity_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_episodic_memories_timestamp", "timestamp"),
        Index("ix_episodic_memories_score", "score"),
    )


# ============================================================
# 语义记忆 — 审查规则与最佳实践（pgvector 向量检索）
# ============================================================

# 向量维度（智谱 embedding-3 默认输出 2048 维）
EMBEDDING_DIM = 2048


class SemanticMemoryRecord(Base):
    """语义记忆记录表。

    存储审查规则、代码模式和最佳实践，使用 pgvector 进行向量检索。
    替代原有的 semantic_memory.json 文件。

    knowledge_type:
    - rule: 审查规则
    - pattern: 代码模式（正例/反例）
    - best_practice: 最佳实践
    """
    __tablename__ = "semantic_memories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    knowledge_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # rule / pattern / best_practice
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 代码示例（正例/反例）
    good_example: Mapped[str | None] = mapped_column(Text, nullable=True)
    bad_example: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 额外元数据
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    # 向量嵌入（用于语义检索）— 统一为 pgvector Vector 类型
    embedding: Mapped[list | None] = mapped_column(
        Vector(EMBEDDING_DIM),
        nullable=True,
    )
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_semantic_memories_type_lang", "knowledge_type", "language"),
        Index("ix_semantic_memories_category", "category"),
    )
