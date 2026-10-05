"""Groq streaming wrapper."""
from typing import AsyncIterator

from groq import AsyncGroq

from backend.config import (GROQ_API_KEY, GROQ_MODEL, MAX_RESPONSE_TOKENS,
                            RESPONSE_TEMPERATURE)

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client
    if not GROQ_API_KEY or GROQ_API_KEY == "your_api_key":
        raise RuntimeError("GROQ_API_KEY is not set. Add your key to the .env file and restart the server.")
    if _client is None:
        _client = AsyncGroq(api_key=GROQ_API_KEY)
    return _client


async def stream_completion(messages: list[dict]) -> AsyncIterator[str]:
    """Yield text deltas as Groq generates them (real streaming)."""
    try:
        stream = await _get_client().chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=RESPONSE_TEMPERATURE,
            max_tokens=MAX_RESPONSE_TOKENS,
            stream=True,
        )
    except Exception as exc:
        msg = str(exc)
        if "model_not_found" in msg.lower() or "does not exist or you do not have access" in msg.lower():
            raise RuntimeError(
                f"Groq model '{GROQ_MODEL}' is unavailable for this API key. "
                "Check your Groq account access and update GROQ_MODEL in .env to a model enabled for your account."
            ) from exc
        raise
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
