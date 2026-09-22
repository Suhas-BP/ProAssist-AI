"""
Persistent Local Vector Database for ProAssist AI RAG
Uses SQLite for robust metadata and vector persistence, with NumPy
matrix dot-product cosine similarity for high-speed retrieval.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
import numpy as np
from rag import config as rag_config


class VectorStore:
    """Lightweight, persistent local vector store backed by SQLite and NumPy."""

    def __init__(self, db_path: Path = rag_config.VECTOR_DB_PATH):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Yields a configured SQLite connection and guarantees closure on exit."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Initializes the database schema if not present."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    page INTEGER,
                    text TEXT NOT NULL,
                    metadata TEXT,
                    embedding BLOB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON chunks(source);")
            conn.commit()

    def add_chunks(self, chunks: List[Dict[str, Any]], embeddings: List[np.ndarray]) -> int:
        """
        Inserts new chunks and their embeddings into the store.
        Skips chunks whose chunk_id already exists to prevent duplicate indexing.
        Returns:
            int: Number of new chunks actually inserted.
        """
        if len(chunks) != len(embeddings):
            raise ValueError(f"Chunks count ({len(chunks)}) does not match embeddings count ({len(embeddings)})")

        inserted_count = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for chunk, emb in zip(chunks, embeddings):
                chunk_id = chunk["chunk_id"]
                source = chunk.get("source", "unknown")
                page = chunk.get("page", 1)
                text = chunk.get("text", "")
                metadata_str = json.dumps(chunk.get("metadata", {}))
                emb_blob = emb.astype(np.float32).tobytes()

                try:
                    cursor.execute("""
                        INSERT INTO chunks (chunk_id, source, page, text, metadata, embedding)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (chunk_id, source, page, text, metadata_str, emb_blob))
                    inserted_count += 1
                except sqlite3.IntegrityError:
                    # Chunk ID already exists (deduplication)
                    continue

            conn.commit()

        print(f"[VectorStore] Added {inserted_count} new chunks (skipped {len(chunks) - inserted_count} existing).")
        return inserted_count

    def search(self, query_embedding: np.ndarray, top_k: int = rag_config.TOP_K) -> List[Tuple[float, Dict[str, Any]]]:
        """
        Performs cosine similarity search against all stored vectors using NumPy matrix operations.
        Returns:
            list of tuples: [(similarity_score, chunk_dict), ...]
        """
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT chunk_id, source, page, text, metadata, embedding FROM chunks")
            rows = cursor.fetchall()

        if not rows:
            return []

        # Load all embeddings into a single contiguous matrix for vectorized dot product
        chunk_dicts = []
        embeddings_list = []

        for r in rows:
            meta = json.loads(r["metadata"]) if r["metadata"] else {}
            chunk_dicts.append({
                "chunk_id": r["chunk_id"],
                "source": r["source"],
                "page": r["page"],
                "text": r["text"],
                "metadata": meta
            })
            emb_arr = np.frombuffer(r["embedding"], dtype=np.float32)
            embeddings_list.append(emb_arr)

        if not embeddings_list:
            return []

        matrix = np.vstack(embeddings_list)  # Shape: (N, D)
        query_vec = query_embedding.astype(np.float32).flatten()  # Shape: (D,)

        # Compute cosine similarity (dot product since both are L2-normalized)
        scores = np.dot(matrix, query_vec)

        # Rank by score descending
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            results.append((score, chunk_dicts[idx]))

        return results

    def get_indexed_sources(self) -> List[str]:
        """Returns list of distinct source document filenames currently stored."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT DISTINCT source FROM chunks")
            return [row[0] for row in cursor.fetchall()]

    def get_stats(self) -> Dict[str, Any]:
        """Returns statistics on the vector database contents."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*), COUNT(DISTINCT source) FROM chunks")
            total_chunks, total_docs = cursor.fetchone()

        return {
            "total_chunks": total_chunks,
            "total_documents": total_docs,
            "db_path": str(self.db_path),
            "db_size_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0
        }

    def clear(self):
        """Clears all stored chunks and vectors."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM chunks")
            conn.commit()
        print("[VectorStore] Cleared all vectors and documents.")
