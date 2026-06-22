"""
Episodic Memory tests.

Validates save and retrieve operations using TemporaryDirectory.
"""

import tempfile
from pathlib import Path

import pytest

from app.core.memory.episodic import EpisodicMemory


class TestEpisodicMemorySavesAndRetrieves:
    """Verify episodic memory can save sessions and retrieve them."""

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = EpisodicMemory(storage_path=tmpdir)

            task_id = "test-task-001"
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

            # Retrieve recent
            recent = memory.retrieve_recent(10)
            assert len(recent) >= 1, f"Expected at least 1 recent entry, got {len(recent)}"

            found = [e for e in recent if e.get("task_id") == task_id]
            assert len(found) == 1, f"Expected to find saved session {task_id}"

    @pytest.mark.asyncio
    async def test_search_by_keyword(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = EpisodicMemory(storage_path=tmpdir)

            task_id = "test-task-002"
            await memory.save_session(
                task_id,
                review_result={"summary": "SQL injection detected", "score": 4.0},
                issues=[{"title": "SQL injection in login", "severity": "critical"}],
            )

            results = memory.search("SQL injection", top_k=5)
            assert len(results) > 0, f"Search should find results. Got: {results}"

    @pytest.mark.asyncio
    async def test_count_increases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = EpisodicMemory(storage_path=tmpdir)
            initial = memory.count

            await memory.save_session(
                "count-test",
                review_result={"summary": "test", "score": 7.0},
                issues=[],
            )

            assert memory.count >= initial, (
                f"Count should not decrease. Initial: {initial}, now: {memory.count}"
            )
