"""
Local Embedding Engine for ProAssist AI RAG
Provides high-performance, normalized local embeddings running entirely
on local CPU via ONNX (fastembed) without cloud API dependency or PyTorch overhead.
"""

import numpy as np
from typing import List, Union
from rag import config as rag_config


class LocalEmbeddingEngine:
    """Local ONNX-based embedding engine generating normalized vectors."""

    def __init__(self, model_name: str = rag_config.EMBEDDING_MODEL_NAME):
        self.model_name = model_name
        self._model = None
        self._dimension = rag_config.EMBEDDING_DIM

    @property
    def model(self):
        """Lazy-loads the fastembed model upon first use."""
        if self._model is None:
            try:
                from fastembed import TextEmbedding
                print(f"[Embeddings] Initializing local ONNX embedding model: '{self.model_name}'...")
                self._model = TextEmbedding(model_name=self.model_name)
                print(f"[Embeddings] Model '{self.model_name}' loaded successfully on local CPU.")
            except Exception as e:
                print(f"[Embeddings ERROR] Failed to load embedding model '{self.model_name}': {e}")
                raise RuntimeError(f"Could not load local embedding model: {e}")
        return self._model

    def _normalize(self, vector: np.ndarray) -> np.ndarray:
        """Applies L2 normalization so cosine similarity equals dot product."""
        norm = np.linalg.norm(vector)
        if norm > 1e-9:
            return (vector / norm).astype(np.float32)
        return vector.astype(np.float32)

    def embed_text(self, text: str) -> np.ndarray:
        """
        Embeds a single text string into a normalized 1D float32 numpy array.
        """
        clean_text = text.strip()
        if not clean_text:
            return np.zeros(self._dimension, dtype=np.float32)

        try:
            embeddings = list(self.model.embed([clean_text]))
            if not embeddings:
                return np.zeros(self._dimension, dtype=np.float32)
            return self._normalize(embeddings[0])
        except Exception as e:
            print(f"[Embeddings ERROR] Failed to embed text: {e}")
            raise

    def embed_batch(self, texts: List[str], batch_size: int = rag_config.EMBEDDING_BATCH_SIZE) -> List[np.ndarray]:
        """
        Embeds a batch of texts into normalized float32 numpy arrays.
        """
        if not texts:
            return []

        clean_texts = [t.strip() if t.strip() else " " for t in texts]

        try:
            raw_embeddings = list(self.model.embed(clean_texts, batch_size=batch_size))
            normalized = [self._normalize(emb) for emb in raw_embeddings]
            return normalized
        except Exception as e:
            print(f"[Embeddings ERROR] Batch embedding failure: {e}")
            raise

    def get_dimension(self) -> int:
        """Returns the embedding vector dimensionality."""
        return self._dimension


if __name__ == "__main__":
    engine = LocalEmbeddingEngine()
    test_text = "ProAssist AI is an intelligent universal voice assistant."
    vec = engine.embed_text(test_text)
    print(f"[Embeddings Diagnostic] Vector shape: {vec.shape} | L2 Norm: {np.linalg.norm(vec):.6f}")
