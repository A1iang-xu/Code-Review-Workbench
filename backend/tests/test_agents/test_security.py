"""
Security Auditor Agent tests.

Validates detection of hardcoded keys and SQL injection patterns.
"""

import pytest

from app.core.agents.base import AgentContext
from app.core.agents.security import SecurityAuditorAgent
from app.integrations.ast_engine import ASTEngine


@pytest.fixture
def security_context() -> AgentContext:
    return AgentContext(language="python")


@pytest.fixture
def security_agent(security_context: AgentContext) -> SecurityAuditorAgent:
    return SecurityAuditorAgent(security_context)


@pytest.fixture
def ast_engine() -> ASTEngine:
    return ASTEngine()


class TestSecurityAgentDetectsHardcodedKey:
    """Verify the security agent detects hardcoded API keys."""

    @pytest.mark.asyncio
    async def test_detects_hardcoded_key(self, security_agent, ast_engine):
        code = 'API_KEY = "sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz"\n'
        parsed = ast_engine.parse(code, "config.py")
        results = await security_agent.review([parsed])

        # Should find at least one hardcoded secret
        secrets = [r for r in results if r.get("category") == "hardcoded_secret"]
        assert len(secrets) >= 1, f"Expected >=1 hardcoded_secret, got {len(secrets)}. Results: {results}"

    @pytest.mark.asyncio
    async def test_ignores_env_variable_reads(self, security_agent, ast_engine):
        code = 'API_KEY = os.getenv("API_KEY")\n'
        parsed = ast_engine.parse(code, "config.py")
        results = await security_agent.review([parsed])

        secrets = [r for r in results if r.get("category") == "hardcoded_secret"]
        assert len(secrets) == 0, f"Should not flag env var reads. Got: {secrets}"

    @pytest.mark.asyncio
    async def test_ignores_comment_lines(self, security_agent, ast_engine):
        code = '# API_KEY = "sk-example"\nprint("hello")\n'
        parsed = ast_engine.parse(code, "main.py")
        results = await security_agent.review([parsed])

        secrets = [r for r in results if r.get("category") == "hardcoded_secret"]
        assert len(secrets) == 0, f"Should not flag comments. Got: {secrets}"


class TestSecurityAgentDetectsSqlInjection:
    """Verify the security agent detects SQL injection patterns."""

    @pytest.mark.asyncio
    async def test_detects_string_concat_sql(self, security_agent, ast_engine):
        code = 'query = f"SELECT * FROM users WHERE id = {user_id}"\n'
        parsed = ast_engine.parse(code, "db.py")
        results = await security_agent.review([parsed])

        sqli = [r for r in results if r.get("category") == "sql_injection"]
        assert len(sqli) >= 1, f"Expected >=1 sql_injection, got {len(sqli)}. Results: {results}"
