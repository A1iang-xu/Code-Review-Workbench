"""
DiffContextSkill

Diff 上下文分析 Skill — 解析 unified diff 格式，提取变更行和上下文。
用于增量审查，仅分析 PR/MR 的变更部分。
"""

import re
from typing import Any

from app.core.skills.registry import BaseSkill, SkillCategory, SkillMetadata, SkillResult


class DiffContextSkill(BaseSkill):
    """Diff 上下文分析 Skill。

    解析 unified diff 格式（git diff 输出），
    提取变更的文件、新增行、删除行和上下文。

    可作为独立工具使用，也可为 Agent 提供增量审查的上下文。
    """

    metadata = SkillMetadata(
        name="diff_context",
        display_name="Diff 上下文分析",
        version="1.0.0",
        category=SkillCategory.UTILITY,
        description="解析 unified diff，提取变更文件和行号，支持增量审查",
        author="Code Review Workbench",
        languages=["python", "go", "typescript", "javascript", "java"],
        tags=["diff", "incremental", "pr-review"],
    )

    async def execute(
        self,
        code: str,
        file_path: str = "<string>",
        context: dict[str, Any] | None = None,
    ) -> SkillResult:
        """解析 diff 内容。

        Args:
            code: unified diff 文本
            file_path: 文件路径（用于报告）
            context: 可选上下文

        Returns:
            SkillResult 包含解析后的变更信息
        """
        diff_text = code
        files = self._parse_diff(diff_text)

        if not files:
            return SkillResult(
                success=True,
                summary="未识别到 diff 变更",
                findings=[],
            )

        findings: list[dict] = []
        total_added = 0
        total_removed = 0

        for file_info in files:
            total_added += file_info["added_lines"]
            total_removed += file_info["removed_lines"]

            # 将每个变更文件作为一个 finding
            findings.append({
                "skill": "diff_context",
                "severity": "info",
                "file_path": file_info["new_path"],
                "line_start": file_info["changes"][0]["new_line"] if file_info["changes"] else 0,
                "line_end": file_info["changes"][-1]["new_line"] if file_info["changes"] else 0,
                "category": "diff_file",
                "title": f"变更文件: {file_info['new_path']}",
                "description": (
                    f"+{file_info['added_lines']} -{file_info['removed_lines']} 行, "
                    f"{len(file_info['changes'])} 处变更"
                ),
                "suggestion": "",
                "code_snippet": file_info["changes"][0]["content"][:200] if file_info["changes"] else "",
            })

        summary = (
            f"Diff 分析完成: {len(files)} 个文件变更, "
            f"+{total_added} -{total_removed} 行"
        )

        return SkillResult(
            success=True,
            findings=findings,
            summary=summary,
            raw_output=str(files)[:5000],
        )

    def _parse_diff(self, diff_text: str) -> list[dict[str, Any]]:
        """解析 unified diff 格式。

        Returns:
            变更文件列表，每个文件包含:
            - old_path, new_path: 文件路径
            - added_lines, removed_lines: 增删行数
            - changes: 变更详情列表
        """
        files: list[dict[str, Any]] = []
        current_file: dict[str, Any] | None = None
        old_line = 0
        new_line = 0

        for line in diff_text.splitlines():
            # 文件头: diff --git a/file.py b/file.py
            if line.startswith("diff --git"):
                if current_file:
                    files.append(current_file)
                current_file = {
                    "old_path": "",
                    "new_path": "",
                    "added_lines": 0,
                    "removed_lines": 0,
                    "changes": [],
                }
            # --- a/file.py
            elif line.startswith("--- "):
                if current_file:
                    current_file["old_path"] = line[4:].strip()
            # +++ b/file.py
            elif line.startswith("+++ "):
                if current_file:
                    path = line[4:].strip()
                    # 去除 b/ 前缀
                    if path.startswith("b/"):
                        path = path[2:]
                    current_file["new_path"] = path
            # 行号信息: @@ -1,5 +1,7 @@
            elif line.startswith("@@"):
                m = re.match(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
                if m and current_file:
                    old_line = int(m.group(1))
                    new_line = int(m.group(2))
            # 新增行
            elif line.startswith("+") and not line.startswith("+++"):
                if current_file:
                    current_file["added_lines"] += 1
                    current_file["changes"].append({
                        "type": "added",
                        "old_line": 0,
                        "new_line": new_line,
                        "content": line[1:],
                    })
                    new_line += 1
            # 删除行
            elif line.startswith("-") and not line.startswith("---"):
                if current_file:
                    current_file["removed_lines"] += 1
                    current_file["changes"].append({
                        "type": "removed",
                        "old_line": old_line,
                        "new_line": 0,
                        "content": line[1:],
                    })
                    old_line += 1
            # 上下文行
            elif line.startswith(" "):
                old_line += 1
                new_line += 1

        if current_file:
            files.append(current_file)

        return files


# Skill 实例（供 SkillLoader 导入）
skill = DiffContextSkill()
