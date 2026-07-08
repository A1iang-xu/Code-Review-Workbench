"""
LangGraph 工作流编排器

构建审查流水线 StateGraph：
parse_code -> [5 个 Agent 并行] -> arbitrate -> generate_report -> END

阶段三：集成记忆系统 - AgentContext 注入 memory_context，
审查完成后自动保存情节记忆和程序性记忆。

阶段四：集成压缩系统 - parse_code_node 后调用 SemanticChunker 分块，
Agent 调用前通过 TokenQuotaManager 检查 token 配额。
"""

import datetime
import time
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
from app.core.compression.chunker import SemanticChunker
from app.core.compression.token_manager import TokenQuotaManager
from app.core.skills.executor import SkillExecutor
from app.api.v1.ws import update_progress, complete_progress


# ============================================================
# OpenTelemetry span 辅助函数
# ============================================================

async def _run_agent_with_tracing(agent, agent_type: str, parsed_files):
    """带 OpenTelemetry span 的 Agent 调用。

    自动记录执行耗时和发现数量到 span。
    """
    start_time = time.time()
    try:
        from opentelemetry import trace
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span(f"agent.{agent_type}") as span:
            span.set_attribute("agent.type", agent_type)
            results = await agent.review(parsed_files)
            span.set_attribute("findings_count", len(results))
            elapsed_ms = int((time.time() - start_time) * 1000)
            span.set_attribute("duration_ms", elapsed_ms)
            return results, []
    except ImportError:
        # OpenTelemetry 未安装，直接调用
        results = await agent.review(parsed_files)
        return results, []
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        try:
            from opentelemetry import trace
            span = trace.get_current_span()
            if span:
                span.set_attribute("error", str(e))
                span.set_attribute("error.type", type(e).__name__)
                span.set_attribute("duration_ms", elapsed_ms)
        except ImportError:
            pass
        return [], [f"{agent_type} 审查失败: {e}"]


# ============================================================
# 压缩系统单例
# ============================================================

_chunker = SemanticChunker()
_token_manager = TokenQuotaManager()


# ============================================================
# 记忆系统初始化
# ============================================================

def _get_memory() -> MemoryManager:
    """获取 MemoryManager 单例。"""
    return MemoryManager(storage_path="./memory_data")


def _get_agent_context(state: ReviewState, agent_type: str = "") -> AgentContext:
    """创建带记忆上下文和压缩系统的 AgentContext。

    使用 get_context_for_review() 根据当前审查的语言、文件路径和 Agent 类型
    生成针对性记忆上下文，让记忆真正影响后续审查。

    注意：原实现在异步上下文中调用 loop.run_until_complete 会被静默吞错，
    导致针对性记忆上下文从未生效。此处改用独立线程跑独立事件循环，
    与主线程的事件循环互不干扰，确保记忆上下文真正被获取。

    Args:
        state: 审查工作流状态
        agent_type: 当前 Agent 类型，用于激活 episodic 定向历史检索
    """
    import asyncio
    import threading

    memory = _get_memory()
    # 同步获取基础上下文（从缓存）
    memory_context = memory.get_system_context()

    # 在独立线程中跑独立事件循环，无论主线程是否有正在运行的循环都能正确执行
    language = state.get("language", "auto")
    file_paths = [f["path"] for f in state.get("files", [])]

    # 按 Agent 类型映射 categories，激活 episodic 定向历史检索
    _AGENT_CATEGORIES: dict[str, list[str]] = {
        "style": ["style"],
        "security": ["security"],
        "architecture": ["architecture"],
        "performance": ["performance"],
        "refactor": ["refactor"],
        "arbitrator": ["security", "performance", "architecture"],
    }
    categories = _AGENT_CATEGORIES.get(agent_type) if agent_type else None

    result_holder: dict = {"context": memory_context, "error": None}

    def _runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            result_holder["context"] = loop.run_until_complete(
                memory.get_context_for_review(
                    language=language,
                    file_paths=file_paths,
                    categories=categories,
                )
            )
        except Exception as e:  # noqa: BLE001
            result_holder["error"] = e
        finally:
            loop.close()

    t = threading.Thread(target=_runner, name="memory-context-fetch")
    t.start()
    t.join()

    if result_holder["error"] is not None:
        # 记忆上下文获取失败时降级到系统缓存上下文，不阻塞主流程
        from app.utils.logger import get_logger

        logger = get_logger(__name__)
        logger.warning(
            "[Orchestrator] 获取针对性记忆上下文失败，降级到系统缓存: %s",
            result_holder["error"],
        )
    else:
        memory_context = result_holder["context"]

    return AgentContext(
        memory_context=memory_context,
        language=state.get("language", "auto"),
        chunker=_chunker,
        token_manager=_token_manager,
    )


