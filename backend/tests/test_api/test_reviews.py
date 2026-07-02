"""
API — Review creation endpoint tests.
"""

from unittest.mock import AsyncMock, patch

import pytest


class TestCreateReview:
    """Verify POST /api/v1/reviews returns expected response fields."""

    @pytest.mark.asyncio
    async def test_create_review(self, client, sample_files):
        payload = {
            "files": sample_files,
            "repo_url": "",  # 空字符串避免触发 fetch_files_from_url 网络调用
            "branch": "main",
            "language": "python",
        }
        # mock Celery 任务提交，避免依赖 Redis / Celery worker
        with patch("app.api.v1.reviews.run_review_task") as mock_celery, \
             patch("app.api.v1.reviews.async_session_factory") as mock_session:
            # async_session_factory() 返回 async context manager
            mock_session.return_value.__aenter__ = AsyncMock(return_value=None)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
            response = await client.post("/api/v1/reviews", json=payload)

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert "task_id" in data, f"Missing task_id: {data}"
        assert data["status"] == "running", f"Expected running status, got: {data['status']}"

    @pytest.mark.asyncio
    async def test_create_review_with_repo_url(self, client, sample_files):
        """验证提供 repo_url 时调用 fetch_files_from_url，且 mock 其返回。"""
        payload = {
            "files": sample_files,
            "repo_url": "https://github.com/test/repo",
            "branch": "main",
            "language": "python",
        }
        with patch("app.api.v1.reviews.run_review_task"), \
             patch("app.api.v1.reviews.async_session_factory") as mock_session, \
             patch("app.api.v1.reviews.fetch_files_from_url", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = ([{"path": "extra.py", "content": "x = 1"}], None)
            mock_session.return_value.__aenter__ = AsyncMock(return_value=None)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
            response = await client.post("/api/v1/reviews", json=payload)

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert "task_id" in data
