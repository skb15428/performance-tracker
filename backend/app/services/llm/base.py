from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Raised when the provider fails or returns unusable output. Callers fall back to rules."""


@dataclass
class GroundedResult:
    text: str
    sources: list[dict] = field(default_factory=list)  # [{title, url}]


class LLMProvider(ABC):
    @abstractmethod
    async def complete_json(self, system: str, prompt: str, schema: type[T]) -> T:
        """Return the model's answer parsed into `schema`."""

    @abstractmethod
    async def search_grounded(self, query: str) -> GroundedResult:
        """Answer `query` using live web search, returning text plus cited sources."""
