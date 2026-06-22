"""
LangGraph 工作流编排器

构建审查流水线 StateGraph：
parse_code → [5 个 Agent 并行] → arbitrate → generate_report → END

阶段二：并行 Agent 编排（8 节点），充分利用异步 I/O 减少总耗时。
"""

import datetime
import uuid
from typing import Any

from langgraph.graph import END, StateGraph

from app.core.agents.base import AgentContext
from app.core.agents.style import StyleCheckerAgent
from app.core.agents.security import SecurityAuditorAgent
from app.core.agents.architecture import ArchitectureAnalyzerAgent
from app.core.agents.performance import PerformanceProfilerAgent
from app.core.agents.refactor import RefactorAdvisorAgent
from app.core.agents.arbitrator import ArbitratorAgent
from app.core.state import ReviewState
from app.integrations.ast_engine import ASTEngine


# ============================================================
# 辅助函数
# ============================================================

def _parse_files(files: list[dict[str, str]]) -> "list":
    """从 ReviewState 的 files 字段解析所有代码文件。

    使用 ASTEngine 解析每个文件，返回 ParsedFile 列表。

    Args:
        files: [{"path": "...", "content": "..."}]

    Returns:
        ParsedFile 对象列表
    """
    engine = ASTEngine()
    parsed_files = []

    for file_info in files:
        path = file_info["path"]
        content = file_info["content"]
        try:
            pf = engine.parse(content, path)
            parsed_files.append(pf)
        except Exception as e:
            print(f"[Orchestrator] 解析 {path} 失败: {e}")

    return parsed_files


# ============================================================
# 节点实现
# ============================================================

async def parse_code_node(state: ReviewState) -> dict[str, Any]:
    """解析所有代码文件节点。

    遍历 state.files，用 ASTEngine 解析每个文件，
    将 ParsedFile 对象存入过渡状态。
    """
    parsed_files = _parse_files(state.get("files", []))

    # 记录解析错误
    for file_info in state.get("files", []):
        path = file_info["path"]
        found = any(pf.path == path for pf in parsed_files)
        if not found:
            state["errors"].append(f"解析 {path} 失败：语言不支持或语法错误")

    return {
        "current_stage": "agent_reviews",
        "progress": 0.1,
        "_parsed_files": parsed_files,
    }


async def style_review_node(state: ReviewState) -> dict[str, Any]:
    """风格审查节点。

    创建 StyleCheckerAgent 对解析后的文件进行审查。
    """
    parsed_files: list = state.get("_parsed_files", [])
    context = AgentContext()

    agent = StyleCheckerAgent(context)
    try:
        results = await agent.review(parsed_files)
    except Exception as e:
        results = []
        state["errors"].append(f"风格审查失败: {e}")

    return {
        "current_stage": "agent_reviews",
        "progress": state.get("progress", 0.1) + 0.12,
        "style_results": results,
    }


async def security_review_node(state: ReviewState) -> dict[str, Any]:
    """安全审计节点。

    创建 SecurityAuditorAgent 执行正则 + LLM 双层安全扫描。
    """
    parsed_files: list = state.get("_parsed_files", [])
    context = AgentContext()

    agent = SecurityAuditorAgent(context)
    try:
        results = await agent.review(parsed_files)
    except Exception as e:
        results = []
        state["errors"].append(f"安全审计失败: {e}")

    return {
        "current_stage": "agent_reviews",
        "progress": state.get("progress", 0.1) + 0.12,
        "security_results": results,
    }


async def architecture_review_node(state: ReviewState) -> dict[str, Any]:
    """架构分析节点。

    创建 ArchitectureAnalyzerAgent 执行依赖图分析 + LLM 架构评估。
    """
    parsed_files: list = state.get("_parsed_files", [])
    context = AgentContext()

    agent = ArchitectureAnalyzerAgent(context)
    try:
        results = await agent.review(parsed_files)
    except Exception as e:
        results = []
        state["errors"].append(f"架构分析失败: {e}")

    return {
        "current_stage": "agent_reviews",
        "progress": state.get("progress", 0.1) + 0.12,
        "architecture_results": results,
    }


async def performance_review_node(state: ReviewState) -> dict[str, Any]:
    """性能分析节点。

    创建 PerformanceProfilerAgent 执行圈复杂度分析 + LLM 性能评估。
    """
    parsed_files: list = state.get("_parsed_files", [])
    context = AgentContext()

    agent = PerformanceProfilerAgent(context)
    try:
        results = await agent.review(parsed_files)
    except Exception as e:
        results = []
        state["errors"].append(f"性能分析失败: {e}")

    return {
        "current_stage": "agent_reviews",
        "progress": state.get("progress", 0.1) + 0.12,
        "performance_results": results,
    }


async def refactor_review_node(state: ReviewState) -> dict[str, Any]:
    """重构建议节点。

    创建 RefactorAdvisorAgent 执行 AST 坏味道检测 + LLM 重构方案。
    """
    parsed_files: list = state.get("_parsed_files", [])
    context = AgentContext()

    agent = RefactorAdvisorAgent(context)
    try:
        results = await agent.review(parsed_files)
    except Exception as e:
        results = []
        state["errors"].append(f"重构分析失败: {e}")

    return {
        "current_stage": "agent_reviews",
        "progress": state.get("progress", 0.1) + 0.12,
        "refactor_results": results,
    }


