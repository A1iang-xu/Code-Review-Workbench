"""
审查状态定义

LangGraph 工作流状态 TypedDict，贯穿整个审查流水线。
所有 Agent 结果通过 Annotated list + operator.add 汇聚。
"""

import operator
from typing import Annotated, TypedDict


def _last_value(a, b):
    """Reducer: 取最后写入的值（用于并行节点覆写同一字段）。"""
    return b


def _merge_dicts(a: dict, b: dict) -> dict:
    """Reducer: 合并两个字典（用于并行节点写入同一字典字段）。"""
    result = dict(a)
    result.update(b)
    return result


class ReviewState(TypedDict):
    """审查工作流全局状态。

    从 parse_code 节点开始逐步填充，最终在 generate_report 节点汇总。
    """

    # ---- 任务元信息 ----
    task_id: str
    repo_url: str
    branch: str
    language: str  # 审查语言: auto / python / go / typescript / javascript / java

    # ---- 代码文件 ----
    files: list[dict[str, str]]  # [{"path": "...", "content": "..."}]

    # ---- Skill 扫描配置与结果 ----
    enabled_skills: list[str]  # 本次审查启用的 Skill 名称列表（空 = 不执行 skill 扫描）
    skill_results: Annotated[list[dict], operator.add]  # Skill 扫描发现的问题

    # ---- 工作流进度 ----
    # Annotated 支持并行节点写入：current_stage 取最后值，progress 取最后值（绝对值覆写）
    current_stage: Annotated[str, _last_value]
    progress: Annotated[float, _last_value]

    # ---- Agent 审查结果（Annotated list 支持 += 追加） ----
    style_results: Annotated[list[dict], operator.add]  # StyleChecker 结果
    security_results: Annotated[list[dict], operator.add]
    architecture_results: Annotated[list[dict], operator.add]
    performance_results: Annotated[list[dict], operator.add]
    refactor_results: Annotated[list[dict], operator.add]

    # ---- 内部过渡数据 ----
    _parsed_files: list  # ParsedFile 对象列表（节点间传递，不持久化）
    _merged_results: list  # 仲裁后的合并结果（节点间传递，不持久化）

    # ---- 报告 ----
    report_summary: str
    report_score: float
    report_html: str

    # ---- 错误 ----
    errors: Annotated[list[str], operator.add]

    # ---- Agent 协作信号与第二轮结果 ----
    # agent_signals: 第一轮各 Agent 输出的跨 Agent 关注信号（operator.add 汇聚）
    agent_signals: Annotated[list[dict], operator.add]
    # collaboration_results: 第二轮 collab 节点的增量发现
    collaboration_results: Annotated[list[dict], operator.add]
    # 协作控制
    collaboration_enabled: bool  # 是否启用协作（配置项，默认 True）
    collaboration_round: int     # 当前协作轮次
    active_collab_agents: list[str]  # 第二轮需触发的 Agent 列表

    # ---- Agent 执行耗时（毫秒）----
    # 并行节点通过 _merge_dicts 合并各自的耗时记录
    agent_durations: Annotated[dict[str, int], _merge_dicts]

    # ---- 时间戳 ----
    started_at: str
    completed_at: str
