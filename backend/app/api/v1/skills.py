"""
Skill 管理 API

GET  /api/v1/skills          — 列出所有已注册 Skill
POST /api/v1/skills/execute   — 执行指定 Skill
POST /api/v1/skills/reload    — 重新加载所有内置 Skill
"""

from fastapi import APIRouter
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
    """重新加载所有内置 Skill。

    调用 SkillLoader.load_builtin() 重新导入所有内置 Skill 模块，
    返回加载数量。
    """
    from app.core.skills.loader import SkillLoader

    # 创建新的 registry 和 loader
    registry = SkillRegistry()
    loader = SkillLoader(registry)
    loaded_count = loader.load_builtin()

    return {
        "success": True,
        "loaded_count": loaded_count,
        "message": f"已重新加载 {loaded_count} 个内置 Skill",
    }
