"""
Prometheus 指标采集

定义 Prometheus 指标并暴露 /metrics 端点。
指标命名遵循 crw_ 前缀约定。

Metrics:
- crw_review_total (Counter, by status)
- crw_review_duration_seconds (Histogram)
- crw_agent_call_total (Counter, by agent_type + status)
- crw_agent_call_duration_seconds (Histogram, by agent_type)
- crw_token_usage_total (Counter, by model + tier)
- crw_active_reviews (Gauge)
"""

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

try:
    from prometheus_client import (
        Counter,
        Histogram,
        Gauge,
        REGISTRY,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )
    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False
    # Create stubs so code doesn't crash at import time
    class _NoOpMetric:
        def labels(self, *args, **kwargs):
            return self
        def inc(self, *args, **kwargs):
            pass
        def dec(self, *args, **kwargs):
            pass
        def observe(self, *args, **kwargs):
            pass
        def set(self, *args, **kwargs):
            pass

    class _NoOpRegistry:
        pass

    def _Counter(name, doc, labelnames=None, **kwargs):
        return _NoOpMetric()

    def _Histogram(name, doc, labelnames=None, buckets=None, **kwargs):
        return _NoOpMetric()

    def _Gauge(name, doc, labelnames=None, **kwargs):
        return _NoOpMetric()

    REGISTRY = _NoOpRegistry()

    def _generate_latest(registry):
        return b"# Prometheus client not installed\n"

    Counter = _Counter
    Histogram = _Histogram
    Gauge = _Gauge
    generate_latest = _generate_latest
    CONTENT_TYPE_LATEST = "text/plain"


# ----------------------------------------------------------------
# Metric definitions
# ----------------------------------------------------------------

# Review metrics
crw_review_total = Counter(
    "crw_review_total",
    "Total number of code reviews",
    labelnames=["status"],  # completed / completed_with_errors / failed
)

crw_review_duration_seconds = Histogram(
    "crw_review_duration_seconds",
    "Review duration in seconds",
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

# Agent call metrics
crw_agent_call_total = Counter(
    "crw_agent_call_total",
    "Total number of Agent calls",
    labelnames=["agent_type", "status"],  # style/security/..., success/error
)

crw_agent_call_duration_seconds = Histogram(
    "crw_agent_call_duration_seconds",
    "Agent call duration in seconds",
    labelnames=["agent_type"],
    buckets=[0.5, 1, 5, 10, 30, 60, 120],
)

# Token usage
crw_token_usage_total = Counter(
    "crw_token_usage_total",
    "Total number of tokens used",
    labelnames=["model", "tier"],  # glm-5.2/deepseek-v4/qwen2.5:7b, reasoning/utility
)

# Active reviews gauge
crw_active_reviews = Gauge(
    "crw_active_reviews",
    "Number of currently active reviews",
)


# ----------------------------------------------------------------
# Metrics endpoint helper
# ----------------------------------------------------------------

def metrics_endpoint() -> tuple[bytes, str]:
    """Generate Prometheus metrics text.

    Returns:
        Tuple of (body_bytes, content_type).
    """
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


# ----------------------------------------------------------------
# Context managers for instrumentation
# ----------------------------------------------------------------

@asynccontextmanager
async def track_review_duration() -> AsyncGenerator[None, None]:
    """Async context manager to track review duration."""
    tracker = _ReviewDurationTracker()
    try:
        yield
    finally:
        tracker.finish()


class _ReviewDurationTracker:
    """Tracks a single review's duration."""

    def __init__(self):
        self._start = time.monotonic()

    def finish(self):
        duration = time.monotonic() - self._start
        crw_review_duration_seconds.observe(duration)


@asynccontextmanager
async def track_agent_call(agent_type: str) -> AsyncGenerator[None, None]:
    """Async context manager to track a single Agent call."""
    start = time.monotonic()
    try:
        yield
        crw_agent_call_total.labels(agent_type=agent_type, status="success").inc()
    except Exception:
        crw_agent_call_total.labels(agent_type=agent_type, status="error").inc()
        raise
    finally:
        duration = time.monotonic() - start
        crw_agent_call_duration_seconds.labels(agent_type=agent_type).observe(duration)


def record_token_usage(model: str, tier: str, count: int) -> None:
    """Record token usage for a model call.

    Args:
        model: Model name (e.g. 'glm-5.2').
        tier: 'reasoning' or 'utility'.
        count: Number of tokens used.
    """
    crw_token_usage_total.labels(model=model, tier=tier).inc(count)
