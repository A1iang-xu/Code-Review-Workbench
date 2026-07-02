"""
GitHub 仓库文件拉取

支持两种 URL 形式：
1. 单文件 blob URL:
   https://github.com/{owner}/{repo}/blob/{branch}/{path}
   → 通过 raw.githubusercontent.com 拉取单个文件

2. 仓库根 URL:
   https://github.com/{owner}/{repo}
   → 通过 GitHub API 列出仓库文件并拉取（需要 token 或受速率限制）

无需 token 也能工作（使用 raw.githubusercontent.com 公开端点），
但有 token 时可提升 API 速率限制并支持私有仓库。
"""

import base64
import re

import httpx

from app.config import get_settings

settings = get_settings()


# 支持的代码文件扩展名（与前端 accept 一致）
SUPPORTED_EXTENSIONS = {
    ".py", ".go", ".ts", ".tsx", ".js", ".jsx", ".java",
}

# 忽略的目录
IGNORED_DIRS = {
    "node_modules", "vendor", "dist", "build", ".git",
    "__pycache__", ".venv", "venv", "env", ".idea", ".vscode",
    "docs", "tests", "test", "examples", "example",
}


def parse_github_url(url: str) -> dict[str, str] | None:
    """解析 GitHub URL，提取 owner/repo/branch/path。

    支持的形式：
    - https://github.com/{owner}/{repo}/blob/{branch}/{path}
    - https://github.com/{owner}/{repo}/tree/{branch}/{path}
    - https://github.com/{owner}/{repo} (默认分支 main)
    - https://github.com/{owner}/{repo}.git

    Args:
        url: GitHub URL

    Returns:
        {"owner": ..., "repo": ..., "branch": ..., "path": ...} 或 None
    """
    if not url:
        return None

    url = url.strip()
    # 去除尾部 .git
    if url.endswith(".git"):
        url = url[:-4]
    # 去除尾部斜杠
    url = url.rstrip("/")

    # 匹配 https://github.com/{owner}/{repo}/blob/{branch}/{path}
    m = re.match(
        r"^https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$",
        url,
    )
    if m:
        return {
            "owner": m.group(1),
            "repo": m.group(2),
            "branch": m.group(3),
            "path": m.group(4),
            "type": "file",
        }

    # 匹配 https://github.com/{owner}/{repo}/tree/{branch}/{path}
    m = re.match(
        r"^https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+)$",
        url,
    )
    if m:
        return {
            "owner": m.group(1),
            "repo": m.group(2),
            "branch": m.group(3),
            "path": m.group(4),
            "type": "dir",
        }

    # 匹配 https://github.com/{owner}/{repo}（整个仓库）
    m = re.match(
        r"^https?://github\.com/([^/]+)/([^/]+)$",
        url,
    )
    if m:
        return {
            "owner": m.group(1),
            "repo": m.group(2),
            "branch": "",  # 默认分支稍后通过 API 获取
            "path": "",
            "type": "repo",
        }

    return None


def _is_supported_file(path: str) -> bool:
    """判断文件路径是否为支持的代码文件。"""
    lower = path.lower()
    return any(lower.endswith(ext) for ext in SUPPORTED_EXTENSIONS)


def _is_ignored_path(path: str) -> bool:
    """判断路径是否在忽略目录中。"""
    parts = path.lower().split("/")
    return any(part in IGNORED_DIRS for part in parts)


def _get_github_headers() -> dict[str, str]:
    """构建 GitHub 请求头，仅在配置了真实 token 时添加 Authorization。"""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "code-review-workbench",
    }
    token = settings.GITHUB_TOKEN
    # 过滤占位符
    if token and not token.startswith("ghp_your") and token != "your-github-token-here":
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def fetch_single_file(
    owner: str, repo: str, branch: str, path: str
) -> dict[str, str] | None:
    """通过 raw.githubusercontent.com 拉取单个文件（无需 token）。

    Args:
        owner: 仓库 owner
        repo: 仓库名
        branch: 分支名
        path: 文件路径

    Returns:
        {"path": ..., "content": ...} 或 None
    """
    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    headers = _get_github_headers()

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(raw_url, headers=headers)
        if resp.status_code != 200:
            return None
        return {"path": path, "content": resp.text}


