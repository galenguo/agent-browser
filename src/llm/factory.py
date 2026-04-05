import os
from typing import Optional
from browser_use.llm.openai.chat import ChatOpenAI as BrowserUseChatOpenAI
from langchain_anthropic import ChatAnthropic


class LLMFactory:
    """统一的 LLM 创建工厂"""

    @staticmethod
    def create(
        provider: str = "openai",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.1,
        **kwargs
    ):
        """创建 LLM 实例"""
        if provider == "openai":
            # 检测是否为 glm-5-turbo 模型，需要特殊配置
            model_name = model or os.getenv("LLM_MODEL") or "gpt-4"
            is_glm = "glm" in model_name.lower()

            # 使用 browser-use 的 ChatOpenAI，它原生支持 output_format
            llm = BrowserUseChatOpenAI(
                model=model_name,
                api_key=api_key or os.getenv("OPENAI_API_KEY"),
                base_url=base_url or os.getenv("OPENAI_BASE_URL"),
                temperature=temperature,
                # glm-5-turbo 兼容性配置
                remove_min_items_from_schema=is_glm,  # 移除 minItems 约束
                remove_defaults_from_schema=is_glm,   # 移除默认值
            )
            return llm
        elif provider == "anthropic":
            # Anthropic 仍使用 LangChain，需要包装
            llm = ChatAnthropic(
                model=model or "claude-3-5-sonnet-20241022",
                api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
                base_url=base_url or os.getenv("ANTHROPIC_BASE_URL"),
                temperature=temperature,
            )
            # 需要为 Anthropic 创建适配器
            return llm
        else:
            raise ValueError(f"不支持的 LLM 提供商: {provider}")
