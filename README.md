# Personal AI Chatbot

Ask questions about the person represented by this assistant. Answers are grounded in the configured profile and streamed live from Groq. The profile stays out of the visitor-facing interface. No database: files on disk + vectors in Python memory + chats in browser `localStorage`.

## Run it

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
# put your key in .env  ->  GROQ_API_KEY=gsk_...
uvicorn backend.main:app --reload
```

Open http://127.0.0.1:8000 and start chatting. The server indexes the configured profile when it starts.
The first start downloads the small embedding model (~130 MB) into `data/model_cache/`. After that it works offline for embeddings. Get a free Groq key at https://console.groq.com.

## Deploy to Render

This project includes a Docker-based Render Blueprint in `render.yaml`.

1. Push the project to a **private** GitHub repository. The profile PDF is included in the app's data, so avoid making the repository public.
2. In Render, choose **New > Blueprint** and connect that repository.
3. Set the required `GROQ_API_KEY` when prompted, then apply the Blueprint.
4. Open the service URL Render provides.

The Blueprint uses Render's free web service plan. Free services can sleep when idle, and their filesystem and in-memory vector index are not persistent. On a cold start, the app downloads the embedding model and rebuilds the index from the bundled profile document, so the first request after sleeping or restarting may take longer. Do not commit `.env`; add secrets through Render's environment settings.

## How it works

```
Preloaded profile -> extract text (pypdf) -> clean -> chunk (900 chars, 150 overlap)
                 -> embed (fastembed, BAAI/bge-small-en-v1.5) -> kept in memory, file kept in data/documents/

Question -> query embedding -> cosine similarity vs. every chunk -> top 5 -> context
         -> Groq (stream=True) -> FastAPI SSE -> browser renders tokens as they arrive
```

On startup the server re-reads `data/documents/` and rebuilds the in-memory index in the background (the status pill shows "Indexing documents…").

| File | Role |
|---|---|
| `backend/main.py` | API routes, startup indexing |
| `backend/services/document_processor.py` | extract, clean, chunk |
| `backend/services/embeddings.py` | local embedding model |
| `backend/services/rag.py` | in-memory store + cosine retrieval |
| `backend/services/llm.py` | Groq streaming |
| `backend/services/chat_service.py` | prompt, anti-hallucination rules, SSE events |

## API

`POST /api/upload` · `GET /api/documents` · `DELETE /api/documents/{filename}` · `POST /api/chat` (SSE) · `GET /api/health`

SSE events from `/api/chat`: `sources`, `debug` (only when enabled), `token`, `done`, `error`.

## Debug RAG

Turn on **Debug RAG** in the sidebar. Each answer then shows the question, query embedding, retrieved chunks with similarity scores, the exact context sent to the LLM, and the model used.

## Settings

Edit `backend/config.py` (chunk size, `TOP_K`, upload limit) or set `GROQ_MODEL` / `EMBEDDING_MODEL` in `.env`.

## Notes

- Scanned/image-only PDFs have no extractable text and are rejected (no OCR).
- The chat interface does not display the configured profile or offer document uploads or deletion.
- Hallucination control is a strict system prompt plus a low temperature. If the profile does not contain an answer, the model says it can answer questions about the person the assistant represents but lacks enough information for that question.
