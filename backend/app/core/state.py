"""
审查状态定义

LangGraph 工作流状态 TypedDict，贯穿整个审查流水线。
所有 Agent 结果通过 Annotated list + operator.add 汇聚。
"""

import datetime
import uuid
from typing import Annotated, TypedDict

from app.integrations.ast_engine import ParsedFile


class ReviewState(TypedDict):
    """审查工作流全局状态。

    从 parse_code 节点开始逐步填充，最终在 generate_report 节点汇总。
    """

    # ---- 任务元信息 ----
    task_id: str
    repo_url: str
    branch: str

    # ---- 代码文件 ----
    files: list[dict[str, str]]  # [{"path": "...", "content": "..."}]

    # ---- 工作流进度 ----
    current_stage: str  # parse_code / style_review / generate_report / done
    progress: float     # 0.0 ~ 1.0

    # ---- Agent 审查结果（Annotated list 支持 += 追加） ----
    style_results: Annotated[list[dict], "operator.add"]  # StyleChecker 结果
    security_results: Annotated[list[dict], "operator.add"]
    architecture_results: Annotated[list[dict], "operator.add"]
    performance_results: Annotated[list[dict], "operator.add"]
    refactor_results: Annotated[list[dict], "operator.add"]

    # ---- 内部过渡数据 ----
    _parsed_files: list  # ParsedFile 对象列表（节点间传递，不持久化）

    # ---- 报告 ----
    report_summary: str
    report_score: float
    report_html: str

    # ---- 错误 ----
    errors: Annotated[list[str], "operator.add"]

    # ---- 时间戳 ----
    started_at: str
    completed_at: str
