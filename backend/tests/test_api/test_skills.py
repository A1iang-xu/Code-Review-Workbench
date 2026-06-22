"""
API — Skills listing tests.
"""

import pytest


class TestListSkills:
    """Verify GET /api/v1/skills returns the Skill catalog."""

    @pytest.mark.asyncio
    async def test_list_skills(self, client):
        response = await client.get("/api/v1/skills")
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"

        if len(data) > 0:
            skill = data[0]
            assert "name" in skill, f"Missing name: {skill}"
            assert "display_name" in skill, f"Missing display_name: {skill}"
            assert "category" in skill, f"Missing category: {skill}"
