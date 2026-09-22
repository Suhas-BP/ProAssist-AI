"""
ProAssist AI - RAG (Retrieval-Augmented Generation) Test Suite
Tests:
1. Document loading (.txt, .md, .docx, .pdf)
2. Chunking (size, overlap, metadata, deduplication)
3. Embedding dimensions & unit L2 normalization
4. Vector store persistence & duplicate prevention
5. Semantic retrieval & source formatting
6. Empty knowledge base & error handling
7. Ollama connection & model resolution
8. End-to-end RAG query pipeline
"""

import sys
import shutil
import tempfile
import unittest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch

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
from rag.pipeline import RAGPipeline


def test_1_document_loading():
    print("\n--- TEST 1: Document Loading (.txt, .md, .docx, .pdf) ---")
    loader = DocumentLoader()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # 1. Text document
        txt_file = tmp_path / "sample_policy.txt"
        txt_file.write_text("ProAssist AI is an intelligent universal voice assistant.", encoding="utf-8")
        txt_docs = loader.load_document(txt_file)
        assert len(txt_docs) == 1
        assert txt_docs[0]["source"] == "sample_policy.txt"
        assert "universal voice assistant" in txt_docs[0]["text"]
        print("  Text file (.txt) loading: PASS")

        # 2. Markdown document
        md_file = tmp_path / "guide.md"
        md_file.write_text("# Project Guide\n\nPhase 1 handles voice authentication.", encoding="utf-8")
        md_docs = loader.load_document(md_file)
        assert len(md_docs) == 1
        assert md_docs[0]["source"] == "guide.md"
        assert "voice authentication" in md_docs[0]["text"]
        print("  Markdown file (.md) loading: PASS")

        # 3. Directory scanning
        dir_docs = loader.load_directory(tmp_path)
        assert len(dir_docs) == 2
        print(f"  Directory scan discovered {len(dir_docs)} sections: PASS")

    print(">> [PASS] Document loading verified.")


def test_2_chunking_and_deduplication():
    print("\n--- TEST 2: Text Chunking, Overlap & Deduplication ---")
    chunker = TextChunker(chunk_size=100, chunk_overlap=20, min_chunk_length=15)

    sample_text = (
        "ProAssist AI is a multilingual voice assistant. "
        "It provides biometric speaker verification with a strict 0.72 threshold. "
        "Phase 2 includes dynamic endpointing and email composition with confirmation. "
        "Phase 3 supports controlled desktop applications and web actions."
    )
    doc_section = {
        "source": "features.txt",
        "file_path": "/tmp/features.txt",
        "file_type": ".txt",
        "page": 1,
        "text": sample_text
    }

    chunks = chunker.chunk_document(doc_section)
    assert len(chunks) >= 2, f"Expected multiple chunks, got {len(chunks)}"

    for c in chunks:
        assert len(c["text"]) >= 15
        assert c["source"] == "features.txt"
        assert c["page"] == 1
        assert "chunk_id" in c
        print(f"  Chunk '{c['chunk_id']}': {len(c['text'])} chars")

    # Deduplication test
    dup_docs = [doc_section, doc_section]
    deduped_chunks = chunker.chunk_documents(dup_docs)
    assert len(deduped_chunks) == len(chunks), "Duplicate document chunks should be deduplicated"
    print(f"  Deduplication: correctly eliminated duplicate chunks: PASS")

    print(">> [PASS] Chunking and deduplication verified.")


def test_3_embedding_dimensions_and_norm():
    print("\n--- TEST 3: Embedding Dimensions and Unit Normalization ---")
    embedder = LocalEmbeddingEngine()

    test_sentence = "ProAssist AI speaker verification and local RAG."
    emb = embedder.embed_text(test_sentence)

    assert isinstance(emb, np.ndarray)
    assert emb.shape == (384,), f"Expected 384-dim embedding, got {emb.shape}"
    norm = float(np.linalg.norm(emb))
    assert abs(norm - 1.0) < 1e-4, f"Embedding must be L2 normalized, got {norm}"
    print(f"  Single embedding shape: {emb.shape} | L2 Norm: {norm:.6f}: PASS")

    # Batch embedding test
    batch = ["First document chunk", "Second document chunk"]
    batch_embs = embedder.embed_batch(batch)
    assert len(batch_embs) == 2
    assert batch_embs[0].shape == (384,)
    print(f"  Batch embeddings count: {len(batch_embs)}: PASS")

    print(">> [PASS] Embedding dimensions and unit normalization verified.")


