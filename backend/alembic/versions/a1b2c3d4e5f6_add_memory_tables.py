"""add memory tables with pgvector

Revision ID: a1b2c3d4e5f6
Revises: fab89f747922
Create Date: 2026-06-25 19:00:00.000000

新增记忆系统持久化表：
- episodic_memories: 情节记忆（审查历史）
- semantic_memories: 语义记忆（审查规则与最佳实践，pgvector 向量检索）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'fab89f747922'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 启用 pgvector 扩展
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 情节记忆表
    op.create_table('episodic_memories',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('task_id', sa.String(length=64), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('key_facts', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('issue_count', sa.Integer(), nullable=False),
        sa.Column('repo_url', sa.String(length=1024), nullable=True),
        sa.Column('top_categories', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('severity_counts', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_episodic_memories_task_id', 'episodic_memories', ['task_id'])
    op.create_index('ix_episodic_memories_timestamp', 'episodic_memories', ['timestamp'])
    op.create_index('ix_episodic_memories_score', 'episodic_memories', ['score'])

    # 语义记忆表（不含 embedding 列，随后用原生 SQL 添加 pgvector vector 列）
    op.create_table('semantic_memories',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('knowledge_type', sa.String(length=20), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('language', sa.String(length=50), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('severity', sa.String(length=20), nullable=True),
        sa.Column('good_example', sa.Text(), nullable=True),
        sa.Column('bad_example', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_semantic_memories_knowledge_type', 'semantic_memories', ['knowledge_type'])
    op.create_index('ix_semantic_memories_category', 'semantic_memories', ['category'])
    op.create_index('ix_semantic_memories_language', 'semantic_memories', ['language'])
    op.create_index('ix_semantic_memories_type_lang', 'semantic_memories', ['knowledge_type', 'language'])

    # 添加 pgvector 向量列（维度 1536，对应 OpenAI text-embedding-3-small）
    # 必须使用 vector 类型才能创建 ivfflat 索引
    op.execute(
        "ALTER TABLE semantic_memories ADD COLUMN embedding vector(1536)"
    )

    # 创建向量索引（IVFFlat，用于近似最近邻搜索）
    op.execute(
        "CREATE INDEX ix_semantic_memories_embedding ON semantic_memories "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.drop_index('ix_semantic_memories_embedding', table_name='semantic_memories')
    op.drop_index('ix_semantic_memories_type_lang', table_name='semantic_memories')
    op.drop_index('ix_semantic_memories_language', table_name='semantic_memories')
    op.drop_index('ix_semantic_memories_category', table_name='semantic_memories')
    op.drop_index('ix_semantic_memories_knowledge_type', table_name='semantic_memories')
    op.drop_table('semantic_memories')

    op.drop_index('ix_episodic_memories_score', table_name='episodic_memories')
    op.drop_index('ix_episodic_memories_timestamp', table_name='episodic_memories')
    op.drop_index('ix_episodic_memories_task_id', table_name='episodic_memories')
    op.drop_table('episodic_memories')