# ============================================================
# 辅助函数
# ============================================================

def _parse_files(files: list[dict[str, str]], language: str = "auto") -> list:
    """从 ReviewState 的 files 字段解析所有代码文件。

    Args:
        files: 文件列表 [{"path": "...", "content": "..."}]
        language: 目标语言，"auto" 表示自动检测
    """
    engine = ASTEngine()
    parsed_files = []
    for file_info in files:
        path = file_info["path"]
        content = file_info["content"]

        # 确定解析语言
        if language != "auto":
            parse_lang = language
        else:
            from app.integrations.ast_engine import detect_language
            parse_lang = detect_language(path)

        try:
            pf = engine.parse(content, path, language=parse_lang)
            parsed_files.append(pf)
        except Exception as e:
            print("[Orchestrator] 解析 {} 失败: {}".format(path, e))
    return parsed_files


# ============================================================
# 节点实现
# ============================================================

async def parse_code_node(state: ReviewState) -> dict[str, Any]:
    """解析所有代码文件节点。

    阶五集成：刷新记忆缓存，确保 get_system_context 返回最新数据。
    注：压缩分块由 Agent 内部 _compress_code_context 按需触发，
    无需在此预分块（原 _file_chunks 从未被 Agent 消费，已移除）。
    """
    start_time = time.time()
    task_id = state.get("task_id", "")
    if task_id:
        update_progress(task_id, 0.05, "parse_code", "running")
    memory = _get_memory()
    memory.new_session(max_tokens=4000)

    # 刷新记忆缓存（从 PostgreSQL 加载语义记忆和最近审查记录）
    try:
        await memory.async_refresh()
    except Exception as e:
        print("[Orchestrator] 记忆缓存刷新失败: {}".format(e))

    lang = state.get("language", "auto")
    parsed_files = _parse_files(state.get("files", []), language=lang)
    errors = []
    for file_info in state.get("files", []):
        path = file_info["path"]
        found = any(pf.path == path for pf in parsed_files)
        if not found:
            errors.append("解析 {} 失败".format(path))

    elapsed_ms = int((time.time() - start_time) * 1000)
    if task_id:
        update_progress(task_id, 0.1, "skill_scan", "running")
    return {
        "current_stage": "skill_scan",
        "progress": 0.1,
        "_parsed_files": parsed_files,
        "errors": errors,
        "agent_durations": {"parser": elapsed_ms},
    }


async def skill_scan_node(state: ReviewState) -> dict[str, Any]:
    """Skill 扫描节点（可选）。

    当 ReviewState.enabled_skills 非空时，对每个已解析文件并行执行选中的
    Skill，收集发现（标记 source='skill'）。结果存入 state.skill_results，
    在 generate_report 节点与 Agent 发现合并进最终报告。

    enabled_skills 为空时直接跳过，不阻塞主流程。
    """
    enabled = state.get("enabled_skills", [])
    if not enabled:
        return {}

    start_time = time.time()
    task_id = state.get("task_id", "")
    if task_id:
        update_progress(task_id, 0.12, "skill_scan", "running")

    parsed_files = state.get("_parsed_files", [])
    executor = SkillExecutor()
    all_findings: list[dict] = []

    for pf in parsed_files:
        try:
            results = await executor.execute_all(
                skill_names=enabled,
                code=pf.content,
                file_path=pf.path,
            )
            for skill_name, result in results.items():
                if not result.success:
                    continue
                for finding in result.findings:
                    # 标记来源为 skill，供报告区分
                    finding["source"] = "skill"
                    finding["skill_name"] = skill_name
                    finding.setdefault("agent_type", "skill")
                    finding.setdefault("file_path", pf.path)
                    all_findings.append(finding)
        except Exception as e:
            print("[Orchestrator] Skill 扫描 {} 失败: {}".format(pf.path, e))

    elapsed_ms = int((time.time() - start_time) * 1000)
    if task_id:
        update_progress(task_id, 0.15, "agent_reviews", "running")
    return {
        "skill_results": all_findings,
        "agent_durations": {"skill_scan": elapsed_ms},
    }


