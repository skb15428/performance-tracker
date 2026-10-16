import json
import logging

from google import genai
from google.genai import types
from pydantic import ValidationError

from app.services.llm.base import GroundedResult, LLMError, LLMProvider, T

log = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    async def complete_json(self, system: str, prompt: str, schema: type[T]) -> T:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.4,
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
        )
        last_err: Exception | None = None
        for _ in range(2):
            try:
                resp = await self.client.aio.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                return schema.model_validate(json.loads(resp.text or ""))
            except (ValidationError, json.JSONDecodeError) as e:
                last_err = e
                log.warning("Gemini returned invalid JSON, retrying: %s", e)
            except Exception as e:  # network, quota, safety blocks
                raise LLMError(str(e)) from e
        raise LLMError(f"Invalid JSON from model: {last_err}")

    async def search_grounded(self, query: str) -> GroundedResult:
        config = types.GenerateContentConfig(
            temperature=0.3, tools=[types.Tool(google_search=types.GoogleSearch())]
        )
        try:
            resp = await self.client.aio.models.generate_content(model=self.model, contents=query, config=config)
        except Exception as e:
            raise LLMError(str(e)) from e
        sources: list[dict] = []
        for cand in resp.candidates or []:
            meta = cand.grounding_metadata
            for chunk in (meta.grounding_chunks or []) if meta else []:
                if chunk.web and chunk.web.uri:
                    sources.append({"title": chunk.web.title or chunk.web.domain or "", "url": chunk.web.uri})
        return GroundedResult(text=resp.text or "", sources=sources)
