"""
Webhook API 端点

POST /api/v1/webhooks/github — GitHub PR Webhook (审查触发)
POST /api/v1/webhooks/gitlab — GitLab MR Webhook (审查触发)

Webhook 使用 BackgroundTasks 异步执行审查，避免超时。
"""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from app.config import get_settings
from app.integrations.github import GitHubIntegration
from app.integrations.gitlab import GitLabIntegration

router = APIRouter(tags=["webhooks"])
settings = get_settings()

# ----------------------------------------------------------------
# File type filtering
# ----------------------------------------------------------------

# Extensions to skip during automated review
_SKIP_EXTENSIONS = {
    ".md", ".markdown", ".rst", ".txt",
    ".json", ".yaml", ".yml", ".toml",
    ".xml", ".svg", ".csv",
    ".lock", ".gitignore", ".dockerignore",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp",
    ".pdf", ".zip", ".tar", ".gz",
}

_CODE_EXTENSIONS = {
    ".py", ".go", ".ts", ".tsx", ".js", ".jsx",
    ".java", ".rs", ".c", ".cpp", ".h", ".hpp",
    ".rb", ".php", ".swift", ".kt",
}


def _is_code_file(filename: str) -> bool:
    """Check if a file is a reviewable code file."""
    name = filename.lower()
    for ext in _SKIP_EXTENSIONS:
        if name.endswith(ext):
            return False
    for ext in _CODE_EXTENSIONS:
        if name.endswith(ext):
            return True
    # Unknown extensions — review if they look like text
    return True


# ----------------------------------------------------------------
# PR Review body formatter
# ----------------------------------------------------------------

def _build_review_body(
    summary: str,
    score: float,
    severity_counts: dict[str, int],
    issue_count: int,
    stats: dict[str, Any],
) -> str:
    """Build a GitHub/GitLab-flavored Markdown review summary."""

    score_emoji = "✅" if score >= 8 else "⚠️" if score >= 6 else "❌"

    lines = [
        f"## {score_emoji} Code Review — Score: {score}/10",
        "",
        f"**Summary:** {summary}",
        "",
        "### Severity Breakdown",
        "",
        "| Severity | Count |",
        "|----------|-------|",
        f"| 🔴 Critical | {severity_counts.get('critical', 0)} |",
        f"| 🟠 High     | {severity_counts.get('high', 0)} |",
        f"| 🟡 Medium   | {severity_counts.get('medium', 0)} |",
        f"| 🔵 Low      | {severity_counts.get('low', 0)} |",
        f"| ⚪ Info     | {severity_counts.get('info', 0)} |",
        f"| **Total**   | **{issue_count}** |",
        "",
    ]

    # Agent stats
    by_agent = stats.get("by_agent", {})
    if by_agent:
        lines.append("### Findings by Agent")
        lines.append("")
        lines.append("| Agent | Findings |")
        lines.append("|-------|----------|")
        for agent, count in by_agent.items():
            lines.append(f"| {agent} | {count} |")
        lines.append("")

    lines.append("---")
    lines.append(
        "*Automated review by [Code Review Workbench]"
        "(https://github.com/code-review-workbench)*"
    )

    return "\n".join(lines)


def _build_inline_comment(issue: dict[str, Any]) -> str:
    """Build an inline review comment for a single issue."""
    sev = issue.get("severity", "info").upper()
    title = issue.get("title", "Issue")
    desc = issue.get("description", "")
    suggestion = issue.get("suggestion", "")

    lines = [
        f"**{sev}** — {title}",
        "",
    ]
    if desc:
        lines.append(desc)
        lines.append("")
    if suggestion:
        lines.append(f"💡 **Suggestion:** {suggestion}")

    return "\n".join(lines)


# ----------------------------------------------------------------
# Background task — PR review
# ----------------------------------------------------------------

