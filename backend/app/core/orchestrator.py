"""
LangGraph 工作流编排器

构建审查流水线 StateGraph：parse_code → style_review → generate_report
阶段一使用线性流程（3 节点），阶段二扩展为并行 Agent 编排。
"""

import datetime
import uuid
from typing import Any

from langgraph.graph import END, StateGraph

from app.core.agents.base import AgentContext
from app.core.agents.style import StyleCheckerAgent
from app.core.state import ReviewState
from app.integrations.ast_engine import ASTEngine


# ============================================================
# 节点实现
# ============================================================

async def parse_code_node(state: ReviewState) -> dict[str, Any]:
    """解析所有代码文件。

    遍历 state.files，用 ASTEngine 解析每个文件，
    将 ParsedFile 对象存入过渡状态。
    """
    engine = ASTEngine()
    parsed_files = []

    for file_info in state.get("files", []):
        path = file_info["path"]
        content = file_info["content"]

        try:
            pf = engine.parse(content, path)
            parsed_files.append(pf)
        except Exception as e:
            state["errors"].append(f"解析 {path} 失败: {e}")

    return {
        "current_stage": "style_review",
        "progress": 0.33,
        "_parsed_files": parsed_files,
    }


async def style_review_node(state: ReviewState) -> dict[str, Any]:
    """执行风格审查。

    创建 StyleCheckerAgent 对解析后的文件进行审查，
    返回 style_results。
    """
    parsed_files: list = state.get("_parsed_files", [])
    context = AgentContext()

    style_agent = StyleCheckerAgent(context)
    try:
        results = await style_agent.review(parsed_files)
    except Exception as e:
        results = []
        state["errors"].append(f"风格审查失败: {e}")

    return {
        "current_stage": "generate_report",
        "progress": 0.66,
        "style_results": results,
    }


async def generate_report_node(state: ReviewState) -> dict[str, Any]:
    """生成审查报告。

    统计各严重等级问题数量，计算扣分制评分，生成摘要。
    """
    # 收集所有 Agent 结果
    all_results: list[dict] = []
    all_results.extend(state.get("style_results", []))
    all_results.extend(state.get("security_results", []))
    all_results.extend(state.get("architecture_results", []))
    all_results.extend(state.get("performance_results", []))
    all_results.extend(state.get("refactor_results", []))

    # 统计严重等级
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    category_counts: dict[str, int] = {}

    for r in all_results:
        sev = r.get("severity", "info")
        if sev in severity_counts:
            severity_counts[sev] += 1
        cat = r.get("category", "other")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    # 扣分制评分计算
    # 基础分为 100，不同严重等级扣分权重不同
    deductions = (
        severity_counts["critical"] * 20
        + severity_counts["high"] * 10
        + severity_counts["medium"] * 5
        + severity_counts["low"] * 2
        + severity_counts["info"] * 0
    )
    score = max(0.0, 100.0 - deductions)

    # 生成摘要
    total = len(all_results)
    if total == 0:
        summary = "代码审查完成，未发现问题。代码质量良好。"
    else:
        summary_parts = [f"代码审查完成，共发现 {total} 个问题："]
        if severity_counts["critical"]:
            summary_parts.append(f"🔴 严重: {severity_counts['critical']} 个")
        if severity_counts["high"]:
            summary_parts.append(f"🟠 高危: {severity_counts['high']} 个")
        if severity_counts["medium"]:
            summary_parts.append(f"🟡 中危: {severity_counts['medium']} 个")
        if severity_counts["low"]:
            summary_parts.append(f"🔵 低危: {severity_counts['low']} 个")
        if severity_counts["info"]:
            summary_parts.append(f"ℹ️  信息: {severity_counts['info']} 个")
        summary = "\n".join(summary_parts)

    # 构建 report_html
    report_lines = ["<h2>代码审查报告</h2>", f"<p>{summary.replace(chr(10), '<br>')}</p>"]
    report_lines.append(f"<p><strong>综合评分: {score:.1f}/100</strong></p>")

    if all_results:
        report_lines.append("<h3>问题详情</h3>")
        report_lines.append("<table border='1'><tr><th>严重度</th><th>分类</th><th>文件</th><th>行号</th><th>标题</th><th>建议</th></tr>")
        for r in all_results:
            report_lines.append(
                f"<tr><td>{r.get('severity')}</td><td>{r.get('category')}</td>"
                f"<td>{r.get('file_path')}</td><td>{r.get('line_start')}-{r.get('line_end')}</td>"
                f"<td>{r.get('title')}</td><td>{r.get('suggestion', '')}</td></tr>"
            )
        report_lines.append("</table>")

    report_html = "\n".join(report_lines)
    completed_at = datetime.datetime.utcnow().isoformat()

    return {
        "current_stage": "done",
        "progress": 1.0,
        "report_summary": summary,
        "report_score": score,
        "report_html": report_html,
        "completed_at": completed_at,
    }


# ============================================================
# 构建 StateGraph
# ============================================================

def build_review_graph() -> StateGraph:
    """构建审查工作流图。

    阶段一：线性流程
    parse_code → style_review → generate_report → END

    Returns:
        编译后的 StateGraph
    """
    graph = StateGraph(ReviewState)

    # 添加节点
    graph.add_node("parse_code", parse_code_node)
    graph.add_node("style_review", style_review_node)
    graph.add_node("generate_report", generate_report_node)

    # 设置边（线性流程）
    graph.set_entry_point("parse_code")
    graph.add_edge("parse_code", "style_review")
    graph.add_edge("style_review", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()


# 全局编译实例
review_graph = build_review_graph()
