"""Chat pipeline: retrieve -> build prompt -> stream Groq -> emit SSE events."""
import asyncio
import json
from typing import AsyncIterator

import numpy as np

from backend.config import EMBEDDING_MODEL, GROQ_MODEL, MAX_HISTORY, TOP_K
from backend.models import ChatRequest, HistoryMessage
from backend.services.llm import stream_completion
from backend.services.rag import RAGEngine

NO_INFO = "I can answer questions about the person this assistant represents, but I don't have enough information for that."
NO_DOCS = "This assistant's profile information isn't available right now."

SYSTEM_PROMPT = f"""You answer questions about the person described in the profile excerpts below. \
Those excerpts are your ONLY source of facts about that person.

Rules:
1. Answer ONLY with facts present in the excerpts. Never use outside knowledge to add personal details.
2. Never invent or guess skills, projects, companies, internships, certifications, achievements, education or experience.
3. If asked about the profile subject's romantic life, dating, girlfriend/boyfriend, crushes, or romantic relationships, reply: "He isn't interested in those things." Do not speculate or provide personal details. This rule takes priority over the other rules.
4. If the question is unrelated to the profile or the excerpts do not contain the answer, reply exactly: "{NO_INFO}"
5. If the excerpts answer only part of the question, answer that part and say what information is missing.
6. Refer to the person in the profile in the third person. Never imply the visitor is that person.
7. Do not mention a resume, document, or the visitor's personal information. Use Markdown (short lists, bold for key terms) when it helps.
8. Keep the answer concise, warm, and easy to read: aim for 2-4 sentences or a very short bullet list, not a long essay.
9. Be friendly and polished, like a helpful personal assistant; avoid vague filler and do not repeat the same point multiple times.
10. You may explain or elaborate on things the profile mentions, but stay faithful to it and keep the whole response brief.

Document excerpts:
{{context}}"""


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def retrieval_query(question: str, history: list[HistoryMessage]) -> str:
    """Short follow-ups ("and the second one?") are embedded together with the previous question."""
    if len(question.split()) < 6:
        previous = [m.content for m in history if m.role == "user"]
        if previous:
            return f"{previous[-1]} {question}"
    return question


def build_context(hits: list[dict]) -> str:
    blocks = []
    for i, h in enumerate(hits, 1):
        meta = h["metadata"]
        where = "Profile" + (f", page {meta['page']}" if meta["page"] else "")
        blocks.append(f"[Excerpt {i} - {where}]\n{h['text']}")
    return "\n\n".join(blocks)


def build_messages(req: ChatRequest, context: str) -> list[dict]:
    # str.replace (not .format) so braces inside the resume text can't break the prompt
    system = SYSTEM_PROMPT.replace("{context}", context)
    messages = [{"role": "system", "content": system}]
    messages += [m.model_dump() for m in req.history[-MAX_HISTORY:]]
    messages.append({"role": "user", "content": req.message})
    return messages


async def stream_chat(req: ChatRequest, rag: RAGEngine) -> AsyncIterator[str]:
    """Yields SSE strings. Event types: sources, debug, token, done, error."""
    try:
        query = retrieval_query(req.message, req.history)
        # Embedding is CPU-bound, so run it off the event loop
        hits, query_vec = await asyncio.to_thread(rag.retrieve, query, TOP_K)

        if not hits:
            yield sse({"type": "token", "text": NO_DOCS})
            yield sse({"type": "done"})
            return

        yield sse({"type": "sources", "sources": [
            {"filename": h["metadata"]["filename"], "page": h["metadata"]["page"],
             "chunk_index": h["metadata"]["chunk_index"], "score": round(h["score"], 4),
             "preview": h["text"][:240]} for h in hits]})

        context = build_context(hits)
        messages = build_messages(req, context)

        if req.debug:
            yield sse({"type": "debug", "debug": {
                "question": req.message,
                "retrieval_query": query,
                "embedding": {"model": EMBEDDING_MODEL, "dimensions": int(len(query_vec)),
                              "norm": round(float(np.linalg.norm(query_vec)), 4),
                              "preview": [round(float(x), 4) for x in query_vec[:8]]},
                "chunks": [{"rank": h["rank"], "score": round(h["score"], 4), "text": h["text"],
                            "filename": h["metadata"]["filename"], "page": h["metadata"]["page"]} for h in hits],
                "context": context,
                "llm": {"model": GROQ_MODEL, "messages": len(messages)}}})

        async for text in stream_completion(messages):
            yield sse({"type": "token", "text": text})
        yield sse({"type": "done"})
    except Exception as exc:
        yield sse({"type": "error", "message": str(exc)})
