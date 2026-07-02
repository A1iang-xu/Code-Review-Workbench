"""
Webhook 端点测试

覆盖 backend/app/api/v1/webhooks.py 的签名校验与回写逻辑：
- POST /api/v1/webhooks/github  — GitHub PR Webhook（HMAC-SHA256 签名校验）
- POST /api/v1/webhooks/gitlab  — GitLab MR Webhook（X-Gitlab-Token 校验）

所有外部调用（GitHubIntegration、Celery run_review_task、repo_fetcher）
均通过 unittest.mock 拦截，确保测试不依赖真实 GitHub / Celery / DB。
"""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import get_settings


# ----------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------

def _github_signature(secret: str, body: bytes) -> str:
    """按 GitHub Webhook 规范生成 HMAC-SHA256 签名。

    返回格式: "sha256=<hex-digest>"，与 X-Hub-Signature-256 头一致。
    """
    digest = hmac.new(
        key=secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _pr_opened_payload() -> dict:
    """构造一个 pull_request opened 事件的 payload。"""
    return {
        "action": "opened",
        "repository": {"full_name": "octocat/Hello-World"},
        "pull_request": {
            "number": 42,
            "head": {"sha": "abc123deadbeef"},
            "base": {"ref": "main"},
        },
    }


# ----------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------

@pytest.fixture
def webhook_secret(monkeypatch) -> str:
    """设置测试用 WEBHOOK_SECRET（非占位符，触发真实 HMAC 校验分支）。

    get_settings() 被 lru_cache 缓存，webhooks / github 模块持有的 settings
    均为同一实例，故修改单例属性即可全局生效。
    """
    secret = "test-webhook-secret"
    monkeypatch.setattr(get_settings(), "WEBHOOK_SECRET", secret)
    return secret


@pytest.fixture
def gitlab_token(monkeypatch) -> str:
    """设置测试用 GITLAB_TOKEN（非占位符，触发 token 比对分支）。"""
    token = "test-gitlab-token"
    monkeypatch.setattr(get_settings(), "GITLAB_TOKEN", token)
    return token


@pytest.fixture
def mock_github(monkeypatch) -> MagicMock:
    """Mock GitHubIntegration 类。

    - 实例方法（set_commit_status / create_pr_review / create_review_comment
      / get_pr_files / get_file_content / close）均替换为 AsyncMock，
      避免 _run_pr_review 回写时发起真实 HTTP 请求。
    - 保留真实的 verify_signature 静态方法，以测试 HMAC 签名校验逻辑。
    """
    from app.integrations.github import GitHubIntegration

    mock_instance = AsyncMock()
    mock_class = MagicMock(return_value=mock_instance)
    # 保留真实签名校验静态方法，便于测试真实 HMAC 逻辑
    mock_class.verify_signature = GitHubIntegration.verify_signature
    monkeypatch.setattr("app.api.v1.webhooks.GitHubIntegration", mock_class)
    return mock_instance


@pytest.fixture
def mock_run_review_task(monkeypatch) -> MagicMock:
    """Mock Celery 任务 run_review_task。

    webhooks._run_pr_review 中通过局部 `from app.core.tasks import run_review_task`
    引用，故 patch 其源模块 app.core.tasks.run_review_task。
    """
    mock_task = MagicMock()
    mock_task.delay = MagicMock(return_value=MagicMock())
    # 配置 AsyncResult(...).get(timeout=...) 返回审查结果 dict
    mock_task.AsyncResult = MagicMock()
    mock_task.AsyncResult.return_value.get.return_value = {
        "summary": "代码审查完成，未发现问题",
        "score": 9.0,
        "issues_count": 0,
    }
    monkeypatch.setattr("app.core.tasks.run_review_task", mock_task)
    return mock_task


@pytest.fixture
def mock_fetch_pr_diff(monkeypatch) -> AsyncMock:
    """Mock repo_fetcher.fetch_pr_diff，返回非空文件列表以进入完整审查流程。

    webhooks._run_pr_review 中通过局部 `from app.integrations.repo_fetcher
    import fetch_pr_diff` 引用，故 patch 其源模块。
    """
    mock = AsyncMock(
        return_value=([{"path": "src/main.py", "content": "print('hi')\n"}], None)
    )
    monkeypatch.setattr("app.integrations.repo_fetcher.fetch_pr_diff", mock)
    return mock


@pytest.fixture
def mock_load_from_db(monkeypatch) -> AsyncMock:
    """Mock reviews._load_from_db，避免真实数据库访问。

    webhooks._run_pr_review 中通过局部 `from app.api.v1.reviews
    import _load_from_db` 引用，故 patch 其源模块。
    """
    mock = AsyncMock(return_value={"issues": []})
    monkeypatch.setattr("app.api.v1.reviews._load_from_db", mock)
    return mock


# ----------------------------------------------------------------
# 测试用例 — GitHub Webhook
# ----------------------------------------------------------------

class TestGitHubWebhook:
    """GitHub Webhook 签名校验与审查触发。"""

    async def test_github_webhook_invalid_signature(
        self, client, webhook_secret, mock_github, mock_run_review_task
    ):
        """错误签名 → 403，且不触发审查。"""
        body = json.dumps({"action": "opened"}).encode()
        headers = {
            "X-Hub-Signature-256": "sha256=invalidsignature",
            "X-GitHub-Event": "pull_request",
            "Content-Type": "application/json",
        }
        response = await client.post(
            "/api/v1/webhooks/github", content=body, headers=headers
        )

        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )
        # 签名校验失败，不应调度审查任务
        mock_run_review_task.delay.assert_not_called()

    async def test_github_webhook_valid_signature_unsupported_event(
        self, client, webhook_secret, mock_github, mock_run_review_task
    ):
        """有效签名但非 pull_request 事件 → 200，且不触发审查。"""
        body = json.dumps({"action": "opened"}).encode()
        headers = {
            "X-Hub-Signature-256": _github_signature(webhook_secret, body),
            "X-GitHub-Event": "push",
            "Content-Type": "application/json",
        }
        response = await client.post(
            "/api/v1/webhooks/github", content=body, headers=headers
        )

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        # 非 pull_request 事件被忽略，不应调度审查任务
        mock_run_review_task.delay.assert_not_called()

    async def test_github_webhook_ping_event(
        self, client, webhook_secret, mock_github, mock_run_review_task
    ):
        """ping 事件 → 200。"""
        body = json.dumps({"zen": "Keep it logically awesome."}).encode()
        headers = {
            "X-Hub-Signature-256": _github_signature(webhook_secret, body),
            "X-GitHub-Event": "ping",
            "Content-Type": "application/json",
        }
        response = await client.post(
            "/api/v1/webhooks/github", content=body, headers=headers
        )

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        # ping 事件不应触发审查
        mock_run_review_task.delay.assert_not_called()

    async def test_github_webhook_pull_request_opened(
        self,
        client,
        webhook_secret,
        mock_github,
        mock_run_review_task,
        mock_fetch_pr_diff,
        mock_load_from_db,
    ):
        """有效签名 + pull_request opened 事件 → 200/202，触发 Celery 审查任务与 GitHub 回写。"""
        payload = _pr_opened_payload()
        body = json.dumps(payload).encode()
        headers = {
            "X-Hub-Signature-256": _github_signature(webhook_secret, body),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-1",
            "Content-Type": "application/json",
        }
        response = await client.post(
            "/api/v1/webhooks/github", content=body, headers=headers
        )

        assert response.status_code in (200, 202), (
            f"Expected 200 or 202, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert data["message"] == "Review scheduled"
        assert data["pr"] == 42
        assert data["owner"] == "octocat"
        assert data["repo"] == "Hello-World"

        # 验证 Celery 审查任务被调度
        mock_run_review_task.delay.assert_called_once()

        # 验证 GitHub 回写：至少设置过 pending 与最终状态
        assert mock_github.set_commit_status.call_count >= 2
        # 验证提交了 PR review
        mock_github.create_pr_review.assert_called_once()


# ----------------------------------------------------------------
# 测试用例 — GitLab Webhook
# ----------------------------------------------------------------

class TestGitLabWebhook:
    """GitLab Webhook token 校验。"""

    async def test_gitlab_webhook_invalid_token(self, client, gitlab_token):
        """错误 X-Gitlab-Token → 403。"""
        body = json.dumps({"object_kind": "merge_request"}).encode()
        headers = {
            "X-Gitlab-Token": "wrong-token",
            "X-Gitlab-Event": "Merge Request Hook",
            "Content-Type": "application/json",
        }
        response = await client.post(
            "/api/v1/webhooks/gitlab", content=body, headers=headers
        )

        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )
