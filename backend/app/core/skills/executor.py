"""
Skill 执行器

提供 Skill 的执行、并行执行、链式执行和分类批量执行功能。
"""

import asyncio
import time
from typing import Any

from app.core.skills.registry import BaseSkill, SkillCategory, SkillRegistry, SkillResult


class SkillExecutor:
    """Skill 执行器。

    支持：
    - 单个 Skill 执行
    - 多个 Skill 并行执行
    - 链式执行（前一个输出注入后一个上下文）
    - 按分类批量执行

    Usage:
        executor = SkillExecutor()
        result = await executor.execute("ast_scan", code, "file.py")
        results = await executor.execute_all(["ast_scan", "semgrep_scan"], code, "file.py")
    """

    def __init__(self, registry: SkillRegistry | None = None):
        self.registry = registry or SkillRegistry()

    async def execute(
        self,
        skill_name: str,
        code: str,
        file_path: str = "<string>",
        context: dict[str, Any] | None = None,
    ) -> SkillResult:
        """执行单个 Skill。

        Args:
            skill_name: Skill 名称
            code: 源代码文本
            file_path: 文件路径
            context: 可选的上下文

        Returns:
            SkillResult
        """
        skill = self.registry.get(skill_name)
        if skill is None:
            return SkillResult(
                success=False,
                summary=f"Skill '{skill_name}' 未找到",
            )

        # 验证环境
        try:
            valid = await skill.validate()
            if not valid:
                return SkillResult(
                    success=False,
                    summary=f"Skill '{skill_name}' 环境验证失败",
                )
        except Exception as e:
            return SkillResult(
                success=False,
                summary=f"Skill '{skill_name}' 验证异常: {str(e)}",
            )

        # 执行
        start = time.perf_counter()
        try:
            result = await skill.execute(code, file_path, context)
            result.execution_time_ms = (time.perf_counter() - start) * 1000
            return result
        except Exception as e:
            return SkillResult(
                success=False,
                summary=f"Skill '{skill_name}' 执行异常: {str(e)}",
                execution_time_ms=(time.perf_counter() - start) * 1000,
            )
        finally:
            # 清理
            try:
                await skill.cleanup()
            except Exception:
                pass

    async def execute_all(
        self,
        skill_names: list[str],
        code: str,
        file_path: str = "<string>",
        context: dict[str, Any] | None = None,
    ) -> dict[str, SkillResult]:
        """并行执行多个 Skill。

        Args:
            skill_names: Skill 名称列表
            code: 源代码文本
            file_path: 文件路径
            context: 可选的上下文

        Returns:
            {skill_name: SkillResult} 字典
        """
        tasks = []
        for name in skill_names:
            tasks.append(self.execute(name, code, file_path, context))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        result_map: dict[str, SkillResult] = {}
        for name, res in zip(skill_names, results):
            if isinstance(res, Exception):
                result_map[name] = SkillResult(
                    success=False,
                    summary=f"执行异常: {str(res)}",
                )
            else:
                result_map[name] = res

        return result_map

    async def execute_pipeline(
        self,
        skill_names: list[str],
        code: str,
        file_path: str = "<string>",
        initial_context: dict[str, Any] | None = None,
    ) -> list[SkillResult]:
        """链式执行 Skill（前一个输出注入后一个上下文）。

        每个 Skill 执行完毕后，其 result 对象被注入到下一个
        Skill 的 context["_previous_result"] 中。

        Args:
            skill_names: Skill 名称列表（按顺序执行）
            code: 源代码文本
            file_path: 文件路径
            initial_context: 初始上下文

        Returns:
            SkillResult 列表（按执行顺序）
        """
        context = initial_context or {}
        results: list[SkillResult] = []

        for name in skill_names:
            result = await self.execute(name, code, file_path, context)
            results.append(result)

            # 将当前结果注入下一个 Skill 的上下文
            context = {**context, "_previous_result": result}

        return results

    async def execute_by_category(
        self,
        category: SkillCategory,
        code: str,
        file_path: str = "<string>",
        context: dict[str, Any] | None = None,
    ) -> dict[str, SkillResult]:
        """按分类批量执行所有匹配的 Skill。

        Args:
            category: SkillCategory 枚举值
            code: 源代码文本
            file_path: 文件路径
            context: 可选的上下文

        Returns:
            {skill_name: SkillResult} 字典
        """
        skills = self.registry.list_by_category(category)
        skill_names = [s.name for s in skills]

        if not skill_names:
            return {}

        return await self.execute_all(skill_names, code, file_path, context)
