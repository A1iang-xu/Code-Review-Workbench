"""
Arbitrator Agent

仲裁与报告生成 Agent。不执行代码审查，而是汇总所有 Agent 的结果，
执行去重、冲突消解、严重等级排序、评分计算，生成综合摘要和 HTML 报告。
"""

import datetime
import json
import re
from typing import Any

from app.core.agents.base import BaseReviewAgent
from app.integrations.ast_engine import ParsedFile


# ============================================================
# 系统提示词
# ============================================================

ARBITRATOR_PROMPT = """You are a senior technical lead summarizing the results of an automated code review for a Chinese-speaking development team.
Multiple specialized agents have analyzed the codebase and produced findings.

Your task:
1. **Deduplicate findings**: Identify issues reported by multiple agents that refer to the same underlying problem.
   Merge them into a single, more complete description.
2. **Resolve conflicts**: If two agents disagree about severity or category, use your judgment to decide.
3. **Prioritize**: Rank issues by importance — consider both severity and impact on the codebase.
4. **Generate summary**: Write a concise 3-5 sentence summary in Chinese that captures:
   - Overall code quality assessment (代码整体质量评价)
   - Most critical issues that need immediate attention (需立即关注的关键问题)
   - Key areas for improvement (主要改进方向)
5. **Suggest next steps**: Recommend the order in which issues should be addressed.

Input format:
You will receive a list of findings from different agents. Each finding has:
- agent_type: which agent found it (style/security/architecture/performance/refactor)
- severity: critical/high/medium/low/info
- category: the type of issue
- title: brief description
- description: detailed explanation
- suggestion: how to fix

Output format (JSON):
{
    "summary": "3-5 sentence Chinese summary of the review. Be specific about what was found, not generic.",
    "next_steps": ["ordered list of recommended actions in Chinese"],
    "key_findings": [
        {
            "title": "consolidated finding title",
            "description": "merged description from multiple agents if applicable",
            "severity": "critical/high/medium/low/info",
            "merged_from": ["agent_type1", "agent_type2"]
        }
    ]
}

IMPORTANT: Return ONLY valid JSON. No markdown, no extra text. Write the summary field in Chinese (中文)."""


