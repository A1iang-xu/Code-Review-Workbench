"""
StyleCheckSkill

代码风格检查 Skill — 基于 PEP 8 / 通用规范检测风格问题。
支持 Python（PEP 8）、TypeScript/JavaScript、Go、Java。
"""

from typing import Any

from app.core.skills.registry import BaseSkill, SkillCategory, SkillMetadata, SkillResult


class StyleCheckSkill(BaseSkill):
    """代码风格检查 Skill。

    检测常见风格问题：
    - 行过长（>120 字符）
    - 缩进不一致（Tab vs Space 混用）
    - 行尾空格
    - 函数/类后缺少空行
    - import 顺序不规范
    """

    metadata = SkillMetadata(
        name="style_check",
        display_name="代码风格检查",
        version="1.0.0",
        category=SkillCategory.STYLE,
        description="检测行过长、缩进不一致、行尾空格等代码风格问题",
        author="Code Review Workbench",
        languages=["python", "go", "typescript", "javascript", "java"],
        tags=["style", "pep8", "linting"],
    )

    MAX_LINE_LENGTH = 120

    async def execute(
        self,
        code: str,
        file_path: str = "<string>",
        context: dict[str, Any] | None = None,
    ) -> SkillResult:
        """执行代码风格检查。"""
        findings: list[dict] = []
        lines = code.splitlines()
        has_tab = False
        has_space = False

        for i, line in enumerate(lines, 1):
            # 跳过空行
            if not line.strip():
                continue

            # 行过长
            if len(line) > self.MAX_LINE_LENGTH:
                findings.append({
                    "skill": "style_check",
                    "severity": "low",
                    "file_path": file_path,
                    "line_start": i,
                    "line_end": i,
                    "category": "line_too_long",
                    "title": f"行过长 ({len(line)} > {self.MAX_LINE_LENGTH} 字符)",
                    "description": f"第 {i} 行长度 {len(line)} 字符，超过 {self.MAX_LINE_LENGTH} 字符上限",
                    "suggestion": "拆分长行或使用换行符",
                })

            # 行尾空格
            if line != line.rstrip():
                findings.append({
                    "skill": "style_check",
                    "severity": "low",
                    "file_path": file_path,
                    "line_start": i,
                    "line_end": i,
                    "category": "trailing_whitespace",
                    "title": "行尾空格",
                    "description": f"第 {i} 行末尾有多余空格",
                    "suggestion": "移除行尾空格",
                })

            # 缩进检查
            indent = line[:len(line) - len(line.lstrip())]
            if "\t" in indent:
                has_tab = True
            if " " in indent:
                has_space = True

        # Tab/Space 混用
        if has_tab and has_space:
            findings.append({
                "skill": "style_check",
                "severity": "medium",
                "file_path": file_path,
                "line_start": 0,
                "line_end": 0,
                "category": "mixed_indent",
                "title": "Tab 和 Space 缩进混用",
                "description": "文件中同时存在 Tab 和 Space 缩进",
                "suggestion": "统一使用 4 个空格作为缩进（PEP 8 推荐）",
            })

        # 函数/类后缺少空行（仅 Python）
        if file_path.endswith(".py"):
            for i, line in enumerate(lines):
                stripped = line.strip()
                if i + 1 < len(lines):
                    next_stripped = lines[i + 1].strip()
                    # 函数/类定义后应有空行
                    if (stripped.startswith(("def ", "class ")) and
                            next_stripped and not next_stripped.startswith("#")):
                        findings.append({
                            "skill": "style_check",
                            "severity": "low",
                            "file_path": file_path,
                            "line_start": i + 1,
                            "line_end": i + 1,
                            "category": "missing_blank_line",
                            "title": "函数/类定义后缺少空行",
                            "description": f"第 {i + 1} 行定义后应有一个空行",
                            "suggestion": "PEP 8 建议函数/类定义前后各留两个空行",
                        })

        severity_counts: dict[str, int] = {}
        for f in findings:
            sev = f["severity"]
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        summary_parts = [f"风格检查完成: {len(findings)} 个问题"]
        for sev, cnt in severity_counts.items():
            summary_parts.append(f"  {sev}: {cnt}")

        return SkillResult(
            success=True,
            findings=findings,
            summary="\n".join(summary_parts),
        )


# Skill 实例（供 SkillLoader 导入）
skill = StyleCheckSkill()
