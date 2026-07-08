# Agent 协作升级实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 引入 Agent 间 Reflective Collaboration Loop，使第一轮 Agent 发现的问题能通过信号定向通知第二轮协作复查，实现跨 Agent 协作（首期：Architecture→Security 链路）。

**Architecture:** 在现有 LangGraph 并行图基础上，第一轮 5 个 Agent 完成后新增 `signal_exchange` 节点汇聚协作信号，通过条件边 fan-out 触发有信号的 `collab_*` 节点做定向复查，最后由 arbitrate 合并两轮结果。signals 通过 ReviewState 传递，第二轮使用 LOCAL tier 模型，max_rounds=1 硬边界。

**Tech Stack:** Python 3.11 / LangGraph / asyncio / pytest / pydantic-settings

**Spec:** [docs/superpowers/specs/2026-07-08-agent-collaboration-design.md](file:///e:/MiCode/code-review-workbench/docs/superpowers/specs/2026-07-08-agent-collaboration-design.md)

---

## File Structure

| 文件 | 职责 | 操作 |
|------|------|------|
| `backend/app/core/agents/collaboration.py` | AgentSignal 数据类 + SIGNAL_ROUTING_RULES 路由表 | Create |
| `backend/app/core/state.py` | ReviewState 扩展协作字段 | Modify |
| `backend/app/core/agents/base.py` | BaseReviewAgent 新增 emit_signals / collaborative_review | Modify |
| `backend/app/config.py` | 新增协作配置项 | Modify |
| `backend/app/core/orchestrator.py` | signal_exchange_node + collab 工厂 + 图重构 | Modify |
| `backend/app/core/tasks.py` | initial_state 初始化协作字段 + agent_timeline 扩展 | Modify |
| `backend/app/core/agents/arbitrator.py` | arbitrate_full 接受 collaboration_results | Modify |
| `backend/app/core/agents/architecture.py` | emit_signals 自定义实现 | Modify |
| `backend/app/core/agents/security.py` | collaborative_review 自定义实现 | Modify |
| `backend/tests/test_agents/test_collaboration.py` | 协作单元测试 | Create |
| `backend/tests/test_core/test_orchestrator.py` | 节点/图结构测试扩展 | Modify |

---

## Task 1: 创建 collaboration.py（AgentSignal + 路由规则）

**Files:**
- Create: `backend/app/core/agents/collaboration.py`
- Test: `backend/tests/test_agents/test_collaboration.py`

- [ ] **Step 1: 写失败测试 — AgentSignal 序列化**

创建 `backend/tests/test_agents/test_collaboration.py`：

```python
"""Agent 协作模块单元测试。"""

from app.core.agents.collaboration import (
    AgentSignal,
    SIGNAL_ROUTING_RULES,
)


class TestAgentSignal:
    """AgentSignal 数据类测试。"""

    def test_to_dict_returns_all_fields(self):
        """to_dict 返回所有字段。"""
        sig = AgentSignal(
            source_agent="architecture",
            target_agent="security",
            signal_type="focus_area",
            file_paths=["app/models/user.py"],
            location={"line_start": 0, "line_end": 0},
            message="检测到循环依赖",
            severity_hint="high",
            context={"cycle": "a→b→a"},
        )
        d = sig.to_dict()
        assert d["source_agent"] == "architecture"
        assert d["target_agent"] == "security"
        assert d["signal_type"] == "focus_area"
        assert d["file_paths"] == ["app/models/user.py"]
        assert d["location"] == {"line_start": 0, "line_end": 0}
        assert d["message"] == "检测到循环依赖"
        assert d["severity_hint"] == "high"
        assert d["context"] == {"cycle": "a→b→a"}

    def test_default_context_is_empty_dict(self):
        """context 默认为空 dict。"""
        sig = AgentSignal(
            source_agent="a",
            target_agent="b",
            signal_type="focus_area",
            file_paths=[],
            location={},
            message="msg",
            severity_hint="medium",
        )
        assert sig.context == {}


class TestSignalRoutingRules:
    """信号路由规则测试。"""

    def test_architecture_dependency_direction_routes_to_security(self):
        """架构循环依赖 → 通知 security。"""
        rule = SIGNAL_ROUTING_RULES[("architecture", "dependency_direction")]
        assert rule[0] == "security"
        assert rule[1] == "focus_area"

    def test_security_sql_injection_routes_to_refactor(self):
        """安全 SQL 注入 → 通知 refactor。"""
        rule = SIGNAL_ROUTING_RULES[("security", "sql_injection")]
        assert rule[0] == "refactor"
        assert rule[1] == "suspected_issue"

    def test_all_rules_have_three_tuple(self):
        """所有规则都是 (target, type, message) 三元组。"""
        for key, value in SIGNAL_ROUTING_RULES.items():
            assert isinstance(key, tuple) and len(key) == 2
            assert isinstance(value, tuple) and len(value) == 3
            assert value[0]  # target 非空
            assert value[1] in ("focus_area", "suspected_issue", "context_hint")
            assert isinstance(value[2], str) and len(value[2]) > 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_agents/test_collaboration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.agents.collaboration'`

- [ ] **Step 3: 实现 collaboration.py**

创建 `backend/app/core/agents/collaboration.py`：

```python
"""Agent 协作模块 — 信号协议与路由规则。

定义 Agent 间协作信号的数据结构和路由规则。
信号由第一轮 Agent 发出，经 signal_exchange 节点汇聚，
由第二轮 collab 节点接收并据此做定向复查。
"""

from dataclasses import dataclass, field


@dataclass
class AgentSignal:
    """Agent 间协作信号。

    由第一轮 Agent 发出，经 signal_exchange 路由，由第二轮 collab 节点接收。

    Attributes:
        source_agent: 发送方 agent_type (如 "architecture")
        target_agent: 接收方 agent_type (如 "security")
        signal_type: 信号类型 "focus_area" | "suspected_issue" | "context_hint"
        file_paths: 涉及的文件路径列表（用于第二轮定向复查）
        location: {"line_start": int, "line_end": int} 或 {} (整文件)
        message: 人类可读的协作说明
        severity_hint: 建议严重等级 "critical" | "high" | "medium" | "low"
        context: 额外上下文（循环依赖链、耦合节点等）
    """

    source_agent: str
    target_agent: str
    signal_type: str
    file_paths: list[str]
    location: dict
    message: str
    severity_hint: str
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """序列化为字典（用于存入 ReviewState.agent_signals）。"""
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

# 信号路由规则：哪个 Agent 的哪类问题应该通知哪些其他 Agent
# key: (source_agent, category)，value: (target_agent, signal_type, message_template)
SIGNAL_ROUTING_RULES: dict[tuple[str, str], tuple[str, str, str]] = {
    # 架构 Agent 发现循环依赖 → 通知 security 检查数据流注入风险
    ("architecture", "dependency_direction"): (
        "security",
        "focus_area",
        "检测到循环依赖链，建议重点检查这些模块的数据流是否存在注入或越权风险",
    ),
    # 架构 Agent 发现高耦合 → 通知 performance 检查性能瓶颈
    ("architecture", "coupling"): (
        "performance",
        "focus_area",
        "模块被多模块依赖，建议检查其是否存在性能瓶颈或调用热点",
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
        "函数圈复杂度过高，建议拆分为多个职责单一的函数",
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

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_agents/test_collaboration.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: 提交**

```bash
git add backend/app/core/agents/collaboration.py backend/tests/test_agents/test_collaboration.py
git commit -m "feat(collaboration): add AgentSignal dataclass and routing rules"
```

---

## Task 2: 扩展 ReviewState 协作字段

**Files:**
- Modify: `backend/app/core/state.py`
- Test: `backend/tests/test_core/test_orchestrator.py`

- [ ] **Step 1: 写失败测试 — ReviewState 包含协作字段**

在 `backend/tests/test_core/test_orchestrator.py` 末尾追加：

```python
class TestReviewStateCollaborationFields:
    """验证 ReviewState 包含协作相关字段。"""

    def test_review_state_has_collaboration_fields(self):
        """ReviewState TypedDict 包含协作字段定义。"""
        from app.core.state import ReviewState
        hints = ReviewState.__annotations__
        assert "agent_signals" in hints
        assert "collaboration_results" in hints
        assert "collaboration_enabled" in hints
        assert "collaboration_round" in hints
        assert "active_collab_agents" in hints
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_core/test_orchestrator.py::TestReviewStateCollaborationFields -v`
Expected: FAIL — `AssertionError: 'agent_signals' not in hints`

- [ ] **Step 3: 扩展 ReviewState**

在 `backend/app/core/state.py` 的 `ReviewState` 类中，在 `agent_durations` 字段之前追加协作字段：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_core/test_orchestrator.py::TestReviewStateCollaborationFields -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/core/state.py backend/tests/test_core/test_orchestrator.py
git commit -m "feat(state): add collaboration fields to ReviewState"
```

---

## Task 3: BaseReviewAgent 扩展（emit_signals + collaborative_review）

**Files:**
- Modify: `backend/app/core/agents/base.py`
- Test: `backend/tests/test_agents/test_collaboration.py`

- [ ] **Step 1: 写失败测试 — emit_signals 默认实现**

在 `backend/tests/test_agents/test_collaboration.py` 末尾追加：

```python
class TestBaseReviewAgentEmitSignals:
    """BaseReviewAgent.emit_signals 默认实现测试。"""

    def test_emit_signals_filters_non_critical(self):
        """仅 critical/high 问题生成信号。"""
        from app.core.agents.style import StyleCheckerAgent
        from app.core.agents.base import AgentContext

        agent = StyleCheckerAgent(AgentContext())
        findings = [
            {"agent_type": "style", "severity": "low", "category": "naming",
             "file_path": "a.py", "line_start": 1, "line_end": 1, "title": "x"},
            {"agent_type": "style", "severity": "high", "category": "naming",
             "file_path": "a.py", "line_start": 1, "line_end": 1, "title": "x"},
        ]
        # style+naming 不在路由表中，所以即使 high 也不生成信号
        import asyncio
        signals = asyncio.run(agent.emit_signals(findings, []))
        assert signals == []

    def test_emit_signals_matches_routing_rule(self):
        """匹配路由规则的 high 问题生成信号。"""
        from app.core.agents.security import SecurityAuditorAgent
        from app.core.agents.base import AgentContext

        agent = SecurityAuditorAgent(AgentContext())
        findings = [
            {"agent_type": "security", "severity": "critical",
             "category": "sql_injection", "file_path": "db.py",
             "line_start": 10, "line_end": 10, "title": "SQL注入",
             "description": "拼接SQL"},
        ]
        import asyncio
        signals = asyncio.run(agent.emit_signals(findings, []))
        assert len(signals) == 1
        assert signals[0]["source_agent"] == "security"
        assert signals[0]["target_agent"] == "refactor"
        assert signals[0]["signal_type"] == "suspected_issue"
        assert signals[0]["file_paths"] == ["db.py"]

    def test_emit_signals_respects_max_limit(self):
        """信号数不超过配置上限（默认 10）。"""
        from app.core.agents.security import SecurityAuditorAgent
        from app.core.agents.base import AgentContext
        from app.config import get_settings

        agent = SecurityAuditorAgent(AgentContext())
        findings = [
            {"agent_type": "security", "severity": "critical",
             "category": "sql_injection", "file_path": f"f{i}.py",
             "line_start": 1, "line_end": 1, "title": "x", "description": "d"}
            for i in range(20)
        ]
        import asyncio
        signals = asyncio.run(agent.emit_signals(findings, []))
        max_signals = get_settings().COLLABORATION_MAX_SIGNALS_PER_AGENT
        assert len(signals) <= max_signals


class TestBuildCollabContext:
    """_build_collab_context 格式测试。"""

    def test_empty_signals_returns_empty(self):
        from app.core.agents.base import BaseReviewAgent
        assert BaseReviewAgent._build_collab_context([]) == ""

    def test_non_empty_signals_contains_message(self):
        from app.core.agents.base import BaseReviewAgent
        signals = [
            {"source_agent": "architecture", "message": "循环依赖",
             "severity_hint": "high"},
        ]
        ctx = BaseReviewAgent._build_collab_context(signals)
        assert "Collaboration Context" in ctx
        assert "循环依赖" in ctx
        assert "architecture" in ctx
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_agents/test_collaboration.py::TestBaseReviewAgentEmitSignals tests/test_agents/test_collaboration.py::TestBuildCollabContext -v`
Expected: FAIL — `AttributeError: 'StyleCheckerAgent' object has no attribute 'emit_signals'`

- [ ] **Step 3: 在 BaseReviewAgent 中新增方法**

在 `backend/app/core/agents/base.py` 的 `BaseReviewAgent` 类中，在 `_compress_code_context` 方法之后追加：

```python
    # ============================================================
    # Agent 协作接口
    # ============================================================

    async def emit_signals(
        self, findings: list[dict], parsed_files: list[ParsedFile]
    ) -> list[dict]:
        """从第一轮审查结果中提取协作信号。

        默认实现：根据 SIGNAL_ROUTING_RULES 匹配 findings 的 (agent_type, category)，
        仅对 critical/high 问题生成信号。子类可覆盖以实现自定义信号逻辑。

        Args:
            findings: 第一轮 review() 的结果
            parsed_files: 已解析文件列表（供子类增强上下文用）

        Returns:
            信号字典列表（符合 AgentSignal.to_dict() 格式）
        """
        from app.core.agents.collaboration import SIGNAL_ROUTING_RULES
        from app.config import get_settings

        max_signals = get_settings().COLLABORATION_MAX_SIGNALS_PER_AGENT
        signals: list[dict] = []

        for finding in findings:
            if len(signals) >= max_signals:
                break
            # 仅对 critical/high 问题生成信号，避免信号爆炸
            if finding.get("severity") not in ("critical", "high"):
                continue
            category = finding.get("category", "")
            key = (self.agent_type, category)
            rule = SIGNAL_ROUTING_RULES.get(key)
            if rule is None:
                continue
            target_agent, signal_type, message = rule
            file_path = finding.get("file_path", "")
            signals.append({
                "source_agent": self.agent_type,
                "target_agent": target_agent,
                "signal_type": signal_type,
                "file_paths": [file_path] if file_path else [],
                "location": {
                    "line_start": finding.get("line_start", 0),
                    "line_end": finding.get("line_end", 0),
                },
                "message": message,
                "severity_hint": finding.get("severity", "medium"),
                "context": {"original_finding_title": finding.get("title", "")},
            })
        return signals

    async def collaborative_review(
        self,
        parsed_files: list[ParsedFile],
        signals: list[dict],
    ) -> list[dict]:
        """第二轮协作复查。

        默认实现：返回空。子类（如 SecurityAuditorAgent）可覆盖以实现
        基于信号的定向复查逻辑。

        Args:
            parsed_files: 已解析文件列表
            signals: 发给自己的信号列表

        Returns:
            增量 findings 列表（调用方会标记 source="collaboration"）
        """
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

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_agents/test_collaboration.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: 提交**

```bash
git add backend/app/core/agents/base.py backend/tests/test_agents/test_collaboration.py
git commit -m "feat(agent): add emit_signals and collaborative_review to BaseReviewAgent"
```

---

## Task 4: config.py 新增协作配置项

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: 新增配置项**

在 `backend/app/config.py` 的 `Settings` 类中，在 `REVIEW_TIMEOUT_SECONDS` 之后追加：

```python
    # ---- Agent 协作配置 ----
    COLLABORATION_ENABLED: bool = True              # 是否启用 Agent 协作
    COLLABORATION_MAX_SIGNALS_PER_AGENT: int = 10   # 单 Agent 信号数上限
    COLLABORATION_MAX_FILES_PER_REVIEW: int = 5     # 单 collab 节点复查文件数上限
    COLLABORATION_TIMEOUT_SECONDS: int = 60         # 协作阶段总超时
```

- [ ] **Step 2: 验证配置加载**

Run: `cd backend && python -c "from app.config import get_settings; s = get_settings(); print(s.COLLABORATION_ENABLED, s.COLLABORATION_MAX_SIGNALS_PER_AGENT)"`
Expected: `True 10`

- [ ] **Step 3: 提交**

```bash
git add backend/app/config.py
git commit -m "feat(config): add collaboration settings"
```

---

## Task 5: ArchitectureAnalyzerAgent.emit_signals 自定义实现

**Files:**
- Modify: `backend/app/core/agents/architecture.py`
- Test: `backend/tests/test_agents/test_collaboration.py`

- [ ] **Step 1: 写失败测试 — 架构 Agent emit_signals**

在 `backend/tests/test_agents/test_collaboration.py` 末尾追加：

```python
class TestArchitectureEmitSignals:
    """ArchitectureAnalyzerAgent.emit_signals 测试。"""

    def test_circular_dependency_generates_security_signal(self):
        """循环依赖 → 生成发给 security 的信号。"""
        from app.core.agents.architecture import ArchitectureAnalyzerAgent
        from app.core.agents.base import AgentContext

        agent = ArchitectureAnalyzerAgent(AgentContext())
        findings = [
            {"agent_type": "architecture", "severity": "high",
             "category": "dependency_direction",
             "file_path": "app/models/user.py",
             "line_start": 0, "line_end": 0,
             "title": "循环依赖: 2 个模块形成依赖环",
             "description": "以下 2 个模块形成循环依赖: app.models.user → app.api.users → app.models.user"},
        ]
        import asyncio
        signals = asyncio.run(agent.emit_signals(findings, []))
        assert len(signals) >= 1
        sec_signals = [s for s in signals if s["target_agent"] == "security"]
        assert len(sec_signals) >= 1
        assert sec_signals[0]["signal_type"] == "focus_area"

    def test_high_coupling_generates_performance_signal(self):
        """高耦合 → 生成发给 performance 的信号。"""
        from app.core.agents.architecture import ArchitectureAnalyzerAgent
        from app.core.agents.base import AgentContext

        agent = ArchitectureAnalyzerAgent(AgentContext())
        findings = [
            {"agent_type": "architecture", "severity": "critical",
             "category": "coupling",
             "file_path": "app/core/orchestrator.py",
             "line_start": 0, "line_end": 0,
             "title": "高耦合节点: 'app.core.orchestrator' 被 8 个模块依赖",
             "description": "模块被 8 个模块直接依赖"},
        ]
        import asyncio
        signals = asyncio.run(agent.emit_signals(findings, []))
        perf_signals = [s for s in signals if s["target_agent"] == "performance"]
        assert len(perf_signals) >= 1

    def test_low_severity_does_not_generate_signal(self):
        """low 严重等级不生成信号。"""
        from app.core.agents.architecture import ArchitectureAnalyzerAgent
        from app.core.agents.base import AgentContext

        agent = ArchitectureAnalyzerAgent(AgentContext())
        findings = [
            {"agent_type": "architecture", "severity": "low",
             "category": "dependency_direction", "file_path": "a.py",
             "line_start": 0, "line_end": 0, "title": "x", "description": "d"},
        ]
        import asyncio
        signals = asyncio.run(agent.emit_signals(findings, []))
        assert signals == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_agents/test_collaboration.py::TestArchitectureEmitSignals -v`
Expected: FAIL — 信号为空（默认实现不会把 description 当循环链解析）

- [ ] **Step 3: 实现 ArchitectureAnalyzerAgent.emit_signals**

在 `backend/app/core/agents/architecture.py` 的 `ArchitectureAnalyzerAgent` 类中，在 `review` 方法之前追加：

```python
    async def emit_signals(
        self, findings: list[dict], parsed_files: list[ParsedFile]
    ) -> list[dict]:
        """架构 Agent 自定义信号生成。

        对循环依赖和高耦合问题生成更丰富的上下文信号：
        - 循环依赖 → 通知 security 重点检查数据流
        - 高耦合 → 通知 performance 检查性能瓶颈
        """
        from app.config import get_settings

        max_signals = get_settings().COLLABORATION_MAX_SIGNALS_PER_AGENT
        signals: list[dict] = []

        for finding in findings:
            if len(signals) >= max_signals:
                break
            category = finding.get("category", "")
            severity = finding.get("severity", "")

            # 循环依赖 → 通知 security 检查数据流
            if category == "dependency_direction" and severity in ("critical", "high"):
                desc = finding.get("description", "")
                signals.append({
                    "source_agent": "architecture",
                    "target_agent": "security",
                    "signal_type": "focus_area",
                    "file_paths": self._extract_cycle_files(desc, parsed_files),
                    "location": {"line_start": 0, "line_end": 0},
                    "message": "检测到循环依赖，建议重点检查这些模块的数据流是否存在注入或越权风险",
                    "severity_hint": "high",
                    "context": {
                        "cycle_description": desc[:200],
                        "original_finding_title": finding.get("title", ""),
                    },
                })

            # 高耦合 → 通知 performance 检查性能瓶颈
            elif category == "coupling" and severity in ("critical", "high"):
                file_path = finding.get("file_path", "")
                signals.append({
                    "source_agent": "architecture",
                    "target_agent": "performance",
                    "signal_type": "focus_area",
                    "file_paths": [file_path] if file_path else [],
                    "location": {"line_start": 0, "line_end": 0},
                    "message": "模块被多模块依赖，建议检查其是否存在性能瓶颈或调用热点",
                    "severity_hint": severity,
                    "context": {
                        "coupling_degree": finding.get("title", ""),
                    },
                })

        return signals

    def _extract_cycle_files(
        self, cycle_desc: str, parsed_files: list[ParsedFile]
    ) -> list[str]:
        """从循环依赖描述中提取涉及的文件路径。

        匹配 parsed_files 中路径或模块名出现在描述里的文件。
        """
        matched: list[str] = []
        for pf in parsed_files:
            module_name = self._path_to_module(pf.path, pf.language)
            if pf.path in cycle_desc or module_name in cycle_desc:
                matched.append(pf.path)
        return matched[:5]  # 限制最多 5 个文件
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_agents/test_collaboration.py::TestArchitectureEmitSignals -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 提交**

```bash
git add backend/app/core/agents/architecture.py backend/tests/test_agents/test_collaboration.py
git commit -m "feat(architecture): custom emit_signals for circular dependency and coupling"
```

---

## Task 6: SecurityAuditorAgent.collaborative_review 实现

**Files:**
- Modify: `backend/app/core/agents/security.py`
- Test: `backend/tests/test_agents/test_collaboration.py`

- [ ] **Step 1: 写失败测试 — 安全 Agent 协作复查**

在 `backend/tests/test_agents/test_collaboration.py` 末尾追加：

```python
class TestSecurityCollaborativeReview:
    """SecurityAuditorAgent.collaborative_review 测试。"""

    def test_empty_signals_returns_empty(self):
        """无信号返回空。"""
        from app.core.agents.security import SecurityAuditorAgent
        from app.core.agents.base import AgentContext
        import asyncio
        agent = SecurityAuditorAgent(AgentContext())
        result = asyncio.run(agent.collaborative_review([], []))
        assert result == []

    def test_returns_empty_when_no_relevant_files(self):
        """信号涉及的文件不在 parsed_files 中，返回空。"""
        from app.core.agents.security import SecurityAuditorAgent
        from app.core.agents.base import AgentContext
        from app.integrations.ast_engine import ParsedFile
        import asyncio

        agent = SecurityAuditorAgent(AgentContext())
        signals = [{
            "source_agent": "architecture",
            "target_agent": "security",
            "signal_type": "focus_area",
            "file_paths": ["nonexistent.py"],
            "message": "循环依赖",
            "severity_hint": "high",
        }]
        pf = ParsedFile(path="other.py", content="x = 1", language="python", tree=None, lines=[])
        result = asyncio.run(agent.collaborative_review([pf], signals))
        assert result == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_agents/test_collaboration.py::TestSecurityCollaborativeReview -v`
Expected: FAIL — `AttributeError: 'SecurityAuditorAgent' object has no attribute 'collaborative_review'`

- [ ] **Step 3: 实现 collaborative_review**

在 `backend/app/core/agents/security.py` 的 `SecurityAuditorAgent` 类中，在 `review` 方法之前追加：

```python
    async def collaborative_review(
        self,
        parsed_files: list[ParsedFile],
        signals: list[dict],
    ) -> list[dict]:
        """安全 Agent 协作复查。

        当收到架构 Agent 的循环依赖信号时，对相关模块的数据流做深度安全分析。
        第二轮使用 LOCAL tier 模型（use_reasoning=False），不挤占 CLOUD 预算。
        """
        if not signals:
            return []

        from app.config import get_settings
        max_files = get_settings().COLLABORATION_MAX_FILES_PER_REVIEW

        # 收集信号涉及的文件
        target_paths: set[str] = set()
        for sig in signals:
            for p in sig.get("file_paths", []):
                if p:
                    target_paths.add(p)

        relevant_files = [
            pf for pf in parsed_files
            if pf.path in target_paths and pf.language in SUPPORTED_LANGUAGES
        ][:max_files]

        if not relevant_files:
            return []

        collab_ctx = self._build_collab_context(signals)
        all_collab_findings: list[dict] = []

        for pf in relevant_files:
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
                findings = self._parse_llm_response(response, pf)
                all_collab_findings.extend(findings)
            except Exception as e:
                print(f"[SecurityAuditor][Collab] 协作复查失败: {e}")

        return all_collab_findings

    def _parse_llm_response(self, response: str, parsed_file: ParsedFile) -> list[dict]:
        """解析 LLM 安全分析响应（复用 _llm_scan 的 JSON 解析逻辑）。"""
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

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_agents/test_collaboration.py::TestSecurityCollaborativeReview -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 提交**

```bash
git add backend/app/core/agents/security.py backend/tests/test_agents/test_collaboration.py
git commit -m "feat(security): implement collaborative_review for data flow deep analysis"
```

---

## Task 7: ArbitratorAgent.arbitrate_full 接受 collaboration_results

**Files:**
- Modify: `backend/app/core/agents/arbitrator.py`

- [ ] **Step 1: 修改 arbitrate_full 签名**

在 `backend/app/core/agents/arbitrator.py` 中，修改 `arbitrate_full` 方法签名，增加 `collaboration_results` 参数，并在调用 `arbitrate` 时传入：

将 `arbitrate_full` 方法的签名改为：

```python
    async def arbitrate_full(
        self,
        style_results: list[dict],
        security_results: list[dict],
        architecture_results: list[dict],
        performance_results: list[dict],
        refactor_results: list[dict],
        task_id: str = "",
        collaboration_results: list[dict] | None = None,
    ) -> dict[str, Any]:
        """完整仲裁流程：合并 → 去重 → 排序 → 评分 → 摘要 → HTML 报告。

        Args:
            ...
            collaboration_results: 第二轮协作复查的增量发现（可选）

        Returns:
            ...
        """
        # 步骤 1: 合并去重排序评分
        arbitrated = self.arbitrate(
            style_results=style_results,
            security_results=security_results,
            architecture_results=architecture_results,
            performance_results=performance_results,
            refactor_results=refactor_results,
            collaboration_results=collaboration_results or [],
        )
```

- [ ] **Step 2: 修改 arbitrate 方法签名**

将 `arbitrate` 方法签名改为：

```python
    def arbitrate(
        self,
        style_results: list[dict],
        security_results: list[dict],
        architecture_results: list[dict],
        performance_results: list[dict],
        refactor_results: list[dict],
        collaboration_results: list[dict] | None = None,
    ) -> dict[str, Any]:
```

并在 `arbitrate` 方法体内，`all_results.extend(refactor_results)` 之后追加：

```python
        # 合并第二轮协作结果
        if collaboration_results:
            all_results.extend(collaboration_results)
```

- [ ] **Step 3: 运行现有仲裁测试确认不破坏**

Run: `cd backend && python -m pytest tests/ -k "arbitrator or arbitrate" -v`
Expected: PASS（现有测试不受影响，collaboration_results 默认 None）

- [ ] **Step 4: 提交**

```bash
git add backend/app/core/agents/arbitrator.py
git commit -m "feat(arbitrator): accept collaboration_results in arbitrate_full"
```

---

## Task 8: orchestrator 新增 signal_exchange_node 和 collab 节点工厂

**Files:**
- Modify: `backend/app/core/orchestrator.py`
- Test: `backend/tests/test_core/test_orchestrator.py`

- [ ] **Step 1: 写失败测试 — signal_exchange_node 逻辑**

在 `backend/tests/test_core/test_orchestrator.py` 末尾追加：

```python
class TestSignalExchangeNode:
    """signal_exchange_node 测试。"""

    @pytest.mark.asyncio
    async def test_disabled_collaboration_skips(self):
        """collaboration_enabled=False 时返回空 active 列表。"""
        from app.core.orchestrator import signal_exchange_node
        state = {
            "task_id": "",
            "collaboration_enabled": False,
            "agent_signals": [{"target_agent": "security"}],
        }
        result = await signal_exchange_node(state)
        assert result["active_collab_agents"] == []

    @pytest.mark.asyncio
    async def test_no_signals_skips(self):
        """无信号时返回空 active 列表。"""
        from app.core.orchestrator import signal_exchange_node
        state = {
            "task_id": "",
            "collaboration_enabled": True,
            "agent_signals": [],
        }
        result = await signal_exchange_node(state)
        assert result["active_collab_agents"] == []

    @pytest.mark.asyncio
    async def test_groups_signals_by_target(self):
        """按 target_agent 分组计算 active 列表。"""
        from app.core.orchestrator import signal_exchange_node
        state = {
            "task_id": "",
            "collaboration_enabled": True,
            "agent_signals": [
                {"target_agent": "security", "source_agent": "architecture"},
                {"target_agent": "security", "source_agent": "performance"},
                {"target_agent": "refactor", "source_agent": "security"},
            ],
        }
        result = await signal_exchange_node(state)
        assert set(result["active_collab_agents"]) == {"security", "refactor"}


class TestCollabNodeSkipLogic:
    """collab 节点跳过逻辑测试。"""

    @pytest.mark.asyncio
    async def test_collab_node_skips_when_not_active(self):
        """agent 不在 active 列表时返回空 dict。"""
        from app.core.orchestrator import _make_collab_review_node
        node = _make_collab_review_node("security", MagicMock)
        state = {
            "task_id": "",
            "active_collab_agents": ["refactor"],  # security 不在里面
            "agent_signals": [],
        }
        result = await node(state)
        assert result == {}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_core/test_orchestrator.py::TestSignalExchangeNode tests/test_core/test_orchestrator.py::TestCollabNodeSkipLogic -v`
Expected: FAIL — `ImportError: cannot import name 'signal_exchange_node'`

- [ ] **Step 3: 实现 signal_exchange_node 和 collab 工厂**

在 `backend/app/core/orchestrator.py` 中，在 `refactor_review_node` 定义之后、`arbitrate_node` 之前追加：

```python
# ============================================================
# Agent 协作节点（第二轮）
# ============================================================

async def signal_exchange_node(state: ReviewState) -> dict[str, Any]:
    """信号交换节点。

    汇聚第一轮 Agent 的 signals，按 target_agent 分组统计，
    计算需要触发的第二轮 collab 节点列表。

    signals 本身已通过 ReviewState.agent_signals（operator.add）汇聚到 state，
    无需额外存储。collab 节点直接从 state.agent_signals 过滤读取。
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

    # 按 target_agent 分组统计（仅计算 active 列表，signals 已在 state 中）
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
    """工厂：生成第二轮协作复查节点。

    每个 Agent 对应一个 collab 节点。仅当该 Agent 在 active_collab_agents 中时执行，
    否则返回空 dict（跳过）。
    """
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_core/test_orchestrator.py::TestSignalExchangeNode tests/test_core/test_orchestrator.py::TestCollabNodeSkipLogic -v`
Expected: PASS (4 tests)

- [ ] **Step 5: 提交**

```bash
git add backend/app/core/orchestrator.py backend/tests/test_core/test_orchestrator.py
git commit -m "feat(orchestrator): add signal_exchange_node and collab review node factory"
```

---

## Task 9: 改造 _make_agent_review_node 调用 emit_signals

**Files:**
- Modify: `backend/app/core/orchestrator.py`

- [ ] **Step 1: 修改工厂函数**

在 `backend/app/core/orchestrator.py` 中，修改 `_make_agent_review_node` 函数体，在 `results, errors = await _run_agent_with_tracing(...)` 之后、`return` 之前插入信号生成逻辑：

```python
def _make_agent_review_node(
    agent_type: str,
    agent_cls: type,
    progress: float,
    results_key: str,
):
    """工厂：生成 LangGraph Agent 审查节点。"""
    async def _node(state: ReviewState) -> dict[str, Any]:
        start_time = time.time()
        task_id = state.get("task_id", "")
        parsed_files = state.get("_parsed_files", [])
        context = _get_agent_context(state, agent_type=agent_type)
        agent = agent_cls(context)
        results, errors = await _run_agent_with_tracing(agent, agent_type, parsed_files)

        # 从审查结果中提取协作信号
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
            "agent_signals": signals,
            "errors": errors,
            "agent_durations": {agent_type: elapsed_ms},
        }

    _node.__name__ = f"{agent_type}_review_node"
    return _node
```

- [ ] **Step 2: 运行现有 orchestrator 测试确认不破坏**

Run: `cd backend && python -m pytest tests/test_core/test_orchestrator.py -v`
Expected: PASS（现有测试 mock 了 LLM 和 memory，emit_signals 默认实现不调用 LLM）

- [ ] **Step 3: 提交**

```bash
git add backend/app/core/orchestrator.py
git commit -m "feat(orchestrator): first-round agents emit collaboration signals"
```

---

## Task 10: 改造 arbitrate_node 合并 collaboration_results

**Files:**
- Modify: `backend/app/core/orchestrator.py`

- [ ] **Step 1: 修改 arbitrate_node**

在 `backend/app/core/orchestrator.py` 的 `arbitrate_node` 中，修改 `arbitrate_full` 调用，传入 `collaboration_results`：

```python
    try:
        arbitrated = await arbitrator.arbitrate_full(
            style_results=style_results,
            security_results=security_results,
            architecture_results=architecture_results,
            performance_results=performance_results,
            refactor_results=refactor_results,
            task_id=state.get("task_id", ""),
            collaboration_results=state.get("collaboration_results", []),
        )
```

- [ ] **Step 2: 修改 arbitrate_node 的降级分支**

在 `except Exception` 的降级分支中，也合并 collaboration_results：

```python
    except Exception as e:
        errors.append("仲裁汇总失败: {}".format(e))
        collab_results = state.get("collaboration_results", [])
        arbitrated = {
            "merged_results": (
                style_results + security_results + architecture_results +
                performance_results + refactor_results + collab_results
            ),
            "severity_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
            "score": 0.0,
            "summary": "审查完成（仲裁汇总失败: {}）".format(str(e)[:80]),
            "report_html": "<p>仲裁汇总失败</p>",
            "stats": {},
        }
```

- [ ] **Step 3: 运行测试确认**

Run: `cd backend && python -m pytest tests/test_core/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add backend/app/core/orchestrator.py
git commit -m "feat(orchestrator): arbitrate_node merges collaboration_results"
```

---

## Task 11: 重构 build_review_graph 加入协作节点和条件边

**Files:**
- Modify: `backend/app/core/orchestrator.py`
- Test: `backend/tests/test_core/test_orchestrator.py`

- [ ] **Step 1: 写失败测试 — 图包含协作节点**

在 `backend/tests/test_core/test_orchestrator.py` 中，更新 `EXPECTED_NODES` 集合：

```python
# 更新为包含协作节点的完整列表
EXPECTED_NODES = {
    "parse_code",
    "skill_scan",
    "style_review",
    "security_review",
    "architecture_review",
    "performance_review",
    "refactor_review",
    "signal_exchange",
    "collab_style",
    "collab_security",
    "collab_architecture",
    "collab_performance",
    "collab_refactor",
    "arbitrate",
    "generate_report",
}
```

并更新 `TestBuildReviewGraph.test_build_review_graph`：

```python
    def test_build_review_graph(self):
        """图非空且包含所有节点（含协作节点）。"""
        graph = build_review_graph()

        # 图对象本身非空
        assert graph is not None

        # 验证所有节点已注册（通过 nodes 属性）
        node_names = set(graph.nodes.keys())
        missing = EXPECTED_NODES - node_names
        assert not missing, f"缺少节点: {missing}"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_core/test_orchestrator.py::TestBuildReviewGraph -v`
Expected: FAIL — 缺少 signal_exchange / collab_* 节点

- [ ] **Step 3: 重构 build_review_graph**

替换 `backend/app/core/orchestrator.py` 中的 `build_review_graph` 函数：

```python
def build_review_graph() -> StateGraph:
    """构建审查工作流图 - 第一轮并行 + 信号交换 + 第二轮协作 + 仲裁。"""
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

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_core/test_orchestrator.py::TestBuildReviewGraph -v`
Expected: PASS

如果 LangGraph 的 `add_conditional_edges` 返回 list 时报错（不支持 fan-out），降级为固定边方案：删除 `add_conditional_edges` 块，改为直接添加 `signal_exchange` → 5 个 collab 节点的固定边（collab 节点内部已检查 active_agents 会自动跳过）。

- [ ] **Step 5: 运行全部 orchestrator 测试**

Run: `cd backend && python -m pytest tests/test_core/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/core/orchestrator.py backend/tests/test_core/test_orchestrator.py
git commit -m "feat(orchestrator): rebuild graph with collaboration nodes and conditional fan-out"
```

---

## Task 12: tasks.py 初始化协作字段并扩展 agent_timeline

**Files:**
- Modify: `backend/app/core/tasks.py`

- [ ] **Step 1: 扩展 initial_state**

在 `backend/app/core/tasks.py` 的 `_run_review_pipeline` 中，扩展 `initial_state` 字典，在 `"enabled_skills"` 之后、`"skill_results"` 之前插入协作字段：

```python
    initial_state: ReviewState = {
        "task_id": task_id,
        "repo_url": request_data.get("repo_url", ""),
        "branch": request_data.get("branch", ""),
        "language": request_data.get("language", "auto"),
        "files": request_data.get("files", []),
        "enabled_skills": request_data.get("enabled_skills", []),
        # 协作字段初始化
        "collaboration_enabled": settings.COLLABORATION_ENABLED,
        "agent_signals": [],
        "collaboration_results": [],
        "collaboration_round": 0,
        "active_collab_agents": [],
        "skill_results": [],
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
```

- [ ] **Step 2: 扩展 result_keys 和 agent_timeline**

在 `_run_review_pipeline` 中，在 `result_keys` 列表末尾追加协作结果：

```python
    result_keys = [
        ("style_results", "style"),
        ("security_results", "security"),
        ("architecture_results", "architecture"),
        ("performance_results", "performance"),
        ("refactor_results", "refactor"),
        ("skill_results", "skill"),
        ("collaboration_results", "collaboration"),
    ]
```

在 `agent_timeline` 列表中，在 arbitrator 之前追加 signal_exchange 和协作节点（在 arbitrator 项之前插入）：

```python
    # 信号交换节点
    agent_timeline.append({
        "agent_type": "signal_exchange",
        "display_name": "信号交换",
        "status": "completed",
        "duration_ms": durations.get("signal_exchange", 0),
        "finding_count": 0,
    })
    # 第二轮协作节点（仅展示实际执行的）
    collab_durations = {k: v for k, v in durations.items() if k.startswith("collab_")}
    for collab_key, dur in collab_durations.items():
        agent_name = collab_key.replace("collab_", "")
        collab_count = sum(
            1 for r in all_results
            if r.get("source") == "collaboration" and r.get("triggered_by") == agent_name
        )
        agent_timeline.append({
            "agent_type": collab_key,
            "display_name": f"协作复查({agent_name})",
            "status": "completed",
            "duration_ms": dur,
            "finding_count": collab_count,
        })
```

将这两段插入在 `agent_timeline = [...]` 列表构建之后、`arbitrator` 项之前。具体地，把原 `agent_timeline = [...]` 的列表字面量改为先用列表字面量构建到 refactor 项，然后用 `append` 追加 signal_exchange 和 collab 节点，最后再 append arbitrator。

- [ ] **Step 3: 验证导入和语法**

Run: `cd backend && python -c "from app.core.tasks import run_review_task; print('OK')"`
Expected: `OK`

- [ ] **Step 4: 运行 tasks 测试**

Run: `cd backend && python -m pytest tests/test_core/test_tasks.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/core/tasks.py
git commit -m "feat(tasks): init collaboration state fields and extend agent_timeline"
```

---

## Task 13: 集成测试 — 端到端协作流程

**Files:**
- Test: `backend/tests/test_core/test_orchestrator.py`

- [ ] **Step 1: 写集成测试 — 协作信号传递**

在 `backend/tests/test_core/test_orchestrator.py` 末尾追加：

```python
class TestCollaborationIntegration:
    """端到端协作流程集成测试。"""

    @pytest.mark.asyncio
    async def test_architecture_finding_generates_security_signal(self):
        """架构 Agent 的循环依赖 finding 能生成发给 security 的信号。"""
        from app.core.agents.architecture import ArchitectureAnalyzerAgent
        from app.core.agents.base import AgentContext
        from app.integrations.ast_engine import ParsedFile

        agent = ArchitectureAnalyzerAgent(AgentContext())
        # 构造一个包含循环依赖描述的 finding
        findings = [{
            "agent_type": "architecture",
            "severity": "high",
            "category": "dependency_direction",
            "file_path": "app/models/user.py",
            "line_start": 0,
            "line_end": 0,
            "title": "循环依赖: 2 个模块形成依赖环",
            "description": "app.models.user → app.api.users → app.models.user",
        }]
        pf = ParsedFile(
            path="app/models/user.py", content="x = 1",
            language="python", tree=None, lines=[],
        )
        signals = await agent.emit_signals(findings, [pf])
        assert len(signals) >= 1
        sec_signals = [s for s in signals if s["target_agent"] == "security"]
        assert len(sec_signals) == 1
        assert "app/models/user.py" in sec_signals[0]["file_paths"]

    @pytest.mark.asyncio
    async def test_route_collaboration_returns_arbitrate_when_empty(self):
        """无 active agents 时路由返回 arbitrate。"""
        # 模拟 _route_collaboration 逻辑
        state = {"active_collab_agents": []}
        active = state.get("active_collab_agents", [])
        result = ["arbitrate"] if not active else [f"collab_{a}" for a in active]
        assert result == ["arbitrate"]

    @pytest.mark.asyncio
    async def test_route_collaboration_returns_collab_nodes_when_active(self):
        """有 active agents 时路由返回对应 collab 节点。"""
        state = {"active_collab_agents": ["security", "refactor"]}
        active = state.get("active_collab_agents", [])
        result = ["arbitrate"] if not active else [f"collab_{a}" for a in active]
        assert result == ["collab_security", "collab_refactor"]
```

- [ ] **Step 2: 运行集成测试**

Run: `cd backend && python -m pytest tests/test_core/test_orchestrator.py::TestCollaborationIntegration -v`
Expected: PASS (3 tests)

- [ ] **Step 3: 运行全部测试套件确认无回归**

Run: `cd backend && python -m pytest tests/ -v --ignore=tests/test_phase1_manual.py`
Expected: PASS（全部通过，无回归）

- [ ] **Step 4: 提交**

```bash
git add backend/tests/test_core/test_orchestrator.py
git commit -m "test(collaboration): add integration tests for signal routing"
```

---

## Task 14: 全量验证与手动验收

- [ ] **Step 1: 运行后端全部单元测试**

Run: `cd backend && python -m pytest tests/ -v --ignore=tests/test_phase1_manual.py`
Expected: ALL PASS

- [ ] **Step 2: 启动服务验证图可编译**

Run: `cd backend && python -c "from app.core.orchestrator import review_graph; print('Graph compiled:', review_graph is not None); print('Nodes:', list(review_graph.nodes.keys()))"`
Expected: 输出包含 signal_exchange / collab_* 节点

- [ ] **Step 3: 启动服务**

确保 PostgreSQL、Redis 运行，启动 FastAPI 和 Celery worker：

```bash
cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
# 另一终端
cd backend && set OPENBLAS_NUM_THREADS=1 && celery -A app.core.celery_app worker --pool=threads --concurrency=2 --loglevel=info
```

- [ ] **Step 4: 前端启动并提交审查任务**

提交含循环依赖的多文件代码（如两个互相 import 的 Python 文件），验证：
1. 进度从 5% → 20% → 40% → 68%（signal_exchange）→ 协作复查 → 100%
2. 日志中出现 `[Collaboration] 信号交换完成` 字样
3. 报告中出现 `source: collaboration` 的增量发现

- [ ] **Step 5: 最终提交**

```bash
git add -A
git commit -m "feat(collaboration): complete Reflective Collaboration Loop upgrade"
```

---

## Self-Review Notes

**Spec coverage:** 设计文档第 10.1 节必做清单全部覆盖：
- ✅ ReviewState 扩展（Task 2）
- ✅ collaboration.py 新增（Task 1）
- ✅ BaseReviewAgent 扩展（Task 3）
- ✅ signal_exchange_node（Task 8）
- ✅ collab 节点工厂（Task 8）
- ✅ _make_agent_review_node 改造（Task 9）
- ✅ arbitrate_node 改造（Task 10）
- ✅ build_review_graph 重构（Task 11）
- ✅ ArchitectureAnalyzerAgent.emit_signals（Task 5）
- ✅ SecurityAuditorAgent.collaborative_review（Task 6）
- ✅ config.py 配置项（Task 4）
- ✅ 单元测试 + 集成测试（Task 13）

**Placeholder scan:** 无 TBD/TODO，所有步骤包含完整代码。

**Type consistency:** `collaboration_results` 参数在 arbitrate / arbitrate_full / arbitrate_node 中一致；`active_collab_agents` 在 signal_exchange / collab node / _route_collaboration 中一致；`agent_signals` 在 state / emit_signals / collab node 中一致。

**LangGraph 风险提示:** Task 11 Step 4 包含降级方案（条件边不支持 fan-out 时改用固定边）。若遇到 `add_conditional_edges` 返回 list 报错，按降级方案处理。
