from llm.base import BaseLLMClient


def get_llm_client(
    provider: str,
    api_key: str,
    model: str = "",
    base_url: str | None = None,
    feature: str = "",
) -> BaseLLMClient:
    """Create LLM client from frontend-provided config.

    Args:
        feature: Usage tracking label (e.g. "simulation", "db_chat", "persona_chat")
    """
    client: BaseLLMClient
    if provider == "openai":
        from llm.openai_client import OpenAIClient
        client = OpenAIClient(api_key=api_key, model=model or "gpt-4o", base_url=base_url)
    elif provider == "anthropic":
        from llm.anthropic_client import AnthropicClient
        client = AnthropicClient(api_key=api_key, model=model or "claude-sonnet-4-20250514")
    elif provider == "gemini":
        from llm.gemini_client import GeminiClient
        client = GeminiClient(api_key=api_key, model=model or "gemini-2.5-flash")
    elif provider == "qwen":
        from llm.qwen_client import QwenClient
        client = QwenClient(api_key=api_key, model=model or "qwen-plus")
    elif provider == "custom":
        from llm.openai_client import OpenAIClient
        if not base_url:
            raise ValueError("Custom provider requires base_url")
        client = OpenAIClient(api_key=api_key, model=model, base_url=base_url)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    client._feature = feature
    return client
