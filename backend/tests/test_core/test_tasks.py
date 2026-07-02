"""
测试 Celery 异步任务 —— app.core.tasks.

覆盖 _run_review_pipeline 的成功 / 失败路径以及 run_review_task Celery 包装器。
所有外部依赖（review_graph / 数据库 / Redis 进度推送）均通过 mock 拦截，
不依赖真实 LLM、PostgreSQL 或 Redis。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core import tasks
from app.core.tasks import _run_review_pipeline, run_review_task

# ---- 公共测试数据 ----

TASK_ID = "00000000-0000-0000-0000-000000000001"
REQUEST_DATA = {
    "files": [{"path": "src/main.py", "content": "print('hi')"}],
    "repo_url": "https://github.com/test/repo",
    "branch": "main",
    "language": "python",
}
STARTED_AT = "2024-01-01T00:00:00"


def _build_final_state(style_count: int = 1, merged_count: int = 2) -> dict:
    """构造 review_graph.ainvoke 返回的 final_state。"""
    return {
        "report_score": 8.0,
        "report_summary": "ok",
        "report_html": "<html>report</html>",
        "style_results": [
            {"agent_type": "style", "severity": "warning"} for _ in range(style_count)
        ],
        "security_results": [],
        "architecture_results": [],
        "performance_results": [],
        "refactor_results": [],
        "_merged_results": [
            {"agent_type": "style", "severity": "warning", "file_path": "src/main.py"}
            for _ in range(merged_count)
        ],
        "_parsed_files": [{"path": "src/main.py"}],
        "agent_durations": {
            "parser": 10,
            "style": 20,
            "security": 30,
            "architecture": 40,
            "performance": 50,
            "refactor": 60,
            "arbitrator": 70,
        },
        "errors": [],
        "started_at": STARTED_AT,
        "completed_at": "2024-01-01T00:01:00",
    }


# ---- _run_review_pipeline 成功路径 ----


@pytest.mark.asyncio
async def test_run_review_pipeline_success():
    """成功路径：ainvoke 返回 final_state，_save_to_db 不报错。

    验证 _run_review_pipeline 返回 status=completed、score=8.0、issues_count 正确。
    """
    final_state = _build_final_state(style_count=1, merged_count=2)

    with patch.object(tasks, "review_graph", MagicMock()) as mock_graph, \
         patch.object(tasks, "_save_to_db", AsyncMock()) as mock_save, \
         patch.object(tasks, "fail_progress") as mock_fail, \
         patch.object(tasks, "update_progress") as _mock_update, \
         patch.object(tasks, "complete_progress") as _mock_complete:
        # review_graph.ainvoke 是 async，用 AsyncMock
        mock_graph.ainvoke = AsyncMock(return_value=final_state)

        result = await _run_review_pipeline(TASK_ID, REQUEST_DATA, STARTED_AT)

        # 基本返回字段
        assert result["task_id"] == TASK_ID
        assert result["status"] == "completed"
        assert result["score"] == 8.0
        assert result["summary"] == "ok"

        # issues_count：merged_count=2 > 0，取 merged 长度
        assert result["issues_count"] == 2

        # agent_stats：仅 style_results 非空
        assert result["stats"] == {"style": 1}

        # review_graph.ainvoke 被调用并 await 一次
        mock_graph.ainvoke.assert_awaited_once()

        # _save_to_db 被 await 一次，merged_results 长度等于 issues_count
        mock_save.assert_awaited_once()
        save_kwargs = mock_save.await_args.kwargs
        assert len(save_kwargs["merged_results"]) == 2
        assert len(save_kwargs["agent_timeline"]) == 8  # 8 个节点：parser + skill_scan + 5 agents + arbitrator
        assert save_kwargs["errors"] == []

        # 成功路径不应调用 fail_progress
        mock_fail.assert_not_called()


# ---- _run_review_pipeline 失败路径（graph 抛异常）----


@pytest.mark.asyncio
async def test_run_review_pipeline_graph_failure():
    """失败路径：review_graph.ainvoke 抛异常。

    验证 _run_review_pipeline 返回 status=failed 且 fail_progress 被调用。
    """
    with patch.object(tasks, "review_graph", MagicMock()) as mock_graph, \
         patch.object(tasks, "_save_to_db", AsyncMock()) as mock_save, \
         patch.object(tasks, "fail_progress") as mock_fail, \
         patch.object(tasks, "update_progress") as _mock_update2, \
         patch.object(tasks, "complete_progress") as _mock_complete2:
        # ainvoke 抛异常
        mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("graph boom"))

        result = await _run_review_pipeline(TASK_ID, REQUEST_DATA, STARTED_AT)

        # 返回失败摘要
        assert result["task_id"] == TASK_ID
        assert result["status"] == "failed"
        assert result["score"] == 0.0
        assert result["issues_count"] == 0
        assert "graph boom" in result["error"]

        # fail_progress 被调用一次，消息包含异常信息
        mock_fail.assert_called_once()
        call_args = mock_fail.call_args
        assert call_args[0][0] == TASK_ID  # 第一个位置参数是 task_id
        assert "graph boom" in call_args[0][1]

        # 失败路径不应调用 _save_to_db
        mock_save.assert_not_awaited()


# ---- run_review_task Celery 包装器 ----


def test_run_review_task_celery_wrapper():
    """验证 run_review_task（Celery task）通过 asyncio.run 调用
    _run_review_pipeline 并返回其结果。

    run_review_task 是 bind=True 的 Celery 任务，直接调用会同步执行函数体；
    这里 mock _run_review_pipeline 与 asyncio.run，断言包装逻辑正确，
    避免触发真实事件循环 / LLM / 数据库。
    """
    expected = {
        "task_id": TASK_ID,
        "status": "completed",
        "summary": "ok",
        "score": 8.0,
        "issues_count": 2,
        "stats": {"style": 1},
    }

    with patch.object(tasks, "_run_review_pipeline", AsyncMock(return_value=expected)) as mock_pipeline, \
         patch.object(tasks, "asyncio") as mock_asyncio, \
         patch.object(tasks, "fail_progress") as mock_fail:
        # asyncio.run 返回预期结果，避免真实事件循环
        mock_asyncio.run = MagicMock(return_value=expected)

        # 直接调用 Celery task 对象（同步执行函数体，bind=True 自动注入 self）
        result = run_review_task(TASK_ID, REQUEST_DATA, STARTED_AT)

        # 返回 asyncio.run 的结果
        assert result == expected
        assert result["status"] == "completed"

        # asyncio.run 被调用一次
        mock_asyncio.run.assert_called_once()

        # _run_review_pipeline 被调用一次，参数透传正确
        mock_pipeline.assert_called_once_with(TASK_ID, REQUEST_DATA, STARTED_AT)

        # 关闭未 await 的协程，避免 RuntimeWarning: coroutine was never awaited
        coro = mock_asyncio.run.call_args[0][0]
        coro.close()

        # 成功路径不应调用 fail_progress
        mock_fail.assert_not_called()
