"""The ModelProvider contract. Adapters implement it; nothing else imports a provider SDK."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, Type

from pydantic import BaseModel


@dataclass
class Generation:
    text: str
    provider: str
    model: str
    parsed: Optional[Dict[str, Any]] = None
    usage: Dict[str, int] = field(default_factory=dict)
    provider_request_id: Optional[str] = None


class ModelProvider(Protocol):
    id: str

    async def generate(self, messages: List[Dict[str, str]], *, model: str, timeout: float,
                       temperature: float = 0.3, schema: Optional[Type[BaseModel]] = None) -> Generation: ...

    def stream(self, messages: List[Dict[str, str]], *, model: str, timeout: float,
               temperature: float = 0.3) -> AsyncIterator[str]: ...

    def embed(self, texts: List[str], *, model: str, timeout: float) -> List[List[float]]: ...


def parse_structured(text: str, schema: Optional[Type[BaseModel]]) -> Optional[Dict[str, Any]]:
    """Validate structured output against a shared schema; raise InvalidOutput on mismatch."""
    if schema is None:
        return None
    import json

    from app.services.ai.errors import InvalidOutput
    try:
        return schema.model_validate(json.loads(text)).model_dump()
    except Exception as exc:  # noqa: BLE001
        raise InvalidOutput(type(exc).__name__) from None
