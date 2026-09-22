"""
ProAssist AI - RAG (Retrieval-Augmented Generation) Package
Provides local document ingestion, semantic chunking, fast ONNX embeddings,
persistent SQLite vector search, and grounded Ollama generation.
"""

from rag.config import (
    KNOWLEDGE_DIR,
    VECTOR_STORE_DIR,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    EMBEDDING_MODEL_NAME,
    TOP_K,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
)
from rag.document_loader import DocumentLoader
from rag.chunker import TextChunker
from rag.embeddings import LocalEmbeddingEngine
from rag.vector_store import VectorStore
from rag.retriever import Retriever
from rag.generator import OllamaGenerator
from rag.pipeline import RAGPipeline

__all__ = [
    "KNOWLEDGE_DIR",
    "VECTOR_STORE_DIR",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "EMBEDDING_MODEL_NAME",
    "TOP_K",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "DocumentLoader",
    "TextChunker",
    "LocalEmbeddingEngine",
    "VectorStore",
    "Retriever",
    "OllamaGenerator",
    "RAGPipeline",
]
