from collections import defaultdict, deque

from app.services.llm.base import GroundedResult, LLMError, LLMProvider


class FakeProvider(LLMProvider):
    """Returns queued responses per output schema. Queue a callable to build the answer from the prompt."""

    def __init__(self):
        self.queues: dict[str, deque] = defaultdict(deque)
        self.prompts: list[tuple[str, str]] = []
        self.grounded = GroundedResult(text="", sources=[])

    def queue(self, schema_name: str, response) -> None:
        self.queues[schema_name].append(response)

    async def complete_json(self, system, prompt, schema):
        self.prompts.append((schema.__name__, prompt))
        q = self.queues[schema.__name__]
        if not q:
            raise LLMError(f"No fake response queued for {schema.__name__}")
        resp = q.popleft()
        if callable(resp):
            resp = resp(prompt)
        return schema.model_validate(resp)

    async def search_grounded(self, query):
        self.prompts.append(("grounded", query))
        return self.grounded
