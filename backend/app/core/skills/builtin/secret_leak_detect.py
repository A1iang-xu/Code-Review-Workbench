"""
SecretLeakDetectSkill

密钥泄露检测 Skill — 基于正则检测硬编码的 API Key、密码、Token。
支持多语言，排除注释行和环境变量读取。
"""

import re
from typing import Any

from app.core.skills.registry import BaseSkill, SkillCategory, SkillMetadata, SkillResult


# 密钥模式（通用，跨语言）
SECRET_PATTERNS = [
    # 通用 API Key / Secret
    (r'(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|'
     r'private[_-]?key|password|passwd|jwt[_-]?secret|encryption[_-]?key)\s*[:=]\s*'
     r'["\'][A-Za-z0-9+/=_\-.@!]{8,}["\']',
     "hardcoded_secret",
     "硬编码密钥"),

    # AWS Access Key
    (r'(?i)\b(AKIA[0-9A-Z]{16})\b',
     "aws_access_key",
     "AWS Access Key ID"),

    # AWS Secret Key
    (r'(?i)\baws[_-]?secret[_-]?access[_-]?key\s*[:=]\s*["\']([A-Za-z0-9/+=]{40})["\']',
     "aws_secret_key",
     "AWS Secret Access Key"),

    # GitHub Token
    (r'\b(ghp_[A-Za-z0-9]{36})\b',
     "github_token",
     "GitHub Personal Access Token"),

    # Slack Token
    (r'\b(xox[baprs]-[A-Za-z0-9-]{10,})\b',
     "slack_token",
     "Slack Token"),

    # JWT
    (r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b',
     "jwt_token",
     "JWT Token"),

    # 私钥（PEM 格式）
    (r'-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----',
     "private_key",
     "PEM 私钥"),
]

# 环境变量读取模式（应排除）
_ENV_PATTERNS = {
    "python": r'(?i)(?:os\.getenv|os\.environ)',
    "go": r'(?i)(?:os\.Getenv|viper\.Get)',
    "typescript": r'(?i)(?:process\.env|import\.meta\.env)',
    "javascript": r'(?i)(?:process\.env)',
    "java": r'(?i)(?:System\.getenv|getProperty)',
}


class SecretLeakDetectSkill(BaseSkill):
    """密钥泄露检测 Skill。

    基于正则模式检测硬编码的敏感信息，
    包括 API Key、密码、Token、私钥等。
    排除注释行和环境变量读取。
    """

    metadata = SkillMetadata(
        name="secret_leak_detect",
        display_name="密钥泄露检测",
        version="1.0.0",
        category=SkillCategory.SECURITY,
        description="检测硬编码的 API Key、密码、Token、私钥等敏感信息",
        author="Code Review Workbench",
        languages=["python", "go", "typescript", "javascript", "java"],
        tags=["security", "secrets", "hardcoded", "owasp"],
    )

    async def execute(
        self,
        code: str,
        file_path: str = "<string>",
        context: dict[str, Any] | None = None,
    ) -> SkillResult:
        """执行密钥泄露检测。"""
        import os
        ext = os.path.splitext(file_path)[1].lower()
        ext_to_lang = {".py": "python", ".go": "go", ".ts": "typescript",
                       ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript", ".java": "java"}
        language = ext_to_lang.get(ext, "python")
        env_re = _ENV_PATTERNS.get(language, _ENV_PATTERNS["python"])

        findings: list[dict] = []
        lines = code.splitlines()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # 跳过注释
            if language == "python" and stripped.startswith("#"):
                continue
            if language != "python" and stripped.startswith(("//", "/*", "*")):
                continue

            # 跳过环境变量读取
            if re.search(env_re, stripped):
                continue

            for pattern, category, desc in SECRET_PATTERNS:
                match = re.search(pattern, line)
                if match:
                    matched = match.group(0)
                    # 脱敏显示
                    if len(matched) > 20:
                        display = matched[:8] + "..." + matched[-4:]
                    else:
                        display = matched[:8] + "..."

                    severity = "critical" if category in ("private_key", "aws_secret_key", "github_token") else "high"

                    findings.append({
                        "skill": "secret_leak_detect",
                        "severity": severity,
                        "file_path": file_path,
                        "line_start": i,
                        "line_end": i,
                        "category": category,
                        "title": f"{desc}: {display}",
                        "description": f"第 {i} 行检测到疑似 {desc}",
                        "suggestion": "将密钥移至环境变量或密钥管理服务（如 Vault、AWS Secrets Manager）",
                        "code_snippet": stripped[:200],
                    })

        summary = f"密钥泄露检测完成: 发现 {len(findings)} 个敏感信息"
        return SkillResult(
            success=True,
            findings=findings,
            summary=summary,
        )


# Skill 实例（供 SkillLoader 导入）
skill = SecretLeakDetectSkill()
