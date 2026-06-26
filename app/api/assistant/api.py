import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from openai import OpenAI
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class ChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class AssistantChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    systemPrompt: Optional[str] = None
    history: List[ChatHistoryItem] = Field(default_factory=list)


class AssistantChatResponse(BaseModel):
    reply: str


@router.post("/chat", response_model=AssistantChatResponse)
async def assistant_chat(body: AssistantChatRequest) -> AssistantChatResponse:
    """Lightweight text chat for the floating MyOS assistant (OpenAI gpt-4o-mini)."""
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured on the server",
        )

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (body.systemPrompt or "").strip()
            or "You are a helpful AI training assistant for ProfSidekick subscribers.",
        },
    ]
    for item in body.history[-8:]:
        messages.append({"role": item.role, "content": item.text})
    messages.append({"role": "user", "content": body.message.strip()})

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=400,
            temperature=0.7,
        )
        reply = (response.choices[0].message.content or "").strip()
        if not reply:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Empty model response",
            )
        return AssistantChatResponse(reply=reply)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("assistant chat failed: %s", exc)
        error_text = str(exc).lower()
        if "insufficient_quota" in error_text or "quota" in error_text:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="OpenAI quota exceeded. Please add billing/credits to the OpenAI account or use a key from an account with available quota.",
            ) from exc
        if "invalid_api_key" in error_text or "incorrect api key" in error_text:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid OpenAI API key. Please create a new key and update OPENAI_API_KEY.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reach OpenAI",
        ) from exc
