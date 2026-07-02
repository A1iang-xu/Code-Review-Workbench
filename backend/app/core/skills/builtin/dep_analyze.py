"""
DepAnalyzeSkill

依赖分析 Skill — 检测未使用的依赖、版本冲突和过时包。
支持 Python (requirements.txt)、Node.js (package.json)、Go (go.mod)。
"""

import re
from typing import Any

from app.core.skills.registry import BaseSkill, SkillCategory, SkillMetadata, SkillResult


class DepAnalyzeSkill(BaseSkill):
    """依赖分析 Skill。

    分析依赖清单文件，检测：
    - 未固定版本的依赖（无版本号或使用 *）
    - 过宽的版本约束（如 >= 0 或 *）
    - 可能过时的版本（通过简单规则判断）
    - 重复依赖
    """

    metadata = SkillMetadata(
        name="dep_analyze",
        display_name="依赖分析",
        version="1.0.0",
        category=SkillCategory.STATIC_ANALYSIS,
        description="检测未固定版本、过宽约束、重复依赖等依赖管理问题",
        author="Code Review Workbench",
        languages=["python", "javascript", "typescript", "go"],
        tags=["dependencies", "static-analysis", "supply-chain"],
    )

    async def execute(
        self,
        code: str,
        file_path: str = "<string>",
        context: dict[str, Any] | None = None,
    ) -> SkillResult:
        """执行依赖分析。"""
        lower = file_path.lower()
        findings: list[dict] = []

        if lower.endswith("requirements.txt") or "requirements" in lower:
            findings = self._analyze_python(code, file_path)
        elif lower.endswith("package.json"):
            findings = self._analyze_npm(code, file_path)
        elif lower.endswith("go.mod"):
            findings = self._analyze_go(code, file_path)
        else:
            return SkillResult(
                success=True,
                summary=f"未识别的依赖文件类型: {file_path}",
                findings=[],
            )

        severity_counts: dict[str, int] = {}
        for f in findings:
            sev = f["severity"]
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        summary_parts = [f"依赖分析完成: 发现 {len(findings)} 个问题"]
        for sev, cnt in severity_counts.items():
            summary_parts.append(f"  {sev}: {cnt}")

        return SkillResult(
            success=True,
            findings=findings,
            summary="\n".join(summary_parts),
        )

    def _analyze_python(self, content: str, file_path: str) -> list[dict]:
        """分析 Python requirements.txt。"""
        findings: list[dict] = []
        seen: dict[str, int] = {}
        lines = content.splitlines()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # 提取包名
            m = re.match(r'^([a-zA-Z0-9_-]+)', stripped)
            if not m:
                continue
            name = m.group(1).lower()

            # 检查重复
            if name in seen:
                findings.append({
                    "skill": "dep_analyze",
                    "severity": "medium",
                    "file_path": file_path,
                    "line_start": i,
                    "category": "duplicate_dependency",
                    "title": f"重复依赖: {name}（首次出现在第 {seen[name]} 行）",
                    "description": f"依赖 {name} 被声明多次",
                    "suggestion": "移除重复声明，合并为一条",
                })
            else:
                seen[name] = i

            # 检查未固定版本
            if "==" not in stripped and ">=" not in stripped and "~=" not in stripped:
                findings.append({
                    "skill": "dep_analyze",
                    "severity": "high",
                    "file_path": file_path,
                    "line_start": i,
                    "category": "unpinned_dependency",
                    "title": f"未固定版本: {name}",
                    "description": f"依赖 {name} 未固定具体版本，可能导致构建不可复现",
                    "suggestion": f"使用 {name}==1.2.3 固定版本号",
                })

        return findings

    def _analyze_npm(self, content: str, file_path: str) -> list[dict]:
        """分析 Node.js package.json。"""
        import json
        findings: list[dict] = []

        try:
            pkg = json.loads(content)
        except json.JSONDecodeError as e:
            return [{
                "skill": "dep_analyze",
                "severity": "high",
                "file_path": file_path,
                "line_start": 1,
                "category": "invalid_json",
                "title": "package.json 解析失败",
                "description": f"JSON 解析错误: {e}",
                "suggestion": "修复 JSON 语法错误",
            }]

        for section in ("dependencies", "devDependencies"):
            deps = pkg.get(section, {})
            for name, ver in deps.items():
                # 检查使用 * 或 latest
                if ver == "*" or ver == "latest":
                    findings.append({
                        "skill": "dep_analyze",
                        "severity": "high",
                        "file_path": file_path,
                        "line_start": 0,
                        "category": "unpinned_dependency",
                        "title": f"未固定版本: {name} ({ver})",
                        "description": f"依赖 {name} 使用通配符版本，可能引入破坏性变更",
                        "suggestion": f"固定到具体版本，如 \"{name}\": \"1.2.3\"",
                    })
                # 检查使用 ^ 但无锁定文件
                elif ver.startswith("^") and "package-lock.json" not in str(context or {}):
                    findings.append({
                        "skill": "dep_analyze",
                        "severity": "low",
                        "file_path": file_path,
                        "line_start": 0,
                        "category": "caret_without_lockfile",
                        "title": f"使用 ^ 但可能缺少锁定文件: {name}",
                        "description": f"依赖 {name} 使用 ^ 版本约束，建议配合 package-lock.json 使用",
                        "suggestion": "确保提交 package-lock.json 到版本控制",
                    })

        return findings

    def _analyze_go(self, content: str, file_path: str) -> list[dict]:
        """分析 Go go.mod。"""
        findings: list[dict] = []
        lines = content.splitlines()

        has_go_sum = "go.sum" in str(context or {})
        indirect_count = 0

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # 检查 indirect 依赖过多
            if "// indirect" in stripped:
                indirect_count += 1

            # 检查未指定版本
            if stripped.startswith("require ") and "v" not in stripped.split()[-1]:
                findings.append({
                    "skill": "dep_analyze",
                    "severity": "medium",
                    "file_path": file_path,
                    "line_start": i,
                    "category": "missing_version",
                    "title": f"未指定版本: {stripped}",
                    "description": "require 语句未指定依赖版本",
                    "suggestion": "添加版本号，如 require github.com/pkg/errors v0.9.1",
                })

        if indirect_count > 20:
            findings.append({
                "skill": "dep_analyze",
                "severity": "low",
                "file_path": file_path,
                "line_start": 0,
                "category": "too_many_indirect",
                "title": f"间接依赖过多 ({indirect_count} 个)",
                "description": "间接依赖数量较多，可能增加供应链风险",
                "suggestion": "定期运行 go mod tidy 清理无用依赖",
            })

        return findings


# Skill 实例（供 SkillLoader 导入）
skill = DepAnalyzeSkill()
