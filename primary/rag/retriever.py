"""
Retriever Module for ProAssist AI RAG
Embeds incoming queries and retrieves top-K semantically relevant document chunks.
"""

from typing import List, Dict, Any, Tuple
from rag import config as rag_config
from rag.embeddings import LocalEmbeddingEngine
from rag.vector_store import VectorStore


class Retriever:
    """Performs semantic similarity retrieval from the persistent vector store."""

    def __init__(self,
                 vector_store: VectorStore = None,
                 embedding_engine: LocalEmbeddingEngine = None,
                 top_k: int = rag_config.TOP_K,
                 similarity_threshold: float = rag_config.SIMILARITY_THRESHOLD):
        self.store = vector_store or VectorStore()
        self.embedder = embedding_engine or LocalEmbeddingEngine()
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold

    def retrieve(self, query: str, top_k: int = None, min_score: float = None) -> List[Dict[str, Any]]:
        """
        Retrieves top-K relevant document chunks for the query.
        Returns:
            list of dicts with:
                - chunk_id
                - source
                - page
                - text
                - score (cosine similarity)
                - formatted_source (e.g. 'policy.pdf, page 2')
        """
        clean_query = query.strip()
        if not clean_query:
            return []

        k = top_k if top_k is not None else self.top_k
        threshold = min_score if min_score is not None else self.similarity_threshold

        # 1. Embed query into normalized vector
        query_vec = self.embedder.embed_text(clean_query)

        # 2. Search vector store
        raw_results = self.store.search(query_vec, top_k=k)

        # 3. Format and filter results
        retrieved_chunks = []
        for score, chunk in raw_results:
            source_file = chunk.get("source", "Document")
            page_num = chunk.get("page")
            if page_num:
                formatted_src = f"{source_file}, page {page_num}"
            else:
                formatted_src = source_file

            chunk_info = {
                "chunk_id": chunk.get("chunk_id"),
                "source": source_file,
                "page": page_num,
                "text": chunk.get("text"),
                "metadata": chunk.get("metadata", {}),
                "score": round(score, 4),
                "formatted_source": formatted_src
            }

            if score >= threshold:
                retrieved_chunks.append(chunk_info)

        try:
            print(f"[Retriever] Query: \"{clean_query}\" -> Retrieved {len(retrieved_chunks)}/{len(raw_results)} chunks (Scores: {[c['score'] for c in retrieved_chunks]})")
        except UnicodeEncodeError:
            safe_q = clean_query.encode("ascii", "backslashreplace").decode("ascii")
            print(f"[Retriever] Query: \"{safe_q}\" -> Retrieved {len(retrieved_chunks)}/{len(raw_results)} chunks (Scores: {[c['score'] for c in retrieved_chunks]})")
        return retrieved_chunks

    def get_sources_list(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """Returns a deduplicated list of formatted source citations."""
        sources = []
        seen = set()
        for c in chunks:
            src = c.get("formatted_source")
            if src and src not in seen:
                seen.add(src)
                sources.append(src)
        return sources
