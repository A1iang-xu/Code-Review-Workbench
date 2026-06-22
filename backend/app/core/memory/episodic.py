"""
Episodic Memory

跨会话的审查历史记忆，基于 JSON 文件持久化。
最大存储 100 条记录，支持检索和关键词搜索。
"""

import json
import os
import datetime
from pathlib import Path
from typing import Any


class EpisodicMemory:
    """情节记忆 — 跨会话的审查历史。

    每次审查完成后保存 episode 记录，包含摘要、评分、关键事实等。
    使用 JSON 文件持久化（后续迁移到 PostgreSQL + Milvus）。

    Usage:
        em = EpisodicMemory(storage_path="./memory_data")
        await em.save_session(task_id, review_result, issues)
        recent = em.retrieve_recent(10)
        results = em.search("SQL injection")
    """

    _MAX_EPISODES = 100
    _STORAGE_FILE = "episodic_memory.json"

    def __init__(self, storage_path: str = "./memory_data"):
        self._storage_path = Path(storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._file_path = self._storage_path / self._STORAGE_FILE
        self._episodes: list[dict[str, Any]] = []
        self._load()

    # ---- 持久化 ----

    def _load(self) -> None:
        """从 JSON 文件加载审查记录。"""
        if self._file_path.exists():
            try:
                with open(self._file_path, "r", encoding="utf-8") as f:
                    self._episodes = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._episodes = []

    def _save(self) -> None:
        """将审查记录持久化到 JSON 文件。"""
        try:
            # 限制最大记录数
            if len(self._episodes) > self._MAX_EPISODES:
                self._episodes = self._episodes[-self._MAX_EPISODES:]

            with open(self._file_path, "w", encoding="utf-8") as f:
                json.dump(self._episodes, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"[EpisodicMemory] 保存失败: {e}")

    # ---- 保存会话 ----

    async def save_session(
        self,
        task_id: str,
        review_result: dict[str, Any],
        issues: list[dict],
    ) -> dict[str, Any]:
        """保存审查会话记录。

        调用 LLM 生成审查摘要，提取关键事实，构建 episode 记录。

        Args:
            task_id: 审查任务 ID
            review_result: 包含 summary、score、stats 等字段的审查结果
            issues: 所有发现的问题列表

        Returns:
            保存的 episode 记录
        """
        # 生成摘要
        summary = review_result.get("summary", "")
        if not summary:
            summary = await self._summarize_session(issues)

        # 提取关键事实
        key_facts = self._extract_facts(issues)

        # 统计 top_categories
        category_counts: dict[str, int] = {}
        for issue in issues:
            cat = issue.get("category", "other")
            category_counts[cat] = category_counts.get(cat, 0) + 1

        top_categories = sorted(
            category_counts.items(), key=lambda x: -x[1]
        )[:5]

        episode = {
            "task_id": task_id,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "summary": summary,
            "key_facts": key_facts,
            "score": review_result.get("score", 0.0),
            "issue_count": len(issues),
            "repo_url": review_result.get("repo_url", ""),
            "top_categories": [
                {"category": cat, "count": cnt}
                for cat, cnt in top_categories
            ],
            "severity_counts": review_result.get("severity_counts", {}),
        }

        self._episodes.append(episode)
        self._save()
        return episode

    # ---- 摘要生成 ----

    async def _summarize_session(self, issues: list[dict]) -> str:
        """使用 LLM utility 模型将 Top 10 问题总结为 2-3 句摘要。

        Args:
            issues: 所有发现的问题列表

        Returns:
            2-3 句中文摘要
        """
        if not issues:
            return "代码审查完成，未发现任何问题。"

        # 按严重等级排序，取 Top 10
        severity_order = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
        sorted_issues = sorted(
            issues,
            key=lambda i: -severity_order.get(i.get("severity", "info"), 0),
        )[:10]

        top_titles = "\n".join(
            f"- [{i.get('severity', '?')}] {i.get('title', 'No title')}"
            for i in sorted_issues
        )

        try:
            from app.integrations.llm import LLMProvider

            response = await LLMProvider.utility(
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"以下是代码审查发现的前 10 个问题。"
                            f"请用 2-3 句中文总结本次审查的核心发现：\n\n{top_titles}"
                        ),
                    }
                ],
                max_tokens=200,
            )
            return (
                response.choices[0].message.content.strip()
                if response.choices
                else f"代码审查完成，共发现 {len(issues)} 个问题。"
            )
        except Exception:
            pass

        # 降级摘要
        return f"代码审查完成，共发现 {len(issues)} 个问题。"

    # ---- 关键事实提取 ----

    @staticmethod
    def _extract_facts(issues: list[dict]) -> list[str]:
        """从审查结果中提取 critical/high 级别的问题标题作为关键事实。

        Args:
            issues: 所有发现的问题列表

        Returns:
            关键事实列表（最多 10 条）
        """
        facts: list[str] = []

        for issue in issues:
            sev = issue.get("severity", "")
            if sev in ("critical", "high"):
                title = issue.get("title", "")
                if title:
                    facts.append(title)

        return facts[:10]

    # ---- 检索 ----

    def retrieve_recent(self, n: int = 10) -> list[dict[str, Any]]:
        """返回最近 N 条审查记录。

        Args:
            n: 返回的记录数

        Returns:
            最近 N 条 episode 记录
        """
        return self._episodes[-n:]

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """基于关键词匹配搜索相关审查记录。

        匹配规则：query 分词后，任意词出现在 summary 或 key_facts 中即匹配。
        按匹配度评分排序。

        Args:
            query: 搜索关键词
            top_k: 返回的记录数上限

        Returns:
            匹配的 episode 列表（按相关性排序）
        """
        keywords = query.lower().split()
        scored: list[tuple[int, dict]] = []

        for ep in self._episodes:
            score = 0
            searchable_text = (
                ep.get("summary", "").lower()
                + " "
                + " ".join(ep.get("key_facts", [])).lower()
            )
            for kw in keywords:
                score += searchable_text.count(kw)
            if score > 0:
                scored.append((score, ep))

        scored.sort(key=lambda x: -x[0])
        return [ep for _, ep in scored[:top_k]]

    # ---- 属性 ----

    @property
    def count(self) -> int:
        """已存储的审查记录数。"""
        return len(self._episodes)
