"""
SemgrepScanSkill

调用 Semgrep CLI 进行静态安全分析 Skill。
解析 semgrep --config auto --json 输出的 JSON 结果。
"""

import asyncio
import json
from typing import Any

from app.core.skills.registry import BaseSkill, SkillCategory, SkillMetadata, SkillResult


class SemgrepScanSkill(BaseSkill):
    """Semgrep 静态分析 Skill。

    通过命令行调用 semgrep，支持：
    - 自动规则集 (--config auto)
    - JSON 输出解析
    - 超时和错误处理
    """

    metadata = SkillMetadata(
        name="semgrep_scan",
        display_name="Semgrep 安全扫描",
        version="1.0.0",
        category=SkillCategory.SECURITY,
        description="调用 Semgrep CLI 进行多语言静态安全分析，支持自动规则集",
        author="Code Review Workbench",
        requires=["semgrep"],
        languages=["python", "go", "javascript", "typescript", "java"],
        tags=["security", "static-analysis", "semgrep", "sast"],
    )

    async def validate(self) -> bool:
        """验证 Semgrep 是否已安装。"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "semgrep", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await asyncio.wait_for(
                proc.communicate(), timeout=10
            )
            return proc.returncode == 0
        except (FileNotFoundError, asyncio.TimeoutError):
            return False

    async def execute(
        self,
        code: str,
        file_path: str = "<string>",
        context: dict[str, Any] | None = None,
    ) -> SkillResult:
        """执行 Semgrep 扫描。

        将代码写入临时文件，调用 semgrep --config auto --json，
        解析输出的 JSON 结果。

        Args:
            code: 源代码文本
            file_path: 文件路径（用于确定语言和报告位置）
            context: 可选上下文

        Returns:
            SkillResult 包含扫描结果
        """
        import tempfile
        import os

        # 验证环境
        if not await self.validate():
            return SkillResult(
                success=False,
                summary=(
                    "Semgrep 未安装或不可用。\n"
                    "请运行: pip install semgrep\n"
                    "或访问 https://semgrep.dev 了解安装方式。"
                ),
            )

        # 确定文件扩展名
        ext = os.path.splitext(file_path)[1]
        if not ext:
            ext = ".py"  # 默认为 Python

        # 写入临时文件
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=ext,
                delete=False,
                encoding="utf-8",
            ) as tmp:
                tmp.write(code)
                tmp_path = tmp.name

            # 调用 semgrep
            proc = await asyncio.create_subprocess_exec(
                "semgrep",
                "--config", "auto",
                "--json",
                "--no-git-ignore",
                "--quiet",
                tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=60
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return SkillResult(
                    success=False,
                    summary="Semgrep 扫描超时（60s）",
                )

            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

            if proc.returncode not in (0, 1):
                # returncode 1 表示发现 findings，这是正常的
                stderr_text = stderr.decode("utf-8", errors="replace")
                return SkillResult(
                    success=False,
                    summary=f"Semgrep 执行失败 (exit code {proc.returncode}): {stderr_text[:200]}",
                )

            # 解析 JSON 输出
            stdout_text = stdout.decode("utf-8", errors="replace")

            try:
                semgrep_results = json.loads(stdout_text)
            except json.JSONDecodeError:
                return SkillResult(
                    success=False,
                    summary=f"Semgrep JSON 解析失败: {stdout_text[:200]}",
                )

            # 转换为统一格式的 findings
            findings: list[dict] = []
            if isinstance(semgrep_results, dict):
                results_list = semgrep_results.get("results", [])
            elif isinstance(semgrep_results, list):
                results_list = semgrep_results
            else:
                results_list = []

            for result in results_list:
                findings.append({
                    "skill": "semgrep_scan",
                    "severity": self._map_severity(result.get("extra", {}).get("severity", "")),
                    "file_path": result.get("path", file_path),
                    "line_start": result.get("start", {}).get("line", 0),
                    "line_end": result.get("end", {}).get("line", 0),
                    "category": result.get("check_id", "semgrep"),
                    "title": result.get("extra", {}).get("message", "Semgrep finding"),
                    "description": result.get("extra", {}).get("message", ""),
                    "suggestion": "",
                    "code_snippet": result.get("extra", {}).get("lines", ""),
                })

            total = len(findings)
            severity_counts: dict[str, int] = {}
            for f in findings:
                sev = f["severity"]
                severity_counts[sev] = severity_counts.get(sev, 0) + 1

            summary_parts = [f"Semgrep 扫描完成: {total} 个发现"]
            for sev, count in sorted(severity_counts.items()):
                summary_parts.append(f"  {sev}: {count}")

            return SkillResult(
                success=True,
                findings=findings,
                summary="\n".join(summary_parts),
                raw_output=stdout_text[:5000],
            )

        except Exception as e:
            return SkillResult(
                success=False,
                summary=f"Semgrep 扫描异常: {str(e)}",
            )

    @staticmethod
    def _map_severity(semgrep_severity: str) -> str:
        """将 Semgrep 严重等级映射为统一格式。"""
        mapping = {
            "ERROR": "high",
            "WARNING": "medium",
            "INFO": "low",
        }
        return mapping.get(semgrep_severity.upper(), "info")


# Skill 实例（供 SkillLoader 导入）
skill = SemgrepScanSkill()
