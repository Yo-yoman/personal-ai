"""Central configuration. Secrets come from .env, never from source code."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

DOCUMENTS_DIR = BASE_DIR / "data" / "documents"
MODEL_CACHE_DIR = BASE_DIR / "data" / "model_cache"  # embedding model is downloaded once
FRONTEND_DIR = BASE_DIR / "frontend"

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
MAX_UPLOAD_MB = 10

CHUNK_SIZE = 900      # max characters per chunk
CHUNK_OVERLAP = 150   # characters shared between neighbouring chunks
TOP_K = 5             # chunks retrieved per question
MAX_HISTORY = 8       # previous messages sent to the LLM
MAX_RESPONSE_TOKENS = 220
RESPONSE_TEMPERATURE = 0.1
