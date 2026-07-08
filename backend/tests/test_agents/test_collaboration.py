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
