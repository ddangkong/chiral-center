from abc import ABC, abstractmethod


class BaseLLMClient(ABC):
    _feature: str = ""  # 토큰 추적용 기능 라벨

    @property
    @abstractmethod
    def provider(self) -> str:
        pass

    @abstractmethod
    async def complete(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4096) -> str:
        pass

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        pass
