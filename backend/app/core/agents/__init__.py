"""
Agents package

导出所有审查 Agent 类和上下文。
"""

from app.core.agents.base import AgentContext, BaseReviewAgent  # noqa: F401
from app.core.agents.style import StyleCheckerAgent  # noqa: F401
from app.core.agents.security import SecurityAuditorAgent  # noqa: F401
from app.core.agents.architecture import ArchitectureAnalyzerAgent  # noqa: F401
from app.core.agents.performance import PerformanceProfilerAgent  # noqa: F401
from app.core.agents.refactor import RefactorAdvisorAgent  # noqa: F401
from app.core.agents.arbitrator import ArbitratorAgent  # noqa: F401

# 注册所有 Agent 类型
AGENT_REGISTRY = {
    "style": StyleCheckerAgent,
    "security": SecurityAuditorAgent,
    "architecture": ArchitectureAnalyzerAgent,
    "performance": PerformanceProfilerAgent,
    "refactor": RefactorAdvisorAgent,
    "arbitrator": ArbitratorAgent,
}
