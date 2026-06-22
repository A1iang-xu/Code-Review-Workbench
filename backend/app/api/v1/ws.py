"""
WebSocket / SSE 端点

GET /api/v1/reviews/{task_id}/stream — SSE 实时进度推送

进度存储使用内存字典（标注后续迁移到 Redis Pub/Sub）。
"""

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["streaming"])

# ============================================================
# 进度存储（内存字典，后续迁移到 Redis Pub/Sub）
# ============================================================

# {task_id: {"progress": float, "stage": str, "status": str, "errors": list}}
_progress_store: dict[str, dict] = {}


def update_progress(task_id: str, progress: float, stage: str, status: str = "running"):
    """更新任务进度（供 Orchestrator 节点调用）。"""
    _progress_store[task_id] = {
        "progress": progress,
        "stage": stage,
        "status": status,
        "errors": _progress_store.get(task_id, {}).get("errors", []),
    }


def complete_progress(task_id: str):
    """标记任务完成。"""
    _progress_store[task_id] = {
        "progress": 1.0,
        "stage": "done",
        "status": "completed",
        "errors": _progress_store.get(task_id, {}).get("errors", []),
    }


def fail_progress(task_id: str, error: str):
    """标记任务失败。"""
    existing = _progress_store.get(task_id, {})
    errors = existing.get("errors", [])
    errors.append(error)
    _progress_store[task_id] = {
        "progress": existing.get("progress", 0.0),
        "stage": existing.get("stage", "error"),
        "status": "failed",
        "errors": errors,
    }


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
        max_polls = 300  # 最多轮询 300 次（约 5 分钟）

        while poll_count < max_polls:
            # 检查客户端是否断开
            if await request.is_disconnected():
                break

            state = _progress_store.get(task_id, {})
            current_progress = state.get("progress", 0.0)
            status = state.get("status", "running")
            stage = state.get("stage", "")

            # 发送进度事件（仅在进度变化时）
            if current_progress > last_progress:
                yield f"event: progress\ndata: {json.dumps({'task_id': task_id, 'stage': stage, 'progress': current_progress, 'status': status})}\n\n"
                last_progress = current_progress

            # 完成
            if status == "completed":
                yield f"event: complete\ndata: {json.dumps({'task_id': task_id, 'stage': 'done', 'progress': 1.0})}\n\n"
                break

            # 失败
            if status == "failed":
                errors = state.get("errors", [])
                yield f"event: error\ndata: {json.dumps({'task_id': task_id, 'error': errors[-1] if errors else 'Unknown error'})}\n\n"
                break

            poll_count += 1
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )
