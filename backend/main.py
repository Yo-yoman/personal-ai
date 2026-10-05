"""FastAPI app: document management, health and streaming chat."""
import asyncio
import logging
import re
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.config import (ALLOWED_EXTENSIONS, DOCUMENTS_DIR, EMBEDDING_MODEL, FRONTEND_DIR,
                            GROQ_API_KEY, GROQ_MODEL, MAX_UPLOAD_MB)
from backend.models import ChatRequest, DocumentInfo, UploadResponse
from backend.services.chat_service import stream_chat
from backend.services.rag import rag_engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
state = {"rag_ready": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

    async def warm_up() -> None:  # rebuild embeddings from data/documents/ in the background
        try:
            await asyncio.to_thread(rag_engine.load_all)
        except Exception:
            logging.exception("Failed to index existing documents at startup")
            raise
        finally:
            state["rag_ready"] = True

    task = asyncio.create_task(warm_up())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Personal AI Chatbot", lifespan=lifespan)


def safe_filename(name: str) -> str:
    name = Path(name or "").name
    return re.sub(r"[^\w.\- ]", "_", name).strip() or "document"


@app.get("/api/health")
async def health() -> dict:
    docs = rag_engine.list_documents()
    return {"status": "ok", "rag_ready": state["rag_ready"], "documents": len(docs),
            "chunks": sum(d["chunks"] for d in docs), "embedding_model": EMBEDDING_MODEL,
            "llm_model": GROQ_MODEL, "groq_configured": bool(GROQ_API_KEY and GROQ_API_KEY != "your_api_key")}


@app.get("/api/documents", response_model=list[DocumentInfo])
async def list_documents() -> list[dict]:
    return rag_engine.list_documents()


@app.post("/api/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...)) -> UploadResponse:
    filename = safe_filename(file.filename)
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "Only PDF, DOCX and TXT files are supported.")
    content = await file.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {MAX_UPLOAD_MB} MB.")
    if not content:
        raise HTTPException(400, "The file is empty.")

    path = DOCUMENTS_DIR / filename
    path.write_bytes(content)
    try:
        chunks = await asyncio.to_thread(rag_engine.ingest_file, path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(422, f"Could not process {filename}: {exc}")
    return UploadResponse(filename=filename, chunks=chunks, message=f"Indexed {chunks} chunks")


@app.delete("/api/documents/{filename}")
async def delete_document(filename: str) -> dict:
    if safe_filename(filename) != filename:
        raise HTTPException(400, "Invalid filename.")
    path = DOCUMENTS_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Document not found.")
    path.unlink()
    rag_engine.remove(filename)
    return {"deleted": filename}


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """Server-Sent Events: tokens are forwarded the moment Groq produces them."""
    return StreamingResponse(
        stream_chat(req, rag_engine),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# Must be registered last so it doesn't shadow the /api routes
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    logging.warning("Frontend directory %s does not exist; only API routes are available.", FRONTEND_DIR)
