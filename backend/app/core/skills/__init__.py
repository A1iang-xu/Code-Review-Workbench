"""
Skill 系统初始化

提供 init_skills() 函数，在应用启动时加载所有内置 Skill 和自定义 Skill。
"""

from pathlib import Path

from app.core.skills.loader import SkillLoader
from app.core.skills.registry import SkillRegistry

# 自定义 Skill 目录（项目根 skills/，与 docker-compose 挂载一致）
CUSTOM_SKILLS_DIR = Path(__file__).resolve().parents[4] / "skills"


def init_skills() -> SkillRegistry:
    """初始化 Skill 系统：创建 SkillLoader 并加载内置 + 自定义 Skill。

    内置 Skill 从 app.core.skills.builtin 加载；
    自定义 Skill 从项目根 skills/ 目录加载（.py 文件，需暴露 skill 变量）。

    应在 FastAPI lifespan 中调用。

    Returns:
        SkillRegistry 实例（包含所有已加载的 Skill）
    """
    registry = SkillRegistry()
    loader = SkillLoader(registry)

    builtin_count = loader.load_builtin()
    print(f"[Skills] 已加载 {builtin_count} 个内置 Skill")

    custom_count = loader.load_custom(CUSTOM_SKILLS_DIR)
    if custom_count > 0:
        print(f"[Skills] 已加载 {custom_count} 个自定义 Skill (from {CUSTOM_SKILLS_DIR})")

    return registry