def _make_agent_review_node(
    agent_type: str,
    agent_cls: type,
    progress: float,
    results_key: str,
):
    """工厂：生成 LangGraph Agent 审查节点。

    消除原 5 个几乎相同的 style/security/architecture/performance/refactor 节点模板。
    每个节点逻辑完全一致，仅 agent 类型、进度值、结果 key 不同。

    Args:
        agent_type: Agent 类型标识（用于 tracing/span 属性）
        agent_cls: Agent 类（如 StyleCheckerAgent）
        progress: 该节点完成时的进度值
        results_key: 结果存入 state 的 key（如 "style_results"）
    """
    async def _node(state: ReviewState) -> dict[str, Any]:
        start_time = time.time()
        task_id = state.get("task_id", "")
        parsed_files = state.get("_parsed_files", [])
        context = _get_agent_context(state, agent_type=agent_type)
        agent = agent_cls(context)
        results, errors = await _run_agent_with_tracing(agent, agent_type, parsed_files)
        elapsed_ms = int((time.time() - start_time) * 1000)
        if task_id:
            update_progress(task_id, progress, "agent_reviews", "running")
        return {
            "current_stage": "agent_reviews",
            "progress": progress,
            results_key: results,
            "errors": errors,
            "agent_durations": {agent_type: elapsed_ms},
        }

    _node.__name__ = f"{agent_type}_review_node"
    return _node


# 通过工厂生成 5 个节点（保持原函数名，图构建代码无需改动）
style_review_node = _make_agent_review_node(
    "style", StyleCheckerAgent, 0.25, "style_results"
)
security_review_node = _make_agent_review_node(
    "security", SecurityAuditorAgent, 0.35, "security_results"
)
architecture_review_node = _make_agent_review_node(
    "architecture", ArchitectureAnalyzerAgent, 0.45, "architecture_results"
)
performance_review_node = _make_agent_review_node(
    "performance", PerformanceProfilerAgent, 0.55, "performance_results"
)
refactor_review_node = _make_agent_review_node(
    "refactor", RefactorAdvisorAgent, 0.65, "refactor_results"
)


# ============================================================
# Agent 协作节点（第二轮）
# ============================================================

async def signal_exchange_node(state: ReviewState) -> dict[str, Any]:
    """信号交换节点。

    汇聚第一轮 Agent 的 signals，按 target_agent 分组统计，
    计算需要触发的第二轮 collab 节点列表。
    """
    start_time = time.time()
    task_id = state.get("task_id", "")

    collaboration_enabled = state.get("collaboration_enabled", True)
    all_signals = state.get("agent_signals", [])

    # 协作被禁用 或 无信号 → 不触发第二轮
    if not collaboration_enabled or not all_signals:
        if task_id:
            update_progress(task_id, 0.7, "arbitrate", "running")
        return {
            "current_stage": "arbitrate",
            "progress": 0.7,
            "collaboration_round": 1,
            "active_collab_agents": [],
        }

    # 按 target_agent 分组统计
    signals_by_target: dict[str, list[dict]] = {}
    for sig in all_signals:
        target = sig.get("target_agent", "")
        if target:
            signals_by_target.setdefault(target, []).append(sig)

    active_agents = list(signals_by_target.keys())

    from app.utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info(
        "[Collaboration] 信号交换完成: %d 个信号, 触发 %d 个协作 Agent: %s",
        len(all_signals), len(active_agents), active_agents,
    )

    elapsed_ms = int((time.time() - start_time) * 1000)
    if task_id:
        update_progress(task_id, 0.68, "collaboration", "running")

    return {
        "current_stage": "collaboration",
        "progress": 0.68,
        "collaboration_round": 1,
        "active_collab_agents": active_agents,
        "agent_durations": {"signal_exchange": elapsed_ms},
    }


def _make_collab_review_node(agent_type: str, agent_cls: type):
    """工厂：生成第二轮协作复查节点。"""
    async def _node(state: ReviewState) -> dict[str, Any]:
        start_time = time.time()
        task_id = state.get("task_id", "")

        # 检查是否需要执行
        active_agents = state.get("active_collab_agents", [])
        if agent_type not in active_agents:
            return {}

        # 从 ReviewState.agent_signals 过滤出发给自己的信号
        all_signals = state.get("agent_signals", [])
        my_signals = [
            sig for sig in all_signals
            if sig.get("target_agent") == agent_type
        ]

        if not my_signals:
            return {}

        parsed_files = state.get("_parsed_files", [])
        context = _get_agent_context(state, agent_type=agent_type)
        agent = agent_cls(context)

        try:
            collab_findings = await agent.collaborative_review(
                parsed_files=parsed_files,
                signals=my_signals,
            )
        except Exception as e:
            collab_findings = []
            from app.utils.logger import get_logger
            get_logger(__name__).warning(
                "[Collaboration] %s 协作复查失败: %s", agent_type, e
            )

        # 标记来源
        for f in collab_findings:
            f["source"] = "collaboration"
            f["triggered_by"] = agent_type

        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            "collaboration_results": collab_findings,
            "agent_durations": {f"collab_{agent_type}": elapsed_ms},
        }

    _node.__name__ = f"collab_{agent_type}_node"
    return _node


