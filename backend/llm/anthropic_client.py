from anthropic import AsyncAnthropic
from llm.base import BaseLLMClient
from core.token_tracker import token_tracker
from utils.logger import log


class AnthropicClient(BaseLLMClient):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self._feature = ""

    @property
    def provider(self) -> str:
        return "anthropic"

    async def complete(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4096) -> str:
        # Extract system message
        system = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                chat_messages.append(m)

        kwargs = dict(
            model=self.model,
            messages=chat_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if system:
            kwargs["system"] = system

        response = await self.client.messages.create(**kwargs)
        content = response.content[0].text

        # 토큰 사용량 추적
        usage = response.usage
        if usage:
            input_tokens = usage.input_tokens or 0
            output_tokens = usage.output_tokens or 0
            total = input_tokens + output_tokens
            log.info("llm_usage",
                     model=self.model,
                     input_tokens=input_tokens,
                     output_tokens=output_tokens,
                     total_tokens=total)
            token_tracker.record(
                provider=self.provider,
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total,
                feature=self._feature,
            )

        return content

    async def embed(self, text: str) -> list[float]:
        # Anthropic doesn't have embedding API, use sentence-transformers
        from utils.embedder import Embedder
        return Embedder.embed_single(text)
