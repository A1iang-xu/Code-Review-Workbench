"""
Episodic Memory

跨会话的审查历史记忆，基于 PostgreSQL 持久化。
替代原有的 JSON 文件存储，支持跨进程共享和高效查询。

最大存储 100 条记录（自动清理旧记录），支持检索和关键词搜索。
"""

import datetime
from typing import Any


class EpisodicMemory:
    """情节记忆 — 跨会话的审查历史。

    每次审查完成后保存 episode 记录到 PostgreSQL，
    包含摘要、评分、关键事实等。

    Usage:
        em = EpisodicMemory()
        await em.save_session(task_id, review_result, issues)
        recent = await em.retrieve_recent(10)
        results = await em.search("SQL injection")
    """

    _MAX_EPISODES = 100

    def __init__(self, storage_path: str = "./memory_data"):
        """初始化情节记忆。

        Args:
            storage_path: 保留参数（兼容旧接口），实际使用 PostgreSQL
        """
        # storage_path 保留用于向后兼容，实际存储在 PostgreSQL
        self._storage_path = storage_path

    # ---- 保存会话 ----

    async def save_session(
        self,
        task_id: str,
        review_result: dict[str, Any],
        issues: list[dict],
    ) -> dict[str, Any]:
        """保存审查会话记录到 PostgreSQL。

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

        episode_data = {
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

        # 写入 PostgreSQL
        try:
            from app.models import async_session_factory
            from app.models.memory import EpisodicMemoryRecord

            async with async_session_factory() as session:
                record = EpisodicMemoryRecord(
                    task_id=task_id,
                    summary=summary,
                    key_facts=key_facts,
                    score=review_result.get("score", 0.0),
                    issue_count=len(issues),
                    repo_url=review_result.get("repo_url", ""),
                    top_categories=[
                        {"category": cat, "count": cnt}
                        for cat, cnt in top_categories
                    ],
                    severity_counts=review_result.get("severity_counts", {}),
                )
                session.add(record)
                await session.commit()

                # 清理旧记录（超过上限时删除最旧的）
                await self._cleanup_old_records(session)
        except Exception as e:
            print("[EpisodicMemory] PostgreSQL 写入失败，降级到内存: {}".format(e))
            # 降级到内存列表
            if not hasattr(self, "_fallback_episodes"):
                self._fallback_episodes = []
            self._fallback_episodes.append(episode_data)
            if len(self._fallback_episodes) > self._MAX_EPISODES:
                self._fallback_episodes = self._fallback_episodes[-self._MAX_EPISODES:]

        return episode_data

    async def _cleanup_old_records(self, session) -> None:
        """清理超过上限的旧记录。"""
        try:
            from sqlalchemy import select, func, delete
            from app.models.memory import EpisodicMemoryRecord

            # 统计总数
            count_result = await session.execute(
                select(func.count(EpisodicMemoryRecord.id))
            )
            total = count_result.scalar() or 0

            if total > self._MAX_EPISODES:
                # 找到需要保留的最近 N 条的时间戳分界点
                cutoff_result = await session.execute(
                    select(EpisodicMemoryRecord.timestamp)
                    .order_by(EpisodicMemoryRecord.timestamp.desc())
                    .offset(self._MAX_EPISODES - 1)
                    .limit(1)
                )
                cutoff_ts = cutoff_result.scalar_one_or_none()
                if cutoff_ts:
                    # 删除分界点之前的记录
                    await session.execute(
                        delete(EpisodicMemoryRecord).where(
                            EpisodicMemoryRecord.timestamp < cutoff_ts
                        )
                    )
                    await session.commit()
        except Exception as e:
            print("[EpisodicMemory] 清理旧记录失败: {}".format(e))

    # ---- 摘要生成 ----

    async def _summarize_session(self, issues: list[dict]) -> str:
        """使用 LLM utility 模型将 Top 10 问题总结为 2-3 句摘要。"""
        if not issues:
            return "代码审查完成，未发现任何问题。"

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

        return f"代码审查完成，共发现 {len(issues)} 个问题。"

    # ---- 关键事实提取 ----

    @staticmethod
    def _extract_facts(issues: list[dict]) -> list[str]:
        """从审查结果中提取 critical/high 级别的问题标题作为关键事实。"""
        facts: list[str] = []
        for issue in issues:
            sev = issue.get("severity", "")
            if sev in ("critical", "high"):
                title = issue.get("title", "")
                if title:
                    facts.append(title)
        return facts[:10]

    # ---- 检索 ----

    async def retrieve_recent(self, n: int = 10) -> list[dict[str, Any]]:
        """返回最近 N 条审查记录。

        优先从 PostgreSQL 查询，降级到内存。
        """
        try:
            from sqlalchemy import select
            from app.models import async_session_factory
            from app.models.memory import EpisodicMemoryRecord

            async with async_session_factory() as session:
                result = await session.execute(
                    select(EpisodicMemoryRecord)
                    .order_by(EpisodicMemoryRecord.timestamp.desc())
                    .limit(n)
                )
                records = result.scalars().all()
                return [self._record_to_dict(r) for r in records]
        except Exception as e:
            print("[EpisodicMemory] PostgreSQL 查询失败，降级到内存: {}".format(e))
            if hasattr(self, "_fallback_episodes"):
                return self._fallback_episodes[-n:]
            return []

    async def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """基于关键词匹配搜索相关审查记录。

        匹配规则：query 分词后，任意词出现在 summary 中即匹配。
        按匹配度评分排序。

        Args:
            query: 搜索关键词
            top_k: 返回的记录数上限

        Returns:
            匹配的 episode 列表（按相关性排序）
        """
        try:
            from sqlalchemy import select, or_
            from app.models import async_session_factory
            from app.models.memory import EpisodicMemoryRecord

            keywords = query.lower().split()
            conditions = []
            for kw in keywords:
                conditions.append(
                    EpisodicMemoryRecord.summary.ilike(f"%{kw}%")
                )

            async with async_session_factory() as session:
                if conditions:
                    result = await session.execute(
                        select(EpisodicMemoryRecord)
                        .where(or_(*conditions))
                        .order_by(EpisodicMemoryRecord.timestamp.desc())
                        .limit(top_k)
                    )
                else:
                    result = await session.execute(
                        select(EpisodicMemoryRecord)
                        .order_by(EpisodicMemoryRecord.timestamp.desc())
                        .limit(top_k)
                    )
                records = result.scalars().all()
                return [self._record_to_dict(r) for r in records]
        except Exception as e:
            print("[EpisodicMemory] PostgreSQL 搜索失败，降级到内存: {}".format(e))
            # 降级到内存：在 _fallback_episodes 中搜索
            if hasattr(self, "_fallback_episodes"):
                keywords = query.lower().split()
                matched = []
                for ep in self._fallback_episodes:
                    summary = (ep.get("summary", "") or "").lower()
                    if any(kw in summary for kw in keywords):
                        matched.append(ep)
                return matched[-top_k:]
            return []

    @staticmethod
    def _record_to_dict(record) -> dict[str, Any]:
        """将 ORM 记录转换为字典。"""
        return {
            "task_id": record.task_id,
            "timestamp": record.timestamp.isoformat() if record.timestamp else "",
            "summary": record.summary or "",
            "key_facts": record.key_facts or [],
            "score": record.score or 0.0,
            "issue_count": record.issue_count or 0,
            "repo_url": record.repo_url or "",
            "top_categories": record.top_categories or [],
            "severity_counts": record.severity_counts or {},
        }

    # ---- 属性 ----

    @property
    def count(self) -> int:
        """已存储的审查记录数（同步降级版，优先用 async_count）。"""
        # 同步方法无法查 DB，返回 0 或内存计数
        if hasattr(self, "_fallback_episodes"):
            return len(self._fallback_episodes)
        return 0

    async def async_count(self) -> int:
        """异步获取已存储的审查记录数。"""
        try:
            from sqlalchemy import select, func
            from app.models import async_session_factory
            from app.models.memory import EpisodicMemoryRecord

            async with async_session_factory() as session:
                result = await session.execute(
                    select(func.count(EpisodicMemoryRecord.id))
                )
                return result.scalar() or 0
        except Exception:
            if hasattr(self, "_fallback_episodes"):
                return len(self._fallback_episodes)
            return 0
