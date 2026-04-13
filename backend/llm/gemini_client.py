from openai import AsyncOpenAI
from llm.base import BaseLLMClient
from core.token_tracker import token_tracker
from utils.logger import log


class GeminiClient(BaseLLMClient):
    """Gemini via OpenAI-compatible API."""
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        self.model = model
        self._feature = ""

    @property
    def provider(self) -> str:
        return "gemini"

    async def complete(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4096) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content or ""

        # 토큰 사용량 추적
        usage = response.usage
        if usage:
            log.info("llm_usage",
                     model=self.model,
                     input_tokens=usage.prompt_tokens,
                     output_tokens=usage.completion_tokens,
                     total_tokens=usage.total_tokens)
            token_tracker.record(
                provider=self.provider,
                model=self.model,
                input_tokens=usage.prompt_tokens or 0,
                output_tokens=usage.completion_tokens or 0,
                total_tokens=usage.total_tokens or 0,
                feature=self._feature,
            )

        return content

    async def embed(self, text: str) -> list[float]:
        response = await self.client.embeddings.create(
            model="text-embedding-004",
            input=text,
        )
        return response.data[0].embedding
