"""
LangGraph 工作流编排器

构建审查流水线 StateGraph：
parse_code -> [5 个 Agent 并行] -> arbitrate -> generate_report -> END

阶段三：集成记忆系统 - AgentContext 注入 memory_context，
审查完成后自动保存情节记忆和程序性记忆。
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
from app.core.memory import MemoryManager
from app.core.state import ReviewState
from app.integrations.ast_engine import ASTEngine


# ============================================================
# 记忆系统初始化
# ============================================================

def _get_memory() -> MemoryManager:
    """获取 MemoryManager 单例。"""
    return MemoryManager(storage_path="./memory_data")


def _get_agent_context() -> AgentContext:
    """创建带记忆上下文的 AgentContext。"""
    memory = _get_memory()
    return AgentContext(
        memory_context=memory.get_system_context()
    )


# ============================================================
# 辅助函数
# ============================================================

def _parse_files(files: list[dict[str, str]]) -> list:
    """从 ReviewState 的 files 字段解析所有代码文件。"""
    engine = ASTEngine()
    parsed_files = []
    for file_info in files:
        path = file_info["path"]
        content = file_info["content"]
        try:
            pf = engine.parse(content, path)
            parsed_files.append(pf)
        except Exception as e:
            print("[Orchestrator] 解析 {} 失败: {}".format(path, e))
    return parsed_files


# ============================================================
# 节点实现
# ============================================================

async def parse_code_node(state: ReviewState) -> dict[str, Any]:
    """解析所有代码文件节点。"""
    memory = _get_memory()
    memory.new_session(max_tokens=4000)
    parsed_files = _parse_files(state.get("files", []))
    for file_info in state.get("files", []):
        path = file_info["path"]
        found = any(pf.path == path for pf in parsed_files)
        if not found:
            state["errors"].append("解析 {} 失败".format(path))
    return {
        "current_stage": "agent_reviews",
        "progress": 0.1,
        "_parsed_files": parsed_files,
    }


async def style_review_node(state: ReviewState) -> dict[str, Any]:
    """风格审查节点。"""
    parsed_files = state.get("_parsed_files", [])
    context = _get_agent_context()
    agent = StyleCheckerAgent(context)
    try:
        results = await agent.review(parsed_files)
    except Exception as e:
        results = []
        state["errors"].append("风格审查失败: {}".format(e))
    return {
        "current_stage": "agent_reviews",
        "progress": state.get("progress", 0.1) + 0.12,
        "style_results": results,
    }


async def security_review_node(state: ReviewState) -> dict[str, Any]:
    """安全审计节点。"""
    parsed_files = state.get("_parsed_files", [])
    context = _get_agent_context()
    agent = SecurityAuditorAgent(context)
    try:
        results = await agent.review(parsed_files)
    except Exception as e:
        results = []
        state["errors"].append("安全审计失败: {}".format(e))
    return {
        "current_stage": "agent_reviews",
        "progress": state.get("progress", 0.1) + 0.12,
        "security_results": results,
    }


async def architecture_review_node(state: ReviewState) -> dict[str, Any]:
    """架构分析节点。"""
    parsed_files = state.get("_parsed_files", [])
    context = _get_agent_context()
    agent = ArchitectureAnalyzerAgent(context)
    try:
        results = await agent.review(parsed_files)
    except Exception as e:
        results = []
        state["errors"].append("架构分析失败: {}".format(e))
    return {
        "current_stage": "agent_reviews",
        "progress": state.get("progress", 0.1) + 0.12,
        "architecture_results": results,
    }


async def performance_review_node(state: ReviewState) -> dict[str, Any]:
    """性能分析节点。"""
    parsed_files = state.get("_parsed_files", [])
    context = _get_agent_context()
    agent = PerformanceProfilerAgent(context)
    try:
        results = await agent.review(parsed_files)
    except Exception as e:
        results = []
        state["errors"].append("性能分析失败: {}".format(e))
    return {
        "current_stage": "agent_reviews",
        "progress": state.get("progress", 0.1) + 0.12,
        "performance_results": results,
    }


async def refactor_review_node(state: ReviewState) -> dict[str, Any]:
    """重构建议节点。"""
    parsed_files = state.get("_parsed_files", [])
    context = _get_agent_context()
    agent = RefactorAdvisorAgent(context)
    try:
        results = await agent.review(parsed_files)
    except Exception as e:
        results = []
        state["errors"].append("重构分析失败: {}".format(e))
    return {
        "current_stage": "agent_reviews",
        "progress": state.get("progress", 0.1) + 0.12,
        "refactor_results": results,
    }


async def arbitrate_node(state: ReviewState) -> dict[str, Any]:
    """仲裁汇总节点。"""
    context = _get_agent_context()
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
        state["errors"].append("仲裁汇总失败: {}".format(e))
        arbitrated = {
            "merged_results": (
                style_results + security_results + architecture_results +
                performance_results + refactor_results
            ),
            "severity_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
            "score": 0.0,
            "summary": "审查完成（仲裁汇总失败: {}）".format(str(e)[:80]),
            "report_html": "<p>仲裁汇总失败</p>",
            "stats": {},
        }
    return {
        "current_stage": "generate_report",
        "progress": 0.8,
        "report_summary": arbitrated["summary"],
        "report_score": arbitrated["score"],
        "_merged_results": arbitrated["merged_results"],
    }


async def generate_report_node(state: ReviewState) -> dict[str, Any]:
    """报告生成节点 - 含记忆保存。"""
    context = _get_agent_context()
    arbitrator = ArbitratorAgent(context)

    all_results = []
    all_results.extend(state.get("style_results", []))
    all_results.extend(state.get("security_results", []))
    all_results.extend(state.get("architecture_results", []))
    all_results.extend(state.get("performance_results", []))
    all_results.extend(state.get("refactor_results", []))

    merged = state.get("_merged_results", [])
    if not merged:
        merged = all_results

    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    category_counts = {}
    for r in merged:
        sev = r.get("severity", "info")
        if sev in severity_counts:
            severity_counts[sev] += 1
        cat = r.get("category", "other")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    score = state.get("report_score", 0.0)
    if score == 0.0:
        deductions = (
            severity_counts["critical"] * 2.0 +
            severity_counts["high"] * 1.0 +
            severity_counts["medium"] * 0.3 +
            severity_counts["low"] * 0.1
        )
        score = round(max(0.0, 10.0 - (deductions * 0.5)), 1)

    summary = state.get("report_summary", "")

    agent_stats = {}
    for r in all_results:
        at = r.get("agent_type", "unknown")
        agent_stats[at] = agent_stats.get(at, 0) + 1

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

    # 保存记忆
    task_id = state.get("task_id", "")
    if task_id:
        try:
            memory = _get_memory()
            review_result = {
                "summary": summary,
                "score": score,
                "severity_counts": severity_counts,
                "repo_url": state.get("repo_url", ""),
                "stats": agent_stats,
            }
            await memory.save_session(
                task_id=task_id,
                review_result=review_result,
                issues=all_results,
            )
            print("[Orchestrator] 记忆已保存 for task {}".format(task_id))
        except Exception as e:
            print("[Orchestrator] 记忆保存失败: {}".format(e))

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
    """构建审查工作流图 - 并行 Agent 编排 + 记忆系统集成。"""
    graph = StateGraph(ReviewState)

    graph.add_node("parse_code", parse_code_node)
    graph.add_node("style_review", style_review_node)
    graph.add_node("security_review", security_review_node)
    graph.add_node("architecture_review", architecture_review_node)
    graph.add_node("performance_review", performance_review_node)
    graph.add_node("refactor_review", refactor_review_node)
    graph.add_node("arbitrate", arbitrate_node)
    graph.add_node("generate_report", generate_report_node)

    graph.set_entry_point("parse_code")

    graph.add_edge("parse_code", "style_review")
    graph.add_edge("parse_code", "security_review")
    graph.add_edge("parse_code", "architecture_review")
    graph.add_edge("parse_code", "performance_review")
    graph.add_edge("parse_code", "refactor_review")

    graph.add_edge("style_review", "arbitrate")
    graph.add_edge("security_review", "arbitrate")
    graph.add_edge("architecture_review", "arbitrate")
    graph.add_edge("performance_review", "arbitrate")
    graph.add_edge("refactor_review", "arbitrate")

    graph.add_edge("arbitrate", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()


review_graph = build_review_graph()
