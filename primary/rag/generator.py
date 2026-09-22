"""
Ollama Local LLM Generation Module for ProAssist AI RAG
Sends grounded context and queries to the local Ollama instance,
ensuring hallucination-free generation with source citation.
"""

import time
import json
import requests
from typing import List, Dict, Any, Optional, Tuple
from rag import config as rag_config


class OllamaGenerator:
    """Interacts with local Ollama server to generate grounded answers with source citations."""

    def __init__(self,
                 model_name: str = rag_config.OLLAMA_MODEL,
                 base_url: str = rag_config.OLLAMA_BASE_URL,
                 timeout: int = rag_config.OLLAMA_TIMEOUT):
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._verified_model = None

    def check_connection(self) -> Tuple[bool, str]:
        """
        Checks if the Ollama service is reachable.
        Returns:
            (is_connected: bool, message: str)
        """
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name") for m in data.get("models", [])]
                return True, f"Ollama is online with {len(models)} installed models: {models}"
            return False, f"Ollama returned HTTP status {resp.status_code}"
        except requests.exceptions.ConnectionError:
            return False, f"Cannot connect to Ollama at {self.base_url}. Please ensure Ollama is running ('ollama serve')."
        except Exception as e:
            return False, f"Ollama connection check error: {e}"

    def get_available_models(self) -> List[str]:
        """Queries Ollama for list of locally installed models."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                return [m.get("name") for m in data.get("models", [])]
        except Exception:
            pass
        return []

    def resolve_model(self) -> str:
        """
        Resolves the active model to use. If configured model is present, uses it;
        otherwise selects the first available model or raises an informative error.
        """
        if self._verified_model:
            return self._verified_model

        installed = self.get_available_models()
        if not installed:
            # If no models yet, default to configured
            return self.model_name

        # Exact or prefix match (e.g. 'llama3.2:1b' vs 'llama3.2:1b-instruct')
        for m in installed:
            if m == self.model_name or m.startswith(self.model_name) or self.model_name.startswith(m):
                self._verified_model = m
                return m

        # Fallback to first available installed model
        print(f"[Generator] Configured model '{self.model_name}' not found in {installed}. Using '{installed[0]}'.")
        self._verified_model = installed[0]
        return self._verified_model

    def build_prompt(self, query: str, context_chunks: List[Dict[str, Any]]) -> str:
        """
        Builds a grounded prompt containing retrieved context passages and user question.
        """
        context_blocks = []
        for idx, chunk in enumerate(context_chunks):
            src = chunk.get("formatted_source", f"Document {idx+1}")
            text = chunk.get("text", "").strip()
            context_blocks.append(f"[Source {idx+1}: {src}]\n{text}")

        joined_context = "\n\n".join(context_blocks)

        prompt = f"""Context from knowledge base documents:
----------------------------------------
{joined_context}
----------------------------------------

User Question: {query}

Instructions:
Answer the question thoroughly based ONLY on the provided context above.
Respond in the language of the user's question (English, Hindi, or Kannada).
If the context does not contain enough information to answer the question, clearly state: "Based on the provided documents, I could not find information regarding this question."
Do not extrapolate, assume, or invent facts not present in the context."""
        return prompt

    def generate(self, query: str, context_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Sends query and context to Ollama and returns the grounded answer with sources.
        """
        start_time = time.time()
        active_model = self.resolve_model()

        # Build prompt
        full_prompt = self.build_prompt(query, context_chunks)
        system_prompt = (
            "You are ProAssist AI, an intelligent, factual voice assistant. "
            "You provide direct, concise, and helpful answers strictly based on the retrieved context."
        )

        sources = []
        for c in context_chunks:
            src = c.get("formatted_source")
            if src and src not in sources:
                sources.append(src)

        # Handle empty context case
        if not context_chunks:
            return {
                "answer": "No relevant documents were found in the knowledge base to answer your question.",
                "sources": [],
                "model": active_model,
                "generation_time": 0.0,
                "status": "empty_context"
            }

        payload = {
            "model": active_model,
            "prompt": full_prompt,
            "system": system_prompt,
            "stream": False,
            "options": {
                "temperature": rag_config.OLLAMA_TEMPERATURE,
            }
        }

        print(f"[Generator] Sending query to local Ollama (Model: {active_model}, Context chunks: {len(context_chunks)})...")

        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout
            )
            elapsed = round(time.time() - start_time, 2)

            if resp.status_code == 200:
                data = resp.json()
                raw_answer = data.get("response", "").strip()
                print(f"[Generator] Answer generated in {elapsed}s via Ollama ({active_model}).")
                return {
                    "answer": raw_answer,
                    "sources": sources,
                    "model": active_model,
                    "generation_time": elapsed,
                    "status": "success"
                }
            elif resp.status_code == 404:
                return {
                    "answer": f"Error: Ollama model '{active_model}' is not pulled. Please run: 'ollama pull {active_model}'",
                    "sources": sources,
                    "model": active_model,
                    "generation_time": round(time.time() - start_time, 2),
                    "status": "model_not_found"
                }
            else:
                return {
                    "answer": f"Ollama generation failed with status code {resp.status_code}: {resp.text}",
                    "sources": sources,
                    "model": active_model,
                    "generation_time": round(time.time() - start_time, 2),
                    "status": "error"
                }

        except requests.exceptions.ConnectionError:
            return {
                "answer": f"Could not connect to local Ollama server at {self.base_url}. Please ensure Ollama is running.",
                "sources": sources,
                "model": active_model,
                "generation_time": round(time.time() - start_time, 2),
                "status": "connection_error"
            }
        except requests.exceptions.Timeout:
            return {
                "answer": f"Local Ollama generation timed out after {self.timeout} seconds.",
                "sources": sources,
                "model": active_model,
                "generation_time": round(time.time() - start_time, 2),
                "status": "timeout"
            }
        except Exception as e:
            return {
                "answer": f"An unexpected error occurred during generation: {e}",
                "sources": sources,
                "model": active_model,
                "generation_time": round(time.time() - start_time, 2),
                "status": "error"
            }
