"""
Procedural Memory

工具使用经验和修复模式积累。
基于 JSON 文件持久化，自动统计高频问题类型和最佳修复建议。
"""

import datetime
import json
from pathlib import Path
from typing import Any


class ProceduralMemory:
    """程序性记忆 — 经验积累。

    记录每种问题类型的发现次数和修复建议，
    自动推荐高频问题的最佳实践。

    Usage:
        pm = ProceduralMemory(storage_path="./memory_data")
        pm.record_finding("sql_injection", "User input in SQL", "Use parameterized queries", "critical")
        pm.record_batch(issues)
        frequent = pm.get_frequent_issues(10)
        suggestions = pm.get_suggestions_for("sql_injection")
    """

    _STORAGE_FILE = "procedural_memory.json"

    def __init__(self, storage_path: str = "./memory_data"):
        self._storage_path = Path(storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._file_path = self._storage_path / self._STORAGE_FILE

        # {issue_type: {"count": int, "suggestions": {suggestion: count}, "severity": str, "last_seen": str}}
        self._findings: dict[str, dict[str, Any]] = {}

        self._load()

    # ---- 持久化 ----

    def _load(self) -> None:
        """从 JSON 文件加载程序性记忆。"""
        if self._file_path.exists():
            try:
                with open(self._file_path, "r", encoding="utf-8") as f:
                    self._findings = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._findings = {}

    def _save(self) -> None:
        """将程序性记忆持久化到 JSON 文件。"""
        try:
            with open(self._file_path, "w", encoding="utf-8") as f:
                json.dump(self._findings, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"[ProceduralMemory] 保存失败: {e}")

    # ---- 记录发现 ----

    def record_finding(
        self,
        issue_type: str,
        title: str,
        suggestion: str,
        severity: str = "medium",
    ) -> None:
        """记录一个审查发现及其修复建议。

        自动累加出现次数，合并相同建议。

        Args:
            issue_type: 问题类型（如 "sql_injection"）
            title: 问题标题
            suggestion: 修复建议
            severity: 严重等级
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if issue_type not in self._findings:
            self._findings[issue_type] = {
                "count": 0,
                "titles": {},
                "suggestions": {},
                "severity": severity,
                "first_seen": now,
                "last_seen": now,
            }

        entry = self._findings[issue_type]
        entry["count"] += 1
        entry["last_seen"] = now

        # 记录标题（去重计数）
        if title:
            entry["titles"][title] = entry["titles"].get(title, 0) + 1

        # 记录建议（按出现次数排序）
        if suggestion:
            entry["suggestions"][suggestion] = entry["suggestions"].get(suggestion, 0) + 1

        # 更新严重等级（取最高）
        severity_order = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
        current_weight = severity_order.get(entry["severity"], 0)
        new_weight = severity_order.get(severity, 0)
        if new_weight > current_weight:
            entry["severity"] = severity

        self._save()

    def record_batch(self, issues: list[dict]) -> int:
        """批量记录审查发现。

        Args:
            issues: 问题列表，每个问题至少含 category、title、suggestion、severity

        Returns:
            记录的问题数量
        """
        count = 0
        for issue in issues:
            self.record_finding(
                issue_type=issue.get("category", "other"),
                title=issue.get("title", ""),
                suggestion=issue.get("suggestion", ""),
                severity=issue.get("severity", "medium"),
            )
            count += 1
        return count

    # ---- 检索 ----

    def get_frequent_issues(self, top_k: int = 10) -> list[dict[str, Any]]:
        """按出现次数降序返回最高频的问题类型。

        Args:
            top_k: 返回的记录数

        Returns:
            最高频问题列表，每项含 issue_type、count、severity、top_titles
        """
        sorted_issues = sorted(
            self._findings.items(), key=lambda x: -x[1]["count"]
        )[:top_k]

        return [
            {
                "issue_type": issue_type,
                "count": entry["count"],
                "severity": entry["severity"],
                "top_titles": sorted(
                    entry["titles"].items(), key=lambda x: -x[1]
                )[:3],
                "last_seen": entry["last_seen"],
            }
            for issue_type, entry in sorted_issues
        ]

    def get_suggestions_for(self, issue_type: str) -> list[dict[str, Any]]:
        """获取某类问题的最佳修复建议（按出现次数排序）。

        Args:
            issue_type: 问题类型

        Returns:
            修复建议列表，每项含 suggestion 和 count
        """
        entry = self._findings.get(issue_type, {})
        suggestions = entry.get("suggestions", {})

        sorted_suggestions = sorted(
            suggestions.items(), key=lambda x: -x[1]
        )

        return [
            {"suggestion": suggestion, "count": count}
            for suggestion, count in sorted_suggestions
        ]

    # ---- 获取上下文 ----

    def get_prompt_context(self) -> str:
        """生成可注入 LLM 提示词的上下文文本。

        包含最高频的 10 种问题类型及其最佳修复建议。

        Returns:
            格式化后的上下文文本
        """
        frequent = self.get_frequent_issues(10)

        if not frequent:
            return ""

        parts = ["## 历史高频问题与修复经验\n"]

        for i, item in enumerate(frequent, 1):
            parts.append(f"{i}. [{item['severity']}] {item['issue_type']} (发现 {item['count']} 次)")

            # 最佳修复建议
            suggestions = self.get_suggestions_for(item["issue_type"])
            if suggestions:
                top_suggestion = suggestions[0]["suggestion"]
                if len(top_suggestion) > 150:
                    top_suggestion = top_suggestion[:150] + "..."
                parts.append(f"   推荐修复: {top_suggestion}")

        parts.append("")
        return "\n".join(parts)

    # ---- 属性 ----

    @property
    def issue_types_count(self) -> int:
        """已记录的问题类型数量。"""
        return len(self._findings)

    @property
    def total_findings(self) -> int:
        """总发现数量。"""
        return sum(entry["count"] for entry in self._findings.values())