async def fetch_repo_files(
    owner: str, repo: str, branch: str = "", path: str = ""
) -> list[dict[str, str]]:
    """通过 GitHub API 列出并拉取仓库中的代码文件。

    递归遍历目录，拉取所有支持的代码文件。
    受 API 速率限制（无 token 时 60 次/小时）。

    Args:
        owner: 仓库 owner
        repo: 仓库名
        branch: 分支名（空则获取默认分支）
        path: 起始路径（空则从根开始）

    Returns:
        文件列表 [{"path": ..., "content": ...}, ...]
    """
    headers = _get_github_headers()

    # 如果未指定分支，获取默认分支
    if not branch:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers=headers,
            )
            if resp.status_code != 200:
                return []
            branch = resp.json().get("default_branch", "main")

    files: list[dict[str, str]] = []
    seen_paths: set[str] = set()

    async def _walk(dir_path: str, depth: int = 0) -> None:
        """递归遍历目录。"""
        if depth > 5:  # 限制递归深度
            return

        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{dir_path}"
        params = {"ref": branch}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code != 200:
                return
            entries = resp.json()

        if not isinstance(entries, list):
            return

        for entry in entries:
            entry_path = entry.get("path", "")
            entry_type = entry.get("type", "")  # "file" or "dir"

            if entry_type == "dir":
                if _is_ignored_path(entry_path):
                    continue
                await _walk(entry_path, depth + 1)
            elif entry_type == "file":
                if not _is_supported_file(entry_path):
                    continue
                if _is_ignored_path(entry_path):
                    continue
                if entry_path in seen_paths:
                    continue

                # 拉取文件内容
                content = await _fetch_file_via_api(
                    owner, repo, branch, entry_path, headers
                )
                if content is not None:
                    files.append({"path": entry_path, "content": content})
                    seen_paths.add(entry_path)

    await _walk(path)
    return files


async def _fetch_file_via_api(
    owner: str, repo: str, branch: str, path: str, headers: dict
) -> str | None:
    """通过 GitHub API 拉取文件内容（返回 base64 解码后的文本）。"""
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    params = {"ref": branch}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            return None
        data = resp.json()

    content_b64 = data.get("content", "")
    if not content_b64:
        return None

    try:
        content_bytes = base64.b64decode(content_b64)
        return content_bytes.decode("utf-8", errors="replace")
    except Exception:
        return None


async def fetch_files_from_url(url: str) -> tuple[list[dict[str, str]], str]:
    """从 GitHub URL 拉取代码文件。

    主入口函数：解析 URL 并调用对应的拉取逻辑。

    Args:
        url: GitHub URL（blob/tree/repo）

    Returns:
        (files, error_message)
        - 成功: (files, "")
        - 失败: ([], "错误信息")
    """
    parsed = parse_github_url(url)
    if parsed is None:
        return [], "无法解析 GitHub URL，请检查格式"

    owner = parsed["owner"]
    repo = parsed["repo"]
    branch = parsed["branch"]
    path = parsed["path"]
    url_type = parsed["type"]

    try:
        if url_type == "file":
            # 单文件 blob URL
            result = await fetch_single_file(owner, repo, branch, path)
            if result is None:
                return [], f"无法拉取文件: {path}（分支: {branch}）"
            return [result], ""

        # 仓库或目录 URL
        files = await fetch_repo_files(owner, repo, branch, path)
        if not files:
            return [], "未在仓库中找到支持的代码文件（.py/.go/.ts/.js/.java）"

        # 限制文件数量
        if len(files) > settings.MAX_FILES_PER_REVIEW:
            files = files[: settings.MAX_FILES_PER_REVIEW]

        return files, ""

    except httpx.HTTPError as e:
        return [], f"网络请求失败: {str(e)[:100]}"
    except Exception as e:
        return [], f"拉取文件失败: {str(e)[:100]}"


