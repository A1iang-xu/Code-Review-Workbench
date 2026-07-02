"""
Skill 管理 API

GET  /api/v1/skills          — 列出所有已注册 Skill
POST /api/v1/skills/execute   — 执行指定 Skill
POST /api/v1/skills/reload    — 重新加载所有内置 + 自定义 Skill
POST /api/v1/skills/custom    — 添加自定义 Skill（保存为 .py 文件 + 热加载）
DELETE /api/v1/skills/custom/{name} — 删除自定义 Skill
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.skills.registry import SkillRegistry
from app.core.skills.executor import SkillExecutor

router = APIRouter(tags=["skills"])


# ============================================================
# Pydantic 模型
# ============================================================

class SkillMetaResponse(BaseModel):
    """Skill 元数据响应。"""
    name: str
    display_name: str
    version: str
    category: str
    description: str
    languages: list[str]
    tags: list[str]


class SkillExecuteRequest(BaseModel):
    """Skill 执行请求。"""
    skill_name: str = Field(..., description="Skill 名称，如 'ast_scan'")
    code: str = Field(..., description="待分析的源代码文本")
    file_path: str = Field(default="<string>", description="文件路径")


class SkillExecuteResponse(BaseModel):
    """Skill 执行响应。"""
    success: bool
    skill_name: str
    summary: str
    findings: list[dict] = Field(default_factory=list)
    execution_time_ms: float = 0.0


class CustomSkillRequest(BaseModel):
    """自定义 Skill 创建请求。"""
    name: str = Field(..., description="Skill 唯一标识（仅小写字母/数字/下划线）")
    display_name: str = Field(..., description="展示名称")
    description: str = Field(default="", description="Skill 描述")
    category: str = Field(default="utility", description="分类：static_analysis/pattern_match/security/architecture/performance/style/utility")
    code: str = Field(..., description="Skill 实现代码（Python），需定义 skill 变量")


# ============================================================
# 端点实现
# ============================================================

@router.get("/skills", response_model=list[SkillMetaResponse])
async def list_skills():
    """列出所有已注册 Skill 的元数据。

    返回每个 Skill 的 name、display_name、version、category、
    description、languages 和 tags。
    """
    registry = SkillRegistry()
    skills = registry.list_all()

    return [
        SkillMetaResponse(
            name=s.name,
            display_name=s.display_name,
            version=s.version,
            category=s.category.value,
            description=s.description,
            languages=s.languages,
            tags=s.tags,
        )
        for s in skills
    ]


@router.post("/skills/execute", response_model=SkillExecuteResponse)
async def execute_skill(request: SkillExecuteRequest):
    """执行指定 Skill。

    接收 skill_name、code、file_path，调用 SkillExecutor 执行，
    返回 success、summary、findings 和 execution_time_ms。
    """
    executor = SkillExecutor()
    result = await executor.execute(
        skill_name=request.skill_name,
        code=request.code,
        file_path=request.file_path,
    )

    return SkillExecuteResponse(
        success=result.success,
        skill_name=request.skill_name,
        summary=result.summary,
        findings=result.findings,
        execution_time_ms=round(result.execution_time_ms, 2),
    )


@router.post("/skills/reload")
async def reload_skills():
    """重新加载所有内置 + 自定义 Skill。

    清空注册中心后重新导入内置 Skill 和自定义 Skill，
    返回各自加载数量。
    """
    from app.core.skills.loader import SkillLoader
    from app.core.skills import CUSTOM_SKILLS_DIR

    registry = SkillRegistry()
    # 清空已注册的 Skill，避免 register() 抛出 ValueError
    registry._skills = {}
    loader = SkillLoader(registry)
    builtin_count = loader.load_builtin()
    custom_count = loader.load_custom(CUSTOM_SKILLS_DIR)

    total = builtin_count + custom_count
    return {
        "success": True,
        "loaded_count": total,
        "builtin_count": builtin_count,
        "custom_count": custom_count,
        "message": f"已重新加载 {total} 个 Skill（内置 {builtin_count} + 自定义 {custom_count}）",
    }


@router.post("/skills/custom")
async def create_custom_skill(request: CustomSkillRequest):
    """添加自定义 Skill。

    将 Skill 代码保存为 skills/{name}.py 文件，然后热加载到注册中心。
    若同名文件已存在则返回 409。

    代码需定义一个 BaseSkill 子类实例的 skill 变量。
    """
    import re
    from app.core.skills import CUSTOM_SKILLS_DIR

    # 名称合法性校验
    if not re.match(r"^[a-z][a-z0-9_]*$", request.name):
        raise HTTPException(
            status_code=400,
            detail="Skill 名称只能包含小写字母、数字和下划线，且以字母开头",
        )

    CUSTOM_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = CUSTOM_SKILLS_DIR / f"{request.name}.py"

    if file_path.exists():
        raise HTTPException(
            status_code=409,
            detail=f"自定义 Skill '{request.name}' 已存在",
        )

    # 保存代码文件
    try:
        file_path.write_text(request.code, encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存 Skill 文件失败: {e}")

    # 热加载该 Skill
    from app.core.skills.loader import SkillLoader

    registry = SkillRegistry()
    loader = SkillLoader(registry)
    loaded = loader.load_custom(CUSTOM_SKILLS_DIR)

    if loaded == 0:
        # 加载失败：代码可能有语法错误，删除文件避免污染
        try:
            file_path.unlink()
        except Exception:
            pass
        raise HTTPException(
            status_code=400,
            detail="Skill 代码加载失败，请检查是否定义了 BaseSkill 实例的 skill 变量",
        )

    return {
        "success": True,
        "name": request.name,
        "message": f"自定义 Skill '{request.name}' 已创建并加载",
    }


@router.delete("/skills/custom/{name}")
async def delete_custom_skill(name: str):
    """删除自定义 Skill。

    从注册中心注销并删除 skills/{name}.py 文件。
    内置 Skill 不允许删除（文件不在 custom 目录则返回 404）。
    """
    import re
    from app.core.skills import CUSTOM_SKILLS_DIR

    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        raise HTTPException(status_code=400, detail="Skill 名称不合法")

    file_path = CUSTOM_SKILLS_DIR / f"{name}.py"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"自定义 Skill '{name}' 不存在")

    # 从注册中心注销
    registry = SkillRegistry()
    registry.unregister(name)

    # 删除文件
    try:
        file_path.unlink()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除 Skill 文件失败: {e}")

    return {
        "success": True,
        "name": name,
        "message": f"自定义 Skill '{name}' 已删除",
    }
