"""
Memory System — MemoryManager 集成

统一管理四层记忆体系：
- WorkingMemory: 当前审查上下文窗口
- EpisodicMemory: 跨会话审查历史
- SemanticMemory: 审查规则与最佳实践
- ProceduralMemory: 工具使用经验

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
        mm.new_session(max_tokens=4000)
        context = mm.get_system_context()
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

    # ---- 会话管理 ----

    def new_session(self, max_tokens: int = 4000) -> WorkingMemory:
        """创建新的工作记忆会话。

        Args:
            max_tokens: 最大 token 数

        Returns:
            WorkingMemory 实例
        """
        self._working = WorkingMemory(max_tokens=max_tokens)
        return self._working

    @property
    def working(self) -> WorkingMemory | None:
        """当前工作记忆实例。"""
        return self._working

    # ---- 系统上下文生成 ----

    def get_system_context(self) -> str:
        """聚合三层记忆生成可注入系统提示词的上下文文本。

        包含：
        - 语义记忆的规则和最佳实践
        - 程序性记忆的高频问题与修复经验
        - 情节记忆的最近审查记录

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

        # 情节记忆（最近 5 条）
        recent = self._episodic.retrieve_recent(5)
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
        await self._episodic.save_session(task_id, review_result, issues)

        # 更新程序性记忆
        self._procedural.record_batch(issues)

    # ---- 委托方法 ----

    def search_history(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """搜索审查历史。

        Args:
            query: 搜索关键词
            top_k: 返回条数

        Returns:
            匹配的审查记录
        """
        return self._episodic.search(query, top_k)

    def get_frequent_issues(self, top_k: int = 10) -> list[dict[str, Any]]:
        """获取历史最高频问题类型。"""
        return self._procedural.get_frequent_issues(top_k)

    def add_rule(self, rule: dict[str, Any]) -> None:
        """添加审查规则到语义记忆。"""
        self._semantic.add_rule(rule)

    def add_best_practice(self, practice: dict[str, Any]) -> None:
        """添加最佳实践到语义记忆。"""
        self._semantic.add_best_practice(practice)

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