# 生成 5 个 collab 节点
collab_style_node = _make_collab_review_node("style", StyleCheckerAgent)
collab_security_node = _make_collab_review_node("security", SecurityAuditorAgent)
collab_architecture_node = _make_collab_review_node("architecture", ArchitectureAnalyzerAgent)
collab_performance_node = _make_collab_review_node("performance", PerformanceProfilerAgent)
collab_refactor_node = _make_collab_review_node("refactor", RefactorAdvisorAgent)


async def arbitrate_node(state: ReviewState) -> dict[str, Any]:
    """仲裁汇总节点。"""
    start_time = time.time()
    task_id = state.get("task_id", "")
    if task_id:
        update_progress(task_id, 0.7, "arbitrate", "running")
    context = _get_agent_context(state, agent_type="arbitrator")
    arbitrator = ArbitratorAgent(context)
    style_results = state.get("style_results", [])
    security_results = state.get("security_results", [])
    architecture_results = state.get("architecture_results", [])
    performance_results = state.get("performance_results", [])
    refactor_results = state.get("refactor_results", [])
    errors = []
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
        errors.append("仲裁汇总失败: {}".format(e))
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
    elapsed_ms = int((time.time() - start_time) * 1000)
    if task_id:
        update_progress(task_id, 0.8, "generate_report", "running")
    return {
        "current_stage": "generate_report",
        "progress": 0.8,
        "report_summary": arbitrated["summary"],
        "report_score": arbitrated["score"],
        "_merged_results": arbitrated["merged_results"],
        "errors": errors,
        "agent_durations": {"arbitrator": elapsed_ms},
    }


async def generate_report_node(state: ReviewState) -> dict[str, Any]:
    """报告生成节点 - 含记忆保存。"""
    start_time = time.time()
    task_id = state.get("task_id", "")
    if task_id:
        update_progress(task_id, 0.9, "generate_report", "running")
    context = _get_agent_context(state, agent_type="arbitrator")
    arbitrator = ArbitratorAgent(context)

    all_results = []
    all_results.extend(state.get("style_results", []))
    all_results.extend(state.get("security_results", []))
    all_results.extend(state.get("architecture_results", []))
    all_results.extend(state.get("performance_results", []))
    all_results.extend(state.get("refactor_results", []))
    # 合并 Skill 扫描发现（source='skill'），与 Agent 发现一起进入报告
    all_results.extend(state.get("skill_results", []))

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

    completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # 保存记忆
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

    elapsed_ms = int((time.time() - start_time) * 1000)
    # 标记任务完成，通知 SSE 推送 complete 事件
    if task_id:
        complete_progress(task_id)
    return {
        "current_stage": "done",
        "progress": 1.0,
        "report_summary": summary,
        "report_score": score,
        "report_html": report_html,
        "completed_at": completed_at,
        "agent_durations": {"report": elapsed_ms},
    }


# ============================================================
# 构建 StateGraph
# ============================================================

def build_review_graph() -> StateGraph:
    """构建审查工作流图 - Skill 扫描 + 并行 Agent 编排 + 记忆系统集成。"""
    graph = StateGraph(ReviewState)

    graph.add_node("parse_code", parse_code_node)
    graph.add_node("skill_scan", skill_scan_node)
    graph.add_node("style_review", style_review_node)
    graph.add_node("security_review", security_review_node)
    graph.add_node("architecture_review", architecture_review_node)
    graph.add_node("performance_review", performance_review_node)
    graph.add_node("refactor_review", refactor_review_node)
    graph.add_node("arbitrate", arbitrate_node)
    graph.add_node("generate_report", generate_report_node)

    graph.set_entry_point("parse_code")

    # parse_code 完成后先进入 skill_scan（可选执行），再并行启动 5 个 Agent
    graph.add_edge("parse_code", "skill_scan")
    graph.add_edge("skill_scan", "style_review")
    graph.add_edge("skill_scan", "security_review")
    graph.add_edge("skill_scan", "architecture_review")
    graph.add_edge("skill_scan", "performance_review")
    graph.add_edge("skill_scan", "refactor_review")

    graph.add_edge("style_review", "arbitrate")
    graph.add_edge("security_review", "arbitrate")
    graph.add_edge("architecture_review", "arbitrate")
    graph.add_edge("performance_review", "arbitrate")
    graph.add_edge("refactor_review", "arbitrate")

    graph.add_edge("arbitrate", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()


review_graph = build_review_graph()
