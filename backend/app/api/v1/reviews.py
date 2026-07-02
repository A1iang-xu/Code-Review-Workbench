"""
审查 API 端点

POST /api/v1/reviews   — 提交代码审查任务（并行 5 Agent + 仲裁）
GET  /api/v1/reviews/{task_id} — 查询审查结果

审查任务通过 Celery 异步执行（解决 BackgroundTasks 进程重启丢失任务的问题）。
"""

import uuid
import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func

from app.config import get_settings
from app.core.tasks import run_review_task
from app.integrations.repo_fetcher import fetch_files_from_url
from app.models import async_session_factory
from app.models.review import ReviewTask, ReviewStatus
from app.models.agent_result import AgentResult
from app.models.report import ReviewReport
from app.api.v1.ws import update_progress, complete_progress, fail_progress

settings = get_settings()

router = APIRouter(tags=["reviews"])

# ============================================================
# 内存存储（热缓存，仅用于快速查询已完成的审查）
# ============================================================
# 修复内存泄漏：增加 TTL 机制，超过 TTL 的条目在访问时被清理。
# 同时限制最大容量，超过上限时淘汰最旧条目。
_task_store: dict[str, dict] = {}
_TASK_STORE_TTL_SECONDS = 3600  # 热缓存保留 1 小时
_TASK_STORE_MAX_SIZE = 200     # 最多保留 200 条热缓存
_task_store_timestamps: dict[str, float] = {}  # task_id -> 写入时间戳


def _task_store_set(task_id: str, data: dict) -> None:
    """写入热缓存并记录时间戳，必要时淘汰旧条目。"""
    import time as _time

    now = _time.time()
    _task_store[task_id] = data
    _task_store_timestamps[task_id] = now

    # 淘汰超过 TTL 的条目
    expired = [
        tid for tid, ts in _task_store_timestamps.items()
        if now - ts > _TASK_STORE_TTL_SECONDS
    ]
    for tid in expired:
        _task_store.pop(tid, None)
        _task_store_timestamps.pop(tid, None)

    # 超过容量上限时按时间顺序淘汰最旧条目
    if len(_task_store) > _TASK_STORE_MAX_SIZE:
        sorted_ids = sorted(
            _task_store_timestamps.items(), key=lambda kv: kv[1]
        )
        for tid, _ in sorted_ids[: len(_task_store) - _TASK_STORE_MAX_SIZE]:
            _task_store.pop(tid, None)
            _task_store_timestamps.pop(tid, None)


def _task_store_get(task_id: str) -> dict | None:
    """读取热缓存，若已过期则视为不存在并清理。"""
    import time as _time

    ts = _task_store_timestamps.get(task_id)
    if ts is None:
        return None
    if _time.time() - ts > _TASK_STORE_TTL_SECONDS:
        _task_store.pop(task_id, None)
        _task_store_timestamps.pop(task_id, None)
        return None
    return _task_store.get(task_id)


# ============================================================
# Pydantic 请求/响应模型
# ============================================================

class CodeFile(BaseModel):
    """单个代码文件的结构。"""
    path: str = Field(..., description="文件路径，如 'src/main.py'")
    content: str = Field(..., description="文件源代码内容")


class ReviewRequest(BaseModel):
    """审查请求结构。"""
    files: list[CodeFile] = Field(..., description="待审查的代码文件列表")
    repo_url: str = Field(default="", description="Git 仓库 URL（可选）")
    branch: str = Field(default="", description="分支名（可选）")
    language: str = Field(
        default="auto",
        description="审查语言: auto / python / go / typescript / javascript / java"
    )
    enabled_skills: list[str] = Field(
        default_factory=list,
        description="本次审查启用的 Skill 名称列表（空 = 仅 Agent 审查，不执行 Skill 扫描）"
    )


class ReviewResponse(BaseModel):
    """审查响应结构。"""
    task_id: str
    status: str
    summary: Optional[str] = None
    score: Optional[float] = None
    report_html: Optional[str] = None
    issues_count: Optional[int] = None
    stats: Optional[dict] = None  # 各 Agent 发现数
    issues: Optional[list[dict]] = None  # 具体问题列表
    agent_timeline: Optional[list[dict]] = None  # Agent 执行时间线
    files: Optional[list[dict]] = None  # 原始代码文件
    errors: Optional[list[str]] = None  # 审查过程中的错误信息


class ReviewListItem(BaseModel):
    """审查记录列表项。"""
    task_id: str
    repo_url: str = ""
    branch: str = ""
    status: str = "completed"
    score: float = 0
    issues_count: int = 0
    created_at: str = ""


