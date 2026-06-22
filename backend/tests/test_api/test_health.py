"""
API — Health check endpoint tests.
"""

import pytest


class TestHealthCheck:
    """Verify the /health endpoint returns 200 and status=ok."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        response = await client.get("/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok", f"Expected status=ok, got {data}"
        assert "app" in data, f"Expected 'app' field, got {data}"