async def arbitrate_node(state: ReviewState) -> dict[str, Any]:
    """仲裁汇总节点。

    收集所有 Agent 结果，调用 ArbitratorAgent 执行去重、排序、
    评分和摘要生成。
    """
    context = AgentContext()
    arbitrator = ArbitratorAgent(context)

    style_results = state.get("style_results", [])
    security_results = state.get("security_results", [])
    architecture_results = state.get("architecture_results", [])
    performance_results = state.get("performance_results", [])
    refactor_results = state.get("refactor_results", [])

    try:
        arbitrated = await arbitrator.arbitrate_full(
            style_results=style_results,
            security_results=security_results,
            architecture_results=architecture_results,
            performance_results=performance_results,
            refactor_results=refactor_results,
            task_id=state.get("task_id", ""),
        )
    except Exception as e:
        # 降级：不为空但也不完整的结果
        state["errors"].append(f"仲裁汇总失败: {e}")
        arbitrated = {
            "merged_results": (
                style_results + security_results + architecture_results +
                performance_results + refactor_results
            ),
            "severity_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
            "score": 0.0,
            "summary": f"审查完成（仲裁汇总失败: {str(e)[:80]}）",
            "report_html": f"<p>仲裁汇总失败: {str(e)[:200]}</p>",
            "stats": {},
        }

    return {
        "current_stage": "generate_report",
        "progress": 0.8,
        "report_summary": arbitrated["summary"],
        "report_score": arbitrated["score"],
        # 将 merged_results 作为 _merged_results 暂存
        "_merged_results": arbitrated["merged_results"],
    }


async def generate_report_node(state: ReviewState) -> dict[str, Any]:
    """报告生成节点。

    调用 ArbitratorAgent 生成 HTML 报告，保存审查结果。
    """
    context = AgentContext()
    arbitrator = ArbitratorAgent(context)

    # 收集所有结果
    all_results: list[dict] = []
    all_results.extend(state.get("style_results", []))
    all_results.extend(state.get("security_results", []))
    all_results.extend(state.get("architecture_results", []))
    all_results.extend(state.get("performance_results", []))
    all_results.extend(state.get("refactor_results", []))

    # 尝试使用仲裁后的结果
    merged = state.get("_merged_results", [])
    if not merged:
        merged = all_results

    # 统计
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    category_counts: dict[str, int] = {}

    for r in merged:
        sev = r.get("severity", "info")
        if sev in severity_counts:
            severity_counts[sev] += 1
        cat = r.get("category", "other")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    # 如果仲裁失败，使用备用评分
    score = state.get("report_score", 0.0)
    if score == 0.0:
        deductions = (
            severity_counts["critical"] * 2.0
            + severity_counts["high"] * 1.0
            + severity_counts["medium"] * 0.3
            + severity_counts["low"] * 0.1
        )
        score = round(max(0.0, 10.0 - (deductions * 0.5)), 1)

    summary = state.get("report_summary", "")

    # 统计各 Agent 发现数
    agent_stats: dict[str, int] = {}
    for r in all_results:
        at = r.get("agent_type", "unknown")
        agent_stats[at] = agent_stats.get(at, 0) + 1

    # 生成 HTML 报告
    report_html = arbitrator.generate_html_report(
        merged_results=merged,
        severity_counts=severity_counts,
        category_counts=category_counts,
        score=score,
        summary=summary,
        stats={"by_agent": agent_stats, "total_issues": len(merged)},
        task_id=state.get("task_id", ""),
    )

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
# 构建 StateGraph（并行编排）
# ============================================================

def build_review_graph() -> StateGraph:
    """构建审查工作流图。

    阶段二：并行 Agent 编排
    parse_code → [style | security | architecture | performance | refactor] (并行)
             → arbitrate → generate_report → END

    Returns:
        编译后的 StateGraph
    """
    graph = StateGraph(ReviewState)

    # 添加节点
    graph.add_node("parse_code", parse_code_node)
    graph.add_node("style_review", style_review_node)
    graph.add_node("security_review", security_review_node)
    graph.add_node("architecture_review", architecture_review_node)
    graph.add_node("performance_review", performance_review_node)
    graph.add_node("refactor_review", refactor_review_node)
    graph.add_node("arbitrate", arbitrate_node)
    graph.add_node("generate_report", generate_report_node)

    # 设置入口
    graph.set_entry_point("parse_code")

    # parse_code → 5 个 Agent（分叉，并行执行）
    graph.add_edge("parse_code", "style_review")
    graph.add_edge("parse_code", "security_review")
    graph.add_edge("parse_code", "architecture_review")
    graph.add_edge("parse_code", "performance_review")
    graph.add_edge("parse_code", "refactor_review")

    # 5 个 Agent → arbitrate（汇聚）
    graph.add_edge("style_review", "arbitrate")
    graph.add_edge("security_review", "arbitrate")
    graph.add_edge("architecture_review", "arbitrate")
    graph.add_edge("performance_review", "arbitrate")
    graph.add_edge("refactor_review", "arbitrate")

    # arbitrate → generate_report → END
    graph.add_edge("arbitrate", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()


# 全局编译实例
review_graph = build_review_graph()
