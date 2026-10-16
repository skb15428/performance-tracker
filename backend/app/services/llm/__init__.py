from app.core.config import get_settings
from app.core.security import decrypt
from app.models import User
from app.services.llm.base import GroundedResult, LLMError, LLMProvider

__all__ = ["GroundedResult", "LLMError", "LLMProvider", "get_llm"]

# Tests replace this to inject a fake provider.
_override: LLMProvider | None = None


def set_llm_override(provider: LLMProvider | None) -> None:
    global _override
    _override = provider


def get_llm(user: User | None) -> LLMProvider | None:
    """Return a provider for this user (their own key first, then the server key), or None."""
    if _override is not None:
        return _override
    settings = get_settings()
    key = (decrypt(user.gemini_key_enc) if user else None) or settings.gemini_api_key
    if not key:
        return None
    if settings.llm_provider == "gemini":
        from app.services.llm.gemini import GeminiProvider

        return GeminiProvider(api_key=key, model=settings.gemini_model)
    raise ValueError(f"Unknown LLM provider {settings.llm_provider}")
