"""
Memory System — MemoryManager 集成

统一管理四层记忆体系：
- WorkingMemory: 当前审查上下文窗口（内存）
- EpisodicMemory: 跨会话审查历史（PostgreSQL）
- SemanticMemory: 审查规则与最佳实践（pgvector）
- ProceduralMemory: 工具使用经验（JSON 文件）

作为单例运行，提供统一的新建会话、获取上下文、保存会话接口。
"""

from pathlib import Path
from typing import Any

from app.core.memory.working import WorkingMemory
from app.core.memory.episodic import EpisodicMemory
from app.core.memory.semantic import SemanticMemory
from app.core.memory.procedural import ProceduralMemory


class MemoryManager:
    """记忆系统管理器（单例模式）。

    统一管理四层记忆，对外暴露高层操作。

    Usage:
        mm = MemoryManager(storage_path="./memory_data")
        await mm.async_refresh()  # 启动时从 DB 加载缓存
        mm.new_session(max_tokens=4000)
        context = mm.get_system_context()
        context = await mm.get_context_for_review(language="python", categories=["security"])
        await mm.save_session(task_id, review_result, issues)
    """

    _instance: "MemoryManager | None" = None

    def __new__(
        cls, storage_path: str = "./memory_data"
    ) -> "MemoryManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, storage_path: str = "./memory_data"):
        if self._initialized:
            return
        self._initialized = True

        self._storage_path = Path(storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self._working: WorkingMemory | None = None
        self._episodic = EpisodicMemory(storage_path)
        self._semantic = SemanticMemory(storage_path)
        self._procedural = ProceduralMemory(storage_path)

        # 缓存最近审查记录（供同步 get_system_context 使用）
        self._recent_episodes_cache: list[dict[str, Any]] = []
        self._episodes_cache_loaded = False

    # ---- 会话管理 ----

    def new_session(self, max_tokens: int = 4000) -> WorkingMemory:
        """创建新的工作记忆会话。"""
        self._working = WorkingMemory(max_tokens=max_tokens)
        return self._working

    @property
    def working(self) -> WorkingMemory | None:
        """当前工作记忆实例。"""
        return self._working

    # ---- 异步初始化 ----

    async def async_refresh(self) -> None:
        """从数据库加载语义记忆缓存和最近审查记录。

        在应用启动时调用，确保 get_system_context() 能返回有效数据。
        """
        # 加载语义记忆缓存
        await self._semantic.async_refresh()

        # 加载最近审查记录缓存
        try:
            self._recent_episodes_cache = await self._episodic.retrieve_recent(5)
            self._episodes_cache_loaded = True
        except Exception as e:
            print("[MemoryManager] 加载最近审查记录失败: {}".format(e))

    # ---- 系统上下文生成 ----

    def get_system_context(self) -> str:
        """聚合三层记忆生成可注入系统提示词的上下文文本。

        包含：
        - 语义记忆的规则和最佳实践
        - 程序性记忆的高频问题与修复经验
        - 情节记忆的最近审查记录（从缓存读取）

        Returns:
            格式化的上下文文本，可直接拼接到系统提示词末尾
        """
        parts: list[str] = []

        # 语义记忆
        semantic_ctx = self._semantic.get_prompt_context()
        if semantic_ctx:
            parts.append(semantic_ctx)

        # 程序性记忆
        procedural_ctx = self._procedural.get_prompt_context()
        if procedural_ctx:
            parts.append(procedural_ctx)

        # 情节记忆（从缓存读取，避免阻塞）
        recent = self._recent_episodes_cache
        if recent:
            parts.append("## 最近审查历史\n")
            for ep in recent:
                parts.append(
                    f"- [{ep.get('timestamp', '')[:10]}] 评分 {ep.get('score', '?')}/10, "
                    f"{ep.get('issue_count', 0)} 个问题"
                )
                summary = ep.get("summary", "")
                if summary and len(summary) > 100:
                    summary = summary[:100] + "..."
                if summary:
                    parts.append(f"  {summary}")
            parts.append("")

        return "\n".join(parts) if parts else ""

    async def get_context_for_review(
        self,
        language: str = "auto",
        categories: list[str] | None = None,
        file_paths: list[str] | None = None,
    ) -> str:
        """为当前审查生成针对性的记忆上下文。

        根据审查的语言和问题分类，从语义记忆中检索相关规则和最佳实践，
        让记忆真正影响后续审查。

        Args:
            language: 当前审查的编程语言
            categories: 预期的问题分类（如 ["security", "performance"]）
            file_paths: 当前审查的文件路径列表（用于检索相关历史）

        Returns:
            针对性上下文文本，包含相关规则、最佳实践和历史经验
        """
        parts: list[str] = []

        # 1. 基础系统上下文（语义 + 程序性 + 最近历史）
        base_ctx = self.get_system_context()
        if base_ctx:
            parts.append(base_ctx)

        # 2. 按语言筛选相关规则
        if language and language != "auto":
            lang_rules = self._semantic.get_rules(language=language)
            if lang_rules:
                parts.append(f"## {language} 语言专属规则\n")
                for i, rule in enumerate(lang_rules[:5], 1):
                    parts.append(
                        f"{i}. [{rule.get('severity', 'medium')}] "
                        f"{rule.get('title', '')}: {rule.get('description', '')}"
                    )
                parts.append("")

        # 3. 按分类检索相关最佳实践
        if categories:
            for cat in categories[:3]:  # 最多 3 个分类
                practices = [
                    bp for bp in self._semantic._best_practices
                    if bp.get("category") == cat
                ][:3]
                if practices:
                    parts.append(f"## {cat} 相关最佳实践\n")
                    for i, bp in enumerate(practices, 1):
                        parts.append(
                            f"{i}. {bp.get('title', '')}\n"
                            f"   {bp.get('description', '')}"
                        )
                        if bp.get("good_example"):
                            parts.append(f"   推荐写法: {bp['good_example'][:200]}")
                    parts.append("")

        # 4. 检索相关历史审查（基于文件路径或分类）
        if categories:
            query = " ".join(categories[:2])
            related = await self._episodic.search(query, top_k=3)
            if related:
                parts.append("## 相关历史审查\n")
                for ep in related:
                    parts.append(
                        f"- [{ep.get('timestamp', '')[:10]}] 评分 {ep.get('score', '?')}/10, "
                        f"{ep.get('issue_count', 0)} 个问题: {ep.get('summary', '')[:120]}"
                    )
                parts.append("")

        # 5. 高频问题提醒（基于程序性记忆）
        frequent = self._procedural.get_frequent_issues(5)
        if frequent:
            parts.append("## 历史高频问题提醒\n")
            for item in frequent:
                parts.append(
                    f"- [{item['severity']}] {item['issue_type']} "
                    f"(历史发现 {item['count']} 次)"
                )
            parts.append("")

        return "\n".join(parts) if parts else ""

    # ---- 审查完成后的记忆保存 ----

    async def save_session(
        self,
        task_id: str,
        review_result: dict[str, Any],
        issues: list[dict],
    ) -> None:
        """审查完成后保存情节记忆和程序性记忆。

        Args:
            task_id: 审查任务 ID
            review_result: 审查结果
            issues: 所有发现的问题列表
        """
        # 保存情节记忆
        episode = await self._episodic.save_session(task_id, review_result, issues)

        # 更新最近审查缓存
        self._recent_episodes_cache.insert(0, episode)
        if len(self._recent_episodes_cache) > 5:
            self._recent_episodes_cache = self._recent_episodes_cache[:5]

        # 更新程序性记忆
        self._procedural.record_batch(issues)

    # ---- 委托方法 ----

    async def search_history(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """搜索审查历史。"""
        return await self._episodic.search(query, top_k)

    def get_frequent_issues(self, top_k: int = 10) -> list[dict[str, Any]]:
        """获取历史最高频问题类型。"""
        return self._procedural.get_frequent_issues(top_k)

    def add_rule(self, rule: dict[str, Any]) -> None:
        """添加审查规则到语义记忆。"""
        self._semantic.add_rule(rule)

    def add_best_practice(self, practice: dict[str, Any]) -> None:
        """添加最佳实践到语义记忆。"""
        self._semantic.add_best_practice(practice)

    async def semantic_search(
        self, query: str, top_k: int = 5, language: str | None = None
    ) -> list[dict[str, Any]]:
        """基于向量相似度搜索语义记忆。"""
        return await self._semantic.semantic_search(query, top_k, language)

    # ---- 属性 ----

    @property
    def stats(self) -> dict[str, Any]:
        """记忆系统统计。"""
        return {
            "episodic_count": self._episodic.count,
            "semantic": self._semantic.stats,
            "procedural_issue_types": self._procedural.issue_types_count,
            "procedural_total_findings": self._procedural.total_findings,
        }