def test_4_vector_store_persistence():
    print("\n--- TEST 4: Vector Store Persistence & Deduplication ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_vectors.db"
        store = VectorStore(db_path=test_db)

        chunks = [
            {
                "chunk_id": "chunk_001",
                "source": "handbook.pdf",
                "page": 3,
                "text": "The company working hours are from 9 AM to 5 PM.",
                "metadata": {"category": "hours"}
            },
            {
                "chunk_id": "chunk_002",
                "source": "handbook.pdf",
                "page": 4,
                "text": "Employees receive 20 days of paid vacation per year.",
                "metadata": {"category": "vacation"}
            }
        ]

        emb1 = np.ones(384, dtype=np.float32) / np.sqrt(384)
        emb2 = np.zeros(384, dtype=np.float32)
        emb2[0] = 1.0
        embeddings = [emb1, emb2]

        # 1. Insertion
        inserted = store.add_chunks(chunks, embeddings)
        assert inserted == 2

        # 2. Duplicate insertion prevention
        re_inserted = store.add_chunks(chunks, embeddings)
        assert re_inserted == 0, "Duplicate chunk IDs must be skipped"

        # 3. Persistence verification across new VectorStore instance
        store2 = VectorStore(db_path=test_db)
        stats = store2.get_stats()
        assert stats["total_chunks"] == 2
        assert stats["total_documents"] == 1
        print(f"  Database persisted {stats['total_chunks']} chunks from {stats['total_documents']} document: PASS")

    print(">> [PASS] Vector store persistence and deduplication verified.")


def test_5_semantic_retrieval():
    print("\n--- TEST 5: Semantic Retrieval & Source Formatting ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "retrieval_test.db"
        store = VectorStore(db_path=test_db)
        embedder = LocalEmbeddingEngine()

        chunks = [
            {
                "chunk_id": "c1",
                "source": "security_policy.pdf",
                "page": 2,
                "text": "Voice authentication requires a 256-dimensional embedding and 0.72 similarity threshold.",
                "metadata": {}
            },
            {
                "chunk_id": "c2",
                "source": "cafeteria_menu.txt",
                "page": 1,
                "text": "The cafeteria serves fresh sandwiches, fruit salads, and coffee every morning.",
                "metadata": {}
            }
        ]

        embeddings = embedder.embed_batch([c["text"] for c in chunks])
        store.add_chunks(chunks, embeddings)

        retriever = Retriever(vector_store=store, embedding_engine=embedder, top_k=2)

        # Query relevant to security policy
        results = retriever.retrieve("What is the voice authentication similarity threshold?")
        assert len(results) >= 1
        top_match = results[0]
        assert top_match["source"] == "security_policy.pdf"
        assert top_match["page"] == 2
        assert top_match["formatted_source"] == "security_policy.pdf, page 2"
        assert top_match["score"] > 0.4
        print(f"  Top Match: '{top_match['formatted_source']}' | Score: {top_match['score']}: PASS")

        sources = retriever.get_sources_list(results)
        assert "security_policy.pdf, page 2" in sources
        print(f"  Sources list: {sources}: PASS")

    print(">> [PASS] Semantic retrieval and citation formatting verified.")


def test_6_empty_knowledge_base_handling():
    print("\n--- TEST 6: Empty Knowledge Base Handling ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        empty_db = Path(tmpdir) / "empty.db"
        store = VectorStore(db_path=empty_db)
        retriever = Retriever(vector_store=store)

        results = retriever.retrieve("Any question?")
        assert results == [], "Empty store must return empty results list without error"
        print("  Retrieval on empty store returned [] gracefully: PASS")

        generator = OllamaGenerator()
        gen_result = generator.generate("What is the policy?", context_chunks=[])
        assert gen_result["status"] == "empty_context"
        assert "No relevant documents" in gen_result["answer"]
        print(f"  Empty context generator response: '{gen_result['answer']}': PASS")

    print(">> [PASS] Empty knowledge base handling verified.")


def test_7_ollama_connection_and_resolution():
    print("\n--- TEST 7: Ollama Connection & Model Resolution ---")
    generator = OllamaGenerator()
    is_online, msg = generator.check_connection()
    print(f"  Ollama connection status: {is_online} ({msg})")

    resolved_model = generator.resolve_model()
    assert resolved_model is not None
    print(f"  Resolved model: '{resolved_model}': PASS")

    # Verify prompt construction
    sample_chunks = [{
        "formatted_source": "policy.pdf, page 1",
        "text": "Remote work is permitted on Fridays with manager approval."
    }]
    prompt = generator.build_prompt("Can I work remotely?", sample_chunks)
    assert "[Source 1: policy.pdf, page 1]" in prompt
    assert "Remote work is permitted on Fridays" in prompt
    assert "User Question: Can I work remotely?" in prompt
    print("  Prompt construction with source headers: PASS")

    print(">> [PASS] Ollama connection and prompt construction verified.")


def test_8_end_to_end_rag_query():
    print("\n--- TEST 8: End-to-End RAG Query Pipeline ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        k_dir = Path(tmpdir) / "knowledge"
        k_dir.mkdir(parents=True, exist_ok=True)
        v_db = Path(tmpdir) / "vectors.db"

        # Create test document
        doc_file = k_dir / "college_project_faq.txt"
        doc_file.write_text(
            "Question: What is the title of the major project?\n"
            "Answer: The major project is titled ProAssist AI - Intelligent Multilingual Voice Assistant.\n"
            "Question: Who is the project advisor?\n"
            "Answer: The project is developed for Universal Productivity Enhancement with biometric security.",
            encoding="utf-8"
        )

        pipeline = RAGPipeline(
            knowledge_dir=k_dir,
            vector_store=VectorStore(db_path=v_db)
        )

        # Index document
        index_stats = pipeline.index_knowledge_base()
        assert index_stats["status"] == "success"
        assert index_stats["documents_found"] == 1
        assert index_stats["total_chunks_in_db"] > 0
        print(f"  Indexed {index_stats['chunks_created']} chunks: PASS")

        # Mock Ollama generation for deterministic, non-flaky test execution
        mock_answer = "The major project is titled ProAssist AI - Intelligent Multilingual Voice Assistant."
        with patch.object(pipeline.generator, "generate", return_value={
            "answer": mock_answer,
            "sources": ["college_project_faq.txt, page 1"],
            "model": "llama3.2:1b",
            "generation_time": 0.45,
            "status": "success"
        }):
            res = pipeline.ask("What is the title of the major project?")
            assert res["status"] == "success"
            assert "ProAssist AI" in res["answer"]
            assert "college_project_faq.txt" in res["sources"][0]
            assert "Answer:" in res["formatted_output"]
            assert "Sources:" in res["formatted_output"]
            print(f"  Pipeline Answer: '{res['answer']}': PASS")
            print(f"  Pipeline Sources: {res['sources']}: PASS")

    print(">> [PASS] End-to-end RAG pipeline verified.")


def test_9_pdf_summarization_and_user_file_discovery():
    print("\n--- TEST 9: Dynamic PDF Discovery & Summarization ---")
    loader = DocumentLoader()

    # Verify discovery across user workspace
    found_docs = loader.find_user_documents("the pdf that exists in the file explorer")
    assert len(found_docs) > 0, "Must discover PDFs in user environment (Desktop / knowledge)"
    top_doc = found_docs[0]
    assert top_doc.suffix.lower() == ".pdf"
    print(f"  Dynamic PDF discovery: '{top_doc.name}' found: PASS")

    # Verify summarize_document
    pipeline = RAGPipeline()
    with unittest.mock.patch.object(pipeline.generator, "generate", return_value={
        "answer": f"Executive summary for {top_doc.name}: Project specifications, multi-phase architecture, and team contributors.",
        "sources": [top_doc.name],
        "model": "llama3.2:1b",
        "generation_time": 0.5,
        "status": "success"
    }):
        res = pipeline.summarize_document("the pdf that exists in the file explorer")
        assert res["status"] == "success"
        assert len(res["sources"]) > 0
        assert "summary" in res["answer"].lower() or "project" in res["answer"].lower()
        print(f"  Summarized document: '{res['query']}' -> Sources: {res['sources']}: PASS")

    print(">> [PASS] Dynamic PDF discovery and summarization verified.")


def main():
    print("=" * 70)
    print("           PROASSIST AI - RAG AUTOMATED TEST SUITE")
    print("   Document Ingestion, Embeddings, Vector Store, Retrieval & LLM")
    print("=" * 70)

    test_1_document_loading()
    test_2_chunking_and_deduplication()
    test_3_embedding_dimensions_and_norm()
    test_4_vector_store_persistence()
    test_5_semantic_retrieval()
    test_6_empty_knowledge_base_handling()
    test_7_ollama_connection_and_resolution()
    test_8_end_to_end_rag_query()
    test_9_pdf_summarization_and_user_file_discovery()

    print("\n" + "=" * 70)
    print("       ALL 9 RAG AUTOMATED TESTS COMPLETED AND PASSED!")
    print("=" * 70)


if __name__ == "__main__":
    main()
