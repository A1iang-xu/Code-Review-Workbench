"""
LLM 统一接入层

封装 LiteLLM，提供统一的模型调用接口。
通过前缀路由分发到不同后端：智谱 (glm/)、DeepSeek (deepseek/)、Ollama (ollama/)。
"""

from typing import Any

import litellm

from app.config import get_settings

settings = get_settings()


class LLMProvider:
    """LLM 统一调用入口。

    封装 LiteLLM，根据模型名前缀自动路由到正确的 API 后端。
    提供 reasoning() 和 utility() 两个快捷方法。
    """

    # ---- 模型前缀 -> API 配置映射 ----
    _PREFIX_MAP = {
        "glm/": {
            "api_base": settings.ZHIPU_BASE_URL,
            "api_key": settings.ZHIPU_API_KEY,
            "custom_llm_provider": "openai",
        },
        "deepseek/": {
            "api_base": settings.DEEPSEEK_BASE_URL,
            "api_key": settings.DEEPSEEK_API_KEY,
            "custom_llm_provider": "openai",
        },
        "ollama/": {
            "api_base": settings.OLLAMA_BASE_URL,
            "api_key": None,  # Ollama 无需 API Key
            "custom_llm_provider": "ollama",
        },
    }

    @classmethod
    def _resolve_model(cls, model: str) -> tuple[str, dict[str, Any]]:
        """解析模型名，返回实际模型名和 API 配置。

        路由规则（按优先级）：
        1. 显式前缀: 'glm/' → 智谱API, 'deepseek/' → DeepSeek API, 'ollama/' → Ollama
        2. 名称检测: 模型名含 'glm' → 智谱, 含 'deepseek' → DeepSeek
        3. 兜底: 其余全部走 Ollama

        Args:
            model: 模型名，如 'glm-5.2'、'ollama/qwen2.5:7b'、'deepseek-v4'

        Returns:
            (actual_model, api_kwargs):
                - actual_model: 发送给 API 的实际模型名
                - api_kwargs: 包含 api_base, api_key, custom_llm_provider 的字典
        """
        # 规则 1: 显式前缀匹配
        for prefix, config in cls._PREFIX_MAP.items():
            if model.startswith(prefix):
                actual = model[len(prefix):]
                return actual, dict(config)

        # 规则 2: 名称检测
        model_lower = model.lower()
        if "glm" in model_lower:
            return model, {
                "api_base": settings.ZHIPU_BASE_URL,
                "api_key": settings.ZHIPU_API_KEY,
                "custom_llm_provider": "openai",
            }
        if "deepseek" in model_lower:
            return model, {
                "api_base": settings.DEEPSEEK_BASE_URL,
                "api_key": settings.DEEPSEEK_API_KEY,
                "custom_llm_provider": "openai",
            }

        # 规则 3: 兜底 → Ollama
        return model, dict(cls._PREFIX_MAP["ollama/"])

    @classmethod
    async def chat(
        cls,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
        **kwargs,
    ) -> Any:
        """通用 LLM 调用方法。

        Args:
            model: 模型名（含可选前缀，如 'ollama/qwen2.5:7b'）
            messages: 消息列表 [{"role": "user", "content": "..."}]
            temperature: 温度参数
            max_tokens: 最大输出 token 数
            stream: 是否流式输出
            **kwargs: 传递给 litellm.acompletion 的额外参数

        Returns:
            litellm 响应对象，或流式生成器
        """
        actual_model, api_kwargs = cls._resolve_model(model)

        return await litellm.acompletion(
            model=actual_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            **api_kwargs,
            **kwargs,
        )

    @classmethod
    async def reasoning(
        cls,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        **kwargs,
    ) -> Any:
        """调用推理模型（默认 GLM-5.2，走智谱 API）。

        用于安全审计、架构分析、重构建议、仲裁汇总等深度推理任务。
        """
        return await cls.chat(
            model=settings.LLM_REASONING_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    @classmethod
    async def utility(
        cls,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        **kwargs,
    ) -> Any:
        """调用工具模型（默认 ollama/qwen2.5:7b，走本地 Ollama）。

        用于风格检查、代码摘要、消息压缩等高频轻量任务。
        """
        return await cls.chat(
            model=settings.LLM_UTILITY_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
