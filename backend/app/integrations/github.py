"""
GitHub Integration — REST API client + Webhook verification

Uses Personal Access Token (PAT) for API operations.
Webhook signature verification uses HMAC-SHA256.
"""

import hashlib
import hmac
import base64
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings

settings = get_settings()


# ----------------------------------------------------------------
# GitHub API client
# ----------------------------------------------------------------

class GitHubIntegration:
    """GitHub REST API client.

    Provides access to:
    - PR file listing
    - File content fetching
    - Review comment creation
    - PR review creation
    - Commit status management

    Usage:
        gh = GitHubIntegration()
        files = await gh.get_pr_files("owner", "repo", 42)
    """

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str | None = None):
        self.token = token or settings.GITHUB_TOKEN
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-init httpx AsyncClient with auth and Accept headers."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "code-review-workbench",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ---- Webhook signature verification ----

    @staticmethod
    def verify_signature(payload_body: bytes, signature: str) -> bool:
        """Verify HMAC-SHA256 webhook signature.

        GitHub sends 'X-Hub-Signature-256' header in the format:
            sha256=<hex-digest>

        Args:
            payload_body: Raw request body bytes.
            signature: Value of X-Hub-Signature-256 header.

        Returns:
            True if the signature matches, False otherwise.
        """
        if not signature or not settings.WEBHOOK_SECRET:
            return False

        prefix = "sha256="
        if signature.startswith(prefix):
            signature = signature[len(prefix):]

        expected = hmac.new(
            key=settings.WEBHOOK_SECRET.encode("utf-8"),
            msg=payload_body,
            digestmod=hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    # ---- PR file listing ----

    async def get_pr_files(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch changed files in a pull request.

        Calls: GET /repos/{owner}/{repo}/pulls/{pr_number}/files

        Args:
            owner: Repository owner (user or org).
            repo: Repository name.
            pr_number: Pull request number.
            per_page: Results per page (max 100).

        Returns:
            List of file objects with fields:
                filename, status, additions, deletions, changes, blob_url,
                raw_url, contents_url, patch
        """
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}/files"
        params = {"per_page": per_page}

        all_files: list[dict[str, Any]] = []
        page = 1

        while True:
            resp = await self.client.get(url, params={**params, "page": page})
            resp.raise_for_status()
            files = resp.json()
            if not files:
                break
            all_files.extend(files)
            if len(files) < per_page:
                break
            page += 1

        return all_files

    # ---- File content fetching ----

    async def get_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str = "",
    ) -> str:
        """Fetch file content from a repository.

        Calls: GET /repos/{owner}/{repo}/contents/{path}?ref={ref}

        Args:
            owner: Repository owner.
            repo: Repository name.
            path: File path within the repo.
            ref: Git ref (branch/tag/commit SHA).

        Returns:
            Decoded file content as UTF-8 string.
        """
        url = f"/repos/{owner}/{repo}/contents/{path}"
        params: dict[str, str] = {}
        if ref:
            params["ref"] = ref

        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        # GitHub returns base64-encoded content
        content_b64 = data.get("content", "")
        if content_b64:
            content_bytes = base64.b64decode(content_b64)
            return content_bytes.decode("utf-8")
        return ""

    # ---- Review comments ----

    async def create_review_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        commit_id: str,
        body: str,
        path: str,
        line: int,
    ) -> dict[str, Any]:
        """Create an inline review comment on a specific line of a PR.

        Calls: POST /repos/{owner}/{repo}/pulls/{pr_number}/comments

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.
            commit_id: The SHA of the commit to comment on.
            body: Comment body text.
            path: Relative file path in the repo.
            line: Line number (in the diff).

        Returns:
            Created comment object.
        """
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}/comments"

        payload = {
            "body": body,
            "commit_id": commit_id,
            "path": path,
            "line": line,
        }

        resp = await self.client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    # ---- PR review ----

    async def create_pr_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        commit_id: str,
        body: str,
        event: str = "COMMENT",
    ) -> dict[str, Any]:
        """Create a pull request review.

        Calls: POST /repos/{owner}/{repo}/pulls/{pr_number}/reviews

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.
            commit_id: The SHA of the commit to review.
            body: Review body text.
            event: One of COMMENT, APPROVE, REQUEST_CHANGES.

        Returns:
            Created review object.
        """
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews"

        payload = {
            "commit_id": commit_id,
            "body": body,
            "event": event,
        }

        resp = await self.client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    # ---- Commit status ----

    async def set_commit_status(
        self,
        owner: str,
        repo: str,
        sha: str,
        state: str,
        description: str = "",
        target_url: str = "",
    ) -> dict[str, Any]:
        """Set commit status for a given SHA.

        Calls: POST /repos/{owner}/{repo}/statuses/{sha}

        Args:
            owner: Repository owner.
            repo: Repository name.
            sha: Commit SHA.
            state: One of pending, success, failure, error.
            description: Short description.
            target_url: URL to link from the status.

        Returns:
            Created status object.
        """
        url = f"/repos/{owner}/{repo}/statuses/{sha}"

        payload = {
            "state": state,
            "description": description or f"Code Review: {state}",
            "context": "code-review-workbench",
        }
        if target_url:
            payload["target_url"] = target_url

        resp = await self.client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()
