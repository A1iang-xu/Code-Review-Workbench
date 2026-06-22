"""
Skill 系统初始化

提供 init_skills() 函数，在应用启动时加载所有内置 Skill。
"""

from app.core.skills.loader import SkillLoader
from app.core.skills.registry import SkillRegistry


def init_skills() -> SkillRegistry:
    """初始化 Skill 系统：创建 SkillLoader 并加载内置 Skill。

    应在 FastAPI lifespan 中调用。

    Returns:
        SkillRegistry 实例（包含所有已加载的 Skill）
    """
    registry = SkillRegistry()
    loader = SkillLoader(registry)

    builtin_count = loader.load_builtin()
    print(f"[Skills] 已加载 {builtin_count} 个内置 Skill")

    return registry
