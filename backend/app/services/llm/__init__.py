from app.models import User
from app.services.llm.base import GroundedResult, LLMError, LLMProvider

__all__ = ["GroundedResult", "LLMError", "LLMProvider", "get_llm"]

# Claude is the coach through the MCP server, so the app itself has no model and uses its rule-based fallbacks.
# Tests replace this to inject a fake provider and exercise the model-backed paths.
_override: LLMProvider | None = None


def set_llm_override(provider: LLMProvider | None) -> None:
    global _override
    _override = provider


def get_llm(user: User | None) -> LLMProvider | None:
    return _override
