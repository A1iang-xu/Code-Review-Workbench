"""
Skill 系统核心模块

提供可插拔的 Skill 架构：
- SkillCategory: 技能分类枚举
- SkillMetadata / SkillResult: 数据类
- BaseSkill: 抽象基类
- SkillRegistry: 单例注册中心
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


# ============================================================
# 枚举与数据类
# ============================================================

class SkillCategory(str, Enum):
    """Skill 分类枚举。"""
    STATIC_ANALYSIS = "static_analysis"
    PATTERN_MATCH = "pattern_match"
    SECURITY = "security"
    ARCHITECTURE = "architecture"
    PERFORMANCE = "performance"
    STYLE = "style"
    UTILITY = "utility"


@dataclass
class SkillMetadata:
    """Skill 元数据，描述 Skill 的基本信息和兼容性。"""
    name: str
    display_name: str
    version: str = "1.0.0"
    category: SkillCategory = SkillCategory.UTILITY
    description: str = ""
    author: str = ""
    requires: list[str] = field(default_factory=list)  # 依赖的其他 Skill 名称
    languages: list[str] = field(default_factory=lambda: ["python"])
    tags: list[str] = field(default_factory=list)


@dataclass
class SkillResult:
    """Skill 执行结果。"""
    success: bool
    findings: list[dict] = field(default_factory=list)
    summary: str = ""
    raw_output: str = ""
    execution_time_ms: float = 0.0
    tokens_used: int = 0


# ============================================================
# 抽象基类
# ============================================================

class BaseSkill(ABC):
    """Skill 抽象基类。

    所有 Skill 必须：
    1. 定义 metadata 属性（SkillMetadata 实例）
    2. 实现 execute(code, file_path, context) 方法

    可选钩子：
    3. validate() — 执行前验证环境
    4. cleanup() — 执行后清理资源
    """

    metadata: SkillMetadata

    @abstractmethod
    async def execute(
        self,
        code: str,
        file_path: str = "<string>",
        context: dict[str, Any] | None = None,
    ) -> SkillResult:
        """执行 Skill 分析。

        Args:
            code: 源代码文本
            file_path: 文件路径
            context: 可选的上下文信息（如 AST 树、Agent 上下文等）

        Returns:
            SkillResult 结果对象
        """
        ...

    async def validate(self) -> bool:
        """执行前环境验证钩子。

        可在此检查依赖工具是否可用、API Key 是否有效等。
        默认返回 True（跳过验证）。

        Returns:
            True 表示验证通过，False 表示环境不满足
        """
        return True

    async def cleanup(self) -> None:
        """执行后清理钩子。

        可在此释放文件句柄、关闭连接等。
        默认不执行任何操作。
        """
        pass


# ============================================================
# 注册中心（单例）
# ============================================================

class SkillRegistry:
    """Skill 注册中心（单例模式）。

    提供 Skill 的注册、查找、列表和搜索功能。

    Usage:
        registry = SkillRegistry()
        registry.register(my_skill)
        skill = registry.get("my_skill")
        all_skills = registry.list_all()
    """

    _instance: "SkillRegistry | None" = None
    _skills: dict[str, BaseSkill]

    def __new__(cls) -> "SkillRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._skills = {}
        return cls._instance

    def register(self, skill: BaseSkill) -> None:
        """注册一个 Skill。

        Args:
            skill: BaseSkill 实例

        Raises:
            ValueError: 同名 Skill 已存在
        """
        name = skill.metadata.name
        if name in self._skills:
            raise ValueError(
                f"Skill '{name}' 已注册。如需覆盖请先调用 unregister()。"
            )
        self._skills[name] = skill

    def unregister(self, name: str) -> bool:
        """注销一个 Skill。

        Args:
            name: Skill 名称

        Returns:
            True 表示成功注销
        """
        if name in self._skills:
            del self._skills[name]
            return True
        return False

    def get(self, name: str) -> BaseSkill | None:
        """获取指定 Skill。

        Args:
            name: Skill 名称

        Returns:
            BaseSkill 实例，不存在返回 None
        """
        return self._skills.get(name)

    def list_all(self) -> list[SkillMetadata]:
        """列出所有已注册 Skill 的元数据。

        Returns:
            SkillMetadata 列表
        """
        return [s.metadata for s in self._skills.values()]

    def list_by_category(self, category: SkillCategory) -> list[SkillMetadata]:
        """按分类列出 Skill。

        Args:
            category: SkillCategory 枚举值

        Returns:
            匹配的 SkillMetadata 列表
        """
        return [
            s.metadata
            for s in self._skills.values()
            if s.metadata.category == category
        ]

    def search(
        self,
        query: str = "",
        category: SkillCategory | None = None,
        language: str | None = None,
        tags: list[str] | None = None,
    ) -> list[SkillMetadata]:
        """搜索 Skill。

        支持按名称/描述模糊搜索、分类、语言和标签过滤。

        Args:
            query: 搜索关键词（匹配名称或描述）
            category: 分类过滤
            language: 语言过滤
            tags: 标签过滤（AND 逻辑）

        Returns:
            匹配的 SkillMetadata 列表
        """
        results: list[SkillMetadata] = []

        for skill in self._skills.values():
            meta = skill.metadata

            # 分类过滤
            if category is not None and meta.category != category:
                continue

            # 语言过滤
            if language is not None and language not in meta.languages:
                continue

            # 标签过滤
            if tags:
                if not all(t in meta.tags for t in tags):
                    continue

            # 关键词搜索
            if query:
                q = query.lower()
                if q not in meta.name.lower() and q not in meta.description.lower():
                    continue

            results.append(meta)

        return results

    @property
    def count(self) -> int:
        """已注册 Skill 数量。"""
        return len(self._skills)
