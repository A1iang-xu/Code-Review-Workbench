"""
审查 API 端点

POST /api/v1/reviews   — 提交代码审查任务（并行 5 Agent + 仲裁）
GET  /api/v1/reviews/{task_id} — 查询审查结果
"""

import uuid
import datetime
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.orchestrator import review_graph
from app.core.state import ReviewState

router = APIRouter(tags=["reviews"])


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


class ReviewResponse(BaseModel):
    """审查响应结构。"""
    task_id: str
    status: str
    summary: Optional[str] = None
    score: Optional[float] = None
    report_html: Optional[str] = None
    issues_count: Optional[int] = None
    stats: Optional[dict] = None  # 各 Agent 发现数


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
    started_at = datetime.datetime.utcnow().isoformat()

    # 构建初始状态
    initial_state: ReviewState = {
        "task_id": task_id,
        "repo_url": request.repo_url,
        "branch": request.branch,
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
        "started_at": started_at,
        "completed_at": "",
    }

    # 执行审查流水线
    try:
        final_state = await review_graph.ainvoke(initial_state)
    except Exception as e:
        return ReviewResponse(
            task_id=task_id,
            status="failed",
            summary=f"审查流水线执行失败: {str(e)}",
        )

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
    merged_count = len(final_state.get("_merged_results", []))
    # 如果仲裁成功，使用去重后的数量
    issues_count = merged_count if merged_count > 0 else len(all_results)

    return ReviewResponse(
        task_id=task_id,
        status="completed" if not errors else "completed_with_errors",
        summary=final_state.get("report_summary", ""),
        score=final_state.get("report_score", 0.0),
        report_html=final_state.get("report_html", ""),
        issues_count=issues_count,
        stats=agent_stats,
    )


@router.get("/reviews/{task_id}", response_model=ReviewResponse)
async def get_review(task_id: str):
    """查询审查结果。

    阶段二返回占位信息，任务状态持久化在阶段三完成。
    """
    return ReviewResponse(
        task_id=task_id,
        status="completed",
        summary="阶段二：审查结果查询需要任务状态持久化（阶段三完成）。",
    )
