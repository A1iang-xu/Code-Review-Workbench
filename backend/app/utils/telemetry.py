"""
OpenTelemetry 链路追踪

提供 setup_telemetry() 配置全链路追踪：
- FastAPI 自动注入 (FastAPIInstrumentor)
- HTTPX 外部调用追踪 (HTTPXClientInstrumentor)
- 自定义 Agent Span (trace_agent 装饰器)
"""

import functools
from typing import Callable, Any

from fastapi import FastAPI

from app.config import get_settings

settings = get_settings()

# Global TracerProvider flag
_initialized = False


# ----------------------------------------------------------------
# Setup
# ----------------------------------------------------------------

def setup_telemetry(app: FastAPI, service_name: str = "code-review-workbench") -> None:
    """Configure OpenTelemetry tracing.

    Creates a TracerProvider with OTLP gRPC exporter and sets it as global.
    Instruments FastAPI and HTTPX.

    Args:
        app: FastAPI application instance.
        service_name: Service name for traces (default: code-review-workbench).
    """
    global _initialized
    if _initialized:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        # Resource
        resource = Resource.create({SERVICE_NAME: service_name})

        # TracerProvider
        provider = TracerProvider(resource=resource)

        # OTLP gRPC exporter
        endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))

        # Set global
        trace.set_tracer_provider(provider)

        # Auto-instrument FastAPI
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)

        # Auto-instrument HTTPX
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
            HTTPXClientInstrumentor().instrument()
        except ImportError:
            pass  # httpx instrumentation not available

        _initialized = True
        print(f"[Telemetry] OpenTelemetry 已配置 — endpoint: {endpoint}")

    except ImportError as e:
        print(f"[Telemetry] OpenTelemetry SDK 未安装, 跳过追踪配置: {e}")
    except Exception as e:
        print(f"[Telemetry] 配置失败: {e}")


# ----------------------------------------------------------------
# trace_agent decorator
# ----------------------------------------------------------------

def trace_agent(agent_type: str) -> Callable:
    """Decorator to create a custom span for an Agent invocation.

    Usage:
        @trace_agent("style")
        async def review(self, parsed_files):
            ...

    The span is named 'agent.{agent_type}' and carries attributes:
    - agent.type: the agent type string
    - findings_count: number of findings returned

    Args:
        agent_type: Agent type string (e.g. 'style', 'security').

    Returns:
        Decorated async function.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            from opentelemetry import trace

            tracer = trace.get_tracer(__name__)
            span_name = f"agent.{agent_type}"

            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute("agent.type", agent_type)

                try:
                    result = await func(*args, **kwargs)

                    # Record findings count
                    if isinstance(result, list):
                        span.set_attribute("findings_count", len(result))

                    return result

                except Exception as e:
                    span.set_attribute("error", str(e))
                    span.set_attribute("error.type", type(e).__name__)
                    raise

        return wrapper
    return decorator
