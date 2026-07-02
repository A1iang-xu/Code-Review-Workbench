"""
阶段一验收测试脚本

使用 httpx 调用 /health、POST /api/v1/reviews 等端点，
验证 LangGraph 工作流和 StyleChecker Agent 功能。

使用方法：
    pip install httpx
    uvicorn app.main:app --port 8000  (另开终端)
    python tests/test_phase1_manual.py
"""

import asyncio

import httpx

BASE_URL = "http://127.0.0.1:8000"


# ---- 测试 Python 代码（包含长函数以触发 AST 检测） ----
LONG_FUNCTION_CODE = '''
"""
示例：BarChart 渲染器 — 包含超长函数和代码风格问题
"""

import json
from typing import Any


class BarChartRenderer:
    def __init__(self, title: str, data: list):
        self.title = title
        self.Data = data  # 命名不规范：应使用 snake_case

    def render_chart_widget(self, chart_config=None):
        """渲染图表组件
        这个函数故意超过 50 行来触发 StyleChecker 的长函数检测
        """
        result = []
        labels = []
        values = []

        # 第 1 段：数据预处理
        if chart_config is None:
            chart_config = {}

        for i, item in enumerate(self.Data):
            if not isinstance(item, dict):
                continue
            label = item.get("label", f"Item {i}")
            value = item.get("value", 0)
            labels.append(label)
            values.append(value)

        # 第 2 段：配置解析
        bar_width = chart_config.get("barWidth", 30)
        bar_spacing = chart_config.get("barSpacing", 10)
        show_grid = chart_config.get("showGrid", False)
        show_labels = chart_config.get("showLabels", True)
        color_scheme = chart_config.get("colorScheme", "default")
        animation_enabled = chart_config.get("animationEnabled", True)
        animation_duration = chart_config.get("animationDuration", 500)
        max_bars = chart_config.get("maxBars", 50)

        # 第 3 段：数据验证
        if len(values) == 0:
            return {"error": "No valid data"}

        max_value = max(values) if values else 0
        min_value = min(values) if values else 0

        # 第 4 段：构建渲染数据
        for i, (label, value) in enumerate(zip(labels, values)):
            if i >= max_bars:
                break

            # 计算柱状图高度
            if max_value > 0:
                height_ratio = value / max_value
            else:
                height_ratio = 0

            bar_data = {
                "index": i,
                "label": label,
                "value": value,
                "heightRatio": round(height_ratio, 4),
                "x": i * (bar_width + bar_spacing),
                "width": bar_width,
                "color": color_scheme,
                "showLabel": show_labels,
                "animation": {
                    "enabled": animation_enabled,
                    "duration": animation_duration,
                },
            }
            result.append(bar_data)

        # 第 5 段：汇总返回
        summary = {
            "title": self.title,
            "totalBars": len(result),
            "maxValue": max_value,
            "minValue": min_value,
            "showGrid": show_grid,
            "bars": result,
        }
        return summary


class DataProcessor:
    def process(self, data):
        return data
'''


# ---- 规范代码（应返回较少问题） ----
CLEAN_CODE = '''
"""一个简单的计算器模块，函数简短且命名规范"""


def add(a: float, b: float) -> float:
    """返回两数之和。"""
    return a + b


def subtract(a: float, b: float) -> float:
    """返回两数之差。"""
    return a - b


def multiply(a: float, b: float) -> float:
    """返回两数之积。"""
    return a * b


def divide(a: float, b: float) -> float:
    """返回两数之商，除数为零时抛出异常。"""
    if b == 0:
        raise ValueError("除数不能为零")
    return a / b
'''


async def test_health():
    """测试健康检查端点。"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE_URL}/health")
        data = resp.json()
        assert resp.status_code == 200, f"Health check failed: {resp.status_code}"
        assert data["status"] == "ok", f"Unexpected health response: {data}"
        assert data["app"] == "code-review-workbench"
        assert data["env"] == "development"
        print(f"  ✅ GET /health — status={data['status']}")


async def test_review_endpoint():
    """测试 POST /api/v1/reviews 端点。"""
    payload = {
        "files": [
            {"path": "bar_chart.py", "content": LONG_FUNCTION_CODE},
            {"path": "calculator.py", "content": CLEAN_CODE},
        ],
        "repo_url": "",
        "branch": "",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{BASE_URL}/api/v1/reviews", json=payload)
        data = resp.json()
        assert resp.status_code == 200, f"Review request failed: {resp.status_code}"
        assert "task_id" in data
        assert data["status"] in ("completed", "completed_with_errors"), f"Unexpected status: {data['status']}"
        print(f"  ✅ POST /api/v1/reviews — task_id={data['task_id']}")
        print(f"     status={data['status']}")
        print(f"     issues_count={data.get('issues_count', 'N/A')}")
        print(f"     score={data.get('score', 'N/A')}")

        if data.get("summary"):
            summary = data["summary"]
            if len(summary) > 200:
                summary = summary[:200] + "..."
            print(f"     summary={summary}")

        return data


async def test_llm():
    """测试 POST /api/test/llm 端点。"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{BASE_URL}/api/test/llm")
        data = resp.json()

        reasoning = data.get("reasoning", {})
        utility = data.get("utility", {})

        print("  ✅ POST /api/test/llm")
        print(f"     reasoning ({reasoning.get('model')}): {reasoning.get('status')}")
        if reasoning.get("status") == "error":
            print(f"       error: {reasoning.get('error')[:100]}")
        else:
            print(f"       response: {reasoning.get('response', '')[:80]}")

        print(f"     utility   ({utility.get('model')}): {utility.get('status')}")
        if utility.get("status") == "error":
            print(f"       error: {utility.get('error')[:100]}")
        else:
            print(f"       response: {utility.get('response', '')[:80]}")


async def main():
    print("=" * 60)
    print("Code Review Workbench — 阶段一验收测试")
    print("=" * 60)
    print(f"服务地址: {BASE_URL}")
    print()

    passed = 0
    failed = 0

    # 测试 1: 健康检查
    print("--- 1. 健康检查 (/health) ---")
    try:
        await test_health()
        passed += 1
    except httpx.ConnectError:
        print("  ❌ 无法连接到服务，请确认后端已启动:")
        print("     uvicorn app.main:app --reload --port 8000")
        print()
        print("=" * 60)
        print("测试终止：后端未启动")
        print("=" * 60)
        return
    except AssertionError as e:
        print(f"  ❌ 断言失败: {e}")
        failed += 1

    print()

    # 测试 2: 审查端点
    print("--- 2. 代码审查 (POST /api/v1/reviews) ---")
    try:
        await test_review_endpoint()
        passed += 1
    except AssertionError as e:
        print(f"  ❌ 断言失败: {e}")
        failed += 1
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        failed += 1

    print()

    # 测试 3: LLM 连通性
    print("--- 3. LLM 连通性 (POST /api/test/llm) ---")
    try:
        await test_llm()
        passed += 1
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        failed += 1

    print()
    print("=" * 60)
    print(f"测试完成: {passed} 通过, {failed} 失败")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