# ============================================================
# PR Diff 拉取（增量审查）
# ============================================================

async def fetch_pr_diff(
    owner: str,
    repo: str,
    pr_number: int,
    token: str | None = None,
) -> tuple[list[dict[str, str]], str]:
    """拉取 PR 变更文件的完整内容（增量审查）。

    通过 GitHub API 获取 PR 的变更文件列表，
    仅拉取有变更的文件内容，而非全量文件。

    Args:
        owner: 仓库 owner
        repo: 仓库名
        pr_number: PR 编号
        token: GitHub token（可选，使用 settings.GITHUB_TOKEN）

    Returns:
        (files, error_message)
        - files: [{"path": ..., "content": ..., "status": "added"|"modified"|"removed"}]
        - error_message: 失败时的错误信息
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "code-review-workbench",
    }
    gh_token = token or settings.GITHUB_TOKEN
    if gh_token and not gh_token.startswith("ghp_your") and gh_token != "your-github-token-here":
        headers["Authorization"] = f"Bearer {gh_token}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 获取 PR 文件列表
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files",
                headers=headers,
                params={"per_page": 100},
            )
            if resp.status_code != 200:
                return [], f"GitHub API 返回 {resp.status_code}: {resp.text[:200]}"

            pr_files = resp.json()
            if not isinstance(pr_files, list):
                return [], "PR 文件列表格式异常"

        files_for_review: list[dict[str, str]] = []

        for f in pr_files:
            filename = f.get("filename", "")
            status = f.get("status", "modified")  # added/modified/removed

            # 跳过删除的文件
            if status == "removed":
                continue

            # 跳过非代码文件
            if not _is_supported_file(filename):
                continue

            # 优先使用 patch 内容（如果可用）
            patch = f.get("patch", "")
            if patch:
                # 从 patch 中提取完整文件内容
                content = _extract_content_from_patch(patch)
                if content:
                    files_for_review.append({
                        "path": filename,
                        "content": content,
                        "status": status,
                    })
                    continue

            # 降级：拉取完整文件内容
            # 获取 PR 的 head SHA
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    pr_resp = await client.get(
                        f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
                        headers=headers,
                    )
                    if pr_resp.status_code == 200:
                        head_sha = pr_resp.json().get("head", {}).get("sha", "")
                        if head_sha:
                            content = await _fetch_file_via_api(
                                owner, repo, head_sha, filename, headers
                            )
                            if content:
                                files_for_review.append({
                                    "path": filename,
                                    "content": content,
                                    "status": status,
                                })
            except Exception:
                continue

        if not files_for_review:
            return [], "PR 中没有可审查的代码文件变更"

        return files_for_review, ""

    except httpx.HTTPError as e:
        return [], f"网络请求失败: {str(e)[:100]}"
    except Exception as e:
        return [], f"拉取 PR diff 失败: {str(e)[:100]}"


def _extract_content_from_patch(patch: str) -> str:
    """从 unified diff patch 中提取文件内容。

    保留新增行和上下文行，去除删除行。

    Args:
        patch: unified diff 格式的 patch 文本

    Returns:
        重建的文件内容
    """
    lines: list[str] = []

    for line in patch.splitlines():
        if line.startswith("@@"):
            # hunk 头，跳过
            continue
        elif line.startswith("+"):
            # 新增行
            lines.append(line[1:])
        elif line.startswith("-"):
            # 删除行，跳过
            continue
        elif line.startswith(" "):
            # 上下文行
            lines.append(line[1:])

    return "\n".join(lines)
