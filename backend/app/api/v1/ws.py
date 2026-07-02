"""
WebSocket / SSE 端点

GET /api/v1/reviews/{task_id}/stream — SSE 实时进度推送

进度存储使用 Redis（支持 Celery worker 跨进程共享），
Redis 不可用时降级到内存字典。
"""

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.config import get_settings

router = APIRouter(tags=["streaming"])

# ============================================================
# Redis 进度存储（降级到内存）
# ============================================================

settings = get_settings()

_redis_client = None
_redis_available = False


def _get_redis():
    """获取 Redis 客户端（惰性初始化，连接失败则降级到内存）。"""
    global _redis_client, _redis_available
    if _redis_client is not None:
        return _redis_client if _redis_available else None
    try:
        import redis
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        _redis_client.ping()
        _redis_available = True
    except Exception:
        _redis_available = False
        _redis_client = None
    return _redis_client if _redis_available else None


# 内存降级存储
_progress_store: dict[str, dict] = {}

_PROGRESS_KEY = "review:progress:{task_id}"
_PROGRESS_TTL = 3600  # 1 小时过期


def update_progress(task_id: str, progress: float, stage: str, status: str = "running"):
    """更新任务进度（供 Orchestrator 节点调用）。

    优先写入 Redis（跨进程共享），Redis 不可用时写入内存。
    """
    data = {
        "progress": progress,
        "stage": stage,
        "status": status,
        "errors": _get_errors(task_id),
    }
    rds = _get_redis()
    if rds is not None:
        rds.setex(_PROGRESS_KEY.format(task_id=task_id), _PROGRESS_TTL, json.dumps(data))
    # 同时写入内存（降级 + SSE 快速读取）
    _progress_store[task_id] = data


def complete_progress(task_id: str):
    """标记任务完成。"""
    data = {
        "progress": 1.0,
        "stage": "done",
        "status": "completed",
        "errors": _get_errors(task_id),
    }
    rds = _get_redis()
    if rds is not None:
        rds.setex(_PROGRESS_KEY.format(task_id=task_id), _PROGRESS_TTL, json.dumps(data))
    _progress_store[task_id] = data


def fail_progress(task_id: str, error: str):
    """标记任务失败。"""
    errors = _get_errors(task_id)
    errors.append(error)
    existing = _progress_store.get(task_id, {})
    data = {
        "progress": existing.get("progress", 0.0),
        "stage": existing.get("stage", "error"),
        "status": "failed",
        "errors": errors,
    }
    rds = _get_redis()
    if rds is not None:
        rds.setex(_PROGRESS_KEY.format(task_id=task_id), _PROGRESS_TTL, json.dumps(data))
    _progress_store[task_id] = data


def _get_errors(task_id: str) -> list:
    """获取当前任务的错误列表。"""
    rds = _get_redis()
    if rds is not None:
        raw = rds.get(_PROGRESS_KEY.format(task_id=task_id))
        if raw:
            try:
                return json.loads(raw).get("errors", [])
            except (json.JSONDecodeError, TypeError):
                pass
    return _progress_store.get(task_id, {}).get("errors", [])


def _get_progress(task_id: str) -> dict:
    """读取任务进度（优先 Redis，降级内存）。"""
    rds = _get_redis()
    if rds is not None:
        raw = rds.get(_PROGRESS_KEY.format(task_id=task_id))
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
    return _progress_store.get(task_id, {})


# ============================================================
# 数据库状态检查（SSE 轮询时定期调用，检测 Celery 完成或超时）
# ============================================================

async def _check_db_status(task_id: str) -> str:
    """查询数据库中任务的最新状态。

    用于 SSE 轮询时检测：
    - Celery 已完成但未更新进度存储的情况
    - 任务超时被 GET 端点标记为 failed

    Returns:
        任务状态字符串（completed / failed / running / not_found）
    """
    try:
        from uuid import UUID as UUIDType
        from app.models import async_session_factory
        from app.models.review import ReviewTask

        async with async_session_factory() as session:
            task = await session.get(ReviewTask, UUIDType(task_id))
            if task is None:
                return "not_found"
            return task.status.value if task.status else "running"
    except Exception as e:
        print("[ws] _check_db_status 失败: {}".format(e))
        return "running"  # 查询失败时不中断 SSE，继续等待


# ============================================================
# SSE 端点
# ============================================================

@router.get("/reviews/{task_id}/stream")
async def stream_review_progress(task_id: str, request: Request):
    """SSE 端点：实时推送审查进度。

    事件类型：
    - progress:  审查进行中，data 包含 stage、progress 和 agent 名称
    - complete:  审查完成，data 包含 summary、score 和 stats
    - error:     审查失败，data 包含 error 信息

    连接在审查完成或失败后自动关闭。
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        # 初始化进度
        if task_id not in _progress_store:
            _progress_store[task_id] = {
                "progress": 0.0,
                "stage": "pending",
                "status": "running",
                "errors": [],
            }

        last_progress = -1.0
        poll_count = 0
        # SSE 超时 15 分钟（按约定长于 REVIEW_TIMEOUT_SECONDS，确保 task 完成后仍能推送结果）
        sse_timeout = settings.REVIEW_TIMEOUT_SECONDS + 600
        max_polls = sse_timeout  # 每次轮询间隔 1 秒

        while poll_count < max_polls:
            # 检查客户端是否断开
            if await request.is_disconnected():
                break

            state = _get_progress(task_id)
            current_progress = state.get("progress", 0.0)
            status = state.get("status", "running")
            stage = state.get("stage", "")

            # 发送进度事件（仅在进度变化时）
            if current_progress > last_progress:
                yield f"event: progress\ndata: {json.dumps({'task_id': task_id, 'stage': stage, 'progress': current_progress, 'status': status})}\n\n"
                last_progress = current_progress

            # 完成（优先检查 Redis 进度存储，Celery 实时写入此处）
            if status == "completed":
                yield f"event: complete\ndata: {json.dumps({'task_id': task_id, 'stage': 'done', 'progress': 1.0})}\n\n"
                break

            # 失败
            if status == "failed":
                errors = state.get("errors", [])
                yield f"event: error\ndata: {json.dumps({'task_id': task_id, 'error': errors[-1] if errors else 'Unknown error'})}\n\n"
                break

            # 每 10 次轮询（约 10 秒）检查数据库状态
            # 检测两种异常：
            # 1. Celery 完成但 _save_to_db 失败，Redis 仍为 running（依赖 DB 兜底）
            # 2. 任务超时/丢失（DB 无记录或 running 过久）
            if poll_count > 0 and poll_count % 10 == 0:
                db_status = await _check_db_status(task_id)
                if db_status == "completed":
                    yield f"event: complete\ndata: {json.dumps({'task_id': task_id, 'stage': 'done', 'progress': 1.0})}\n\n"
                    break
                if db_status == "failed":
                    yield f"event: error\ndata: {json.dumps({'task_id': task_id, 'error': '审查任务失败或超时，请重新提交'})}\n\n"
                    break
                # 任务在数据库中不存在且已轮询超过 60 秒，判定为任务丢失
                if db_status == "not_found" and poll_count >= 60:
                    yield f"event: error\ndata: {json.dumps({'task_id': task_id, 'error': '审查任务不存在或已丢失（可能因服务重启），请重新提交审查'})}\n\n"
                    break

            poll_count += 1
            await asyncio.sleep(1)

        # 超时未完成，通知前端
        if poll_count >= max_polls:
            yield f"event: error\ndata: {json.dumps({'task_id': task_id, 'error': '审查超时（超过 15 分钟），请重新提交'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )
