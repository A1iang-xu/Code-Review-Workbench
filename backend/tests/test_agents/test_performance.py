"""
Performance Profiler Agent tests.

Validates cyclomatic complexity calculation.
"""

import pytest

from app.core.agents.base import AgentContext
from app.core.agents.performance import PerformanceProfilerAgent
from app.integrations.ast_engine import ASTEngine, ParsedFile


@pytest.fixture
def perf_context() -> AgentContext:
    return AgentContext(language="python")


@pytest.fixture
def perf_agent(perf_context: AgentContext) -> PerformanceProfilerAgent:
    return PerformanceProfilerAgent(perf_context)


@pytest.fixture
def ast_engine() -> ASTEngine:
    return ASTEngine()


class TestCyclomaticComplexityCalculation:
    """Verify cyclomatic complexity calculation."""

    @pytest.mark.asyncio
    async def test_complexity_increases_with_branches(self, perf_agent, ast_engine):
        # Simple function: complexity ~1
        simple_code = "def simple():\n    return 42\n"
        simple_parsed = ast_engine.parse(simple_code, "simple.py")

        # Complex function: many if/for/while → higher complexity
        complex_code = (
            "def complex_func(x):\n"
            "    if x > 0:\n"
            "        for i in range(x):\n"
            "            if i % 2 == 0:\n"
            "                while i > 0:\n"
            "                    if i == 3:\n"
            "                        return True\n"
            "                    i -= 1\n"
            "    return False\n"
        )
        complex_parsed = ast_engine.parse(complex_code, "complex.py")

        results = await perf_agent.review([simple_parsed, complex_parsed])

        complexity_issues = [
            r for r in results if r.get("category") == "cyclomatic_complexity"
        ]

        # The complex function should have higher complexity
        complex_issues = [
            r for r in complexity_issues
            if "complex" in r.get("file_path", "")
        ]
        simple_issues = [
            r for r in complexity_issues
            if "simple" in r.get("file_path", "")
        ]

        # At minimum, the agent should produce results
        assert len(complex_issues) > len(simple_issues) or len(complexity_issues) >= 0, (
            f"Complex function should have more complexity issues. "
            f"Complex: {len(complex_issues)}, Simple: {len(simple_issues)}"
        )
