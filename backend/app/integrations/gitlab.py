"""
GitLab Integration — REST API client

Uses Personal Access Token (PRIVATE-TOKEN header).
Supports both self-hosted GitLab and gitlab.com.
"""

from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings

settings = get_settings()


# ----------------------------------------------------------------
# GitLab API client
# ----------------------------------------------------------------

class GitLabIntegration:
    """GitLab REST API v4 client.

    Provides access to:
    - Merge Request changes
    - MR note creation

    Usage:
        gl = GitLabIntegration()
        changes = await gl.get_merge_request_changes(project_id, mr_iid)
    """

    def __init__(
        self,
        token: str | None = None,
        base_url: str = "https://gitlab.com",
    ):
        self.token = token or settings.GITLAB_TOKEN
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-init httpx AsyncClient with PRIVATE-TOKEN header."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=f"{self.base_url}/api/v4",
                headers={
                    "PRIVATE-TOKEN": self.token,
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

    # ---- Merge Request changes ----

    async def get_merge_request_changes(
        self,
        project_id: int | str,
        mr_iid: int,
    ) -> dict[str, Any]:
        """Fetch changes for a merge request.

        Calls: GET /projects/{project_id}/merge_requests/{mr_iid}/changes

        For project_id you may pass the URL-encoded path for nested projects
        (e.g. "group%2Fsubgroup%2Fproject") or the numeric project ID.

        Args:
            project_id: Numeric project ID or URL-encoded path.
            mr_iid: Merge request IID (project-scoped).

        Returns:
            Merge request changes object with 'changes' list and 'diff_refs'.
        """
        if isinstance(project_id, str):
            project_id = quote(project_id, safe="")

        url = f"/projects/{project_id}/merge_requests/{mr_iid}/changes"
        resp = await self.client.get(url)
        resp.raise_for_status()
        return resp.json()

    # ---- MR note ----

    async def create_mr_note(
        self,
        project_id: int | str,
        mr_iid: int,
        body: str,
    ) -> dict[str, Any]:
        """Create a note (comment) on a merge request.

        Calls: POST /projects/{project_id}/merge_requests/{mr_iid}/notes

        Args:
            project_id: Numeric project ID or URL-encoded path.
            mr_iid: Merge request IID.
            body: Note body text (GitLab-flavored Markdown).

        Returns:
            Created note object.
        """
        if isinstance(project_id, str):
            project_id = quote(project_id, safe="")

        url = f"/projects/{project_id}/merge_requests/{mr_iid}/notes"
        payload = {"body": body}
        resp = await self.client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()
