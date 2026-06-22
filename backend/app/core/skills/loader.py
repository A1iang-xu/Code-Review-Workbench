"""
Skill 加载器

负责加载内置 Skill 和用户自定义 Skill。
支持热重载指定 Skill（重新导入模块）。
"""

import importlib
import os
import sys
from pathlib import Path
from typing import Any

from app.core.skills.registry import BaseSkill, SkillRegistry


class SkillLoader:
    """Skill 动态加载器。

    负责从 builtin/ 目录加载内置 Skill，
    以及从用户指定目录加载自定义 Skill。

    Usage:
        loader = SkillLoader()
        loader.load_builtin()
        loader.load_custom("/path/to/custom/skills")
        loader.reload("ast_scan")
    """

    def __init__(self, registry: SkillRegistry | None = None):
        self.registry = registry or SkillRegistry()

    def load_builtin(self) -> int:
        """从 builtin/ 目录加载所有内置 Skill。

        扫描 builtin/ 下的子目录，每个子目录应包含一个
        与目录同名的 Python 模块，并在顶层暴露一个
        `skill` 变量（BaseSkill 实例）。

        Returns:
            成功加载的 Skill 数量
        """
        # builtin 目录路径
        builtin_dir = Path(__file__).parent / "builtin"
        if not builtin_dir.exists():
            return 0

        loaded_count = 0

        for item in builtin_dir.iterdir():
            if not item.is_dir():
                continue
            if item.name.startswith("_") or item.name.startswith("."):
                continue

            try:
                module_path = f"app.core.skills.builtin.{item.name}"
                module = importlib.import_module(module_path)

                if hasattr(module, "skill") and isinstance(module.skill, BaseSkill):
                    self.registry.register(module.skill)
                    loaded_count += 1
            except ImportError as e:
                print(f"[SkillLoader] 无法导入内置 Skill '{item.name}': {e}")
            except ValueError as e:
                print(f"[SkillLoader] Skill '{item.name}' 注册失败: {e}")
            except Exception as e:
                print(f"[SkillLoader] 加载 Skill '{item.name}' 时出错: {e}")

        return loaded_count

    def load_custom(self, custom_dir: str | Path) -> int:
        """从用户指定目录加载自定义 Skill。

        每个 .py 文件应包含一个 `skill` 变量（BaseSkill 实例）。

        Args:
            custom_dir: 包含 Skill 定义的目录路径

        Returns:
            成功加载的 Skill 数量
        """
        custom_dir = Path(custom_dir)
        if not custom_dir.exists():
            return 0

        # 将自定义目录加入 sys.path
        custom_dir_str = str(custom_dir.absolute())
        if custom_dir_str not in sys.path:
            sys.path.insert(0, custom_dir_str)

        loaded_count = 0

        for item in custom_dir.iterdir():
            if item.suffix != ".py":
                continue
            if item.name.startswith("_"):
                continue

            module_name = item.stem
            try:
                module = importlib.import_module(module_name)

                if hasattr(module, "skill") and isinstance(module.skill, BaseSkill):
                    self.registry.register(module.skill)
                    loaded_count += 1
            except ImportError as e:
                print(f"[SkillLoader] 无法导入自定义 Skill '{module_name}': {e}")
            except ValueError as e:
                print(f"[SkillLoader] 自定义 Skill '{module_name}' 注册失败: {e}")
            except Exception as e:
                print(f"[SkillLoader] 加载自定义 Skill '{module_name}' 时出错: {e}")

        return loaded_count

    def reload(self, skill_name: str) -> bool:
        """热重载指定 Skill。

        重新导入模块并更新注册中心。

        Args:
            skill_name: Skill 名称

        Returns:
            True 表示重载成功
        """
        # 先从注册中心获取当前 Skill 的模块信息
        old_skill = self.registry.get(skill_name)
        if old_skill is None:
            return False

        module = old_skill.__class__.__module__
        try:
            # 重新导入模块
            mod = importlib.reload(sys.modules[module])

            if hasattr(mod, "skill") and isinstance(mod.skill, BaseSkill):
                # 先注销旧的
                self.registry.unregister(skill_name)
                # 注册新的
                self.registry.register(mod.skill)
                return True
        except Exception as e:
            print(f"[SkillLoader] 重载 Skill '{skill_name}' 失败: {e}")

        return False
