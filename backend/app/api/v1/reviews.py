"""
审查 API 端点

POST /api/v1/reviews   — 提交代码审查任务（并行 5 Agent + 仲裁）
GET  /api/v1/reviews/{task_id} — 查询审查结果
"""

import uuid
import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func

from app.config import get_settings
from app.core.orchestrator import review_graph
from app.core.state import ReviewState
from app.models import async_session_factory
from app.models.review import ReviewTask, ReviewStatus
from app.models.agent_result import AgentResult
from app.models.report import ReviewReport

settings = get_settings()

router = APIRouter(tags=["reviews"])

# ============================================================
# 内存存储（阶段三将替换为持久化存储）
# ============================================================
_task_store: dict[str, dict] = {}


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
# 数据库持久化辅助函数
# ============================================================

async def _save_to_db(
    task_id: str,
    request: ReviewRequest,
    final_state: dict,
    all_results: list,
    merged_results: list,
    score: float,
    summary: str,
    report_html: str,
    agent_timeline: list,
    errors: list,
) -> None:
    """将审查结果持久化到 PostgreSQL。

    写入 ReviewTask 记录及每条 AgentResult。
    任何异常都被捕获并打印，不会影响 API 响应。
    """
    try:
        # 解析 started_at（ISO 字符串 -> datetime）
        started_at_str = final_state.get("started_at", "")
        created_at = None
        if started_at_str:
            try:
                created_at = datetime.datetime.fromisoformat(started_at_str)
            except (ValueError, TypeError):
                created_at = None

        # 判断状态：有错误则 FAILED，否则 COMPLETED
        status = ReviewStatus.FAILED if errors else ReviewStatus.COMPLETED

        # 文件路径列表（存为 JSONB）
        file_paths = [f.path for f in request.files]

        async with async_session_factory() as session:
            # 插入 ReviewTask
            task = ReviewTask(
                id=UUID(task_id),
                repo_url=request.repo_url or None,
                branch=request.branch or None,
                status=status,
                file_paths=file_paths,
                created_at=created_at,
            )
            session.add(task)

            # 插入每条 AgentResult
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

            # 插入 ReviewReport（评分、摘要、HTML 报告）
            report = ReviewReport(
                task_id=UUID(task_id),
                summary=summary,
                score=score,
                stats=agent_timeline,  # 复用 timeline 作为 stats 快照
                full_report_html=report_html,
            )
            session.add(report)

            await session.commit()
    except Exception as e:
        # 持久化失败不影响 API 响应
        try:
            await session.rollback()
        except Exception:
            pass
        print("[reviews] _save_to_db 失败: {}".format(e))


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
            return {
                "task_id": str(task.id),
                "status": status_str,
                "summary": report.summary if report else "",
                "score": report.score if report else 0.0,
                "report_html": report.full_report_html if report else None,
                "issues_count": len(issues),
                "stats": {},
                "issues": issues,
                "agent_timeline": [],
                "files": [],
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
    """提交代码审查任务。

    接收代码文件列表，启动 LangGraph 审查流水线：
    parse_code → [5 Agent 并行审查] → arbitrate → generate_report

    5 个 Agent 并行执行：
    - StyleChecker：代码风格与命名规范
    - SecurityAuditor：安全漏洞检测（正则 + LLM）
    - ArchitectureAnalyzer：依赖图分析 + 架构评估
    - PerformanceProfiler：圈复杂度 + 性能分析
    - RefactorAdvisor：代码坏味道 + 重构方案

    审查完成后由 ArbitratorAgent 汇总去重、评分并生成 HTML 报告。
    """
    task_id = str(uuid.uuid4())
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # 文件数量校验
    if len(request.files) > settings.MAX_FILES_PER_REVIEW:
        raise HTTPException(
            status_code=400,
            detail=f"文件数量超过上限: {len(request.files)} > {settings.MAX_FILES_PER_REVIEW}",
        )

    # 文件大小校验
    for file in request.files:
        if len(file.content) > settings.MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"文件 {file.path} 超过大小上限: {len(file.content)} > {settings.MAX_FILE_SIZE_BYTES} 字节",
            )

    # 构建初始状态
    initial_state: ReviewState = {
        "task_id": task_id,
        "repo_url": request.repo_url,
        "branch": request.branch,
        "language": request.language,
        "files": [f.model_dump() for f in request.files],
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
        failed_response = ReviewResponse(
            task_id=task_id,
            status="failed",
            summary=f"审查流水线执行失败: {str(e)}",
        )
        _task_store[task_id] = failed_response.model_dump()
        return failed_response

    # 统计问题总数和各 Agent 发现数
    all_results: list = []
    agent_stats: dict[str, int] = {}

    result_keys = [
        ("style_results", "style"),
        ("security_results", "security"),
        ("architecture_results", "architecture"),
        ("performance_results", "performance"),
        ("refactor_results", "refactor"),
    ]

    for key, agent_name in result_keys:
        results = final_state.get(key, [])
        all_results.extend(results)
        if results:
            agent_stats[agent_name] = len(results)

    errors = final_state.get("errors", [])
    merged = final_state.get("_merged_results", [])
    merged_count = len(merged)
    # 如果仲裁成功，使用去重后的数量
    issues_count = merged_count if merged_count > 0 else len(all_results)
    issues = merged if merged_count > 0 else all_results

    # 构建 Agent 时间线（使用真实执行耗时）
    durations = final_state.get("agent_durations", {})
    parsed_files = final_state.get("_parsed_files", [])
    agent_timeline = [
        {
            "agent_type": "parser",
            "display_name": "代码解析",
            "status": "completed",
            "duration_ms": durations.get("parser", 0),
            "finding_count": len(parsed_files),
        },
        {
            "agent_type": "style",
            "display_name": "风格检查",
            "status": "completed",
            "duration_ms": durations.get("style", 0),
            "finding_count": agent_stats.get("style", 0),
        },
        {
            "agent_type": "security",
            "display_name": "安全审计",
            "status": "completed",
            "duration_ms": durations.get("security", 0),
            "finding_count": agent_stats.get("security", 0),
        },
        {
            "agent_type": "architecture",
            "display_name": "架构分析",
            "status": "completed",
            "duration_ms": durations.get("architecture", 0),
            "finding_count": agent_stats.get("architecture", 0),
        },
        {
            "agent_type": "performance",
            "display_name": "性能分析",
            "status": "completed",
            "duration_ms": durations.get("performance", 0),
            "finding_count": agent_stats.get("performance", 0),
        },
        {
            "agent_type": "refactor",
            "display_name": "重构建议",
            "status": "completed",
            "duration_ms": durations.get("refactor", 0),
            "finding_count": agent_stats.get("refactor", 0),
        },
        {
            "agent_type": "arbitrator",
            "display_name": "仲裁汇总",
            "status": "completed",
            "duration_ms": durations.get("arbitrator", 0),
            "finding_count": issues_count,
        },
    ]

    response = ReviewResponse(
        task_id=task_id,
        status="completed",
        summary=final_state.get("report_summary", ""),
        score=final_state.get("report_score", 0.0),
        report_html=final_state.get("report_html", ""),
        issues_count=issues_count,
        stats=agent_stats,
        issues=issues,
        agent_timeline=agent_timeline,
        files=[f.model_dump() for f in request.files],
        errors=errors if errors else None,
    )

    # 持久化到数据库（失败不影响 API 响应）
    await _save_to_db(
        task_id=task_id,
        request=request,
        final_state=final_state,
        all_results=all_results,
        merged_results=issues,
        score=final_state.get("report_score", 0.0),
        summary=final_state.get("report_summary", ""),
        report_html=final_state.get("report_html", ""),
        agent_timeline=agent_timeline,
        errors=errors,
    )

    # 存入内存存储（热缓存），供 GET 端点查询
    _task_store[task_id] = response.model_dump()

    return response


@router.get("/reviews", response_model=ReviewListResponse)
async def list_reviews(limit: int = 20, offset: int = 0):
    """列出审查记录（分页）。

    优先从数据库查询，返回分页后的审查任务列表。
    """
    try:
        async with async_session_factory() as session:
            # 总数
            count_result = await session.execute(select(func.count(ReviewTask.id)))
            total = count_result.scalar() or 0

            # 分页查询
            result = await session.execute(
                select(ReviewTask)
                .order_by(ReviewTask.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            tasks = result.scalars().all()

            # 构建响应项
            items = []
            for task in tasks:
                # 统计该任务的 issue 数量
                issues_result = await session.execute(
                    select(func.count(AgentResult.id)).where(
                        AgentResult.task_id == task.id
                    )
                )
                issues_count = issues_result.scalar() or 0

                # 从 ReviewReport 获取评分
                report_result = await session.execute(
                    select(ReviewReport).where(ReviewReport.task_id == task.id)
                )
                report = report_result.scalar_one_or_none()
                score = report.score if report and report.score is not None else 0.0

                items.append(
                    ReviewListItem(
                        task_id=str(task.id),
                        repo_url=task.repo_url or "",
                        branch=task.branch or "",
                        status=task.status.value if task.status else "completed",
                        score=score,
                        issues_count=issues_count,
                        created_at=task.created_at.isoformat() if task.created_at else "",
                    )
                )

            return ReviewListResponse(total=total, items=items)
    except Exception as e:
        print("[reviews] list_reviews 失败: {}".format(e))
        return ReviewListResponse(total=0, items=[])


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

    优先从内存热缓存获取；未命中则查询数据库；
    数据库也未找到时返回占位状态。
    """
    # 1. 热缓存
    if task_id in _task_store:
        return _task_store[task_id]

    # 2. 数据库
    db_data = await _load_from_db(task_id)
    if db_data is not None:
        return db_data

    # 3. 占位响应
    return ReviewResponse(
        task_id=task_id,
        status="pending",
        summary="审查任务尚未完成或不存在。",
    )
