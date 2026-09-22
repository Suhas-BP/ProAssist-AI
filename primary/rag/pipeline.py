"""
RAG Pipeline Orchestrator for ProAssist AI
Combines Document Ingestion, Chunking, Local Vector Storage,
Semantic Retrieval, and Ollama LLM Generation into a unified interface.
"""

import sys
import argparse
from pathlib import Path
from typing import Dict, Any, Optional

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag import config as rag_config
from rag.document_loader import DocumentLoader
from rag.chunker import TextChunker
from rag.embeddings import LocalEmbeddingEngine
from rag.vector_store import VectorStore
from rag.retriever import Retriever
from rag.generator import OllamaGenerator


class RAGPipeline:
    """Unified local Retrieval-Augmented Generation pipeline."""

    def __init__(self,
                 knowledge_dir: Path = rag_config.KNOWLEDGE_DIR,
                 vector_store: VectorStore = None,
                 embedding_engine: LocalEmbeddingEngine = None,
                 ollama_generator: OllamaGenerator = None):
        self.knowledge_dir = Path(knowledge_dir).resolve()
        self.embedder = embedding_engine or LocalEmbeddingEngine()
        self.store = vector_store or VectorStore()
        self.retriever = Retriever(vector_store=self.store, embedding_engine=self.embedder)
        self.generator = ollama_generator or OllamaGenerator()
        self.loader = DocumentLoader()
        self.chunker = TextChunker()
        try:
            self._auto_sync_knowledge_base()
        except Exception as e:
            print(f"[RAG Pipeline] Auto-sync notice: {e}")

    def _auto_sync_knowledge_base(self):
        """Ensures any supported documents in knowledge_dir are indexed in the vector store."""
        if not self.knowledge_dir.exists():
            return
        exts = set(self.loader.supported_extensions)
        files = [f for f in self.knowledge_dir.iterdir() if f.is_file() and f.suffix.lower() in exts]
        if not files:
            return
        indexed = set(self.store.get_indexed_sources())
        unindexed = [f for f in files if f.name not in indexed]
        if unindexed or self.store.get_stats()["total_chunks"] == 0:
            print(f"[RAG Pipeline] Auto-indexing {len(unindexed or files)} document(s) into vector store...")
            self.index_knowledge_base(self.knowledge_dir)

    def index_knowledge_base(self, directory: Optional[Path] = None) -> Dict[str, Any]:
        """
        Scans knowledge directory, extracts text, chunks, embeds, and stores in vector database.
        Returns:
            dict containing indexing statistics.
        """
        target_dir = Path(directory or self.knowledge_dir).resolve()
        print(f"\n[RAG Indexing] Starting knowledge base ingestion from: {target_dir}")

        # 1. Discover and load documents
        doc_pages = self.loader.load_directory(target_dir)
        if not doc_pages:
            print("[RAG Indexing] No supported documents (.txt, .md, .pdf, .docx) found to index.")
            return {
                "documents_found": 0,
                "chunks_created": 0,
                "embeddings_generated": 0,
                "status": "empty_directory"
            }

        # 2. Chunk documents with deduplication
        chunks = self.chunker.chunk_documents(doc_pages)
        print(f"[RAG Indexing] Created {len(chunks)} unique text chunks from {len(doc_pages)} document sections.")

        if not chunks:
            return {
                "documents_found": len(doc_pages),
                "chunks_created": 0,
                "embeddings_generated": 0,
                "status": "no_chunks"
            }

        # 3. Generate embeddings locally on CPU
        texts_to_embed = [c["text"] for c in chunks]
        print(f"[RAG Indexing] Generating local embeddings ({self.embedder.model_name})...")
        embeddings = self.embedder.embed_batch(texts_to_embed)

        # 4. Insert into persistent vector store
        new_inserted = self.store.add_chunks(chunks, embeddings)
        stats = self.store.get_stats()

        print(f"[RAG Indexing Complete] Stored {new_inserted} new chunks. Total vector DB size: {stats['total_chunks']} chunks across {stats['total_documents']} documents.")
        return {
            "documents_found": len(doc_pages),
            "chunks_created": len(chunks),
            "new_chunks_inserted": new_inserted,
            "total_chunks_in_db": stats["total_chunks"],
            "status": "success"
        }

    def ask(self, query: str, top_k: int = rag_config.TOP_K) -> Dict[str, Any]:
        """
        Executes end-to-end RAG query:
        Query -> Semantic Retrieval -> Grounded Ollama Generation -> Answer + Sources.
        """
        clean_query = query.strip()
        if not clean_query:
            return {
                "query": "",
                "answer": "Please ask a question.",
                "sources": [],
                "formatted_output": "Answer:\nPlease ask a question.\n\nSources:\nNone",
                "chunks": [],
                "status": "empty_query"
            }

        try:
            print(f"\n[RAG Pipeline] Processing user query: \"{clean_query}\"")
        except UnicodeEncodeError:
            safe_q = clean_query.encode("ascii", "backslashreplace").decode("ascii")
            print(f"\n[RAG Pipeline] Processing user query: \"{safe_q}\"")

        # Optimize retrieval query if asking to check or summarize a file
        retrieval_query = clean_query
        lower_q = clean_query.lower()
        if any(w in lower_q for w in ["check the file", "check file", "check the document", "check document", "read the file", "what does the file say", "what is in the file"]):
            retrieval_query = f"overview title summary authors objectives {clean_query}"

        # 1. Semantic retrieval
        retrieved_chunks = self.retriever.retrieve(retrieval_query, top_k=top_k)

        # 2. Local Ollama generation
        gen_result = self.generator.generate(clean_query, retrieved_chunks)

        answer_text = gen_result.get("answer", "")
        sources_list = gen_result.get("sources", [])

        # Extractive fallback if Ollama produced empty or generic non-answer despite having chunks
        if (not answer_text or "could not find information" in answer_text.lower() or gen_result.get("status") != "success") and retrieved_chunks:
            top_chunk = retrieved_chunks[0]
            lines = [l.strip() for l in top_chunk["text"].split("\n") if l.strip() and not l.startswith("#")]
            summary_excerpt = " ".join(lines[:3]) if lines else top_chunk["text"][:250]
            answer_text = f"According to {top_chunk['formatted_source']}: {summary_excerpt}"
            if not sources_list:
                sources_list = [top_chunk["formatted_source"]]

        # Format user-facing text with sources
        formatted_lines = [f"Answer:\n{answer_text}"]
        if sources_list:
            formatted_lines.append("\nSources:")
            for s in sources_list:
                formatted_lines.append(f"- {s}")
        else:
            formatted_lines.append("\nSources:\nNone (Knowledge base had no matching information)")

        full_output = "\n".join(formatted_lines)

        return {
            "query": clean_query,
            "answer": answer_text,
            "sources": sources_list,
            "formatted_output": full_output,
            "chunks": retrieved_chunks,
            "model_used": gen_result.get("model", ""),
            "generation_time": gen_result.get("generation_time", 0.0),
            "status": gen_result.get("status", "success")
        }

    def summarize_document(self, file_query_or_path: str = None) -> Dict[str, Any]:
        """
        Dynamically discovers, reads, and summarizes a PDF or document
        from the file explorer / user's workspace (Desktop, Downloads, Documents, data/knowledge).
        """
        # 1. Discover target document
        matched = self.loader.find_user_documents(query_name=file_query_or_path)
        if not matched:
            return {
                "query": file_query_or_path or "Document Summary",
                "answer": "I could not find any matching PDF or document in your file explorer or Desktop.",
                "sources": [],
                "formatted_output": "Answer:\nI could not find any matching PDF or document in your file explorer or Desktop.\n\nSources:\nNone",
                "status": "not_found"
            }

        target_file = matched[0]
        print(f"[RAG Summarizer] Selected document: '{target_file.name}' ({target_file})")

        # 2. Load pages
        try:
            pages = self.loader.load_document(target_file)
        except Exception as e:
            return {
                "query": file_query_or_path or f"Summarize {target_file.name}",
                "answer": f"Error loading '{target_file.name}': {e}",
                "sources": [target_file.name],
                "formatted_output": f"Answer:\nError loading '{target_file.name}': {e}\n\nSources:\n- {target_file.name}",
                "status": "error"
            }

        if not pages:
            return {
                "query": file_query_or_path or f"Summarize {target_file.name}",
                "answer": f"The document '{target_file.name}' is empty or has no readable text.",
                "sources": [target_file.name],
                "formatted_output": f"Answer:\nThe document '{target_file.name}' is empty or has no readable text.\n\nSources:\n- {target_file.name}",
                "status": "empty_document"
            }

        # 3. Auto-index if not already in vector store
        indexed_sources = set(self.store.get_indexed_sources())
        if target_file.name not in indexed_sources:
            try:
                chunks = self.chunker.chunk_documents(pages)
                if chunks:
                    texts = [c["text"] for c in chunks]
                    embeddings = self.embedder.embed_batch(texts)
                    self.store.add_chunks(chunks, embeddings)
                    print(f"[RAG Summarizer] Auto-indexed {len(chunks)} chunks for '{target_file.name}'.")
            except Exception as e:
                print(f"[RAG Summarizer] Notice: vector indexing skipped: {e}")

        # 4. Formulate summary prompt from key pages
        key_pages = pages[:3]
        if len(pages) > 3:
            key_pages.append(pages[-1])

        combined_text = "\n\n--- Section ---\n\n".join(
            f"Page {p.get('page', 1)}:\n{p.get('text', '')[:1000]}" for p in key_pages
        )

        context_chunks = [
            {
                "text": combined_text[:3000],
                "formatted_source": f"{target_file.name}, pages 1-{len(pages)}"
            }
        ]

        gen_result = self.generator.generate(
            f"Summarize the document {target_file.name}. State what kind of document it is, key details, purpose, and a clear summary.",
            context_chunks=context_chunks
        )

        answer_text = gen_result.get("answer", "")
        # Robust extractive fallback if LLM answer is empty or generic
        if not answer_text or gen_result.get("status") != "success" or "could not find information" in answer_text.lower():
            p1_text = pages[0].get("text", "")
            lines = [l.strip() for l in p1_text.split("\n") if l.strip()]
            title = lines[0] if lines else target_file.stem
            lead = " ".join(lines[1:5]) if len(lines) > 1 else (p1_text[:250] if p1_text else "Document contents extracted successfully.")
            answer_text = (
                f"Document: {target_file.name} (Total Pages/Sections: {len(pages)})\n"
                f"Title: {title}\n"
                f"Content: {lead}\n"
                f"The document is indexed and ready for specific queries."
            )

        sources = [f"{target_file.name} (pages 1-{len(pages)})"]
        formatted_output = f"Answer:\n{answer_text}\n\nSources:\n- {sources[0]}"

        return {
            "query": f"Summarize {target_file.name}",
            "answer": answer_text,
            "sources": sources,
            "formatted_output": formatted_output,
            "target_file": str(target_file),
            "total_pages": len(pages),
            "status": "success"
        }


