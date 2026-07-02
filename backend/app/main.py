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

    # 初始化 OpenTelemetry（接入 Jaeger，可视化审查流水线耗时）
    try:
        from app.utils.telemetry import setup_telemetry
        setup_telemetry(app)
    except Exception as e:
        print(f"[{settings.APP_NAME}] Telemetry 初始化失败: {e}")

    # 预加载 Ollama 模型（避免审查任务首次调用时冷启动延迟）
    try:
        import asyncio as _asyncio
        import httpx
        from app.config import get_settings as _get_settings
        _s = _get_settings()
        _models_to_warm = []
        if _s.LLM_UTILITY_MODEL.startswith("ollama/"):
            _models_to_warm.append(_s.LLM_UTILITY_MODEL[len("ollama/"):])
        if _s.LLM_REASONING_MODEL.startswith("ollama/"):
            _models_to_warm.append(_s.LLM_REASONING_MODEL[len("ollama/"):])
        # 额外预热配置中的所有模型（过滤掉系统环境变量污染的路径）
        for m in (_s.OLLAMA_MODELS or "").split(","):
            m = m.strip()
            # 跳过空值和路径（Windows 系统 OLLAMA_MODELS 环境变量可能指向模型存储目录）
            if not m or "\\" in m or "/" in m or ":" in m[1:]:
                continue
            if m not in _models_to_warm:
                _models_to_warm.append(m)
        # 若配置中的 OLLAMA_MODELS 被系统环境变量污染（仅含路径），使用默认值
        if not _models_to_warm:
            _models_to_warm.extend(["qwen2.5:7b", "deepseek-coder:6.7b"])

        async def _warmup():
            for model_name in _models_to_warm:
                try:
                    async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
                        resp = await client.post(
                            f"{_s.OLLAMA_BASE_URL}/api/generate",
                            json={"model": model_name, "prompt": "hi", "stream": False, "keep_alive": "30m"},
                        )
                        if resp.status_code == 200:
                            print(f"[{_s.APP_NAME}] Ollama 模型预热完成: {model_name}")
                        else:
                            print(f"[{_s.APP_NAME}] Ollama 模型预热失败 {model_name}: HTTP {resp.status_code}")
                except Exception as e:
                    print(f"[{_s.APP_NAME}] Ollama 模型预热异常 {model_name}: {e}")
        # 后台执行，不阻塞启动
        _asyncio.create_task(_warmup())
    except Exception as e:
        print(f"[{settings.APP_NAME}] Ollama 预热初始化失败: {e}")

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
# 允许的源从环境变量读取，避免硬编码；生产环境应配置真实域名
_cors_origins = [
    o.strip()
    for o in (
        settings.APP_ENV.lower() in {"production", "prod"}
        and __import__("os").getenv("CORS_ORIGINS", "")
        or "http://localhost:3000,http://127.0.0.1:3000,http://localhost"
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
)


# ============================================================
# 全局异常处理器 — 统一错误响应格式，避免裸露堆栈泄露内部信息
# ============================================================
from fastapi import Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from app.utils.logger import get_logger  # noqa: E402

_logger = get_logger(__name__)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """请求参数校验失败 — 返回 422 + 结构化错误详情。"""
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "请求参数校验失败",
            "detail": exc.errors(),
            "path": str(request.url.path),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """未捕获异常兜底 — 记录完整堆栈，对外仅返回通用错误信息。

    生产环境绝不向客户端泄露堆栈，避免暴露内部实现细节。
    """
    _logger.exception(
        "[Unhandled] %s %s -> %s: %s",
        request.method,
        request.url.path,
        type(exc).__name__,
        exc,
    )
    is_prod = settings.APP_ENV.lower() in {"production", "prod"}
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "服务器内部错误" if is_prod else f"服务器内部错误: {exc}",
            "detail": None if is_prod else str(exc),
            "path": str(request.url.path),
        },
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
