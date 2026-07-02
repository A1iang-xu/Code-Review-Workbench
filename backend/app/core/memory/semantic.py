"""
Semantic Memory

长期语义记忆，存储审查规则、代码模式和最佳实践。
基于 PostgreSQL + pgvector 持久化，支持向量语义检索。

替代原有的 JSON 文件存储。为兼容同步调用（get_system_context），
维护内存缓存，通过 async_refresh() 从数据库刷新。
"""

import datetime
from typing import Any


class SemanticMemory:
    """语义记忆 — 长期知识积累。

    存储三个维度的知识：
    - rules: 审查规则（按分类和语言组织）
    - patterns: 代码模式（正例和反例）
    - best_practices: 最佳实践（含代码示例）

    使用 PostgreSQL 持久化 + pgvector 向量检索。
    内存缓存用于同步访问场景（如 get_prompt_context）。

    Usage:
        sm = SemanticMemory()
        await sm.async_refresh()  # 从 DB 加载缓存
        sm.add_rule({"category": "security", "language": "python", ...})
        context = sm.get_prompt_context()
        results = await sm.semantic_search("SQL injection prevention", top_k=5)
    """

    def __init__(self, storage_path: str = "./memory_data"):
        """初始化语义记忆。

        Args:
            storage_path: 保留参数（兼容旧接口），实际使用 PostgreSQL
        """
        self._storage_path = storage_path

        # 内存缓存（供同步 get_prompt_context 使用）
        self._rules: list[dict[str, Any]] = []
        self._patterns: list[dict[str, Any]] = []
        self._best_practices: list[dict[str, Any]] = []
        self._cache_loaded = False

    # ---- 缓存刷新 ----

    async def async_refresh(self) -> None:
        """从 PostgreSQL 加载所有语义记忆到内存缓存。

        在应用启动时或添加新知识后调用。
        """
        try:
            from sqlalchemy import select
            from app.models import async_session_factory
            from app.models.memory import SemanticMemoryRecord

            self._rules = []
            self._patterns = []
            self._best_practices = []

            async with async_session_factory() as session:
                result = await session.execute(
                    select(SemanticMemoryRecord).order_by(
                        SemanticMemoryRecord.timestamp.desc()
                    )
                )
                records = result.scalars().all()

                for record in records:
                    item = self._record_to_dict(record)
                    ktype = record.knowledge_type
                    if ktype == "rule":
                        self._rules.append(item)
                    elif ktype == "pattern":
                        self._patterns.append(item)
                    elif ktype == "best_practice":
                        self._best_practices.append(item)

                self._cache_loaded = True
        except Exception as e:
            print("[SemanticMemory] async_refresh 失败: {}".format(e))
            # 尝试从 JSON 文件降级加载
            self._load_from_json_fallback()

    def _load_from_json_fallback(self) -> None:
        """JSON 文件降级加载（兼容旧数据）。"""
        import json
        from pathlib import Path

        file_path = Path(self._storage_path) / "semantic_memory.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._rules = data.get("rules", [])
                    self._patterns = data.get("patterns", [])
                    self._best_practices = data.get("best_practices", [])
                    self._cache_loaded = True
            except (json.JSONDecodeError, OSError):
                pass

    # ---- 添加知识 ----

    def add_rule(self, rule: dict[str, Any]) -> None:
        """添加审查规则到内存缓存和 PostgreSQL。"""
        if "timestamp" not in rule:
            rule["timestamp"] = datetime.datetime.utcnow().isoformat()
        self._rules.append(rule)
        self._persist_async("rule", rule)

    def add_pattern(self, pattern: dict[str, Any]) -> None:
        """添加代码模式（正例或反例）。"""
        if "timestamp" not in pattern:
            pattern["timestamp"] = datetime.datetime.utcnow().isoformat()
        self._patterns.append(pattern)
        self._persist_async("pattern", pattern)

    def add_best_practice(self, practice: dict[str, Any]) -> None:
        """添加最佳实践。"""
        if "timestamp" not in practice:
            practice["timestamp"] = datetime.datetime.utcnow().isoformat()
        self._best_practices.append(practice)
        self._persist_async("best_practice", practice)

    def _persist_async(self, knowledge_type: str, data: dict[str, Any]) -> None:
        """异步写入 PostgreSQL（fire-and-forget）。

        使用 asyncio.create_task 在后台执行，不阻塞调用方。
        同时生成 embedding 向量写入 embedding 列，供 pgvector 语义检索使用。
        """
        import asyncio

        async def _write():
            try:
                from app.models import async_session_factory
                from app.models.memory import SemanticMemoryRecord

                # 生成 embedding 向量（基于 title + description 拼接文本）
                embed_text = "{} {}".format(
                    data.get("title", ""), data.get("description", "")
                ).strip()
                embedding = None
                if embed_text:
                    try:
                        embedding = await self._generate_embedding(embed_text)
                    except Exception as emb_e:
                        print("[SemanticMemory] embedding 生成失败，该条记录将无法被向量检索: {}".format(emb_e))

                async with async_session_factory() as session:
                    record = SemanticMemoryRecord(
                        knowledge_type=knowledge_type,
                        category=data.get("category"),
                        language=data.get("language"),
                        title=data.get("title", ""),
                        description=data.get("description"),
                        severity=data.get("severity"),
                        good_example=data.get("good_example"),
                        bad_example=data.get("bad_example"),
                        extra_data=data,
                        embedding=embedding,
                    )
                    session.add(record)
                    await session.commit()
            except Exception as e:
                print("[SemanticMemory] PostgreSQL 写入失败: {}".format(e))

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_write())
            else:
                loop.run_until_complete(_write())
        except Exception as e:
            print("[SemanticMemory] _persist_async 失败: {}".format(e))

    # ---- 检索 ----

    def get_rules(
        self, category: str | None = None, language: str | None = None
    ) -> list[dict[str, Any]]:
        """按分类和语言筛选审查规则（从内存缓存）。"""
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
        """按类型和语言筛选代码模式（从内存缓存）。"""
        results = []
        for pat in self._patterns:
            if pattern_type and pat.get("type") != pattern_type:
                continue
            if language and pat.get("language") != language:
                continue
            results.append(pat)
        return results

    async def semantic_search(
        self, query: str, top_k: int = 5, language: str | None = None
    ) -> list[dict[str, Any]]:
        """基于向量相似度搜索语义记忆。

        使用 pgvector 进行近似最近邻搜索，找到与查询最相关的知识。

        Args:
            query: 搜索查询文本
            top_k: 返回的记录数上限
            language: 过滤语言（可选）

        Returns:
            匹配的知识列表（按相似度排序）
        """
        try:
            from sqlalchemy import select, text
            from app.models import async_session_factory
            from app.models.memory import SemanticMemoryRecord

            # 生成查询向量（使用 embedding 模型）
            query_embedding = await self._generate_embedding(query)
            if query_embedding is None:
                # embedding 不可用，降级到关键词搜索
                return self._keyword_search(query, top_k, language)

            # pgvector 余弦相似度搜索
            # 使用 <=> 操作符（余弦距离），转换为相似度
            sql = text("""
                SELECT id, knowledge_type, category, language, title, description,
                       severity, good_example, bad_example, metadata, timestamp,
                       1 - (embedding <=> :embedding) as similarity
                FROM semantic_memories
                WHERE embedding IS NOT NULL
                {lang_filter}
                ORDER BY embedding <=> :embedding
                LIMIT :top_k
            """.format(
                lang_filter="AND language = :language" if language else ""
            ))

            params = {"embedding": str(query_embedding), "top_k": top_k}
            if language:
                params["language"] = language

            async with async_session_factory() as session:
                result = await session.execute(sql, params)
                rows = result.fetchall()
                return [self._row_to_dict(row) for row in rows]
        except Exception as e:
            print("[SemanticMemory] semantic_search 失败，降级到关键词搜索: {}".format(e))
            return self._keyword_search(query, top_k, language)

    def _keyword_search(
        self, query: str, top_k: int = 5, language: str | None = None
    ) -> list[dict[str, Any]]:
        """关键词搜索降级方案。"""
        keywords = query.lower().split()
        all_items = self._rules + self._patterns + self._best_practices
        scored: list[tuple[int, dict]] = []

        for item in all_items:
            if language and item.get("language") != language:
                continue
            searchable = (
                item.get("title", "").lower() + " " + item.get("description", "").lower()
            )
            score = sum(searchable.count(kw) for kw in keywords)
            if score > 0:
                scored.append((score, item))

        scored.sort(key=lambda x: -x[0])
        return [item for _, item in scored[:top_k]]

    async def _generate_embedding(self, text: str) -> list[float] | None:
        """使用 LLM embedding 模型生成文本向量。

        Args:
            text: 输入文本

        Returns:
            向量列表，失败时返回 None（调用方据此降级到关键词搜索）
        """
        try:
            from app.integrations.llm import LLMProvider

            return await LLMProvider.embedding(text)
        except Exception as e:
            # embedding 不可用不阻断主流程，仅记录原因，由调用方降级
            print("[SemanticMemory] embedding 生成失败，降级到关键词搜索: {}".format(e))
            return None

    # ---- 上下文生成 ----

    def get_prompt_context(self) -> str:
        """生成可注入 LLM 提示词的上下文文本（从内存缓存）。

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

    # ---- 转换辅助 ----

    @staticmethod
    def _record_to_dict(record) -> dict[str, Any]:
        """将 ORM 记录转换为字典。"""
        return {
            "knowledge_type": record.knowledge_type,
            "category": record.category,
            "language": record.language,
            "title": record.title,
            "description": record.description or "",
            "severity": record.severity,
            "good_example": record.good_example,
            "bad_example": record.bad_example,
            "timestamp": record.timestamp.isoformat() if record.timestamp else "",
        }

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        """将 SQL 行转换为字典。"""
        return {
            "knowledge_type": row.knowledge_type,
            "category": row.category,
            "language": row.language,
            "title": row.title,
            "description": row.description or "",
            "severity": row.severity,
            "good_example": row.good_example,
            "bad_example": row.bad_example,
            "similarity": float(row.similarity) if row.similarity else 0.0,
        }

    # ---- 属性 ----

    @property
    def stats(self) -> dict[str, int]:
        """各维度知识数量统计（从内存缓存）。"""
        return {
            "rules": len(self._rules),
            "patterns": len(self._patterns),
            "best_practices": len(self._best_practices),
        }
