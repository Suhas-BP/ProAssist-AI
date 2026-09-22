"""
Document Chunker Module for ProAssist AI RAG
Splits loaded document text into semantic chunks with configurable size,
overlap, metadata preservation, and SHA-256 deduplication.
"""

import hashlib
import re
from pathlib import Path
from rag import config as rag_config


class TextChunker:
    """Splits document text into overlapping semantic chunks with unique IDs."""

    def __init__(self,
                 chunk_size: int = rag_config.CHUNK_SIZE,
                 chunk_overlap: int = rag_config.CHUNK_OVERLAP,
                 min_chunk_length: int = rag_config.MIN_CHUNK_LENGTH):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_length = min_chunk_length
        self.separators = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]

    def _split_text(self, text: str, separators: list) -> list[str]:
        """Recursively splits text using hierarchical separators."""
        final_chunks = []
        separator = separators[-1]
        new_separators = []

        for i, sep in enumerate(separators):
            if sep == "":
                separator = ""
                break
            if sep in text:
                separator = sep
                new_separators = separators[i + 1:]
                break

        splits = text.split(separator) if separator else list(text)

        # Merge splits up to chunk_size with overlap
        good_splits = []
        for s in splits:
            if s:
                good_splits.append(s)

        current_chunk = []
        current_len = 0

        for piece in good_splits:
            piece_len = len(piece) + (len(separator) if current_chunk else 0)
            if current_len + piece_len > self.chunk_size and current_chunk:
                doc_text = separator.join(current_chunk).strip()
                if len(doc_text) >= self.min_chunk_length:
                    final_chunks.append(doc_text)

                # Keep overlap pieces from the tail
                overlap_len = 0
                overlap_chunk = []
                for item in reversed(current_chunk):
                    if overlap_len + len(item) <= self.chunk_overlap:
                        overlap_chunk.insert(0, item)
                        overlap_len += len(item) + len(separator)
                    else:
                        break
                current_chunk = overlap_chunk
                current_len = sum(len(x) for x in current_chunk) + len(separator) * max(0, len(current_chunk) - 1)

            current_chunk.append(piece)
            current_len += piece_len

        if current_chunk:
            doc_text = separator.join(current_chunk).strip()
            if len(doc_text) >= self.min_chunk_length:
                final_chunks.append(doc_text)

        return final_chunks

    def chunk_document(self, doc_page: dict) -> list[dict]:
        """
        Takes a document section/page dictionary and produces structured chunks.
        """
        raw_text = doc_page.get("text", "").strip()
        if not raw_text:
            return []

        source = doc_page.get("source", "unknown")
        page = doc_page.get("page", 1)
        file_path = doc_page.get("file_path", "")
        file_type = doc_page.get("file_type", "")

        raw_chunks = self._split_text(raw_text, self.separators)
        structured_chunks = []

        for idx, chunk_text in enumerate(raw_chunks):
            # Deterministic SHA-256 chunk hash for deduplication
            hash_input = f"{source}:{page}:{chunk_text}".encode("utf-8")
            chunk_hash = hashlib.sha256(hash_input).hexdigest()[:16]
            chunk_id = f"{Path(source).stem}_p{page}_c{idx}_{chunk_hash}"

            structured_chunks.append({
                "chunk_id": chunk_id,
                "source": source,
                "file_path": file_path,
                "file_type": file_type,
                "page": page,
                "chunk_index": idx,
                "text": chunk_text,
                "char_count": len(chunk_text),
                "metadata": {
                    "source": source,
                    "page": page,
                    "chunk_index": idx,
                    "char_count": len(chunk_text),
                    "file_type": file_type
                }
            })

        return structured_chunks

    def chunk_documents(self, documents: list[dict]) -> list[dict]:
        """
        Chunks an entire list of document sections/pages.
        Automatically deduplicates identical chunks.
        """
        all_chunks = []
        seen_hashes = set()

        for doc in documents:
            chunks = self.chunk_document(doc)
            for c in chunks:
                # Deduplicate by text hash
                content_hash = hashlib.sha256(c["text"].strip().encode("utf-8")).hexdigest()
                if content_hash in seen_hashes:
                    continue
                seen_hashes.add(content_hash)
                all_chunks.append(c)

        return all_chunks
