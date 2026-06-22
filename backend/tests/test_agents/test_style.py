"""
Style Checker Agent tests.

Validates detection of long functions.
"""

import pytest

from app.core.agents.base import AgentContext
from app.core.agents.style import StyleCheckerAgent
from app.integrations.ast_engine import ASTEngine


@pytest.fixture
def style_context() -> AgentContext:
    return AgentContext(language="python")


@pytest.fixture
def style_agent(style_context: AgentContext) -> StyleCheckerAgent:
    return StyleCheckerAgent(style_context)


@pytest.fixture
def ast_engine() -> ASTEngine:
    return ASTEngine()


class TestStyleAgentDetectsLongFunction:
    """Verify the style agent detects functions exceeding length limits."""

    @pytest.mark.asyncio
    async def test_detects_long_function(self, style_agent, ast_engine):
        # Generate a function with >50 lines
        lines = ["def very_long_function():"]
        for i in range(60):
            lines.append(f"    result{i} = {i}")
        lines.append("    return result0")
        code = "\n".join(lines)

        parsed = ast_engine.parse(code, "long.py")
        results = await style_agent.review([parsed])

        length_issues = [r for r in results if r.get("category") == "function_length"]
        assert len(length_issues) >= 1, (
            f"Expected >=1 function_length issue for a {len(lines)}-line function, "
            f"got {len(length_issues)}. Results: {results}"
        )

    @pytest.mark.asyncio
    async def test_short_function_no_warning(self, style_agent, ast_engine):
        code = "def short():\n    return 42\n"
        parsed = ast_engine.parse(code, "short.py")
        results = await style_agent.review([parsed])

        length_issues = [r for r in results if r.get("category") == "function_length"]
        assert len(length_issues) == 0, (
            f"Short function should not trigger warning. Got: {length_issues}"
        )
