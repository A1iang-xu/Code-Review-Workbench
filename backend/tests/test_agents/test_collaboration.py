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
        pf = ParsedFile(path="other.py", content="x = 1", language="python")
        result = asyncio.run(agent.collaborative_review([pf], signals))
        assert result == []
