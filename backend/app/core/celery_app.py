"""
Celery 应用配置

使用 Redis 作为 broker 和 result backend。
审查任务通过 Celery 异步执行，解决 BackgroundTasks 在进程重启时丢失任务的问题。

Usage:
    # 启动 worker（开发环境）
    celery -A app.core.celery_app worker --loglevel=info --concurrency=4

    # 提交任务
    from app.core.tasks import run_review_task
    result = run_review_task.delay(task_id, request_data, started_at)
"""

from celery import Celery

from app.config import get_settings

settings = get_settings()

# Celery 实例
celery_app = Celery(
    "code_review_workbench",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.core.tasks"],
)

# ---- 配置 ----
celery_app.conf.update(
    # 序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # 任务路由
    task_routes={
        "app.core.tasks.run_review_task": {"queue": "review"},
    },
    # 默认队列
    task_default_queue="review",
    # 可靠性：任务确认机制
    task_acks_late=True,          # 任务完成后才确认（防止 worker 崩溃丢失任务）
    task_reject_on_worker_lost=True,  # worker 异常退出时拒绝任务（重新入队）
    worker_prefetch_multiplier=1,     # 每次只预取 1 个任务（长任务场景更公平）
    # 结果过期时间（7 天）
    result_expires=7 * 24 * 60 * 60,
    # 任务超时（秒）— 审查任务最长 10 分钟
    task_time_limit=600,
    task_soft_time_limit=540,
)