class ArbitratorAgent(BaseReviewAgent):
    """仲裁 Agent。

    汇总所有 Agent 审查结果，执行去重、排序、评分，生成综合报告。
    使用推理模型（DeepSeek V4）生成中文摘要。
    """

    agent_type = "arbitrator"
    display_name = "仲裁Agent"

    # 不需要实现 review() 方法，仲裁 Agent 不直接审查代码
    async def review(self, parsed_files: list[ParsedFile]) -> list[dict]:
        """仲裁 Agent 不直接审查代码，返回空列表。"""
        return []

    # ---- 仲裁核心逻辑 ----

    @staticmethod
    def _severity_weight(severity: str) -> int:
        """返回严重等级的排序权重。

        权重越大越严重，排序时排前面。
        """
        weights = {
            "critical": 5,
            "high": 4,
            "medium": 3,
            "low": 2,
            "info": 1,
        }
        return weights.get(severity.lower(), 0)

    def arbitrate(
        self,
        style_results: list[dict],
        security_results: list[dict],
        architecture_results: list[dict],
        performance_results: list[dict],
        refactor_results: list[dict],
        collaboration_results: list[dict] | None = None,
    ) -> dict[str, Any]:
        """合并所有 Agent 结果，执行去重、排序、统计和评分。

        Args:
            style_results: StyleChecker 的结果
            security_results: SecurityAuditor 的结果
            architecture_results: ArchitectureAnalyzer 的结果
            performance_results: PerformanceProfiler 的结果
            refactor_results: RefactorAdvisor 的结果
            collaboration_results: 第二轮 Agent 协作的结果（可选）

        Returns:
            {
                "merged_results": list[dict],    # 去重排序后的所有问题
                "severity_counts": dict,          # 各严重等级数量
                "category_counts": dict,          # 各分类数量
                "score": float,                   # 综合评分 (0-10)
                "stats": dict,                    # 各 Agent 统计
            }
        """
        # --- 收集所有结果 ---
        all_results: list[dict] = []
        all_results.extend(style_results)
        all_results.extend(security_results)
        all_results.extend(architecture_results)
        all_results.extend(performance_results)
        all_results.extend(refactor_results)
        # 合并第二轮协作结果
        if collaboration_results:
            all_results.extend(collaboration_results)

        # --- 统计各 Agent 发现数 ---
        agent_stats: dict[str, int] = {}
        for r in all_results:
            at = r.get("agent_type", "unknown")
            agent_stats[at] = agent_stats.get(at, 0) + 1

        # --- 去重 ---
        # 去重 Key: (file_path, line_start, category)
        # 但 LLM 发现的 line_start 可能为 0，所以对于 line_start=0 的结果用 title 辅助去重
        seen: set[tuple] = set()
        deduped: list[dict] = []

        for r in all_results:
            file_path = r.get("file_path", "")
            line_start = r.get("line_start", 0)
            category = r.get("category", "")

            # 对于 line_start=0 的 LLM 结果，使用 title 的前 60 字符作为区分
            if line_start == 0:
                title_key = r.get("title", "")[:60]
                dedup_key = (file_path, title_key, category)
            else:
                dedup_key = (file_path, line_start, category)

            if dedup_key not in seen:
                seen.add(dedup_key)
                deduped.append(r)

        # --- 按严重等级排序 ---
        deduped.sort(key=lambda x: -self._severity_weight(x.get("severity", "info")))

        # --- 统计严重等级 ---
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        category_counts: dict[str, int] = {}

        for r in deduped:
            sev = r.get("severity", "info")
            if sev in severity_counts:
                severity_counts[sev] += 1
            else:
                severity_counts["info"] += 1

            cat = r.get("category", "other")
            category_counts[cat] = category_counts.get(cat, 0) + 1

        # --- 评分计算（扣分制）---
        # 基础分 10，扣分：critical -2.0, high -1.0, medium -0.3, low -0.1
        # 总扣分乘以系数 0.5（缓解多 Agent 重复扣分）
        deductions = (
            severity_counts["critical"] * 2.0
            + severity_counts["high"] * 1.0
            + severity_counts["medium"] * 0.3
            + severity_counts["low"] * 0.1
        )
        raw_score = 10.0 - (deductions * 0.5)
        score = max(0.0, min(10.0, raw_score))

        return {
            "merged_results": deduped,
            "severity_counts": severity_counts,
            "category_counts": category_counts,
            "score": round(score, 1),
            "stats": {
                "total_issues": len(deduped),
                "by_severity": severity_counts,
                "by_category": category_counts,
                "by_agent": agent_stats,
            },
        }

    # ---- 摘要生成 ----

    async def _generate_summary(
        self,
        merged_results: list[dict],
        severity_counts: dict[str, int],
        score: float,
    ) -> str:
        """使用 LLM 生成 3-5 句中文摘要。

        将 Top 20 问题和统计信息传给推理模型（DeepSeek V4）。

        Args:
            merged_results: 去重排序后的问题列表
            severity_counts: 严重等级统计
            score: 综合评分

        Returns:
            中文摘要（3-5 句）
        """
        total = len(merged_results)

        if total == 0:
            return "代码审查完成，未发现问题。代码质量良好，架构清晰，安全可靠。"

        # 构建 Top 20 问题摘要
        top_issues_text_parts: list[str] = []
        for i, r in enumerate(merged_results[:20]):
            top_issues_text_parts.append(
                f"{i + 1}. [{r.get('severity')}][{r.get('agent_type')}] "
                f"{r.get('title')} — {r.get('file_path', '')}:{r.get('line_start', 0)}"
            )

        top_issues_text = "\n".join(top_issues_text_parts)

        # 统计文本
        stats_text = (
            f"总问题数: {total}\n"
            f"严重: {severity_counts['critical']}, "
            f"高危: {severity_counts['high']}, "
            f"中危: {severity_counts['medium']}, "
            f"低危: {severity_counts['low']}, "
            f"信息: {severity_counts['info']}\n"
            f"综合评分: {score}/10"
        )

        try:
            response = await self._llm_analyze(
                prompt=(
                    f"{ARBITRATOR_PROMPT}\n\n"
                    f"Review statistics:\n{stats_text}\n\n"
                    f"Top issues:\n{top_issues_text}\n\n"
                    f"Write a 3-5 sentence summary in Chinese. Be specific about the actual problems found. "
                    f"If the code has no critical issues, acknowledge that. "
                    f"Focus on: (1) overall quality level, (2) the most important 1-2 issues, (3) key improvement direction."
                ),
                code_context="",  # 不需要代码上下文
                use_reasoning=True,  # 使用 DeepSeek V4 推理
            )

            # 尝试提取 JSON 中的 summary 字段
            try:
                json_match = re.search(r"\{.*\}", response, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group(0))
                    if isinstance(data, dict) and "summary" in data:
                        return data["summary"]
            except (json.JSONDecodeError, KeyError):
                pass

            # 如果无法解析 JSON，直接使用 LLM 响应（截短）
            clean = response.strip().strip('"').strip("'")
            if len(clean) > 500:
                clean = clean[:500]
            if clean:
                return clean

        except Exception:
            pass

        # 降级：生成规则摘要
        if total == 0:
            return "代码审查完成，未发现问题。代码质量良好。"
        else:
            parts = [f"代码审查完成，共发现 {total} 个问题。"]
            if severity_counts["critical"]:
                parts.append(
                    f"其中严重问题 {severity_counts['critical']} 个，需立即修复。"
                )
            if severity_counts["high"]:
                parts.append(
                    f"高危问题 {severity_counts['high']} 个，建议优先处理。"
                )
            if severity_counts["medium"]:
                parts.append(
                    f"中危问题 {severity_counts['medium']} 个。"
                )
            parts.append(f"综合评分: {score}/10。")
            return "".join(parts)

    # ---- HTML 报告生成 ----

    def generate_html_report(
        self,
        merged_results: list[dict],
        severity_counts: dict[str, int],
        category_counts: dict[str, int],
        score: float,
        summary: str,
        stats: dict[str, Any],
        task_id: str = "",
    ) -> str:
        """生成包含评分、统计、问题详情的 HTML 审查报告。

        Args:
            merged_results: 去重排序后的问题列表
            severity_counts: 各严重等级统计
            category_counts: 各分类统计
            score: 综合评分
            summary: 审查摘要
            stats: 统计数据
            task_id: 任务 ID

        Returns:
            完整的 HTML 报告字符串
        """
        # 严重等级颜色标记
        severity_colors = {
            "critical": "#dc2626",  # 红色
            "high": "#ea580c",      # 橙色
            "medium": "#ca8a04",    # 黄色
            "low": "#2563eb",       # 蓝色
            "info": "#6b7280",      # 灰色
        }

        severity_bg = {
            "critical": "#fef2f2",
            "high": "#fff7ed",
            "medium": "#fefce8",
            "low": "#eff6ff",
            "info": "#f9fafb",
        }

        # 评分颜色
        if score >= 8:
            score_color = "#16a34a"  # 绿色
        elif score >= 6:
            score_color = "#ca8a04"  # 黄色
        else:
            score_color = "#dc2626"  # 红色

        total = len(merged_results)
        # 生成时间用北京时间（UTC+8）显示，更符合用户预期
        tz_bj = datetime.timezone(datetime.timedelta(hours=8))
        now = datetime.datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M:%S (北京时间)")

        html_parts = [
            '<!DOCTYPE html>',
            '<html lang="zh-CN">',
            '<head>',
            '<meta charset="UTF-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
            '<title>代码审查报告</title>',
            '<style>',
            '  :root { color-scheme: light; }',
            '  * { margin: 0; padding: 0; box-sizing: border-box; }',
            '  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;',
            '         background: #f5f5f5; color: #1f2937; line-height: 1.6; }',
            '  .container { max-width: 1000px; margin: 0 auto; padding: 24px; }',
            '  .header { background: #fff; border-radius: 12px; padding: 32px; margin-bottom: 24px;',
            '            box-shadow: 0 1px 3px rgba(0,0,0,0.1); }',
            '  .header h1 { font-size: 24px; margin-bottom: 8px; }',
            '  .header .meta { color: #6b7280; font-size: 14px; }',
            '  .score-section { display: flex; align-items: center; gap: 24px; margin-top: 20px; }',
            '  .score-circle { width: 100px; height: 100px; border-radius: 50%; display: flex;',
            '                  align-items: center; justify-content: center; font-size: 36px;',
            '                  font-weight: 700; color: #fff; }',
            '  .summary-box { background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 24px;',
            '                 box-shadow: 0 1px 3px rgba(0,0,0,0.1); }',
            '  .summary-box h2 { font-size: 18px; margin-bottom: 12px; }',
            '  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));',
            '                gap: 12px; margin-bottom: 24px; }',
            '  .stat-card { background: #fff; border-radius: 8px; padding: 16px;',
            '              box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }',
            '  .stat-card .count { font-size: 28px; font-weight: 700; }',
            '  .stat-card .label { font-size: 13px; color: #6b7280; margin-top: 4px; }',
            '  .issues-section { background: #fff; border-radius: 12px; padding: 24px;',
            '                    box-shadow: 0 1px 3px rgba(0,0,0,0.1); }',
            '  .issues-section h2 { font-size: 18px; margin-bottom: 16px; }',
            '  .issue-item { border-radius: 8px; padding: 16px; margin-bottom: 12px; }',
            '  .issue-header { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }',
            '  .severity-badge { padding: 2px 8px; border-radius: 4px; font-size: 12px;',
            '                   font-weight: 600; color: #fff; white-space: nowrap; }',
            '  .issue-title { font-size: 15px; font-weight: 600; }',
            '  .issue-meta { font-size: 12px; color: #6b7280; margin-bottom: 8px; }',
            '  .issue-desc { font-size: 14px; margin-bottom: 8px; color: #374151; }',
            '  .issue-suggestion { font-size: 13px; color: #1d4ed8; background: #eff6ff;',
            '                      border-radius: 6px; padding: 10px 12px; }',
            '  .code-snippet { background: #1e293b; color: #e2e8f0; border-radius: 6px;',
            '                  padding: 12px; font-family: "Fira Code", "Cascadia Code", monospace;',
            '                  font-size: 13px; overflow-x: auto; margin-top: 8px;',
            '                  white-space: pre-wrap; word-break: break-all; }',
            '  .footer { text-align: center; padding: 24px; color: #9ca3af; font-size: 12px; }',
            '</style>',
            '</head>',
            '<body>',
            '<div class="container">',
            # Header
            '<div class="header">',
            '<h1>代码审查报告</h1>',
            f'<div class="meta">生成时间: {now}</div>',
            f'<div class="meta">任务 ID: {self._escape_html(task_id)}</div>',
            '<div class="score-section">',
            f'<div class="score-circle" style="background: {score_color};">{score}</div>',
            '<div>',
            f'<div style="font-size: 18px; font-weight: 600;">综合评分: {score}/10</div>',
            f'<div style="color: #6b7280; font-size: 14px;">共发现 {total} 个问题</div>',
            '</div>',
            '</div>',
            '</div>',
            # Summary
            '<div class="summary-box">',
            '<h2>审查摘要</h2>',
            f'<p>{self._escape_html(summary)}</p>',
            '</div>',
            # Statistics
            '<div class="stats-grid">',
            f'<div class="stat-card"><div class="count" style="color: #dc2626;">{severity_counts["critical"]}</div><div class="label">严重</div></div>',
            f'<div class="stat-card"><div class="count" style="color: #ea580c;">{severity_counts["high"]}</div><div class="label">高危</div></div>',
            f'<div class="stat-card"><div class="count" style="color: #ca8a04;">{severity_counts["medium"]}</div><div class="label">中危</div></div>',
            f'<div class="stat-card"><div class="count" style="color: #2563eb;">{severity_counts["low"]}</div><div class="label">低危</div></div>',
            f'<div class="stat-card"><div class="count" style="color: #6b7280;">{severity_counts["info"]}</div><div class="label">信息</div></div>',
            '</div>',
            # Agent breakdown
            '<div class="summary-box">',
            '<h2>各 Agent 发现统计</h2>',
            '<div class="stats-grid">',
        ]

        for agent, count in stats.get("by_agent", {}).items():
            html_parts.append(
                f'<div class="stat-card"><div class="count">{count}</div>'
                f'<div class="label">{self._escape_html(agent)}</div></div>'
            )

        html_parts.append('</div></div>')

        # Issue details
        html_parts.append('<div class="issues-section">')
        html_parts.append(f'<h2>问题详情 ({total})</h2>')

        if total == 0:
            html_parts.append(
                '<div style="text-align:center; padding: 40px; color: #16a34a;">'
                '未发现问题，代码质量良好！</div>'
            )
        else:
            for i, r in enumerate(merged_results):
                sev = r.get("severity", "info")
                color = severity_colors.get(sev, "#6b7280")
                bg = severity_bg.get(sev, "#f9fafb")
                title = r.get("title", "未命名问题")
                desc = r.get("description", "")
                suggestion = r.get("suggestion", "")
                code_snippet = r.get("code_snippet", "")
                file_path = r.get("file_path", "")
                line_start = r.get("line_start", 0)
                line_end = r.get("line_end", 0)
                category = r.get("category", "")
                agent_type = r.get("agent_type", "")

                html_parts.append(
                    f'<div class="issue-item" style="background: {bg};">'
                    f'<div class="issue-header">'
                    f'<span class="severity-badge" style="background: {color};">{self._escape_html(sev.upper())}</span>'
                    f'<span class="issue-title">{self._escape_html(title)}</span>'
                    f'</div>'
                    f'<div class="issue-meta">'
                    f'📁 {self._escape_html(file_path)}:{line_start}-{line_end} '
                    f'| 🏷️ {self._escape_html(category)} '
                    f'| 🤖 {self._escape_html(agent_type)}'
                    f'</div>'
                )

                if desc:
                    html_parts.append(
                        f'<div class="issue-desc">{self._escape_html(desc)}</div>'
                    )

                if suggestion:
                    html_parts.append(
                        f'<div class="issue-suggestion">💡 {self._escape_html(suggestion)}</div>'
                    )

                if code_snippet:
                    html_parts.append(
                        f'<div class="code-snippet">{self._escape_html(code_snippet)}</div>'
                    )

                html_parts.append('</div>')

        html_parts.append('</div>')

        # Footer
        html_parts.extend([
            '<div class="footer">',
            'Code Review Workbench — 智能代码审查与重构工坊',
            '</div>',
            '</div>',
            '</body>',
            '</html>',
        ])

        return "\n".join(html_parts)

    @staticmethod
    def _escape_html(text: str) -> str:
        """转义 HTML 特殊字符。"""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    # ---- 完整仲裁流程 ----

    async def arbitrate_full(
        self,
        style_results: list[dict],
        security_results: list[dict],
        architecture_results: list[dict],
        performance_results: list[dict],
        refactor_results: list[dict],
        task_id: str = "",
        collaboration_results: list[dict] | None = None,
    ) -> dict[str, Any]:
        """完整仲裁流程：合并 → 去重 → 排序 → 评分 → 摘要 → HTML 报告。

        Args:
            style_results: StyleChecker 结果
            security_results: SecurityAuditor 结果
            architecture_results: ArchitectureAnalyzer 结果
            performance_results: PerformanceProfiler 结果
            refactor_results: RefactorAdvisor 结果
            task_id: 任务 ID
            collaboration_results: 第二轮 Agent 协作的结果（可选）

        Returns:
            {
                "merged_results": list[dict],
                "severity_counts": dict,
                "score": float,
                "summary": str,
                "report_html": str,
                "stats": dict,
            }
        """
        # 步骤 1: 合并去重排序评分
        arbitrated = self.arbitrate(
            style_results=style_results,
            security_results=security_results,
            architecture_results=architecture_results,
            performance_results=performance_results,
            refactor_results=refactor_results,
            collaboration_results=collaboration_results or [],
        )

        merged_results = arbitrated["merged_results"]
        severity_counts = arbitrated["severity_counts"]
        category_counts = arbitrated["category_counts"]
        score = arbitrated["score"]
        stats = arbitrated["stats"]

        # 步骤 2: LLM 生成摘要
        summary = await self._generate_summary(
            merged_results=merged_results,
            severity_counts=severity_counts,
            score=score,
        )

        # 步骤 3: 生成 HTML 报告
        report_html = self.generate_html_report(
            merged_results=merged_results,
            severity_counts=severity_counts,
            category_counts=category_counts,
            score=score,
            summary=summary,
            stats=stats,
            task_id=task_id,
        )

        return {
            "merged_results": merged_results,
            "severity_counts": severity_counts,
            "category_counts": category_counts,
            "score": score,
            "summary": summary,
            "report_html": report_html,
            "stats": stats,
        }