async def _run_pr_review(
    owner: str,
    repo: str,
    pr_number: int,
    sha: str,
    target_branch: str,
) -> None:
    """Background task: fetch PR diff, run incremental review, post results back.

    使用增量审查（fetch_pr_diff）仅审查 PR 变更部分，而非全量文件。
    通过 Celery 异步执行，解决 BackgroundTasks 进程重启丢失任务的问题。

    Flow:
    1. Set commit status → pending
    2. Fetch PR diff (仅变更文件)
    3. Run LangGraph review pipeline (增量审查)
    4. Post PR review summary
    5. Post inline comments (max 5 for critical/high)
    6. Set commit status → success/failure
    """
    gh = GitHubIntegration()
    errors: list[str] = []

    try:
        # --- 1. Set status: pending ---
        await gh.set_commit_status(
            owner, repo, sha,
            state="pending",
            description="Code review in progress...",
        )

        # --- 2. Fetch PR diff (增量审查) ---
        from app.integrations.repo_fetcher import fetch_pr_diff

        files_for_review, fetch_err = await fetch_pr_diff(owner, repo, pr_number)

        if fetch_err:
            await gh.set_commit_status(
                owner, repo, sha,
                state="error",
                description=f"Failed to fetch PR diff: {fetch_err[:100]}",
            )
            return

        if not files_for_review:
            await gh.set_commit_status(
                owner, repo, sha,
                state="success",
                description="No code changes to review",
            )
            return

        # --- 3. Run the review pipeline (via Celery) ---
        from app.core.tasks import run_review_task
        import datetime

        task_id = f"pr-{owner}-{repo}-{pr_number}"
        started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        request_data = {
            "repo_url": f"https://github.com/{owner}/{repo}",
            "branch": target_branch,
            "language": "auto",
            "files": files_for_review,
        }

        # 通过 Celery 异步执行增量审查
        run_review_task.delay(
            task_id=task_id,
            request_data=request_data,
            started_at=started_at,
        )

        # 等待 Celery 任务完成（轮询结果）
        # 注意：这里使用同步等待，因为 Webhook 需要最终状态
        # 实际生产中可改为异步回调
        result = run_review_task.AsyncResult(task_id)

        try:
            review_result = result.get(timeout=settings.REVIEW_TIMEOUT_SECONDS)
        except Exception as e:
            errors.append(f"Celery task failed: {e}")
            review_result = {}

        # --- 4. Build and post PR review ---
        summary = review_result.get("summary", "Review completed with errors.")
        score = review_result.get("score", 0.0)
        issues_count = review_result.get("issues_count", 0)

        # 从数据库加载完整结果获取 issues 详情
        from app.api.v1.reviews import _load_from_db
        db_data = await _load_from_db(task_id)
        merged = db_data.get("issues", []) if db_data else []

        # Count severities
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for r in merged:
            sev = r.get("severity", "info")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        # Build stats
        agent_stats = {}
        for r in merged:
            at = r.get("agent_type", "unknown")
            agent_stats[at] = agent_stats.get(at, 0) + 1

        # Build review body
        review_body = _build_review_body(
            summary=summary,
            score=score,
            severity_counts=severity_counts,
            issue_count=issues_count,
            stats={"by_agent": agent_stats},
        )

        # Determine review event
        review_event = "REQUEST_CHANGES" if score < 5 else "COMMENT"

        # Post the review
        try:
            await gh.create_pr_review(
                owner, repo, pr_number, sha,
                body=review_body,
                event=review_event,
            )
        except Exception as e:
            errors.append(f"Failed to post PR review: {e}")

        # --- 5. Post inline comments (max 5, critical/high only) ---
        inline_count = 0
        for issue in merged:
            if inline_count >= 5:
                break
            sev = issue.get("severity", "info")
            if sev not in ("critical", "high"):
                continue

            file_path = issue.get("file_path", "")
            line = issue.get("line_start", 0)
            if not file_path or line <= 0:
                continue

            comment_body = _build_inline_comment(issue)
            try:
                await gh.create_review_comment(
                    owner, repo, pr_number, sha,
                    body=comment_body,
                    path=file_path,
                    line=line,
                )
                inline_count += 1
            except Exception:
                continue

        # --- 6. Set final commit status ---
        final_state_str = "success" if not errors else "error"
        await gh.set_commit_status(
            owner, repo, sha,
            state=final_state_str,
            description=(
                f"Review complete — Score: {score}/10, "
                f"{issues_count} issues"
            ),
        )

    except Exception as e:
        errors.append(f"Background review failed: {e}")
        try:
            await gh.set_commit_status(
                owner, repo, sha,
                state="error",
                description=f"Review failed: {str(e)[:100]}",
            )
        except Exception:
            pass

    finally:
        await gh.close()


