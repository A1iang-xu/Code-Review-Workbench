"""
FastAPI 应用入口

- 生命周期管理（Skill 初始化、Telemetry、日志）
- CORS 中间件
- 健康检查端点
- Prometheus /metrics 端点
- API 路由注册（reviews、streaming、skills、webhooks）
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理：启动/关闭时的初始化与清理。"""
    # 启动
    print(f"[{settings.APP_NAME}] 启动中 — 环境: {settings.APP_ENV}")

    # 初始化结构化日志
    try:
        from app.utils.logger import setup_logging
        setup_logging()
    except Exception as e:
        print(f"[{settings.APP_NAME}] 日志初始化失败: {e}")

    # 初始化 Skill 系统
    try:
        from app.core.skills import init_skills
        registry = init_skills()
        print(f"[{settings.APP_NAME}] Skill 系统已初始化，已注册 {registry.count} 个 Skill")
    except Exception as e:
        print(f"[{settings.APP_NAME}] Skill 系统初始化失败: {e}")

    # 初始化 OpenTelemetry (需要 Jaeger 运行时才启用)
    # try:
    #     from app.utils.telemetry import setup_telemetry
    #     setup_telemetry(app)
    # except Exception as e:
    #     print(f"[{settings.APP_NAME}] Telemetry 初始化失败: {e}")

    yield
    # 关闭
    print(f"[{settings.APP_NAME}] 已关闭")


app = FastAPI(
    title="Code Review Workbench",
    description="智能代码审查与重构工坊 — 多 Agent 协作平台",
    version="0.3.0",
    lifespan=lifespan,
)

# --- CORS 中间件 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost"],
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
        "version": "0.3.0",
    }


# --- Prometheus Metrics 端点 ---
@app.get("/metrics")
async def metrics():
    """Prometheus 指标端点。

    返回 Prometheus 文本格式的指标数据。
    Scraped by Prometheus service at configured interval.
    """
    from app.utils.metrics import metrics_endpoint
    body, content_type = metrics_endpoint()
    return Response(content=body, media_type=content_type)


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

# Webhook API
from app.api.v1.webhooks import router as webhooks_router  # noqa: E402
app.include_router(webhooks_router, prefix="/api/v1")
