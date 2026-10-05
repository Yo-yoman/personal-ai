"""Text -> vector. Runs locally with fastembed (ONNX), no API key required.
Groq does not offer an embeddings endpoint, so embeddings are computed here.
The model is downloaded once into data/model_cache/ on first use."""
import numpy as np

from backend.config import EMBEDDING_MODEL, MODEL_CACHE_DIR

_model = None


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding  # imported lazily: heavy import

        MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _model = TextEmbedding(model_name=EMBEDDING_MODEL, cache_dir=str(MODEL_CACHE_DIR))
    return _model


def _normalize(vectors: np.ndarray) -> np.ndarray:
    """Unit-length vectors make cosine similarity a plain dot product."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.clip(norms, 1e-12, None)


def embed_documents(texts: list[str]) -> np.ndarray:
    vectors = np.array(list(_get_model().embed(texts)), dtype=np.float32)
    return _normalize(vectors)


def embed_query(text: str) -> np.ndarray:
    # query_embed adds the retrieval instruction prefix that BGE models expect
    vectors = np.array(list(_get_model().query_embed(text)), dtype=np.float32)
    return _normalize(vectors)[0]
