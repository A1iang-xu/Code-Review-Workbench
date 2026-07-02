"""
MemoryManager tests.

验证 MemoryManager 单例行为、会话生命周期、上下文聚合，
以及对三层子记忆（semantic / episodic / procedural）的委托调用。
所有数据库与 LLM 依赖均通过 MagicMock 隔离，不触碰真实 PostgreSQL / Ollama / 智谱 API。
"""

import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.memory import MemoryManager
from app.core.memory.working import WorkingMemory


@pytest.fixture
def memory_manager():
    """提供一个干净的 MemoryManager 实例，内部组件全部 mock。

    由于 MemoryManager 是单例，每个测试前需重置 _instance；
    测试结束后再次重置，避免污染其他测试。
    """
    # 重置单例，确保拿到全新实例
    MemoryManager._instance = None

    with tempfile.TemporaryDirectory() as tmpdir:
        mm = MemoryManager(storage_path=tmpdir)
        # 用 MagicMock 替换三层子记忆，避免触碰真实 DB / LLM
        mm._semantic = MagicMock()
        mm._episodic = MagicMock()
        mm._procedural = MagicMock()
        # 重置最近审查缓存
        mm._recent_episodes_cache = []
        yield mm

    # 测试结束后清理单例
    MemoryManager._instance = None


class TestMemoryManagerSingleton:
    """验证 MemoryManager 的单例行为。"""

    def test_memory_manager_singleton(self):
        # 重置单例，从一个干净状态开始
        MemoryManager._instance = None
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                mm1 = MemoryManager(storage_path=tmpdir)
                mm2 = MemoryManager(storage_path=tmpdir)
                assert mm1 is mm2, "两次实例化应返回同一对象"

                # 重置 _instance 后再实例化应得到新对象（与之前不同）
                MemoryManager._instance = None
                mm3 = MemoryManager(storage_path=tmpdir)
                assert mm3 is not mm1, "重置 _instance 后应得到新对象"
        finally:
            MemoryManager._instance = None


class TestMemoryManagerSession:
    """验证会话管理。"""

    def test_new_session(self, memory_manager):
        wm = memory_manager.new_session(max_tokens=4000)
        assert isinstance(wm, WorkingMemory), (
            f"new_session 应返回 WorkingMemory 实例，实际: {type(wm)}"
        )
        assert memory_manager.working is wm, "working 属性应返回当前会话实例"


class TestMemoryManagerSystemContext:
    """验证系统上下文生成。"""

    def test_get_system_context_empty(self, memory_manager):
        # 三层记忆都返回空字符串，缓存也为空
        memory_manager._semantic.get_prompt_context.return_value = ""
        memory_manager._procedural.get_prompt_context.return_value = ""
        memory_manager._recent_episodes_cache = []

        ctx = memory_manager.get_system_context()
        assert ctx == "", f"空记忆应返回空字符串，实际: {ctx!r}"

    def test_get_system_context_with_data(self, memory_manager):
        semantic_ctx = "## 最佳实践\n1. [security] 使用参数化查询"
        procedural_ctx = "## 历史高频问题\n- [high] SQL injection (5 次)"
        memory_manager._semantic.get_prompt_context.return_value = semantic_ctx
        memory_manager._procedural.get_prompt_context.return_value = procedural_ctx
        memory_manager._recent_episodes_cache = []

        ctx = memory_manager.get_system_context()
        assert semantic_ctx in ctx, "上下文应包含语义记忆部分"
        assert procedural_ctx in ctx, "上下文应包含程序性记忆部分"
        # 验证拼接顺序：语义在前，程序性在后
        assert ctx.index(semantic_ctx) < ctx.index(procedural_ctx), (
            "语义记忆应拼接在程序性记忆之前"
        )


class TestMemoryManagerSaveSession:
    """验证会话保存逻辑。"""

    async def test_save_session_calls_episodic_and_procedural(self, memory_manager):
        # episodic.save_session 是异步方法，返回一个 episode 字典
        episode = {
            "task_id": "task-001",
            "timestamp": "2026-01-01T00:00:00",
            "score": 8,
            "issue_count": 2,
            "summary": "测试摘要",
        }
        memory_manager._episodic.save_session = AsyncMock(return_value=episode)
        memory_manager._procedural.record_batch = MagicMock()

        task_id = "task-001"
        review_result = {"summary": "ok", "score": 8}
        issues = [{"title": "issue1", "severity": "high"}]

        await memory_manager.save_session(task_id, review_result, issues)

        # 验证 episodic.save_session 被正确调用
        memory_manager._episodic.save_session.assert_awaited_once_with(
            task_id, review_result, issues
        )
        # 验证 procedural.record_batch 被正确调用
        memory_manager._procedural.record_batch.assert_called_once_with(issues)
        # 验证 recent_episodes_cache 被更新（新 episode 插入到缓存中）
        assert episode in memory_manager._recent_episodes_cache, (
            "save_session 应将新 episode 插入最近审查缓存"
        )
        assert len(memory_manager._recent_episodes_cache) == 1, (
            "缓存中应恰好包含一条记录"
        )


class TestMemoryManagerDelegation:
    """验证委托方法是否正确转发到对应子记忆。"""

    def test_add_rule_delegates_to_semantic(self, memory_manager):
        rule = {"title": "禁止使用 eval", "severity": "high", "category": "security"}
        memory_manager._semantic.add_rule = MagicMock()

        memory_manager.add_rule(rule)

        memory_manager._semantic.add_rule.assert_called_once_with(rule)

    def test_get_frequent_issues_delegates(self, memory_manager):
        expected = [
            {"issue_type": "sql_injection", "severity": "high", "count": 5},
            {"issue_type": "hardcoded_secret", "severity": "critical", "count": 3},
        ]
        memory_manager._procedural.get_frequent_issues = MagicMock(return_value=expected)

        result = memory_manager.get_frequent_issues(top_k=5)

        memory_manager._procedural.get_frequent_issues.assert_called_once_with(5)
        assert result == expected, "get_frequent_issues 应原样返回程序性记忆的结果"
