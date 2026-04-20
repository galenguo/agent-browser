"""LLM factory -- unified LLM instance creation for OpenAI, Anthropic, and GLM providers.

Wraps browser-use's ChatOpenAI for OpenAI/GLM models (native output_format support)
and LangChain's ChatAnthropic for Anthropic models.

All optional dependencies are imported lazily so that ``pip install stealth-browser``
works without ``[full]`` extra.
"""

import os


class LLMFactory:
    """Unified LLM creation factory."""

    @staticmethod
    def create(
        provider: str = "openai",
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.1,
        **kwargs,
    ):
        """Create an LLM instance.

        Args:
            provider: LLM provider name ("openai", "anthropic")
            model: Model name (defaults to env var or "gpt-4")
            api_key: API key (defaults to env var)
            base_url: Base URL (defaults to env var)
            temperature: Sampling temperature

        Returns:
            Configured LLM instance

        Raises:
            ValueError: If provider is not supported
            ImportError: If provider's dependencies are not installed
        """
        if provider == "openai":
            from browser_use.llm.openai.chat import ChatOpenAI as BrowserUseChatOpenAI

            model_name = model or os.getenv("LLM_MODEL") or "gpt-4"
            is_glm = "glm" in model_name.lower()

            return BrowserUseChatOpenAI(
                model=model_name,
                api_key=api_key or os.getenv("OPENAI_API_KEY"),
                base_url=base_url or os.getenv("OPENAI_BASE_URL"),
                temperature=temperature,
                remove_min_items_from_schema=is_glm,
                remove_defaults_from_schema=is_glm,
            )
        if provider == "anthropic":
            try:
                from langchain_anthropic import ChatAnthropic
            except ImportError:
                raise ImportError(
                    "anthropic provider requires 'langchain-anthropic'. Install with: pip install stealth-browser[full]"
                ) from None

            return ChatAnthropic(
                model=model or "claude-3-5-sonnet-20241022",
                api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
                base_url=base_url or os.getenv("ANTHROPIC_BASE_URL"),
                temperature=temperature,
            )
        raise ValueError(f"Unsupported LLM provider: {provider}")
