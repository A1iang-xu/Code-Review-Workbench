"""
审查 API 端点

POST /api/v1/reviews   — 提交代码审查任务
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


# ============================================================
# 端点实现
# ============================================================

@router.post("/reviews", response_model=ReviewResponse)
async def create_review(request: ReviewRequest):
    """提交代码审查任务。

    接收代码文件列表，启动 LangGraph 审查流水线，
    异步执行 parse_code → style_review → generate_report。
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

    # 统计问题总数
    all_results: list = []
    all_results.extend(final_state.get("style_results", []))
    all_results.extend(final_state.get("security_results", []))
    all_results.extend(final_state.get("architecture_results", []))
    all_results.extend(final_state.get("performance_results", []))
    all_results.extend(final_state.get("refactor_results", []))

    errors = final_state.get("errors", [])

    return ReviewResponse(
        task_id=task_id,
        status="completed" if not errors else "completed_with_errors",
        summary=final_state.get("report_summary", ""),
        score=final_state.get("report_score", 0.0),
        report_html=final_state.get("report_html", ""),
        issues_count=len(all_results),
    )


@router.get("/reviews/{task_id}", response_model=ReviewResponse)
async def get_review(task_id: str):
    """查询审查结果。

    阶段一返回占位信息，完整实现在阶段三完成。
    """
    return ReviewResponse(
        task_id=task_id,
        status="completed",
        summary="阶段一：此端点返回占位信息，完整实现在阶段三完成。",
    )
