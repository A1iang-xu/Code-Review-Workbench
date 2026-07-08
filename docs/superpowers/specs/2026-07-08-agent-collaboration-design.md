# Agent 协作升级设计文档

> **方案**：Reflective Collaboration Loop（反思式协作循环）
> **日期**：2026-07-08
> **状态**：待审阅
> **参考**：Loop Engineering — Reflective Loop + Multi-Agent Negotiation 模式

---

## 1. 背景与目标

### 1.1 当前架构问题

当前系统采用 LangGraph 编排 5 个审查 Agent（style / security / architecture / performance / refactor）**完全并行执行**：

```
parse_code → skill_scan → [5 Agent 并行] → arbitrate → generate_report
```

**核心缺陷**：
- Agent 间**零通信**：每个 Agent 独立调用 LLM，互不知晓其他 Agent 的发现
- **协作机会丧失**：例如架构 Agent 发现循环依赖时，无法通知安全 Agent 重点检查这些模块的数据流；安全 Agent 发现 SQL 注入时，无法建议重构 Agent 介入数据访问层重构
- **仲裁阶段才去重**：问题在事后被发现重复，而非事中协同避免

### 1.2 升级目标

引入 Agent 间协作机制，使一个 Agent 的发现能**定向通知**其他 Agent 进行重点复查，同时：
- **保持第一轮并行速度**（不退化为串行）
- **协作是可选增量**（无信号时零开销）
- **复用现有基础设施**（ReviewState 状态管理、LangGraph 并行编排）
- **遵循 Loop Engineering 工程化原则**（硬边界、可观测、错误恢复）

### 1.3 Loop Engineering 理念映射

本方案融合 Loop Engineering 的两种经典模式：

| Loop 模式 | 在本方案中的体现 |
|----------|-----------------|
| **Reflective Loop** | 第一轮生成 → 信号交换 → 第二轮反思复查 → 收敛 |
| **Multi-Agent Negotiation** | Agent 间通过信号交换信息，定向协作 |

遵循 Anthropic《Building Effective Agents》建议：**第一轮即产出完整结果，第二轮仅作质量增强**，避免过度工程化。

---

## 2. 总体架构

### 2.1 新图结构

```
┌─────────────────────── 第一轮（保持并行速度）───────────────────────┐
                                                                     │
parse_code → skill_scan → ┬─ style_review ─────────┐                 │
                          ├─ security_review ──────┤                 │
                          ├─ architecture_review ──┼─→ signal_exchange
                          ├─ performance_review ───┤                 │
                          └─ refactor_review ──────┘                 │
                                                                     │
└────────────────────────────────────────────────────────────────────┘
                                                                     │
┌─────────────────────── 第二轮（可选，仅触发有信号的）──────────────┐ │
                                                                     ↓
              ┌─ collab_style ──────────┐ (仅当有发给 style 的信号)
              │                          │
              ├─ collab_security ────────┤ (仅当有发给 security 的信号)
              │                          │
signal_exchange → collab_architecture ───┤ → arbitrate → generate_report
              │                          │
              ├─ collab_performance ─────┤ (仅当有发给 performance 的信号)
              │                          │
              └─ collab_refactor ────────┘ (仅当有发给 refactor 的信号)
```

### 2.2 执行流程说明

1. **第一轮**：5 个 Agent 完全并行执行（与现有架构一致），每个 Agent 输出 `findings` + `signals`
2. **signal_exchange 节点**：
   - 汇聚所有 Agent 的 signals（已通过 `ReviewState.agent_signals` 的 `operator.add` reducer 自动汇聚）
   - 按 `target_agent` 分组统计，计算需要触发的 collab 节点列表
   - signals 本身保留在 state 中，collab 节点直接从 state 过滤读取
3. **第二轮 collaborative_review**（可选）：
   - 仅对"收到信号"的 Agent 触发对应的 collab 节点
   - 每个 collab 节点读取发给自己的 signals，**仅对信号涉及的特定文件/区域**做定向复查
   - 增量 findings 标记 `source: "collaboration"`
4. **仲裁汇总**：合并第一轮 + 第二轮结果，去重排序

### 2.3 关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 第一轮是否保持并行 | ✅ 是 | 速度不退化，符合"简单优先" |
| 第二轮是否必选 | ❌ 否（有信号才触发） | 无信号时零开销，向后兼容 |
| 协作轮次上限 | `max_collaboration_rounds = 1` | Anthropic 硬边界建议，避免无限循环 |
| 第二轮复查范围 | 仅信号涉及的文件/区域 | 避免全量重审，控制 token 成本 |
| 共享黑板载体 | ReviewState.agent_signals（LangGraph 状态） | 状态驱动，跨节点可靠共享，无需外部存储 |
| 第二轮模型层级 | LOCAL tier（本地模型） | 不挤占 CLOUD 推理预算，协作是增量优化 |

---

## 3. 数据结构设计

### 3.1 ReviewState 扩展