# ----------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------

@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str = Header(default=""),
    x_github_event: str = Header(default=""),
    x_github_delivery: str = Header(default=""),
):
    """Handle GitHub Webhook events.

    Only processes pull_request events (opened / synchronize / reopened).
    Signature verification uses X-Hub-Signature-256 (HMAC-SHA256).

    The review runs asynchronously via BackgroundTasks to return
    a response within GitHub's 10-second timeout.
    """
    # Read raw body for signature verification
    raw_body = await request.body()

    # 校验 GitHub Webhook 签名
    # - 若 WEBHOOK_SECRET 未配置或为占位符 → 拒绝（生产安全要求必须配置）
    # - 若已配置 → 强制 HMAC 校验，签名不匹配返回 403
    webhook_secret = settings.WEBHOOK_SECRET
    _PLACEHOLDER = "your-webhook-secret"
    if not webhook_secret or webhook_secret == _PLACEHOLDER:
        # 开发环境放行（方便本地调试），生产环境严格拒绝
        if settings.APP_ENV.lower() in {"production", "prod"}:
            raise HTTPException(
                status_code=500,
                detail="WEBHOOK_SECRET 未配置或仍为占位符，生产环境禁止此行为",
            )
    else:
        if not GitHubIntegration.verify_signature(raw_body, x_hub_signature_256):
            raise HTTPException(status_code=403, detail="Invalid webhook signature")

    # Parse JSON body
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Only process pull_request events we care about
    if x_github_event != "pull_request":
        return {"message": f"Event '{x_github_event}' ignored — only pull_request is processed"}

    action = payload.get("action", "")
    if action not in ("opened", "synchronize", "reopened"):
        return {
            "message": f"PR action '{action}' ignored — only opened/synchronize/reopened trigger review",
        }

    # Extract PR information
    try:
        repo_full = payload["repository"]["full_name"]
        owner, repo = repo_full.split("/")
        pr_number = payload["pull_request"]["number"]
        sha = payload["pull_request"]["head"]["sha"]
        target_branch = payload["pull_request"]["base"]["ref"]
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Missing required PR fields: {e}")

    # Schedule background review
    background_tasks.add_task(
        _run_pr_review,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        sha=sha,
        target_branch=target_branch,
    )

    return {
        "message": "Review scheduled",
        "delivery_id": x_github_delivery,
        "owner": owner,
        "repo": repo,
        "pr": pr_number,
    }


