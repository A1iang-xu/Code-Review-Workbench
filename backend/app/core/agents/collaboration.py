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
