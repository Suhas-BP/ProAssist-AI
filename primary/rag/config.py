"""
ProAssist AI - RAG (Retrieval-Augmented Generation) Configuration
Central configuration for document loading, chunking, local embeddings,
vector storage, retrieval, and local Ollama LLM generation.
"""

from pathlib import Path

# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# =====================================================================
# PATHS CONFIGURATION
# =====================================================================
DATA_DIR = PROJECT_ROOT / "data"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
VECTOR_STORE_DIR = DATA_DIR / "vector_store"

# Ensure runtime directories exist
KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)

# Vector store database and index paths
VECTOR_DB_PATH = VECTOR_STORE_DIR / "rag_vectors.db"
VECTOR_EMBEDDINGS_PATH = VECTOR_STORE_DIR / "embeddings.npy"
VECTOR_METADATA_PATH = VECTOR_STORE_DIR / "chunks_metadata.json"

# =====================================================================
# DOCUMENT INGESTION & CHUNKING
# =====================================================================
SUPPORTED_EXTENSIONS = [".txt", ".md", ".pdf", ".docx"]

# Chunking settings
CHUNK_SIZE = 500              # Target characters per chunk (~80-120 words)
CHUNK_OVERLAP = 100           # Character overlap to preserve context across boundaries
MIN_CHUNK_LENGTH = 30         # Filter out tiny noise chunks (headers, blank lines)

# =====================================================================
# EMBEDDINGS CONFIGURATION (Local ONNX fastembed)
# =====================================================================
# Fast, local, normalized embedding model running on local CPU via ONNX
# Default: BAAI/bge-small-en-v1.5 (384 dimensions, highly performant)
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384
EMBEDDING_BATCH_SIZE = 32

# =====================================================================
# RETRIEVAL CONFIGURATION
# =====================================================================
TOP_K = 3                     # Number of relevant chunks to retrieve for context
SIMILARITY_THRESHOLD = 0.25   # Minimum cosine similarity to consider relevant

# =====================================================================
# OLLAMA CONFIGURATION (Local inference)
# =====================================================================
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2:1b"  # Default local model; will fallback/auto-detect if needed
OLLAMA_TIMEOUT = 90           # Seconds timeout for local generation
OLLAMA_TEMPERATURE = 0.1      # Low temperature for fact-grounded responses
