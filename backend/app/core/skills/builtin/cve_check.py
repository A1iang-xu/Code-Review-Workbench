"""
CVECheckSkill

检查项目依赖中是否存在已知 CVE（通用漏洞披露）。
解析 requirements.txt / package.json / go.mod 等依赖清单，
调用 OSV.dev API 查询已知漏洞。
"""

import asyncio
import json
import re
from typing import Any

import httpx

from app.core.skills.registry import BaseSkill, SkillCategory, SkillMetadata, SkillResult


class CVECheckSkill(BaseSkill):
    """CVE 漏洞检查 Skill。

    解析依赖清单文件，调用 OSV.dev API 查询每个包的已知漏洞。
    支持 Python (requirements.txt)、Node.js (package.json)、Go (go.mod)。
    """

    metadata = SkillMetadata(
        name="cve_check",
        display_name="CVE 漏洞检查",
        version="1.0.0",
        category=SkillCategory.SECURITY,
        description="解析依赖清单并查询 OSV.dev API，检测已知 CVE 漏洞",
        author="Code Review Workbench",
        languages=["python", "javascript", "typescript", "go"],
        tags=["security", "cve", "dependencies", "osv"],
    )

    OSV_API = "https://api.osv.dev/v1/query"

    async def execute(
        self,
        code: str,
        file_path: str = "<string>",
        context: dict[str, Any] | None = None,
    ) -> SkillResult:
        """执行 CVE 检查。

        Args:
            code: 依赖清单文件内容
            file_path: 文件路径（用于确定清单类型）
            context: 可选上下文

        Returns:
            SkillResult 包含发现的 CVE 列表
        """
        # 解析依赖
        deps = self._parse_dependencies(code, file_path)
        if not deps:
            return SkillResult(
                success=True,
                summary=f"未在 {file_path} 中识别到依赖声明",
                findings=[],
            )

        # 查询 OSV.dev
        findings: list[dict] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            tasks = [self._query_osv(client, name, version, ecosystem)
                     for name, version, ecosystem in deps]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                continue
            findings.extend(result)

        # 构建摘要
        severity_counts: dict[str, int] = {}
        for f in findings:
            sev = f["severity"]
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        summary_parts = [f"CVE 检查完成: 检查 {len(deps)} 个依赖，发现 {len(findings)} 个漏洞"]
        for sev in ("critical", "high", "medium", "low"):
            if sev in severity_counts:
                summary_parts.append(f"  {sev}: {severity_counts[sev]}")

        return SkillResult(
            success=True,
            findings=findings,
            summary="\n".join(summary_parts),
        )

    def _parse_dependencies(self, content: str, file_path: str) -> list[tuple[str, str, str]]:
        """解析依赖清单，返回 (name, version, ecosystem) 列表。"""
        deps: list[tuple[str, str, str]] = []
        lower = file_path.lower()

        if lower.endswith("requirements.txt") or "requirements" in lower:
            # Python requirements.txt
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # package==1.0.0 或 package>=1.0.0
                m = re.match(r'^([a-zA-Z0-9_-]+)\s*[=<>~!]=?\s*([0-9][0-9a-zA-Z.\-]*)', line)
                if m:
                    deps.append((m.group(1), m.group(2), "PyPI"))

        elif lower.endswith("package.json"):
            # Node.js package.json
            try:
                pkg = json.loads(content)
                for section in ("dependencies", "devDependencies"):
                    for name, ver in pkg.get(section, {}).items():
                        # 去除 ^ ~ 等前缀
                        clean_ver = re.sub(r'^[\^~>=<]*\s*', '', ver)
                        if clean_ver and clean_ver[0].isdigit():
                            deps.append((name, clean_ver, "npm"))
            except json.JSONDecodeError:
                pass

        elif lower.endswith("go.mod"):
            # Go go.mod
            for line in content.splitlines():
                m = re.match(r'^\s*(?:require\s+)?(\S+)\s+(v[0-9]+\.[0-9]+\.[0-9]+)', line)
                if m:
                    deps.append((m.group(1), m.group(2), "Go"))

        return deps

    async def _query_osv(
        self, client: httpx.AsyncClient, name: str, version: str, ecosystem: str
    ) -> list[dict]:
        """查询单个包的已知漏洞。"""
        payload = {
            "package": {"name": name, "ecosystem": ecosystem},
            "version": version,
        }
        try:
            resp = await client.post(self.OSV_API, json=payload)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            return []

        findings: list[dict] = []
        for vuln in data.get("vulns", []):
            # 提取严重等级
            severity = "medium"
            for sev_entry in vuln.get("severity", []):
                if sev_entry.get("type") == "CVSS_V3":
                    score_str = sev_entry.get("score", "")
                    # CVSS 向量中提取基础分数
                    m = re.search(r'CVSS:3.[01]/AV:.*', score_str)
                    if m:
                        severity = "high"  # 简化处理
                    break

            cve_id = vuln.get("id", "UNKNOWN")
            summary_text = vuln.get("summary", "No description available")

            findings.append({
                "skill": "cve_check",
                "severity": severity,
                "file_path": "",
                "line_start": 0,
                "category": "cve",
                "title": f"CVE {cve_id}: {name}@{version}",
                "description": summary_text[:500],
                "suggestion": f"升级 {name} 到修复版本，或查看 {vuln.get('references', [{}])[0].get('url', '')}",
            })

        return findings


# Skill 实例（供 SkillLoader 导入）
skill = CVECheckSkill()
