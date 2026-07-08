"""
测试 LangGraph 工作流编排器 (orchestrator) 的核心逻辑。

覆盖：
- build_review_graph(): 验证返回的图非空且包含 8 个核心节点
- parse_code_node(): 验证解析流程、记忆系统调用、返回字段
- _make_agent_review_node(): 验证工厂函数生成的节点属性

Mock 策略：
- 用 unittest.mock.patch 拦截 app.core.orchestrator._get_memory 返回 MagicMock
- 用 unittest.mock.patch 拦截 update_progress / complete_progress / fail_progress
- 额外拦截 LLMProvider.reasoning / utility，避免真实 LLM 调用
- 不调用 review_graph.ainvoke，只测节点函数
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.orchestrator import (
    _make_agent_review_node,
    build_review_graph,
    parse_code_node,
)


# 包含协作节点的完整节点列表（与 build_review_graph() 中 add_node 一致）
EXPECTED_NODES = {
    "parse_code",
    "skill_scan",
    "style_review",
    "security_review",
    "architecture_review",
    "performance_review",
    "refactor_review",
    "signal_exchange",
    "collab_style",
    "collab_security",
    "collab_architecture",
    "collab_performance",
    "collab_refactor",
    "arbitrate",
    "generate_report",
}


@pytest.fixture
def mock_memory():
    """构造一个 Mock 记忆系统。

    - new_session: 同步方法，返回 None
    - async_refresh: 异步方法，返回 None
    - get_system_context: 同步方法，返回空 dict（被 _get_agent_context 调用）
    """
    memory = MagicMock()
    memory.new_session = MagicMock(return_value=None)
    memory.async_refresh = AsyncMock(return_value=None)
    memory.get_system_context = MagicMock(return_value={})
    return memory


@pytest.fixture(autouse=True)
def mock_llm():
    """全局拦截 LLMProvider 的 reasoning / utility，避免真实 API 调用。

    即使 parse_code_node 本身不调用 LLM，也作为防御性 mock，
    确保后续扩展或工厂节点测试不会触发真实请求。
    """
    with patch(
        "app.core.agents.base.LLMProvider.reasoning",
        new=AsyncMock(return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="{}"))]),
    )), patch(
        "app.core.agents.base.LLMProvider.utility",
        new=AsyncMock(return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="{}"))]),
    )):
        yield


class TestBuildReviewGraph:
    """验证 build_review_graph() 构造的图结构。"""

    def test_build_review_graph(self):
        """图非空且包含所有节点（含协作节点）。"""
        graph = build_review_graph()

        # 图对象本身非空
        assert graph is not None

        # 兼容不同 langgraph 版本：优先从 .nodes 取
        node_names: set[str] = set()
        if hasattr(graph, "nodes") and getattr(graph, "nodes", None):
            node_names = set(graph.nodes.keys())
        elif hasattr(graph, "get_graph"):
            try:
                node_names = set(graph.get_graph().nodes.keys())
            except Exception:
                node_names = set()

        # __start__ / __end__ 是 langgraph 自动添加的伪节点
        missing = EXPECTED_NODES - node_names
        assert not missing, f"缺少节点: {missing}, 实际节点: {node_names}"


class TestParseCodeNode:
    """验证 parse_code_node 的核心行为。"""

    async def test_parse_code_node_basic(self, sample_files, mock_memory):
        """使用 conftest.py 的 sample_files fixture 测试基本解析流程。

        验证返回 dict 包含 _parsed_files、errors、agent_durations、progress=0.1，
        并验证 memory 的 async_refresh 和 new_session 被调用。
        """
        with patch("app.core.orchestrator._get_memory", return_value=mock_memory), \
             patch("app.core.orchestrator.update_progress") as mock_update_progress, \
             patch("app.core.orchestrator.complete_progress") as mock_complete_progress:

            state = {
                "task_id": "test-task-1",
                "files": sample_files,
                "language": "auto",
            }
            result = await parse_code_node(state)

            # 返回值必须是 dict
            assert isinstance(result, dict)

            # 必须包含要求的字段
            assert "_parsed_files" in result, "返回值缺少 _parsed_files"
            assert "errors" in result, "返回值缺少 errors"
            assert "agent_durations" in result, "返回值缺少 agent_durations"
            assert result["progress"] == 0.1, f"progress 应为 0.1, 实际: {result['progress']}"

            # sample_python_code 可被 AST 正常解析，_parsed_files 应有 1 个文件
            assert len(result["_parsed_files"]) == 1, (
                f"应解析出 1 个文件, 实际: {len(result['_parsed_files'])}"
            )
            # errors 应为空（解析成功）
            assert result["errors"] == [], f"errors 应为空, 实际: {result['errors']}"

            # 验证记忆系统被调用
            mock_memory.new_session.assert_called_once()
            mock_memory.async_refresh.assert_awaited_once()

            # task_id 非空时 update_progress 应被调用
            assert mock_update_progress.called, "update_progress 应被调用"
            # complete_progress / fail_progress 在 parse_code_node 中不应被调用
            mock_complete_progress.assert_not_called()

    async def test_parse_code_node_empty_files(self, mock_memory):
        """传入空 files 列表，验证不报错且 _parsed_files 为空。"""
        with patch("app.core.orchestrator._get_memory", return_value=mock_memory), \
             patch("app.core.orchestrator.update_progress"), \
             patch("app.core.orchestrator.complete_progress"):

            state = {
                "task_id": "test-task-empty",
                "files": [],
                "language": "auto",
            }
            # 不应抛出异常
            result = await parse_code_node(state)

            assert isinstance(result, dict)
            assert result["_parsed_files"] == [], (
                f"空文件列表应返回空 _parsed_files, 实际: {result['_parsed_files']}"
            )
            assert result["errors"] == [], (
                f"空文件列表 errors 应为空, 实际: {result['errors']}"
            )
            assert result["progress"] == 0.1

            # 记忆系统仍应被初始化（new_session / async_refresh 在解析前调用）
            mock_memory.new_session.assert_called_once()
            mock_memory.async_refresh.assert_awaited_once()


class TestMakeAgentReviewNode:
    """验证 _make_agent_review_node 工厂函数。"""

    def test_factory_creates_callable_with_correct_name(self):
        """工厂函数应返回可调用对象，且 __name__ 符合 {agent_type}_review_node 规范。"""
        from app.core.agents.style import StyleCheckerAgent

        node = _make_agent_review_node(
            "style", StyleCheckerAgent, 0.25, "style_results"
        )

        # 返回值应是可调用的协程函数
        assert callable(node), "工厂函数应返回可调用对象"
        # __name__ 应为 style_review_node（与 orchestrator 中其他节点保持一致）
        assert node.__name__ == "style_review_node", (
            f"节点 __name__ 应为 style_review_node, 实际: {node.__name__}"
        )


class TestReviewStateCollaborationFields:
    """验证 ReviewState 包含协作相关字段。"""

    def test_review_state_has_collaboration_fields(self):
        """ReviewState TypedDict 包含协作字段定义。"""
        from app.core.state import ReviewState
        hints = ReviewState.__annotations__
        assert "agent_signals" in hints
        assert "collaboration_results" in hints
        assert "collaboration_enabled" in hints
        assert "collaboration_round" in hints
        assert "active_collab_agents" in hints


class TestSignalExchangeNode:
    """signal_exchange_node 测试。"""

    @pytest.mark.asyncio
    async def test_disabled_collaboration_skips(self):
        """collaboration_enabled=False 时返回空 active 列表。"""
        from app.core.orchestrator import signal_exchange_node
        state = {
            "task_id": "",
            "collaboration_enabled": False,
            "agent_signals": [{"target_agent": "security"}],
        }
        result = await signal_exchange_node(state)
        assert result["active_collab_agents"] == []

    @pytest.mark.asyncio
    async def test_no_signals_skips(self):
        """无信号时返回空 active 列表。"""
        from app.core.orchestrator import signal_exchange_node
        state = {
            "task_id": "",
            "collaboration_enabled": True,
            "agent_signals": [],
        }
        result = await signal_exchange_node(state)
        assert result["active_collab_agents"] == []

    @pytest.mark.asyncio
    async def test_groups_signals_by_target(self):
        """按 target_agent 分组计算 active 列表。"""
        from app.core.orchestrator import signal_exchange_node
        state = {
            "task_id": "",
            "collaboration_enabled": True,
            "agent_signals": [
                {"target_agent": "security", "source_agent": "architecture"},
                {"target_agent": "security", "source_agent": "performance"},
                {"target_agent": "refactor", "source_agent": "security"},
            ],
        }
        result = await signal_exchange_node(state)
        assert set(result["active_collab_agents"]) == {"security", "refactor"}


class TestCollabNodeSkipLogic:
    """collab 节点跳过逻辑测试。"""

    @pytest.mark.asyncio
    async def test_collab_node_skips_when_not_active(self):
        """agent 不在 active 列表时返回空 dict。"""
        from app.core.orchestrator import _make_collab_review_node
        node = _make_collab_review_node("security", MagicMock)
        state = {
            "task_id": "",
            "active_collab_agents": ["refactor"],  # security 不在里面
            "agent_signals": [],
        }
        result = await node(state)
        assert result == {}
