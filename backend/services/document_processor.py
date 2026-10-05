"""File -> pages -> cleaned text -> overlapping chunks."""
import re
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from backend.config import CHUNK_OVERLAP, CHUNK_SIZE


def extract_pages(path: Path) -> list[tuple[int | None, str]]:
    """Return [(page_number, raw_text)]. DOCX/TXT have no pages, so page is None."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        reader = PdfReader(str(path))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    if ext == ".docx":
        doc = Document(str(path))
        lines = [p.text for p in doc.paragraphs]
        for table in doc.tables:  # resumes often keep skills/experience in tables
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    lines.append(" | ".join(cells))
        return [(None, "\n".join(lines))]
    if ext == ".txt":
        return [(None, path.read_text(encoding="utf-8", errors="ignore"))]
    raise ValueError(f"Unsupported file type: {ext}")


def clean_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)      # re-join words hyphenated across lines
    text = re.sub(r"[ \t\u00a0]+", " ", text)         # collapse spaces
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split_long_line(line: str, size: int) -> list[str]:
    """Split a very long line on sentence ends, hard-slicing as a last resort."""
    parts, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", line):
        while len(sentence) > size:
            if current:
                parts.append(current)
                current = ""
            parts.append(sentence[:size])
            sentence = sentence[size:]
        if current and len(current) + len(sentence) + 1 > size:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def split_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Pack whole lines into chunks of <= size chars; neighbours share ~overlap chars."""
    pieces: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if line:
            pieces.extend([line] if len(line) <= size else _split_long_line(line, size))

    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for piece in pieces:
        if current and length + len(piece) + 1 > size:
            chunks.append("\n".join(current))
            tail, tail_len = [], 0
            for prev in reversed(current):        # carry the last lines into the next chunk
                if tail_len + len(prev) > overlap:
                    break
                tail.insert(0, prev)
                tail_len += len(prev) + 1
            current, length = tail, tail_len
        current.append(piece)
        length += len(piece) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def process_file(path: Path) -> list[dict]:
    """Extract, clean and chunk a file. Embeddings are added later by the RAG engine."""
    chunks: list[dict] = []
    for page, raw in extract_pages(path):
        for text in split_text(clean_text(raw)):
            chunks.append({
                "text": text,
                "metadata": {"filename": path.name, "page": page, "chunk_index": len(chunks)},
            })
    return chunks
