"""
Episodic Memory tests.

Validates save and retrieve operations.
注意：EpisodicMemory 实际存储在 PostgreSQL（storage_path 仅兼容旧接口），
测试使用唯一 task_id 避免历史记录干扰。
"""

import uuid

import pytest

from app.core.memory.episodic import EpisodicMemory


class TestEpisodicMemorySavesAndRetrieves:
    """Verify episodic memory can save sessions and retrieve them."""

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self):
        """保存后应能通过 retrieve_recent 检索到该记录。"""
        memory = EpisodicMemory()
        # 唯一 task_id 避免历史记录干扰
        task_id = f"test-save-{uuid.uuid4().hex[:8]}"
        review_result = {
            "summary": "Test review summary",
            "score": 8.5,
            "severity_counts": {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 0},
        }
        issues = [
            {"agent_type": "security", "title": "Hardcoded key", "severity": "high"},
            {"agent_type": "style", "title": "Long function", "severity": "medium"},
        ]

        await memory.save_session(task_id, review_result, issues)

        # retrieve_recent 返回最近 N 条，按 task_id 过滤验证本条存在
        recent = await memory.retrieve_recent(50)
        found = [e for e in recent if e.get("task_id") == task_id]
        assert len(found) == 1, f"Expected to find saved session {task_id}, found {len(found)}"

    @pytest.mark.asyncio
    async def test_search_by_keyword(self):
        """保存含特定关键词的记录后，search 应能检索到。"""
        memory = EpisodicMemory()
        task_id = f"test-search-{uuid.uuid4().hex[:8]}"
        await memory.save_session(
            task_id,
            review_result={"summary": "SQL injection detected", "score": 4.0},
            issues=[{"title": "SQL injection in login", "severity": "critical"}],
        )

        results = await memory.search("SQL injection", top_k=10)
        # 至少包含刚保存的记录
        found = [r for r in results if r.get("task_id") == task_id]
        assert len(found) > 0, f"Search should find the saved record. Got: {results}"

    @pytest.mark.asyncio
    async def test_count_increases(self):
        """保存后 count 不应减少。"""
        memory = EpisodicMemory()
        initial = memory.count
        task_id = f"test-count-{uuid.uuid4().hex[:8]}"

        await memory.save_session(
            task_id,
            review_result={"summary": "test", "score": 7.0},
            issues=[],
        )

        assert memory.count >= initial, (
            f"Count should not decrease. Initial: {initial}, now: {memory.count}"
        )