class ReviewListResponse(BaseModel):
    """审查记录列表响应。"""
    total: int
    items: list[ReviewListItem]


# ============================================================
# 数据库查询辅助函数
# ============================================================

async def _repair_db_status(task_id: str, status: "ReviewStatus") -> bool:
    """修复数据库中的任务状态（Celery 完成但 _save_to_db 失败时调用）。

    Args:
        task_id: 任务 ID
        status: 应设置的目标状态（COMPLETED / FAILED）

    Returns:
        True 表示修复成功，False 表示修复失败
    """
    try:
        async with async_session_factory() as session:
            from uuid import UUID as UUIDType
            task = await session.get(ReviewTask, UUIDType(task_id))
            if task is None:
                return False
            task.status = status
            await session.commit()
            return True
    except Exception as e:
        print("[reviews] _repair_db_status 失败: {}".format(e))
        return False


async def _load_from_db(task_id: str) -> Optional[dict]:
    """从数据库加载审查结果。

    查询 ReviewTask 及关联的 AgentResult 列表，重建响应字典。
    未找到时返回 None。
    """
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(ReviewTask).where(ReviewTask.id == UUID(task_id))
            )
            task = result.scalar_one_or_none()
            if task is None:
                return None

            # 加载关联的 AgentResult 列表
            issues_result = await session.execute(
                select(AgentResult)
                .where(AgentResult.task_id == task.id)
                .order_by(AgentResult.created_at)
            )
            agent_results = issues_result.scalars().all()

            # 加载关联的 ReviewReport（评分、摘要、HTML 报告）
            report_result = await session.execute(
                select(ReviewReport).where(ReviewReport.task_id == task.id)
            )
            report = report_result.scalar_one_or_none()

            # 重建 issues 列表
            issues = []
            for ar in agent_results:
                issues.append({
                    "agent_type": ar.agent_type,
                    "severity": ar.severity,
                    "file_path": ar.file_path or "",
                    "line_start": ar.line_start,
                    "line_end": ar.line_end,
                    "category": ar.category or "",
                    "title": ar.title,
                    "description": ar.description or "",
                    "suggestion": ar.suggestion or "",
                    "code_snippet": ar.code_snippet or "",
                })

            status_str = task.status.value if task.status else "completed"
            # 从 ReviewReport.stats 恢复 agent_timeline（保存时存为 stats 快照）
            agent_timeline = report.stats if (report and isinstance(report.stats, list)) else []
            # 从 ReviewTask.config 恢复文件内容快照
            config = task.config if isinstance(task.config, dict) else {}
            files_snapshot = config.get("files", [])
            return {
                "task_id": str(task.id),
                "status": status_str,
                "summary": report.summary if report else "",
                "score": report.score if report else 0.0,
                "report_html": report.full_report_html if report else None,
                "issues_count": len(issues),
                "stats": {},
                "issues": issues,
                "agent_timeline": agent_timeline,
                "files": files_snapshot,
                "errors": None,
            }
    except Exception as e:
        print("[reviews] _load_from_db 失败: {}".format(e))
        return None


# ============================================================
# 端点实现
# ============================================================