@router.post("/webhooks/gitlab")
async def gitlab_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_gitlab_event: str = Header(default=""),
    x_gitlab_token: str = Header(default=""),
):
    """Handle GitLab Webhook events.

    Processes Merge Request Hook events.
    The review runs asynchronously via BackgroundTasks.
    """
    # 校验 GitLab Webhook token（X-Gitlab-Token）
    # - 生产环境：必须配置 GITLAB_TOKEN 且与请求头匹配，否则拒绝
    # - 开发环境：若 GITLAB_TOKEN 未配置则放行；若已配置但请求头不匹配则拒绝
    import secrets as _secrets

    if not settings.GITLAB_TOKEN:
        if settings.APP_ENV.lower() in {"production", "prod"}:
            raise HTTPException(
                status_code=500,
                detail="GITLAB_TOKEN 未配置，生产环境禁止此行为",
            )
    else:
        if not x_gitlab_token or not _secrets.compare_digest(
            x_gitlab_token, settings.GITLAB_TOKEN
        ):
            raise HTTPException(status_code=403, detail="Invalid GitLab webhook token")

    if x_gitlab_event != "Merge Request Hook":
        return {"message": f"Event '{x_gitlab_event}' ignored"}

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    object_kind = payload.get("object_kind", "")
    if object_kind != "merge_request":
        return {"message": f"object_kind '{object_kind}' ignored"}

    object_attributes = payload.get("object_attributes", {})
    action = object_attributes.get("action", "")

    if action not in ("open", "update", "reopen"):
        return {"message": f"MR action '{action}' ignored"}

    try:
        project = payload.get("project", {})
        project_id = project.get("id")
        mr_iid = object_attributes["iid"]
        source_branch = object_attributes.get("source_branch", "")
        target_branch = object_attributes.get("target_branch", "")

        # GitLab merge request info
        mr_title = object_attributes.get("title", "")
        _ = object_attributes.get("source_project_id", project_id)
    except (KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Missing MR fields: {e}")

    # Schedule background GitLab MR review
    background_tasks.add_task(
        _run_gitlab_mr_review,
        project_id=project_id,
        mr_iid=mr_iid,
        source_branch=source_branch,
        target_branch=target_branch,
        mr_title=mr_title,
    )

    return {
        "message": "GitLab MR review scheduled",
        "project_id": project_id,
        "mr_iid": mr_iid,
    }


async def _run_gitlab_mr_review(
    project_id: int,
    mr_iid: int,
    source_branch: str,
    target_branch: str,
    mr_title: str,
) -> None:
    """Background task: fetch GitLab MR changes, run review, post note."""
    gl = GitLabIntegration()
    errors: list[str] = []

    try:
        # 1. Fetch MR changes
        try:
            mr_data = await gl.get_merge_request_changes(project_id, mr_iid)
        except Exception as e:
            await gl.create_mr_note(
                project_id, mr_iid,
                body=f"❌ Failed to fetch MR changes for review: {e}",
            )
            return

        changes = mr_data.get("changes", [])
        if not changes:
            await gl.create_mr_note(
                project_id, mr_iid,
                body="No file changes to review.",
            )
            return

        # 2. Filter to code files & build review input
        files_for_review: list[dict[str, str]] = []
        for change in changes:
            file_path = change.get("new_path", change.get("old_path", ""))
            if not _is_code_file(file_path):
                continue
            # Use the 'diff' content; for full content we'd need a different approach
            content = change.get("diff", "")
            if not content:
                continue
            files_for_review.append({
                "path": file_path,
                "content": content,
            })

        if not files_for_review:
            await gl.create_mr_note(
                project_id, mr_iid,
                body="No reviewable code changes found.",
            )
            return

        # 3. Run the review pipeline
        from app.core.orchestrator import review_graph
        from app.core.state import ReviewState

        task_id = f"gl-mr-{project_id}-{mr_iid}"

        initial_state: ReviewState = {
            "task_id": task_id,
            "repo_url": f"https://gitlab.com/project/{project_id}",
            "branch": source_branch,
            "files": files_for_review,
            "current_stage": "parse_code",
            "progress": 0.0,
            "style_results": [],
            "security_results": [],
            "architecture_results": [],
            "performance_results": [],
            "refactor_results": [],
            "_parsed_files": [],
            "_merged_results": [],
            "report_summary": "",
            "report_score": 0.0,
            "report_html": "",
            "errors": [],
            "started_at": "",
            "completed_at": "",
        }

        try:
            final_state = await review_graph.ainvoke(initial_state)
        except Exception as e:
            errors.append(f"Review pipeline failed: {e}")
            final_state = {}

        # 4. Build and post MR note
        summary = final_state.get("report_summary", "Review completed with errors.")
        score = final_state.get("report_score", 0.0)
        merged = final_state.get("_merged_results", [])

        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for r in merged:
            sev = r.get("severity", "info")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        review_body = _build_review_body(
            summary=summary,
            score=score,
            severity_counts=severity_counts,
            issue_count=len(merged),
            stats={"by_agent": {}},
        )

        # Add top issues detail
        if merged:
            review_body += "\n\n### Top Issues\n\n"
            for i, issue in enumerate(merged[:10]):
                sev = issue.get("severity", "info").upper()
                review_body += (
                    f"{i + 1}. **[{sev}]** {issue.get('title', '')} "
                    f"(`{issue.get('file_path', '')}:{issue.get('line_start', 0)}`)\n"
                )

        try:
            await gl.create_mr_note(project_id, mr_iid, body=review_body)
        except Exception as e:
            errors.append(f"Failed to post MR note: {e}")

    except Exception as e:
        errors.append(f"GitLab MR review failed: {e}")

    finally:
        await gl.close()
