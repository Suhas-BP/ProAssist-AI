# ProAssist AI — Major Project Overview

## Project Title
ProAssist AI: Intelligent Multilingual Voice Assistant for Universal Productivity Enhancement.

## System Architecture
ProAssist AI is designed with a multi-phase modular architecture:
- **Phase 1: Biometric Security Engine**: Implements local "Hey Agent" wake-word spotting, 256-dimensional speaker voice embedding generation using an ONNX ResNet-34 model, and strict cosine similarity verification with a threshold of 0.72.
- **Phase 2: Continuous Conversation & Communications**: Features dynamic voice endpointing (VAD), continuous command listening ("How can I help you?"), a safe command router, local contact management, and a voice-guided email drafting and dispatch pipeline with strict confirmation gating.
- **Phase 3: Desktop & Web Action Agent**: Provides allowlisted desktop application launching (Chrome, Edge, Firefox, Calculator, Notepad, File Explorer), website navigation (Google, YouTube, Gmail, GitHub), Google search, YouTube search and playback, safe AST mathematical evaluation, and Notepad text automation.
- **RAG Module: Local Knowledge Retrieval**: Implements local document ingestion (.txt, .md, .pdf, .docx), semantic text chunking with deduplication, fast ONNX local embeddings (BAAI/bge-small-en-v1.5), persistent SQLite vector storage, top-K cosine similarity retrieval, and local Ollama LLM response generation with source citations.

## Hardware and Execution Constraints
- All speech recognition, wake-word spotting, speaker verification, embeddings, and LLM inference operate 100% locally on the user's computer.
- Cloud APIs are strictly avoided for privacy, reliability, and offline autonomy.
- The voice authentication similarity threshold is permanently calibrated to 0.72.
