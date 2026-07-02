"""
Celery 异步任务

将审查流水线从 FastAPI BackgroundTasks 迁移到 Celery，
解决进程重启时丢失任务的问题。

任务通过 Celery worker 异步执行，进度通过 Redis 共享给 SSE 端点。
"""

import asyncio
import datetime
from typing import Any

from app.core.celery_app import celery_app
from app.core.orchestrator import review_graph
from app.core.state import ReviewState
from app.api.v1.ws import fail_progress


@celery_app.task(
    name="app.core.tasks.run_review_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def run_review_task(
    self,
    task_id: str,
    request_data: dict,
    started_at: str,
) -> dict[str, Any]:
    """Celery 任务：执行代码审查流水线。

    在 Celery worker 进程中运行，通过 asyncio.run() 调用异步流水线。
    进度和结果通过 Redis 共享给 FastAPI 进程的 SSE 端点。

    Args:
        task_id: 审查任务 ID
        request_data: 序列化的 ReviewRequest（files、repo_url、branch、language）
        started_at: 任务开始时间 ISO 字符串

    Returns:
        审查结果摘要（task_id、status、score、issues_count）
    """
    try:
        return asyncio.run(_run_review_pipeline(task_id, request_data, started_at))
    except Exception as e:
        fail_progress(task_id, f"Celery 任务执行失败: {str(e)}")
        # 重试（仅对可重试异常）
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        return {
            "task_id": task_id,
            "status": "failed",
            "error": str(e),
            "score": 0.0,
            "issues_count": 0,
        }


async def _run_review_pipeline(
    task_id: str,
    request_data: dict,
    started_at: str,
) -> dict[str, Any]:
    """异步执行审查流水线（与 reviews.py 中的逻辑一致）。

    完成后将结果持久化到数据库，进度通过 Redis 推送给 SSE 客户端。
    """
    # 构建初始状态
    initial_state: ReviewState = {
        "task_id": task_id,
        "repo_url": request_data.get("repo_url", ""),
        "branch": request_data.get("branch", ""),
        "language": request_data.get("language", "auto"),
        "files": request_data.get("files", []),
        "enabled_skills": request_data.get("enabled_skills", []),
        "skill_results": [],
        "current_stage": "parse_code",
        "progress": 0.0,
        "style_results": [],
        "security_results": [],
        "architecture_results": [],
        "performance_results": [],
        "refactor_results": [],
        "_parsed_files": [],
        "_merged_results": [],
        "report_summary": "",
        "report_score": 0.0,
        "report_html": "",
        "errors": [],
        "agent_durations": {},
        "started_at": started_at,
        "completed_at": "",
    }

    # 执行审查流水线
    try:
        final_state = await review_graph.ainvoke(initial_state)
    except Exception as e:
        fail_progress(task_id, f"审查流水线执行失败: {str(e)}")
        return {
            "task_id": task_id,
            "status": "failed",
            "error": str(e),
            "score": 0.0,
            "issues_count": 0,
        }

    # 统计问题总数和各 Agent 发现数
    all_results: list = []
    agent_stats: dict[str, int] = {}

    result_keys = [
        ("style_results", "style"),
        ("security_results", "security"),
        ("architecture_results", "architecture"),
        ("performance_results", "performance"),
        ("refactor_results", "refactor"),
        ("skill_results", "skill"),
    ]

    for key, agent_name in result_keys:
        results = final_state.get(key, [])
        all_results.extend(results)
        if results:
            agent_stats[agent_name] = len(results)

    errors = final_state.get("errors", [])
    merged = final_state.get("_merged_results", [])
    merged_count = len(merged)
    issues_count = merged_count if merged_count > 0 else len(all_results)
    issues = merged if merged_count > 0 else all_results

    # 构建 Agent 时间线
    durations = final_state.get("agent_durations", {})
    parsed_files = final_state.get("_parsed_files", [])
    skill_findings = final_state.get("skill_results", [])
    agent_timeline = [
        {"agent_type": "parser", "display_name": "代码解析", "status": "completed",
         "duration_ms": durations.get("parser", 0), "finding_count": len(parsed_files)},
        {"agent_type": "skill_scan", "display_name": "Skill 扫描", "status": "completed",
         "duration_ms": durations.get("skill_scan", 0), "finding_count": len(skill_findings)},
        {"agent_type": "style", "display_name": "风格检查", "status": "completed",
         "duration_ms": durations.get("style", 0), "finding_count": agent_stats.get("style", 0)},
        {"agent_type": "security", "display_name": "安全审计", "status": "completed",
         "duration_ms": durations.get("security", 0), "finding_count": agent_stats.get("security", 0)},
        {"agent_type": "architecture", "display_name": "架构分析", "status": "completed",
         "duration_ms": durations.get("architecture", 0), "finding_count": agent_stats.get("architecture", 0)},
        {"agent_type": "performance", "display_name": "性能分析", "status": "completed",
         "duration_ms": durations.get("performance", 0), "finding_count": agent_stats.get("performance", 0)},
        {"agent_type": "refactor", "display_name": "重构建议", "status": "completed",
         "duration_ms": durations.get("refactor", 0), "finding_count": agent_stats.get("refactor", 0)},
        {"agent_type": "arbitrator", "display_name": "仲裁汇总", "status": "completed",
         "duration_ms": durations.get("arbitrator", 0), "finding_count": issues_count},
    ]

    # 持久化到数据库
    await _save_to_db(
        task_id=task_id,
        request_data=request_data,
        final_state=final_state,
        merged_results=issues,
        agent_timeline=agent_timeline,
        errors=errors,
    )

    score = final_state.get("report_score", 0.0)
    summary = final_state.get("report_summary", "")

    return {
        "task_id": task_id,
        "status": "completed",
        "summary": summary,
        "score": score,
        "issues_count": issues_count,
        "stats": agent_stats,
    }