def cli_main():
    """Terminal CLI for testing RAG without voice or microphone."""
    parser = argparse.ArgumentParser(description="ProAssist AI - Local RAG Pipeline CLI")
    parser.add_argument("--index", "-i", action="store_true", help="Index all documents in data/knowledge")
    parser.add_argument("--query", "-q", type=str, default=None, help="Execute a single question")
    parser.add_argument("--dir", "-d", type=str, default=None, help="Custom knowledge directory path")
    args = parser.parse_args()

    pipeline = RAGPipeline(knowledge_dir=Path(args.dir) if args.dir else rag_config.KNOWLEDGE_DIR)

    # 1. Handle Indexing
    if args.index:
        pipeline.index_knowledge_base()
        return

    # 2. Handle Single Query
    if args.query:
        result = pipeline.ask(args.query)
        print("\n" + "=" * 65)
        print(result["formatted_output"])
        print("=" * 65)
        return

    # 3. Interactive CLI Loop
    print("=" * 65)
    print("      PROASSIST AI - LOCAL RAG INTERACTIVE TERMINAL")
    print("    Local Document Retrieval & Ollama Grounded Generation")
    print("=" * 65)

    stats = pipeline.store.get_stats()
    print(f"[*] Knowledge Directory : {pipeline.knowledge_dir}")
    print(f"[*] Indexed Chunks      : {stats['total_chunks']} chunks from {stats['total_documents']} documents")
    print(f"[*] Embedding Model     : {pipeline.embedder.model_name}")
    print(f"[*] Ollama Base URL     : {pipeline.generator.base_url}")
    print(f"[*] Ollama Model        : {pipeline.generator.resolve_model()}")
    print("=" * 65)
    print("Type your question below (or type 'exit' / 'quit' to stop):\n")

    if stats["total_chunks"] == 0:
        print("[Notice] The vector store is currently empty.")
        print("Place documents in 'data/knowledge/' and run:")
        print("    python -m rag.pipeline --index\n")

    while True:
        try:
            user_input = input("Enter question: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit", "bye"]:
                print("Exiting RAG CLI. Goodbye!")
                break

            result = pipeline.ask(user_input)
            print("\n" + result["formatted_output"] + "\n")
            print(f"(Generated in {result['generation_time']}s using {result['model_used']})")
            print("-" * 65)
        except (KeyboardInterrupt, EOFError):
            print("\nSession interrupted. Exiting.")
            break


if __name__ == "__main__":
    cli_main()