@router.post("/reviews", response_model=ReviewResponse)
async def create_review(request: ReviewRequest):
    """提交代码审查任务（异步）。

    立即返回 task_id（status=running），通过 Celery 异步执行 LangGraph 审查流水线：
    parse_code → [5 Agent 并行审查] → arbitrate → generate_report

    进度通过 SSE 端点 GET /reviews/{task_id}/stream 实时推送。
    完成后结果存入数据库，可通过 GET /reviews/{task_id} 查询。

    如果提供了 repo_url，会先从 GitHub 拉取文件内容。
    """
    task_id = str(uuid.uuid4())
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # 如果提供了 repo_url，从 GitHub 拉取文件
    files_for_review = list(request.files)
    if request.repo_url:
        fetched, err = await fetch_files_from_url(request.repo_url)
        if err:
            raise HTTPException(status_code=400, detail=f"拉取仓库文件失败: {err}")
        if not fetched:
            raise HTTPException(status_code=400, detail="未从仓库拉取到任何代码文件")
        # 合并拉取的文件（覆盖同路径）
        existing_paths = {f.path for f in files_for_review}
        for f in fetched:
            if f["path"] not in existing_paths:
                files_for_review.append(CodeFile(path=f["path"], content=f["content"]))

    if not files_for_review:
        raise HTTPException(status_code=400, detail="没有可审查的文件")

    # 文件数量校验
    if len(files_for_review) > settings.MAX_FILES_PER_REVIEW:
        raise HTTPException(
            status_code=400,
            detail=f"文件数量超过上限: {len(files_for_review)} > {settings.MAX_FILES_PER_REVIEW}",
        )

    # 文件大小校验
    for file in files_for_review:
        if len(file.content) > settings.MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"文件 {file.path} 超过大小上限: {len(file.content)} > {settings.MAX_FILE_SIZE_BYTES} 字节",
            )

    # 初始化 SSE 进度存储
    update_progress(task_id, 0.0, "pending", "running")

    # 立即返回 running 状态响应
    initial_response = ReviewResponse(
        task_id=task_id,
        status="running",
        summary="审查任务已提交，正在执行中...",
        files=[f.model_dump() for f in files_for_review],
    )
    _task_store_set(task_id, initial_response.model_dump())

    # 构建更新后的 request（含拉取的文件），传给 Celery 任务
    updated_request = request.model_copy(update={"files": files_for_review})

    # 在数据库中创建 running 状态的 ReviewTask，确保 GET 端点能查到
    # （即使 Celery 任务丢失，GET 也能通过超时机制检测到）
    try:
        async with async_session_factory() as session:
            from uuid import UUID as UUIDType
            started_dt = datetime.datetime.fromisoformat(started_at)
            task = ReviewTask(
                id=UUIDType(task_id),
                repo_url=request.repo_url or None,
                branch=request.branch or None,
                status=ReviewStatus.RUNNING,
                file_paths=[f.path for f in files_for_review],
                config={"files": [f.model_dump() for f in files_for_review]},
                created_at=started_dt,
            )
            session.add(task)
            await session.commit()
    except Exception as e:
        print("[reviews] 创建 ReviewTask 失败: {}".format(e))

    # 通过 Celery 异步执行审查流水线（解决 BackgroundTasks 进程重启丢失任务的问题）
    run_review_task.delay(
        task_id=task_id,
        request_data=updated_request.model_dump(),
        started_at=started_at,
    )

    return initial_response