async def _save_to_db(
    task_id: str,
    request_data: dict,
    final_state: dict,
    merged_results: list,
    agent_timeline: list,
    errors: list,
) -> None:
    """将审查结果持久化到 PostgreSQL（带重试，独立 engine 隔离）。

    使用独立的 engine 实例，避免与 orchestrator 中的 memory.save_session()
    共享连接池导致的 asyncpg "another operation is in progress" 错误。
    """
    import traceback
    from uuid import UUID
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    from app.config import get_settings
    from app.models.review import ReviewTask, ReviewStatus
    from app.models.agent_result import AgentResult
    from app.models.report import ReviewReport

    started_at_str = final_state.get("started_at", "")
    created_at = None
    if started_at_str:
        try:
            created_at = datetime.datetime.fromisoformat(started_at_str)
        except (ValueError, TypeError):
            created_at = None

    status = ReviewStatus.FAILED if errors else ReviewStatus.COMPLETED
    file_paths = [f["path"] for f in request_data.get("files", [])]
    files_snapshot = request_data.get("files", [])

    # 独立 engine：避免与 memory session 共享连接池
    _settings = get_settings()
    save_engine = create_async_engine(
        _settings.DATABASE_URL_ASYNC,
        pool_size=5,
        max_overflow=5,
        echo=False,  # 关闭 SQL 日志减少干扰
        pool_pre_ping=True,  # 连接前检测活性
    )
    SaveSession = async_sessionmaker(save_engine, expire_on_commit=False)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with SaveSession() as session:
                # POST 时已创建 running 状态的 ReviewTask，此处更新状态
                existing = await session.get(ReviewTask, UUID(task_id))
                if existing is not None:
                    existing.status = status
                    existing.file_paths = file_paths
                    existing.config = {"files": files_snapshot}
                    if created_at is not None:
                        existing.created_at = created_at
                else:
                    # 兜底：POST 未创建记录时直接插入
                    task = ReviewTask(
                        id=UUID(task_id),
                        repo_url=request_data.get("repo_url") or None,
                        branch=request_data.get("branch") or None,
                        status=status,
                        file_paths=file_paths,
                        config={"files": files_snapshot},
                        created_at=created_at,
                    )
                    session.add(task)

                for issue in merged_results:
                    agent_result = AgentResult(
                        task_id=UUID(task_id),
                        agent_type=issue.get("agent_type", "unknown"),
                        severity=issue.get("severity", "info"),
                        file_path=issue.get("file_path") or issue.get("path"),
                        line_start=issue.get("line_start") or issue.get("line"),
                        line_end=issue.get("line_end"),
                        category=issue.get("category"),
                        title=issue.get("title") or issue.get("message", ""),
                        description=issue.get("description") or issue.get("message"),
                        suggestion=issue.get("suggestion") or issue.get("fix"),
                        code_snippet=issue.get("code_snippet") or issue.get("code"),
                    )
                    session.add(agent_result)

                report = ReviewReport(
                    task_id=UUID(task_id),
                    summary=final_state.get("report_summary", ""),
                    score=final_state.get("report_score", 0.0),
                    stats=agent_timeline,
                    full_report_html=final_state.get("report_html", ""),
                )
                session.add(report)

                await session.commit()
                if attempt > 0:
                    print("[celery tasks] _save_to_db 重试成功 (attempt={})".format(attempt))
                await save_engine.dispose()
                return  # 成功则退出

        except Exception as e:
            print("[celery tasks] _save_to_db 第 {} 次失败: {}".format(attempt + 1, e))
            traceback.print_exc()
            await asyncio.sleep(1 * (attempt + 1))  # 递增退避

    # 全部重试失败：尝试只更新状态（最小化写入）
    print("[celery tasks] _save_to_db 全部失败，尝试仅更新状态")
    try:
        async with SaveSession() as session:
            existing = await session.get(ReviewTask, UUID(task_id))
            if existing is not None:
                existing.status = status
                await session.commit()
                print("[celery tasks] 仅状态更新成功")
    except Exception as e:
        print("[celery tasks] 仅状态更新也失败: {}".format(e))
    finally:
        await save_engine.dispose()
