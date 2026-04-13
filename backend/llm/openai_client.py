from openai import AsyncOpenAI
from llm.base import BaseLLMClient
from core.token_tracker import token_tracker
from utils.logger import log


class OpenAIClient(BaseLLMClient):
    def __init__(self, api_key: str, model: str = "gpt-4o", base_url: str | None = None):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self._feature = ""  # 호출 컨텍스트 (simulation, db_chat 등)

    @property
    def provider(self) -> str:
        return "openai"

    def _is_reasoning_model(self) -> bool:
        """Reasoning models: o-series + gpt-5.x (all use internal chain-of-thought).
        These: no temperature, use max_completion_tokens with large budget."""
        return any(self.model.startswith(p) for p in ("o1", "o3", "o4", "gpt-5"))

    def _is_new_gpt(self) -> bool:
        """GPT-4.1 uses max_completion_tokens + temperature."""
        return self.model.startswith("gpt-4.1")

    async def complete(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4096) -> str:
        kwargs: dict = {"model": self.model, "messages": messages}

        if self._is_reasoning_model():
            kwargs["max_completion_tokens"] = max_tokens * 2
        elif self._is_new_gpt():
            kwargs["max_completion_tokens"] = max_tokens
            kwargs["temperature"] = temperature
        else:
            kwargs["max_tokens"] = max_tokens
            kwargs["temperature"] = temperature

        log.info("openai_call", model=self.model, tokens=max_tokens, temp=temperature)

        response = await self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""

        # 토큰 사용량 로깅 + 추적
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

        if not content:
            log.warning("openai_empty_response",
                        model=self.model,
                        finish_reason=response.choices[0].finish_reason,
                        usage=str(response.usage))

        return content

    async def embed(self, text: str) -> list[float]:
        response = await self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding
