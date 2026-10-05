"""In-memory vector store + cosine-similarity retrieval. No database involved."""
import logging
import threading
from pathlib import Path

import numpy as np

from backend.config import ALLOWED_EXTENSIONS, DOCUMENTS_DIR
from backend.services.document_processor import process_file
from backend.services.embeddings import embed_documents, embed_query

log = logging.getLogger("rag")


class RAGEngine:
    def __init__(self) -> None:
        # Each item: {"text": str, "embedding": np.ndarray, "metadata": {...}}
        self.chunks: list[dict] = []
        self._lock = threading.Lock()

    def ingest_file(self, path: Path) -> int:
        """Extract -> chunk -> embed -> store in memory. Returns number of chunks."""
        chunks = process_file(path)
        if not chunks:
            raise ValueError("No readable text found (scanned/image-only PDFs are not supported).")
        embeddings = embed_documents([c["text"] for c in chunks])
        for chunk, vector in zip(chunks, embeddings):
            chunk["embedding"] = vector
        with self._lock:  # replace any previous version of the same file
            self.chunks = [c for c in self.chunks if c["metadata"]["filename"] != path.name] + chunks
        return len(chunks)

    def remove(self, filename: str) -> None:
        with self._lock:
            self.chunks = [c for c in self.chunks if c["metadata"]["filename"] != filename]

    def load_all(self) -> None:
        """Rebuild the in-memory index from data/documents/ (runs at startup)."""
        for path in sorted(DOCUMENTS_DIR.iterdir()):
            if path.suffix.lower() in ALLOWED_EXTENSIONS:
                try:
                    n = self.ingest_file(path)
                    log.info("Indexed %s (%d chunks)", path.name, n)
                except Exception as exc:  # one bad file must not block the rest
                    log.warning("Could not index %s: %s", path.name, exc)

    def list_documents(self) -> list[dict]:
        with self._lock:
            snapshot = list(self.chunks)
        docs: dict[str, dict] = {}
        for c in snapshot:
            meta = c["metadata"]
            d = docs.setdefault(meta["filename"], {"filename": meta["filename"], "chunks": 0, "pages": set()})
            d["chunks"] += 1
            d["pages"].add(meta["page"] or 1)
        result = []
        for d in docs.values():
            file = DOCUMENTS_DIR / d["filename"]
            size = file.stat().st_size / 1024 if file.exists() else 0
            result.append({"filename": d["filename"], "chunks": d["chunks"],
                           "pages": len(d["pages"]), "size_kb": round(size, 1)})
        return sorted(result, key=lambda x: x["filename"].lower())

    def retrieve(self, query: str, k: int) -> tuple[list[dict], np.ndarray | None]:
        """Embed the query, score every chunk by cosine similarity, return the top k."""
        with self._lock:
            snapshot = list(self.chunks)
        if not snapshot:
            return [], None
        query_vec = embed_query(query)
        matrix = np.vstack([c["embedding"] for c in snapshot])
        scores = matrix @ query_vec  # unit vectors: dot product == cosine similarity
        top = np.argsort(scores)[::-1][:k]
        hits = [{"rank": rank + 1, "score": float(scores[i]),
                 "text": snapshot[i]["text"], "metadata": snapshot[i]["metadata"]}
                for rank, i in enumerate(top)]
        return hits, query_vec


rag_engine = RAGEngine()
