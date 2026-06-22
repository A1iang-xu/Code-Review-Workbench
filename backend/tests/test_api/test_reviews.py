"""
API — Review creation endpoint tests.
"""

import pytest


class TestCreateReview:
    """Verify POST /api/v1/reviews returns expected response fields."""

    @pytest.mark.asyncio
    async def test_create_review(self, client, sample_files):
        payload = {
            "files": sample_files,
            "repo_url": "https://github.com/test/repo",
            "branch": "main",
            "language": "python",
        }
        response = await client.post("/api/v1/reviews", json=payload)
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert "task_id" in data, f"Missing task_id: {data}"
        assert "score" in data, f"Missing score: {data}"
        assert "stats" in data or "issues_count" in data, f"Missing stats: {data}"
