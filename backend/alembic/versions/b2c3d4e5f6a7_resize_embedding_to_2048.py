"""resize embedding column from 1536 to 2048

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-01 22:30:00.000000

将 semantic_memories.embedding 列维度从 1536 调整为 2048，
对齐智谱 embedding-3 模型的默认输出维度。

由于现有 embedding 列恒为 NULL（原代码缺失 embedding 生成方法），
维度变更不会丢失数据。重建 ivfflat 索引以匹配新维度。
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 删除旧维度索引
    op.execute("DROP INDEX IF EXISTS ix_semantic_memories_embedding")
    # 调整向量列维度（现有数据为 NULL，无需 USING 转换）
    op.execute("ALTER TABLE semantic_memories ALTER COLUMN embedding TYPE vector(2048)")
    # 重建向量索引
    op.execute(
        "CREATE INDEX ix_semantic_memories_embedding ON semantic_memories "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_semantic_memories_embedding")
    op.execute("ALTER TABLE semantic_memories ALTER COLUMN embedding TYPE vector(1536)")
    op.execute(
        "CREATE INDEX ix_semantic_memories_embedding ON semantic_memories "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