@router.get("/reviews", response_model=ReviewListResponse)
async def list_reviews(
    limit: int = 20,
    offset: int = 0,
    search: str = "",
    repo: str = "",
    min_score: float = 0,
    max_score: float = 10,
    status: str = "",
):
    """列出审查记录（分页 + 搜索 + 过滤）。

    性能修复：原实现对每个 task 单独查询 issues 数量（N+1）和 report 评分，
    且 score/search 过滤在 Python 层做导致 limit/offset 失效。
    现改为单条 SQL 通过 outerjoin + 聚合一次性取出，过滤条件下推到 SQL 层。
    """
    from app.utils.logger import get_logger

    logger = get_logger(__name__)
    try:
        async with async_session_factory() as session:
            # 单条聚合查询：ReviewTask LEFT JOIN ReviewReport（取 score）
            #                 LEFT JOIN AgentResult（COUNT issues）
            # 使用 func.coalesce 将 NULL 转为 0，避免前端处理
            issues_count_col = func.coalesce(
                func.count(AgentResult.id), 0
            ).label("issues_count")
            score_col = func.coalesce(ReviewReport.score, 0.0).label("score")

            base_query = (
                select(
                    ReviewTask,
                    score_col,
                    issues_count_col,
                )
                .outerjoin(ReviewReport, ReviewReport.task_id == ReviewTask.id)
                .outerjoin(AgentResult, AgentResult.task_id == ReviewTask.id)
                .group_by(ReviewTask.id, ReviewReport.score)
            )

            # ---- 过滤条件下推到 SQL 层 ----
            # 仓库过滤
            if repo:
                base_query = base_query.where(
                    ReviewTask.repo_url.ilike(f"%{repo}%")
                )

            # 状态过滤
            if status:
                try:
                    status_enum = ReviewStatus(status)
                    base_query = base_query.where(ReviewTask.status == status_enum)
                except ValueError:
                    pass

            # 评分过滤（原在 Python 层，现下推 SQL）
            base_query = base_query.where(score_col >= min_score)
            base_query = base_query.where(score_col <= max_score)

            # 关键词搜索（原在 Python 层，现下推 SQL）
            if search:
                # PostgreSQL ILIKE 大小写不敏感
                base_query = base_query.where(
                    (ReviewTask.repo_url.ilike(f"%{search}%"))
                    | (ReviewTask.branch.ilike(f"%{search}%"))
                )

            # 总数（在分页前计算，反映过滤后的真实数量）
            count_subquery = base_query.subquery()
            count_query = select(func.count()).select_from(count_subquery)
            total_result = await session.execute(count_query)
            total = total_result.scalar() or 0

            # 分页查询
            page_query = (
                base_query
                .order_by(ReviewTask.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(page_query)

            items = []
            for row in result.all():
                task = row[0]
                score = row[1] or 0.0
                issues_count = row[2] or 0
                items.append(
                    ReviewListItem(
                        task_id=str(task.id),
                        repo_url=task.repo_url or "",
                        branch=task.branch or "",
                        status=task.status.value if task.status else "completed",
                        score=float(score),
                        issues_count=int(issues_count),
                        created_at=task.created_at.isoformat() if task.created_at else "",
                    )
                )

            return ReviewListResponse(total=total, items=items)
    except Exception as e:
        # 修复：原直接返回空列表掩盖错误，前端无法区分"无数据"和"服务异常"
        # 现改为记录日志并抛出，由全局异常处理器统一返回 500
        logger.exception("[reviews] list_reviews 失败: %s", e)
        raise


@router.get("/reviews/stats/summary")
async def get_review_stats():
    """获取审查统计摘要。"""
    try:
        async with async_session_factory() as session:
            # 审查总数
            total_result = await session.execute(select(func.count(ReviewTask.id)))
            total_reviews = total_result.scalar() or 0

            # 平均评分 - 从 ReviewReport 表查询
            score_result = await session.execute(
                select(func.avg(ReviewReport.score)).where(ReviewReport.score.isnot(None))
            )
            avg_score = round(score_result.scalar() or 0, 1)

            # 已注册 Skill 数量
            from app.core.skills.registry import SkillRegistry
            registry = SkillRegistry()
            skill_count = registry.count

            return {
                "total_reviews": total_reviews,
                "avg_score": avg_score,
                "active_agents": 5,  # 5 个审查 Agent
                "registered_skills": skill_count,
            }
    except Exception as e:
        print("[reviews] get_review_stats 失败: {}".format(e))
        return {
            "total_reviews": 0,
            "avg_score": 0,
            "active_agents": 5,
            "registered_skills": 0,
        }


@router.get("/reviews/{task_id}", response_model=ReviewResponse)
async def get_review(task_id: str):
    """查询审查结果。

    优先从内存热缓存获取；缓存中状态仍为 running 时回退数据库
    （Celery 在独立进程完成后无法更新内存缓存，需查 DB 确认真实状态）；
    数据库中状态为 running 且超过 10 分钟未完成，判定为任务丢失，返回 failed。
    """
    # 1. 热缓存：仅在已完成时直接返回
    cached = _task_store_get(task_id)
    if cached is not None and cached.get("status") in ("completed", "failed"):
        return cached

    # 2. 数据库：缓存未命中或仍 running 时查询（Celery 可能已完成但未更新缓存）
    db_data = await _load_from_db(task_id)
    if db_data is not None:
        db_status = db_data.get("status")
        # 数据库显示 running 时，检查 Redis 进度存储以判定真实状态
        # （Celery 可能已完成审查但 _save_to_db 失败/延迟，Redis 是实时进度）
        if db_status == "running":
            from app.api.v1.ws import _get_progress
            redis_state = _get_progress(task_id)
            redis_status = redis_state.get("status", "running")

            if redis_status == "completed":
                # Celery 已完成但数据库未更新 — 修复数据库状态后重新加载完整数据
                # 不直接构造空响应，避免 issues/score 等字段为空
                await _repair_db_status(task_id, ReviewStatus.COMPLETED)
                refreshed = await _load_from_db(task_id)
                if refreshed is not None and refreshed.get("status") == "completed":
                    _task_store_set(task_id, refreshed)
                    return refreshed
                # 数据库仍无完整数据（_save_to_db 全部失败）— 返回 running 让前端继续等待
                # 不写入 _task_store 缓存，避免后续永远返回空壳
                return db_data

            if redis_status == "failed":
                await _repair_db_status(task_id, ReviewStatus.FAILED)
                refreshed = await _load_from_db(task_id)
                if refreshed is not None and refreshed.get("status") == "failed":
                    _task_store_set(task_id, refreshed)
                    return refreshed
                return db_data

            # Redis 也是 running — 检查是否真的超时（Celery 崩溃/重启）
            try:
                async with async_session_factory() as session:
                    from uuid import UUID as UUIDType
                    task = await session.get(ReviewTask, UUIDType(task_id))
                    if task and task.created_at:
                        elapsed = (
                            datetime.datetime.now(datetime.timezone.utc)
                            - task.created_at
                        ).total_seconds()
                        if elapsed > settings.REVIEW_TIMEOUT_SECONDS:
                            task.status = ReviewStatus.FAILED
                            await session.commit()
                            # 重新加载完整数据
                            refreshed = await _load_from_db(task_id)
                            if refreshed is not None:
                                _task_store_set(task_id, refreshed)
                                return refreshed
            except Exception as e:
                print("[reviews] 超时检测失败: {}".format(e))

        # 数据库已确认完成，更新内存缓存避免后续重复查询
        if db_status in ("completed", "failed"):
            _task_store_set(task_id, db_data)
        return db_data

    # 3. 缓存仍为 running 且数据库无记录：返回缓存的 running 状态（任务进行中）
    if cached is not None:
        return cached

    # 4. 占位响应
    return ReviewResponse(
        task_id=task_id,
        status="pending",
        summary="审查任务尚未完成或不存在。",
    )


@router.get("/reviews/{task_id}/export")
async def export_review(task_id: str, format: str = "markdown"):
    """导出审查报告为 Markdown 或 PDF。

    Args:
        task_id: 审查任务 ID
        format: 导出格式（markdown / pdf）
    """
    # 加载审查结果（同样需回退数据库，避免缓存 running 状态导致导出空报告）
    cached = _task_store_get(task_id)
    if cached is not None and cached.get("status") in ("completed", "failed"):
        data = cached
    else:
        data = await _load_from_db(task_id)

    if data is None:
        raise HTTPException(status_code=404, detail="审查任务不存在")

    if format == "markdown":
        content = _build_markdown_report(data)
        return Response(
            content=content,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="review_{task_id}.md"'
            },
        )
    elif format == "pdf":
        # PDF 导出：将 Markdown 转为 HTML 再下载（前端可打印为 PDF）
        html_content = _build_html_report(data)
        return Response(
            content=html_content,
            media_type="text/html",
            headers={
                "Content-Disposition": f'attachment; filename="review_{task_id}.html"'
            },
        )
    else:
        raise HTTPException(status_code=400, detail=f"不支持的格式: {format}")


def _build_markdown_report(data: dict) -> str:
    """构建 Markdown 格式的审查报告。"""
    lines: list[str] = []
    lines.append(f"# 代码审查报告")
    lines.append(f"")
    lines.append(f"**任务 ID:** {data.get('task_id', '')}")
    lines.append(f"**状态:** {data.get('status', '')}")
    lines.append(f"**评分:** {data.get('score', 0)}/10")
    lines.append(f"**问题数:** {data.get('issues_count', 0)}")
    lines.append(f"")
    lines.append(f"## 摘要")
    lines.append(f"")
    lines.append(data.get("summary", "无摘要"))
    lines.append(f"")

    # Agent 统计
    stats = data.get("stats", {})
    if stats:
        lines.append(f"## Agent 发现统计")
        lines.append(f"")
        lines.append(f"| Agent | 发现数 |")
        lines.append(f"|-------|--------|")
        for agent, count in stats.items():
            lines.append(f"| {agent} | {count} |")
        lines.append(f"")

    # 问题列表
    issues = data.get("issues", [])
    if issues:
        lines.append(f"## 问题详情")
        lines.append(f"")
        for i, issue in enumerate(issues, 1):
            sev = issue.get("severity", "info").upper()
            lines.append(f"### {i}. [{sev}] {issue.get('title', '无标题')}")
            lines.append(f"")
            lines.append(f"- **文件:** `{issue.get('file_path', '')}:{issue.get('line_start', 0)}`")
            lines.append(f"- **分类:** {issue.get('category', '')}")
            lines.append(f"- **Agent:** {issue.get('agent_type', '')}")
            if issue.get("description"):
                lines.append(f"- **描述:** {issue['description']}")
            if issue.get("suggestion"):
                lines.append(f"- **建议:** {issue['suggestion']}")
            lines.append(f"")

    lines.append(f"---")
    lines.append(f"*由 Code Review Workbench 自动生成*")
    return "\n".join(lines)


def _build_html_report(data: dict) -> str:
    """构建 HTML 格式的审查报告（可打印为 PDF）。"""
    md_content = _build_markdown_report(data)
    # 简单的 HTML 包装
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>审查报告 - {data.get('task_id', '')}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.6; color: #333; }}
h1 {{ color: #1e40af; border-bottom: 2px solid #e5e7eb; padding-bottom: 10px; }}
h2 {{ color: #374151; margin-top: 30px; }}
h3 {{ color: #4b5563; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th, td {{ border: 1px solid #e5e7eb; padding: 8px 12px; text-align: left; }}
th {{ background: #f9fafb; }}
code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
@media print {{ body {{ max-width: none; }} }}
</style>
</head>
<body>
<pre style="white-space: pre-wrap; font-family: inherit;">{md_content}</pre>
</body>
</html>"""
