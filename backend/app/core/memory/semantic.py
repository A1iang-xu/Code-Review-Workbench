"""
Semantic Memory

长期语义记忆，存储审查规则、代码模式和最佳实践。
基于 JSON 文件持久化，可注入 LLM 提示词增强审查效果。
"""

import datetime
import json
from pathlib import Path
from typing import Any


class SemanticMemory:
    """语义记忆 — 长期知识积累。

    存储三个维度的知识：
    - rules: 审查规则（按分类和语言组织）
    - patterns: 代码模式（正例和反例）
    - best_practices: 最佳实践（含代码示例）

    Usage:
        sm = SemanticMemory(storage_path="./memory_data")
        sm.add_rule({"category": "security", "language": "python", ...})
        sm.add_best_practice({"title": "Use parameterized queries", ...})
        context = sm.get_prompt_context()
    """

    _STORAGE_FILE = "semantic_memory.json"

    def __init__(self, storage_path: str = "./memory_data"):
        self._storage_path = Path(storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._file_path = self._storage_path / self._STORAGE_FILE

        self._rules: list[dict[str, Any]] = []
        self._patterns: list[dict[str, Any]] = []
        self._best_practices: list[dict[str, Any]] = []

        self._load()

    # ---- 持久化 ----

    def _load(self) -> None:
        """从 JSON 文件加载语义记忆。"""
        if self._file_path.exists():
            try:
                with open(self._file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._rules = data.get("rules", [])
                    self._patterns = data.get("patterns", [])
                    self._best_practices = data.get("best_practices", [])
            except (json.JSONDecodeError, OSError):
                self._rules, self._patterns, self._best_practices = [], [], []

    def _save(self) -> None:
        """将语义记忆持久化到 JSON 文件。"""
        try:
            with open(self._file_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "rules": self._rules,
                        "patterns": self._patterns,
                        "best_practices": self._best_practices,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except OSError as e:
            print(f"[SemanticMemory] 保存失败: {e}")

    # ---- 添加知识 ----

    def add_rule(self, rule: dict[str, Any]) -> None:
        """添加审查规则。

        rule 格式:
        {
            "category": "security",      # 分类
            "language": "python",         # 适用语言
            "title": "...",               # 规则标题
            "description": "...",         # 规则描述
            "severity": "high",           # 默认严重等级
        }
        """
        if "timestamp" not in rule:
            rule["timestamp"] = datetime.datetime.utcnow().isoformat()
        self._rules.append(rule)
        self._save()

    def add_pattern(self, pattern: dict[str, Any]) -> None:
        """添加代码模式（正例或反例）。

        pattern 格式:
        {
            "name": "...",                # 模式名称
            "type": "positive|negative",  # 正例或反例
            "language": "python",
            "code": "...",                # 代码片段
            "description": "...",
        }
        """
        if "timestamp" not in pattern:
            pattern["timestamp"] = datetime.datetime.utcnow().isoformat()
        self._patterns.append(pattern)
        self._save()

    def add_best_practice(self, practice: dict[str, Any]) -> None:
        """添加最佳实践。

        practice 格式:
        {
            "title": "...",
            "category": "security",
            "language": "python",
            "description": "...",
            "bad_example": "...",   # 反面示例（可选）
            "good_example": "...",  # 正面示例（可选）
        }
        """
        if "timestamp" not in practice:
            practice["timestamp"] = datetime.datetime.utcnow().isoformat()
        self._best_practices.append(practice)
        self._save()

    # ---- 检索 ----

    def get_rules(
        self, category: str | None = None, language: str | None = None
    ) -> list[dict[str, Any]]:
        """按分类和语言筛选审查规则。

        Args:
            category: 规则分类（为 None 则不限）
            language: 适用语言（为 None 则不限）

        Returns:
            匹配的规则列表
        """
        results = []
        for rule in self._rules:
            if category and rule.get("category") != category:
                continue
            if language and rule.get("language") != language:
                continue
            results.append(rule)
        return results

    def get_patterns(
        self, pattern_type: str | None = None, language: str | None = None
    ) -> list[dict[str, Any]]:
        """按类型和语言筛选代码模式。

        Args:
            pattern_type: "positive" 或 "negative"
            language: 适用语言

        Returns:
            匹配的模式列表
        """
        results = []
        for pat in self._patterns:
            if pattern_type and pat.get("type") != pattern_type:
                continue
            if language and pat.get("language") != language:
                continue
            results.append(pat)
        return results

    def get_prompt_context(self) -> str:
        """生成可注入 LLM 提示词的上下文文本。

        包含最近 5 条最佳实践和最近 10 条自定义规则。

        Returns:
            格式化后的上下文文本
        """
        parts: list[str] = []

        # 最佳实践（最近 5 条）
        if self._best_practices:
            parts.append("## 最佳实践\n")
            recent_practices = sorted(
                self._best_practices,
                key=lambda p: p.get("timestamp", ""),
                reverse=True,
            )[:5]
            for i, bp in enumerate(recent_practices, 1):
                parts.append(
                    f"{i}. [{bp.get('category', 'general')}] {bp.get('title', '')}\n"
                    f"   {bp.get('description', '')}"
                )
                if bp.get("good_example"):
                    parts.append(f"\n   推荐写法:\n   ```\n   {bp['good_example']}\n   ```")
            parts.append("")

        # 自定义规则（最近 10 条）
        if self._rules:
            parts.append("## 自定义审查规则\n")
            recent_rules = sorted(
                self._rules,
                key=lambda r: r.get("timestamp", ""),
                reverse=True,
            )[:10]
            for i, rule in enumerate(recent_rules, 1):
                parts.append(
                    f"{i}. [{rule.get('severity', 'medium')}][{rule.get('category', 'general')}] "
                    f"{rule.get('title', '')}: {rule.get('description', '')}"
                )
            parts.append("")

        return "\n".join(parts) if parts else ""

    # ---- 属性 ----

    @property
    def stats(self) -> dict[str, int]:
        """各维度知识数量统计。"""
        return {
            "rules": len(self._rules),
            "patterns": len(self._patterns),
            "best_practices": len(self._best_practices),
        }