在 [backend/app/core/state.py](file:///e:/MiCode/code-review-workbench/backend/app/core/state.py) 中扩展：

```python
class ReviewState(TypedDict):
    # ... 现有字段保持不变 ...

    # ---- Agent 协作信号（第一轮 → signal_exchange）----
    # 每个 Agent 第一轮完成后输出的跨 Agent 关注信号
    agent_signals: Annotated[list[dict], operator.add]

    # ---- 第二轮协作复查结果 ----
    collaboration_results: Annotated[list[dict], operator.add]

    # ---- 协作控制 ----
    collaboration_enabled: bool  # 是否启用协作（配置项，默认 True）
    collaboration_round: int     # 当前协作轮次（0=未开始, 1=第一轮完成, 2=第二轮完成）
    active_collab_agents: list[str]  # 第二轮需要触发的 Agent 列表（由 signal_exchange 计算）
```

### 3.2 Signal 协议定义

在 `backend/app/core/agents/collaboration.py`（新增文件）中定义：

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentSignal:
    """Agent 间协作信号。

    由第一轮 Agent 发出，经 signal_exchange 路由，由第二轮 collab 节点接收。
    """

    source_agent: str          # 发送方 agent_type (如 "architecture")
    target_agent: str          # 接收方 agent_type (如 "security")
    signal_type: str           # "focus_area" | "suspected_issue" | "context_hint"
    file_paths: list[str]      # 涉及的文件路径（用于第二轮定向复查）
    location: dict             # {"line_start": int, "line_end": int} 或 {} (整文件)
    message: str               # 人类可读的协作说明
    severity_hint: str         # "critical" | "high" | "medium" | "low" 建议严重等级
    context: dict = field(default_factory=dict)  # 额外上下文（循环依赖链、耦合节点等）

    def to_dict(self) -> dict:
        return {
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
            "signal_type": self.signal_type,
            "file_paths": self.file_paths,
            "location": self.location,
            "message": self.message,
            "severity_hint": self.severity_hint,
            "context": self.context,
        }


# 信号类型语义：
# - focus_area: 建议接收方重点检查某些文件/区域（不指定具体问题）
# - suspected_issue: 发送方怀疑存在某类问题，请接收方确认
# - context_hint: 提供背景上下文，帮助接收方更准确地判断
```

### 3.3 信号路由规则

```python
# 哪个 Agent 的哪类问题应该通知哪些其他 Agent
# key: (source_agent, category)，value: (target_agent, signal_type, message_template)
SIGNAL_ROUTING_RULES: dict[tuple[str, str], tuple[str, str, str]] = {
    # 架构 Agent 发现循环依赖 → 通知 security 检查数据流注入风险
    ("architecture", "dependency_direction"): (
        "security",
        "focus_area",
        "检测到循环依赖链 {cycle}，建议重点检查这些模块的数据流是否存在注入或越权风险",
    ),
    # 架构 Agent 发现高耦合 → 通知 performance 检查性能瓶颈
    ("architecture", "coupling"): (
        "performance",
        "focus_area",
        "模块 {node} 被 {degree} 个模块依赖，建议检查其是否存在性能瓶颈或调用热点",
    ),
    # 架构 Agent 发现接口设计问题 → 通知 refactor 建议重构
    ("architecture", "interface_design"): (
        "refactor",
        "suspected_issue",
        "接口设计存在问题，建议重构以降低参数数量或拆分职责",
    ),
    # 安全 Agent 发现 SQL 注入 → 通知 refactor 建议重构数据访问层
    ("security", "sql_injection"): (
        "refactor",
        "suspected_issue",
        "发现 SQL 注入风险，建议重构数据访问层，引入 ORM 或参数化查询封装",
    ),
    # 安全 Agent 发现硬编码密钥 → 通知 refactor 建议提取配置层
    ("security", "hardcoded_secret"): (
        "refactor",
        "suspected_issue",
        "发现硬编码密钥，建议提取到配置层并使用环境变量管理",
    ),
    # 性能 Agent 发现高复杂度 → 通知 refactor 建议拆分函数
    ("performance", "complexity"): (
        "refactor",
        "focus_area",
        "函数圈复杂度过高 {complexity}，建议拆分为多个职责单一的函数",
    ),
    # 性能 Agent 发现嵌套循环 → 通知 architecture 评估算法选择
    ("performance", "nested_loop"): (
        "architecture",
        "context_hint",
        "发现深层嵌套循环，建议评估算法选择是否合理，考虑数据结构优化",
    ),
    # 重构 Agent 发现长参数列表 → 通知 style 检查命名规范
    ("refactor", "long_parameter_list"): (
        "style",
        "focus_area",
        "函数参数过多，建议检查参数命名是否清晰，考虑引入参数对象",
    ),
}
```

---

## 4. 节点设计

### 4.1 Agent 接口扩展

在 [backend/app/core/agents/base.py](file:///e:/MiCode/code-review-workbench/backend/app/core/agents/base.py) 的 `BaseReviewAgent` 中新增两个可选方法：

```python
class BaseReviewAgent(ABC):
    # ... 现有方法保持不变 ...

    async def emit_signals(
        self, findings: list[dict], parsed_files: list[ParsedFile]
    ) -> list[dict]:
        """从第一轮审查结果中提取协作信号。

        默认实现：根据 SIGNAL_ROUTING_RULES 匹配 findings 的 (agent_type, category)，
        生成对应信号。子类可覆盖以实现自定义信号逻辑。

        Args:
            findings: 第一轮 review() 的结果
            parsed_files: 已解析文件列表

        Returns:
            信号字典列表（每个字典符合 AgentSignal.to_dict() 格式）
        """
        # 默认实现在 BaseReviewAgent 中提供，子类通常无需覆盖
        from app.core.agents.collaboration import SIGNAL_ROUTING_RULES

        signals: list[dict] = []
        # 仅对 critical/high 问题生成信号，避免信号爆炸
        for finding in findings:
            if finding.get("severity") not in ("critical", "high"):
                continue
            category = finding.get("category", "")
            key = (self.agent_type, category)
            rule = SIGNAL_ROUTING_RULES.get(key)
            if rule is None:
                continue
            target_agent, signal_type, message_tmpl = rule
            # 填充模板变量
            message = message_tmpl.format(
                cycle=finding.get("description", "")[:80],
                node=finding.get("title", "")[:60],
                degree=finding.get("description", "").count(",") + 1,
                complexity=finding.get("title", ""),
            )
            signals.append({
                "source_agent": self.agent_type,
                "target_agent": target_agent,
                "signal_type": signal_type,
                "file_paths": [finding.get("file_path", "")] if finding.get("file_path") else [],
                "location": {
                    "line_start": finding.get("line_start", 0),
                    "line_end": finding.get("line_end", 0),
                },
                "message": message,
                "severity_hint": finding.get("severity", "medium"),
                "context": {"original_finding": finding},
            })
        return signals

    async def collaborative_review(
        self,
        parsed_files: list[ParsedFile],
        signals: list[dict],
    ) -> list[dict]:
        """第二轮协作复查。

        默认实现：筛选出信号涉及的文件，注入协作上下文到 LLM prompt，
        对相关文件做定向复查。子类可覆盖以实现特定协作逻辑。

        Args:
            parsed_files: 已解析文件列表
            signals: 发给自己的信号列表

        Returns:
            增量 findings 列表（每个 finding 标记 source="collaboration"）
        """
        if not signals:
            return []

        # 收集信号涉及的文件路径
        target_paths: set[str] = set()
        for sig in signals:
            for p in sig.get("file_paths", []):
                if p:
                    target_paths.add(p)

        # 筛选相关文件
        relevant_files = [pf for pf in parsed_files if pf.path in target_paths]
        if not relevant_files:
            return []

        # 构建协作上下文
        collab_context = self._build_collab_context(signals)

        # 调用子类的 _collab_llm_review（由子类实现具体复查逻辑）
        # 默认实现：复用 _llm_analyze，注入协作上下文
        return await self._default_collab_review(relevant_files, collab_context, signals)

    async def _default_collab_review(
        self,
        relevant_files: list[ParsedFile],
        collab_context: str,
        signals: list[dict],
    ) -> list[dict]:
        """默认协作复查实现（子类可覆盖）。"""
        # 默认返回空，由具体 Agent 决定是否实现
        return []

    @staticmethod
    def _build_collab_context(signals: list[dict]) -> str:
        """构建协作上下文文本，注入 LLM prompt。"""
        if not signals:
            return ""
        parts = ["\n\n--- Collaboration Context ---"]
        parts.append("Other agents have flagged the following concerns for your attention:")
        for i, sig in enumerate(signals, 1):
            parts.append(
                f"{i}. [{sig.get('source_agent')}] {sig.get('message')} "
                f"(severity_hint: {sig.get('severity_hint')})"
            )
        parts.append("Please pay extra attention to these areas during your review.")
        parts.append("--- End Collaboration Context ---\n")
        return "\n".join(parts)
```

### 4.2 signal_exchange 节点

新增 `signal_exchange_node`，位于第一轮之后、第二轮之前：

```python
async def signal_exchange_node(state: ReviewState) -> dict[str, Any]:
    """信号交换节点。

    汇聚所有第一轮 Agent 的 signals，按 target_agent 分组统计，
    计算需要触发的第二轮 collab 节点列表。

    设计说明：
    signals 本身已通过 ReviewState.agent_signals（Annotated list + operator.add）
    汇聚到 state 中，无需额外存入 WorkingMemory。collab 节点直接从
    state.agent_signals 过滤 target_agent 即可。这避免了 WorkingMemory
    跨节点共享的问题（_get_memory() 每次返回新实例，实例属性不共享），
    也更符合 LangGraph 状态驱动的设计理念。

    若无任何信号或协作被禁用，则不触发第二轮。
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

    # 按 target_agent 分组统计（仅计算 active 列表，signals 本身已在 state 中）
    signals_by_target: dict[str, list[dict]] = {}
    for sig in all_signals:
        target = sig.get("target_agent", "")
        if target:
            signals_by_target.setdefault(target, []).append(sig)

    # 计算需要触发的 collab 节点
    active_agents = list(signals_by_target.keys())

    # 记录协作链路日志
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
```

### 4.3 collaborative_review 节点（工厂生成）

```python
def _make_collab_review_node(agent_type: str, agent_cls: type):
    """工厂：生成第二轮协作复查节点。

    每个 Agent 对应一个 collab 节点，读取发给自己的 signals，
    对信号涉及的文件做定向复查。
    """
    async def _node(state: ReviewState) -> dict[str, Any]:
        start_time = time.time()
        task_id = state.get("task_id", "")

        # 检查是否需要执行（signal_exchange 计算的 active_collab_agents）
        active_agents = state.get("active_collab_agents", [])
        if agent_type not in active_agents:
            # 无信号发给本 Agent，跳过
            return {}

        # 从 ReviewState.agent_signals 过滤出发给自己的信号
        # （signals 已通过 operator.add 汇聚到 state，无需依赖 WorkingMemory）
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

        # 调用协作复查
        try:
            collab_findings = await agent.collaborative_review(
                parsed_files=parsed_files,
                signals=my_signals,
            )
        except Exception as e:
            collab_findings = []
            from app.utils.logger import get_logger
            logger = get_logger(__name__)
            logger.warning("[Collaboration] %s 协作复查失败: %s", agent_type, e)

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
```

### 4.4 第一轮节点改造（emit_signals）

修改 `_make_agent_review_node` 工厂，在第一轮 review 后调用 emit_signals：

```python
def _make_agent_review_node(agent_type, agent_cls, progress, results_key):
    async def _node(state: ReviewState) -> dict[str, Any]:
        start_time = time.time()
        task_id = state.get("task_id", "")
        parsed_files = state.get("_parsed_files", [])
        context = _get_agent_context(state, agent_type=agent_type)
        agent = agent_cls(context)

        # 第一轮审查
        results, errors = await _run_agent_with_tracing(agent, agent_type, parsed_files)

        # 新增：从审查结果中提取协作信号
        signals: list[dict] = []
        try:
            signals = await agent.emit_signals(results, parsed_files)
        except Exception as e:
            from app.utils.logger import get_logger
            get_logger(__name__).warning(
                "[Collaboration] %s 信号生成失败: %s", agent_type, e
            )

        elapsed_ms = int((time.time() - start_time) * 1000)
        if task_id:
            update_progress(task_id, progress, "agent_reviews", "running")

        return {
            "current_stage": "agent_reviews",
            "progress": progress,
            results_key: results,
            "agent_signals": signals,  # 新增：输出信号
            "errors": errors,
            "agent_durations": {agent_type: elapsed_ms},
        }

    _node.__name__ = f"{agent_type}_review_node"
    return _node
```

### 4.5 arbitrate_node 改造

合并第一轮 + 第二轮结果：

```python
async def arbitrate_node(state: ReviewState) -> dict[str, Any]:
    # ... 现有逻辑 ...

    # 合并第一轮结果
    all_first_round = (
        state.get("style_results", []) +
        state.get("security_results", []) +
        state.get("architecture_results", []) +
        state.get("performance_results", []) +
        state.get("refactor_results", [])
    )

    # 新增：合并第二轮协作结果
    collab_results = state.get("collaboration_results", [])

    # 传给仲裁器（arbitrate_full 内部去重时会保留 source 字段）
    arbitrated = await arbitrator.arbitrate_full(
        style_results=state.get("style_results", []),
        security_results=state.get("security_results", []),
        architecture_results=state.get("architecture_results", []),
        performance_results=state.get("performance_results", []),
        refactor_results=state.get("refactor_results", []),
        collaboration_results=collab_results,  # 新增参数
        task_id=state.get("task_id", ""),
    )
    # ... 其余逻辑不变 ...
```

### 4.6 图构建

```python
def build_review_graph() -> StateGraph:
    graph = StateGraph(ReviewState)

    # 第一轮节点
    graph.add_node("parse_code", parse_code_node)
    graph.add_node("skill_scan", skill_scan_node)
    graph.add_node("style_review", style_review_node)
    graph.add_node("security_review", security_review_node)
    graph.add_node("architecture_review", architecture_review_node)
    graph.add_node("performance_review", performance_review_node)
    graph.add_node("refactor_review", refactor_review_node)

    # 协作节点
    graph.add_node("signal_exchange", signal_exchange_node)
    graph.add_node("collab_style", collab_style_node)
    graph.add_node("collab_security", collab_security_node)
    graph.add_node("collab_architecture", collab_architecture_node)
    graph.add_node("collab_performance", collab_performance_node)
    graph.add_node("collab_refactor", collab_refactor_node)

    # 仲裁与报告
    graph.add_node("arbitrate", arbitrate_node)
    graph.add_node("generate_report", generate_report_node)

    graph.set_entry_point("parse_code")

    # 第一轮并行
    graph.add_edge("parse_code", "skill_scan")
    graph.add_edge("skill_scan", "style_review")
    graph.add_edge("skill_scan", "security_review")
    graph.add_edge("skill_scan", "architecture_review")
    graph.add_edge("skill_scan", "performance_review")
    graph.add_edge("skill_scan", "refactor_review")

    # 第一轮 → signal_exchange（汇聚）
    graph.add_edge("style_review", "signal_exchange")
    graph.add_edge("security_review", "signal_exchange")
    graph.add_edge("architecture_review", "signal_exchange")
    graph.add_edge("performance_review", "signal_exchange")
    graph.add_edge("refactor_review", "signal_exchange")

    # signal_exchange → 条件 fan-out（仅触发有信号的 collab 节点）
    def _route_collaboration(state: ReviewState) -> list[str]:
        """根据 active_collab_agents 返回需要执行的 collab 节点列表。"""
        active = state.get("active_collab_agents", [])
        if not active:
            return ["arbitrate"]  # 无信号，直接仲裁
        # 返回需要触发的 collab 节点名
        return [f"collab_{a}" for a in active]

    graph.add_conditional_edges(
        "signal_exchange",
        _route_collaboration,
        {
            "collab_style": "collab_style",
            "collab_security": "collab_security",
            "collab_architecture": "collab_architecture",
            "collab_performance": "collab_performance",
            "collab_refactor": "collab_refactor",
            "arbitrate": "arbitrate",
        },
    )

    # 所有 collab 节点 → arbitrate
    graph.add_edge("collab_style", "arbitrate")
    graph.add_edge("collab_security", "arbitrate")
    graph.add_edge("collab_architecture", "arbitrate")
    graph.add_edge("collab_performance", "arbitrate")
    graph.add_edge("collab_refactor", "arbitrate")

    graph.add_edge("arbitrate", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()
```

---

## 5. 具体 Agent 协作实现

### 5.1 ArchitectureAnalyzerAgent（信号发送方）

架构 Agent 是主要的信号发送方。复用现有 `_analyze_graph` 的发现，在 `emit_signals` 中增强信号上下文：

```python
class ArchitectureAnalyzerAgent(BaseReviewAgent):
    # ... 现有方法不变 ...

    async def emit_signals(
        self, findings: list[dict], parsed_files: list[ParsedFile]
    ) -> list[dict]:
        """架构 Agent 自定义信号生成。

        对循环依赖和高耦合问题生成更丰富的上下文信号。
        """
        signals: list[dict] = []
        for finding in findings:
            category = finding.get("category", "")
            severity = finding.get("severity", "")

            # 循环依赖 → 通知 security 检查数据流
            if category == "dependency_direction" and severity in ("critical", "high"):
                # 从 description 提取循环依赖链
                desc = finding.get("description", "")
                signals.append({
                    "source_agent": "architecture",
                    "target_agent": "security",
                    "signal_type": "focus_area",
                    "file_paths": self._extract_cycle_files(desc, parsed_files),
                    "location": {"line_start": 0, "line_end": 0},
                    "message": f"检测到循环依赖，建议重点检查这些模块的数据流是否存在注入或越权风险",
                    "severity_hint": "high",
                    "context": {
                        "cycle_description": desc[:200],
                        "original_finding_title": finding.get("title", ""),
                    },
                })

            # 高耦合 → 通知 performance 检查性能瓶颈
            elif category == "coupling" and severity in ("critical", "high"):
                signals.append({
                    "source_agent": "architecture",
                    "target_agent": "performance",
                    "signal_type": "focus_area",
                    "file_paths": [finding.get("file_path", "")] if finding.get("file_path") else [],
                    "location": {"line_start": 0, "line_end": 0},
                    "message": f"模块被多模块依赖，建议检查其是否存在性能瓶颈或调用热点",
                    "severity_hint": severity,
                    "context": {
                        "coupling_degree": finding.get("title", ""),
                        "original_finding": finding,
                    },
                })

        return signals

    def _extract_cycle_files(self, cycle_desc: str, parsed_files: list) -> list[str]:
        """从循环依赖描述中提取涉及的文件路径。"""
        # 简单实现：匹配 parsed_files 中的路径
        matched = []
        for pf in parsed_files:
            if pf.path in cycle_desc or self._path_to_module(pf.path, pf.language) in cycle_desc:
                matched.append(pf.path)
        return matched[:5]  # 限制最多 5 个文件
```

### 5.2 SecurityAuditorAgent（信号接收方）

安全 Agent 实现协作复查，对架构 Agent 标记的循环依赖模块重点检查数据流：

```python
class SecurityAuditorAgent(BaseReviewAgent):
    # ... 现有方法不变 ...

    async def collaborative_review(
        self,
        parsed_files: list[ParsedFile],
        signals: list[dict],
    ) -> list[dict]:
        """安全 Agent 协作复查。

        当收到架构 Agent 的循环依赖信号时，对这些模块的数据流做深度安全分析。
        """
        if not signals:
            return []

        # 收集信号涉及的文件
        target_paths: set[str] = set()
        for sig in signals:
            for p in sig.get("file_paths", []):
                if p:
                    target_paths.add(p)

        relevant_files = [pf for pf in parsed_files if pf.path in target_paths]
        if not relevant_files:
            return []

        all_collab_findings: list[dict] = []
        for pf in relevant_files:
            if pf.language not in SUPPORTED_LANGUAGES:
                continue

            # 构建协作上下文增强的 prompt
            collab_ctx = self._build_collab_context(signals)
            content = pf.content
            if len(content) > 8000:
                content = content[:8000] + "\n# ... (truncated)"

            prompt = (
                f"{SECURITY_PROMPT}\n\n"
                f"Another agent has flagged this file as potentially risky. "
                f"Pay special attention to data flow, input validation, and "
                f"authorization boundaries in this module.\n\n"
                f"File path: {pf.path}{collab_ctx}"
            )

            try:
                response = await self._llm_analyze(
                    prompt=prompt,
                    code_context=content,
                    use_reasoning=False,  # 第二轮用本地模型，节省 CLOUD 预算
                )
                # 解析 JSON（复用现有逻辑）
                findings = self._parse_llm_response(response, pf)
                all_collab_findings.extend(findings)
            except Exception as e:
                print(f"[SecurityAuditor][Collab] 协作复查失败: {e}")

        return all_collab_findings

    def _parse_llm_response(self, response: str, parsed_file: ParsedFile) -> list[dict]:
        """复用现有 _llm_scan 的 JSON 解析逻辑。"""
        # 提取自 _llm_scan 的解析部分
        import json, re
        json_match = re.search(r"\[.*\]", response, re.DOTALL)
        if not json_match:
            return []
        try:
            findings = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            raw = re.sub(r",\s*]", "]", json_match.group(0))
            try:
                findings = json.loads(raw)
            except json.JSONDecodeError:
                return []
        for f in findings:
            f["agent_type"] = self.agent_type
            f["file_path"] = parsed_file.path
            f["line_start"] = f.get("line_start", 0)
            f["line_end"] = f.get("line_end", 0)
            f["code_snippet"] = f.get("code_snippet", "")
            if f.get("severity") not in ("critical", "high", "medium", "low", "info"):
                f["severity"] = "medium"
        return findings
```

### 5.3 其他 Agent 的协作实现

- **PerformanceProfilerAgent**：收到高耦合信号时，对相关模块做复杂度热点分析
- **RefactorAdvisorAgent**：收到 SQL 注入/硬编码密钥信号时，建议数据访问层重构方案
- **StyleCheckerAgent**：收到长参数列表信号时，检查命名规范和参数对象化建议

> 注：为控制实现复杂度，**首期仅实现 Architecture→Security 关键协作链路**（架构发现循环依赖/高耦合 → 通知安全深度复查）。Architecture→Performance 链路及其他 Agent 暂用 `BaseReviewAgent` 的默认实现（collaborative_review 返回空），后续迭代再扩展。emit_signals 默认实现仍会为所有匹配路由规则的 Agent 生成信号，只是接收方暂不处理。

---

## 6. 降级与硬边界策略

### 6.1 硬边界（Loop Engineering 必需）

| 边界类型 | 限制值 | 实现位置 |
|---------|--------|---------|
| 协作轮次上限 | `max_collaboration_rounds = 1` | 图结构固定（仅一轮 collab） |
| 单 Agent 信号数上限 | 每个 Agent 最多发出 10 个信号 | `emit_signals` 中截断 |
| 协作复查文件数上限 | 每个 collab 节点最多复查 5 个文件 | `collaborative_review` 中限制 |
| 协作阶段总超时 | 60 秒（可配置） | `collab_*_node` 中检查 |
| 第二轮 token 预算 | 使用 LOCAL tier，不挤占 CLOUD | `_llm_analyze(use_reasoning=False)` |

### 6.2 降级策略

| 故障场景 | 降级行为 |
|---------|---------|
| `collaboration_enabled = False`（配置项） | 完全跳过协作，行为同现有架构 |
| `emit_signals` 异常 | 记录 warning，该 Agent 不发信号，不影响第一轮 |
| `signal_exchange` 异常 | 跳过第二轮，直接进入 arbitrate |
| `collab_*_node` 异常 | 该 Agent 协作结果为空，其他 Agent 不受影响 |
| `agent_signals` 为空 | signal_exchange 返回 `active_collab_agents=[]`，直接仲裁 |
| 第二轮 LLM 超时 | 跳过该文件，继续下一个 |
| 无任何信号产生 | `_route_collaboration` 返回 `["arbitrate"]`，直接仲裁 |

### 6.3 配置项

在 [backend/app/config.py](file:///e:/MiCode/code-review-workbench/backend/app/config.py) 中新增：

```python
# Agent 协作配置
COLLABORATION_ENABLED: bool = True              # 是否启用 Agent 协作
COLLABORATION_MAX_SIGNALS_PER_AGENT: int = 10   # 单 Agent 信号数上限
COLLABORATION_MAX_FILES_PER_REVIEW: int = 5     # 单 collab 节点复查文件数上限
COLLABORATION_TIMEOUT_SECONDS: int = 60         # 协作阶段总超时
```

---

## 7. 可观测性设计

### 7.1 日志追踪

每个协作环节记录结构化日志：

```python
# signal_exchange 节点
logger.info(
    "[Collaboration] 信号交换完成: task=%s signals=%d active_agents=%s",
    task_id, len(all_signals), active_agents,
)

# collab 节点
logger.info(
    "[Collaboration] %s 收到 %d 个信号, 复查 %d 个文件, 发现 %d 个增量问题",
    agent_type, len(my_signals), len(relevant_files), len(collab_findings),
)
```

### 7.2 OpenTelemetry Span

为协作节点添加独立 span：

```python
async def _run_collab_with_tracing(agent, agent_type, parsed_files, signals):
    with tracer.start_as_current_span(f"collab.{agent_type}") as span:
        span.set_attribute("collab.agent", agent_type)
        span.set_attribute("collab.signals_count", len(signals))
        results = await agent.collaborative_review(parsed_files, signals)
        span.set_attribute("collab.findings_count", len(results))
        return results
```

### 7.3 前端展示

在 [frontend/src/components/review/AgentTimeline.tsx](file:///e:/MiCode/code-review-workbench/frontend/src/components/review/AgentTimeline.tsx) 中扩展时间线，展示协作链路：

- 第一轮 Agent 节点（现有）
- signal_exchange 节点（新增，显示信号数）
- 第二轮 collab 节点（新增，标记"协作"标签）
- 每个 collab finding 在报告中标明 `triggered_by` 来源

### 7.4 报告标记

协作发现的问题在 HTML 报告中额外显示：

```html
<div class="issue-item">
  <span class="severity-badge">HIGH</span>
  <span class="collab-badge">协作发现</span>  <!-- 新增 -->
  <span class="triggered-by">由 architecture 触发</span>  <!-- 新增 -->
  ...
</div>
```

---

## 8. 兼容性与风险分析

### 8.1 向后兼容性

| 方面 | 兼容性 |
|------|--------|
| 现有 API（POST /reviews） | ✅ 完全兼容，`collaboration_enabled` 默认 True 但可关闭 |
| 现有 ReviewState 字段 | ✅ 全部保留，仅新增字段 |
| 现有 Agent 实现 | ✅ 无需改动即可运行（BaseReviewAgent 提供默认空实现） |
| 现有测试 | ✅ 通过 `collaboration_enabled=False` 可回退到原行为 |
| 前端时间线 | ⚠️ 需扩展（新增 collab 节点展示），但不影响现有功能 |

### 8.2 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 第二轮增加总耗时 | 中（有信号时增加 10-30 秒） | 并行触发 + 文件数限制 + 超时保护 |
| 信号爆炸（大量误报信号） | 中（第二轮过载） | 仅 critical/high 生成信号 + 单 Agent 信号上限 |
| 协作发现与第一轮重复 | 低（仲裁去重） | arbitrate 去重时合并 `source` 字段 |
| LangGraph 条件边 fan-out 行为不确定 | 中 | 测试验证 + 降级方案（固定边 + 节点内跳过） |
| signals 在 state 中体积过大 | 低 | 仅 critical/high 生成信号 + 单 Agent 上限 + context 截断 |

### 8.3 LangGraph 条件边 fan-out 验证

需验证 `add_conditional_edges` 返回多个节点时是否真正并行执行。若不支持，降级方案：

```python
# 降级方案：用固定 collab_router 节点，所有 collab 节点都执行，
# 但在节点内部检查 active_collab_agents 决定是否实际工作
graph.add_edge("signal_exchange", "collab_style")  # 固定边
graph.add_edge("signal_exchange", "collab_security")
# ... collab 节点内部若不在 active_agents 则返回空 ...
```

---

## 9. 测试策略

### 9.1 单元测试

| 测试项 | 文件 |
|--------|------|
| `AgentSignal` 序列化/反序列化 | `tests/test_agents/test_collaboration.py`（新增） |
| `emit_signals` 默认实现匹配路由规则 | 同上 |
| `BaseReviewAgent._build_collab_context` 格式 | 同上 |
| `signal_exchange_node` 信号分组逻辑 | `tests/test_core/test_orchestrator.py`（扩展） |
| `_route_collaboration` 条件路由 | 同上 |
| `collab_*_node` 跳过逻辑（无信号时返回空） | 同上 |

### 9.2 集成测试

| 测试项 | 验证点 |
|--------|--------|
| 架构 Agent 发现循环依赖 → 安全 Agent 协作复查 | 增量 findings 标记 `source="collaboration"` |
| 无信号场景 → 跳过第二轮 | `active_collab_agents=[]`，直接仲裁 |
| `collaboration_enabled=False` → 行为同旧版 | 无 collab 节点执行 |
| collab 节点异常 → 降级 | 其他 Agent 不受影响，最终报告生成 |

### 9.3 手动验收脚本

扩展 `tests/test_phase1_manual.py`（手动验收），新增场景：

```python
# 场景：提交含循环依赖 + SQL 注入的代码
# 预期：
# 1. architecture Agent 检测到循环依赖，发出信号给 security
# 2. collab_security 节点被触发，对循环依赖涉及的文件做深度安全复查
# 3. 报告中出现 source="collaboration" 的增量发现
# 4. 总耗时不超过 120 秒
```

---

## 10. 实现范围（首期）

为控制复杂度，首期实现范围：

### 10.1 必做（首期）

- [ ] ReviewState 扩展（新增 4 个字段）
- [ ] `collaboration.py` 新增（AgentSignal + 路由规则）
- [ ] `BaseReviewAgent` 扩展（emit_signals + collaborative_review 默认实现）
- [ ] `signal_exchange_node` 实现
- [ ] `_make_collab_review_node` 工厂 + 5 个 collab 节点
- [ ] `_make_agent_review_node` 改造（调用 emit_signals）
- [ ] `arbitrate_node` 改造（合并 collaboration_results）
- [ ] `build_review_graph` 重构（新增协作节点和条件边）
- [ ] **ArchitectureAnalyzerAgent.emit_signals** 实现（循环依赖 + 高耦合信号）
- [ ] **SecurityAuditorAgent.collaborative_review** 实现（数据流深度复查）
- [ ] config.py 新增协作配置项
- [ ] 单元测试 + 集成测试

### 10.2 可选（后续迭代）

- PerformanceProfilerAgent.collaborative_review
- RefactorAdvisorAgent.collaborative_review
- StyleCheckerAgent.collaborative_review
- 前端 AgentTimeline 展示协作链路
- HTML 报告中协作发现特殊标记
- 信号路由规则可视化配置界面

---

## 11. 数据流示例

### 场景：提交含循环依赖 + SQL 注入的代码

```
1. parse_code → 解析出 app/models/user.py 和 app/api/users.py

2. 第一轮并行:
   - architecture_review:
     findings: [{循环依赖: user.py ↔ users.py, severity: high}]
     signals: [{
       source: "architecture",
       target: "security",
       type: "focus_area",
       file_paths: ["app/models/user.py", "app/api/users.py"],
       message: "检测到循环依赖，建议重点检查数据流注入风险"
     }]
   - security_review:
     findings: [{SQL 注入: app/api/users.py:42, severity: critical}]
     signals: [{
       source: "security",
       target: "refactor",
       type: "suspected_issue",
       file_paths: ["app/api/users.py"],
       message: "建议重构数据访问层"
     }]
   - 其他 Agent: findings=[], signals=[]

3. signal_exchange:
   - 汇聚 2 个信号
   - signals_by_target = {
       "security": [架构发来的信号],
       "refactor": [安全发来的信号]
     }
   - active_collab_agents = ["security", "refactor"]

4. 第二轮（仅触发 collab_security 和 collab_refactor）:
   - collab_security: 读取架构信号，对 user.py + users.py 做深度数据流分析
     → 发现 path traversal 风险（第一轮未检出）
   - collab_refactor: 读取安全信号，建议引入 ORM
     → 输出重构方案

5. arbitrate:
   - 合并第一轮 + 第二轮结果
   - 去重排序
   - 标记 source="collaboration" 的增量发现
```

---

## 12. 总结

本方案通过引入 **Reflective Collaboration Loop**，在不牺牲第一轮并行速度的前提下，实现了 Agent 间的定向协作：

- **核心价值**：架构 Agent 能真正通知安全 Agent 重点检查，安全 Agent 能建议重构 Agent 介入
- **工程化保障**：硬边界（1 轮协作）、降级策略、可观测性（日志 + span + 报告标记）
- **Loop Engineering 契合**：Reflective Loop 模式 + Multi-Agent Negotiation 信号交换
- **渐进式实现**：首期仅做 Architecture→Security 关键链路，其他 Agent 用默认空实现，后续迭代扩展
- **向后兼容**：`collaboration_enabled=False` 即可回退到原并行架构

方案设计遵循 Anthropic "简单优先" 原则：第一轮即产出完整结果，第二轮仅作质量增强，避免过度工程化。

---

**请审阅此设计文档，确认无误后我将调用 writing-plans skill 生成详细实现计划并执行。**
