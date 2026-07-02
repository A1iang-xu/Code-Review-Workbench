"""
SQLInjectionDetectSkill

SQL 注入检测 Skill — 基于正则模式检测字符串拼接 SQL。
支持 Python、Go、TypeScript/JavaScript、Java。
"""

import re
from typing import Any

from app.core.skills.registry import BaseSkill, SkillCategory, SkillMetadata, SkillResult


# 各语言 SQL 注入模式
SQL_PATTERNS = {
    "python": [
        (r'(?i)f["\']\s*(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE)\b[^"\']*\{',
         "f-string 拼接 SQL"),
        (r'(?i)["\']\s*(?:SELECT|INSERT|UPDATE|DELETE)\b[^"\']*["\']\s*\+',
         "字符串拼接 SQL"),
        (r'(?i)\.execute\s*\(\s*(?:f["\']|.*\+)',
         "execute() 接收拼接字符串"),
    ],
    "go": [
        (r'(?i)fmt\.Sprintf\s*\(\s*["\'](?:SELECT|INSERT|UPDATE|DELETE)\b[^"\']*\%[svd]',
         "fmt.Sprintf 拼接 SQL"),
        (r'(?i)db\.(?:Query|Exec)\s*\(\s*fmt\.Sprintf',
         "db.Query/Exec 接收 fmt.Sprintf 结果"),
    ],
    "javascript": [
        (r'(?i)`(?:SELECT|INSERT|UPDATE|DELETE|DROP)\b[^`]*\$\{',
         "模板字符串拼接 SQL"),
        (r'(?i)["\']\s*(?:SELECT|INSERT|UPDATE|DELETE)\b[^"\']*["\']\s*\+',
         "字符串拼接 SQL"),
    ],
    "typescript": [
        (r'(?i)`(?:SELECT|INSERT|UPDATE|DELETE|DROP)\b[^`]*\$\{',
         "模板字符串拼接 SQL"),
        (r'(?i)["\']\s*(?:SELECT|INSERT|UPDATE|DELETE)\b[^"\']*["\']\s*\+',
         "字符串拼接 SQL"),
    ],
    "java": [
        (r'(?i)["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP)\b[^"\']*["\']\s*\+\s*\w+',
         "字符串拼接 SQL"),
        (r'(?i)\.execute\s*\(\s*["\'].*["\']\s*\+',
         "execute() 接收拼接字符串"),
    ],
}

_EXT_TO_LANG = {
    ".py": "python", ".go": "go", ".ts": "typescript",
    ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript", ".java": "java",
}


class SQLInjectionDetectSkill(BaseSkill):
    """SQL 注入检测 Skill。

    基于正则模式检测字符串拼接 SQL 语句，
    识别潜在的 SQL 注入风险。
    """

    metadata = SkillMetadata(
        name="sql_injection_detect",
        display_name="SQL 注入检测",
        version="1.0.0",
        category=SkillCategory.SECURITY,
        description="基于正则检测字符串拼接 SQL，识别潜在 SQL 注入风险",
        author="Code Review Workbench",
        languages=["python", "go", "typescript", "javascript", "java"],
        tags=["security", "sql-injection", "owasp"],
    )

    async def execute(
        self,
        code: str,
        file_path: str = "<string>",
        context: dict[str, Any] | None = None,
    ) -> SkillResult:
        """执行 SQL 注入检测。"""
        import os
        ext = os.path.splitext(file_path)[1].lower()
        language = _EXT_TO_LANG.get(ext, "python")
        patterns = SQL_PATTERNS.get(language, SQL_PATTERNS["python"])

        findings: list[dict] = []
        lines = code.splitlines()

        for i, line in enumerate(lines, 1):
            # 跳过注释行
            stripped = line.strip()
            if language == "python" and stripped.startswith("#"):
                continue
            if language != "python" and stripped.startswith(("//", "/*", "*")):
                continue

            for pattern, desc in patterns:
                match = re.search(pattern, line)
                if match:
                    matched = match.group(0)[:80]
                    findings.append({
                        "skill": "sql_injection_detect",
                        "severity": "critical",
                        "file_path": file_path,
                        "line_start": i,
                        "line_end": i,
                        "category": "sql_injection",
                        "title": f"SQL 注入风险: {desc}",
                        "description": f"第 {i} 行疑似通过 {desc}: {matched}",
                        "suggestion": "使用参数化查询（prepared statement），避免字符串拼接 SQL",
                        "code_snippet": stripped[:200],
                    })
                    break  # 每行只报告一次

        summary = f"SQL 注入检测完成: 发现 {len(findings)} 个风险点"
        return SkillResult(
            success=True,
            findings=findings,
            summary=summary,
        )


# Skill 实例（供 SkillLoader 导入）
skill = SQLInjectionDetectSkill()
