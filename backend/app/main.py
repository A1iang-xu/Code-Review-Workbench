"""
FastAPI 应用入口

- 生命周期管理（Skill 初始化）
- CORS 中间件
- 健康检查端点
- API 路由注册（reviews、streaming、skills）
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理：启动/关闭时的初始化与清理。"""
    # 启动
    print(f"[{settings.APP_NAME}] 启动中 — 环境: {settings.APP_ENV}")

    # 初始化 Skill 系统
    try:
        from app.core.skills import init_skills
        registry = init_skills()
        print(f"[{settings.APP_NAME}] Skill 系统已初始化，已注册 {registry.count} 个 Skill")
    except Exception as e:
        print(f"[{settings.APP_NAME}] Skill 系统初始化失败: {e}")

    yield
    # 关闭
    print(f"[{settings.APP_NAME}] 已关闭")


app = FastAPI(
    title="Code Review Workbench",
    description="智能代码审查与重构工坊 — 多 Agent 协作平台",
    version="0.2.0",
    lifespan=lifespan,
)

# --- CORS 中间件 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 健康检查 ---
@app.get("/health")
async def health_check():
    """健康检查端点。"""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.APP_ENV,
    }


# ============================================================
# 测试端点 (POST /api/test/llm)
# ============================================================

from fastapi import APIRouter  # noqa: E402

test_router = APIRouter(prefix="/api/test", tags=["test"])


@test_router.post("/llm")
async def test_llm():
    """测试 LLM 连通性。

    分别测试 reasoning 模型（GLM-5.2）和 utility 模型（Qwen2.5-7B）的连通性。
    """
    from app.integrations.llm import LLMProvider

    results = {}

    # 测试 reasoning 模型
    try:
        resp = await LLMProvider.reasoning(
            messages=[{"role": "user", "content": "Hello, respond with 'ok' only."}],
            max_tokens=32,
        )
        content = resp.choices[0].message.content if resp.choices else "no response"
        results["reasoning"] = {
            "model": settings.LLM_REASONING_MODEL,
            "status": "ok",
            "response": content[:200],
        }
    except Exception as e:
        results["reasoning"] = {
            "model": settings.LLM_REASONING_MODEL,
            "status": "error",
            "error": str(e),
        }

    # 测试 utility 模型
    try:
        resp = await LLMProvider.utility(
            messages=[{"role": "user", "content": "Hello, respond with 'ok' only."}],
            max_tokens=32,
        )
        content = resp.choices[0].message.content if resp.choices else "no response"
        results["utility"] = {
            "model": settings.LLM_UTILITY_MODEL,
            "status": "ok",
            "response": content[:200],
        }
    except Exception as e:
        results["utility"] = {
            "model": settings.LLM_UTILITY_MODEL,
            "status": "error",
            "error": str(e),
        }

    return results


app.include_router(test_router)


# ============================================================
# v1 API 路由注册
# ============================================================

# 审查 API
from app.api.v1.reviews import router as reviews_router  # noqa: E402
app.include_router(reviews_router, prefix="/api/v1")

# SSE 进度推送
from app.api.v1.ws import router as ws_router  # noqa: E402
app.include_router(ws_router, prefix="/api/v1")

# Skill 管理 API
from app.api.v1.skills import router as skills_router  # noqa: E402
app.include_router(skills_router, prefix="/api/v1")
