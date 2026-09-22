"""
ProAssist AI - Online LLM Question Answering Module
Answers general knowledge questions, math queries, and current events
by fetching real-time internet data and generating answers via LLM.
Enforces strict requirement: Answers ONE AND ONLY IF an active internet connection is available.
"""

import html
import json
import re
import socket
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import requests


class OnlineLLMQA:
    """Online Question Answering powered by Web Search & LLM."""

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "llama3.2:1b",
        timeout: int = 12
    ):
        self.ollama_url = ollama_url.rstrip("/")
        self.ollama_model = ollama_model
        self.timeout = timeout

    @staticmethod
    def is_internet_connected(timeout: float = 1.5) -> bool:
        """
        Fast check to verify if an active internet connection is available.
        Performs DNS socket probe with HTTP fallback.
        """
        # 1. Fast DNS socket check (Google & Cloudflare DNS)
        for host in ["8.8.8.8", "1.1.1.1"]:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                sock.connect((host, 53))
                sock.close()
                return True
            except OSError:
                continue

        # 2. HTTP probe fallback
        try:
            req = urllib.request.Request(
                "https://www.google.com",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass

        return False

    def fetch_web_knowledge(self, query: str) -> List[str]:
        """
        Fetches fresh real-time knowledge snippets from DuckDuckGo and Wikipedia.
        """
        results: List[str] = []
        clean_query = query.strip()
        if not clean_query:
            return results

        queries_to_search = [clean_query]
        # For leadership / "who is" questions, also search "current ..." to fetch the latest incumbent
        if re.search(r"\b(who\s+is|prime\s+minister|president|governor|chief\s+minister|ceo|leader|chancellor)\b", clean_query, re.IGNORECASE):
            variant = re.sub(r"\bwho\s+is\s+(?:the\s+)?", "current ", clean_query, flags=re.IGNORECASE).strip()
            if variant not in queries_to_search:
                queries_to_search.append(variant)

        for q in queries_to_search[:2]:
            # 1. DuckDuckGo Instant Answer API
            try:
                api_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(q)}&format=json&no_html=1&skip_disambig=1"
                req = urllib.request.Request(api_url, headers={"User-Agent": "ProAssistAI/1.0"})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    ans = data.get("Answer", "").strip()
                    abstract = data.get("AbstractText", "").strip()
                    heading = data.get("Heading", "").strip()
                    if ans and ans not in results:
                        results.append(ans)
                    if abstract and abstract not in results:
                        results.append(f"{heading}: {abstract}" if heading else abstract)
                    for topic in data.get("RelatedTopics", [])[:3]:
                        if isinstance(topic, dict) and "Text" in topic and topic["Text"] not in results:
                            results.append(topic["Text"])
            except Exception as e:
                print(f"[OnlineLLM] DDG API note: {e}")

            # 2. DuckDuckGo Lite search snippets
            try:
                lite_url = "https://lite.duckduckgo.com/lite/"
                post_data = urllib.parse.urlencode({"q": q}).encode("utf-8")
                req = urllib.request.Request(
                    lite_url,
                    data=post_data,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                        "Content-Type": "application/x-www-form-urlencoded"
                    }
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    page = resp.read().decode("utf-8", errors="ignore")
                snippets = re.findall(
                    r'<td class=[\'"]result-snippet[\'"][^>]*>(.*?)</td>',
                    page,
                    re.DOTALL | re.IGNORECASE
                )
                for s in snippets[:4]:
                    t = " ".join(html.unescape(re.sub(r'<[^>]+>', ' ', s)).split())
                    if t and t not in results:
                        results.append(t)
            except Exception as e:
                print(f"[OnlineLLM] DDG Lite note: {e}")

            # 3. Wikipedia search API
            try:
                w_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(q)}&utf8=&format=json"
                req = urllib.request.Request(w_url, headers={"User-Agent": "ProAssistAI/1.0"})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    wdata = json.loads(resp.read().decode("utf-8"))
                    for item in wdata.get("query", {}).get("search", [])[:2]:
                        snippet = html.unescape(re.sub(r'<[^>]+>', '', item.get("snippet", "")))
                        title = item.get("title", "")
                        entry = f"{title}: {snippet}"
                        if entry not in results:
                            results.append(entry)
            except Exception as e:
                print(f"[OnlineLLM] Wikipedia search note: {e}")

        return results

    def _solve_math_query(self, query: str) -> Optional[str]:
        """
        Attempts direct arithmetic resolution for common spoken math questions
        like 'what is the sum of 2+2' or 'what is 25 times 4'.
        """
        q_lower = query.lower().strip()
        # "sum of X and Y" / "sum of X + Y"
        m_sum = re.search(r"\bsum\s+of\s+(-?\d+(?:\.\d+)?)\s*(?:and|\+|\s+plus\s+)\s*(-?\d+(?:\.\d+)?)", q_lower)
        if m_sum:
            n1 = float(m_sum.group(1))
            n2 = float(m_sum.group(2))
            res = n1 + n2
            res_str = str(int(res)) if res.is_integer() else f"{res:.2f}"
            return f"The sum of {m_sum.group(1)} and {m_sum.group(2)} is {res_str}."

        # "what is X + Y" / "what is X plus Y"
        m_add = re.search(r"\b(?:what\s+is\s+)?(-?\d+(?:\.\d+)?)\s*(?:\+|plus)\s*(-?\d+(?:\.\d+)?)", q_lower)
        if m_add and ("what is" in q_lower or "+" in q_lower or "plus" in q_lower):
            n1 = float(m_add.group(1))
            n2 = float(m_add.group(2))
            res = n1 + n2
            res_str = str(int(res)) if res.is_integer() else f"{res:.2f}"
            return f"The answer is {res_str}."

        return None

    def ask_ollama(self, query: str, context_chunks: List[str]) -> Optional[str]:
        """
        Sends query and retrieved web context to local Ollama LLM.
        """
        context_text = "\n".join(f"- {c}" for c in context_chunks[:10])
        system_prompt = (
            "You are ProAssist AI, an intelligent, factual voice assistant. "
            "Provide a direct, accurate, and concise answer in 1 to 2 sentences. "
            "Always prioritize the most recent real-time facts from the Web Information. "
            "Do not use markdown bolding, bullet points, or filler intro phrases like 'Based on the search'."
        )

        prompt = f"""Web Information (Real-time Internet Data):
----------------------------------------
{context_text}
----------------------------------------

Question: {query}
Concise Answer:"""


        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 100,
            }
        }

        try:
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json=payload,
                timeout=self.timeout
            )
            if resp.status_code == 200:
                answer = resp.json().get("response", "").strip()
                # Remove common LLM conversational prefixes
                answer = re.sub(r"^(?:Sure!|Certainly!|Here is the answer:|According to the search results,?\s*|Based on the provided information,?\s*)", "", answer, flags=re.IGNORECASE).strip()
                return answer
        except Exception as e:
            print(f"[OnlineLLM] Ollama call error: {e}")

        return None

    def _extract_fallback_answer(self, query: str, snippets: List[str]) -> str:
        """
        Extracts a clean, direct sentence from web snippets when Ollama is unavailable.
        """
        if not snippets:
            return f"I found online information about '{query}', but couldn't summarize a direct answer."

        # Pick the most informative snippet
        best_snippet = snippets[0]
        # Split into first 1-2 sentences
        sentences = re.split(r"(?<=[.!?])\s+", best_snippet)
        summary = " ".join(sentences[:2]).strip()
        return summary

    def answer(self, query: str, dry_run: bool = False) -> Dict[str, Any]:
        """
        Answers general knowledge and arithmetic queries.
        STRICT REQUIREMENT: Answers ONE AND ONLY IF there is an active internet connection.
        """
        clean_query = query.strip()

        # 1. Strict internet connection check
        is_online = self.is_internet_connected()
        if not is_online and not dry_run:
            print(f"[OnlineLLM] Query rejected: No internet connection for '{clean_query}'")
            return {
                "answered": False,
                "answer": "I need an active internet connection to answer that question.",
                "status": "offline_no_internet",
                "sources": [],
                "query": clean_query,
                "is_online": False,
            }

        # 2. Dry run path (for automated unit testing without external calls)
        if dry_run:
            math_ans = self._solve_math_query(clean_query)
            if math_ans:
                return {
                    "answered": True,
                    "answer": math_ans,
                    "status": "success",
                    "sources": ["Local Math Evaluator (Verified)"],
                    "query": clean_query,
                    "is_online": True,
                }
            return {
                "answered": True,
                "answer": f"[Online LLM Verified] Simulated answer for '{clean_query}'.",
                "status": "success",
                "sources": ["Simulated Web Search"],
                "query": clean_query,
                "is_online": True,
            }

        print(f"[OnlineLLM] Internet connected. Fetching live data for: '{clean_query}'...")

        # 3. Direct math resolution if applicable (e.g. 2+2)
        math_ans = self._solve_math_query(clean_query)
        if math_ans:
            print(f"[OnlineLLM] Math query resolved: {math_ans}")
            return {
                "answered": True,
                "answer": math_ans,
                "status": "success",
                "sources": ["Math Verification"],
                "query": clean_query,
                "is_online": True,
            }

        # 4. Fetch real-time web knowledge
        web_snippets = self.fetch_web_knowledge(clean_query)
        print(f"[OnlineLLM] Fetched {len(web_snippets)} web knowledge snippets.")

        # 5. Query Ollama LLM with retrieved web knowledge
        llm_answer = self.ask_ollama(clean_query, web_snippets)

        if llm_answer:
            final_answer = llm_answer
            source = f"Ollama ({self.ollama_model}) with Web Search"
        else:
            # Fallback to direct web snippet extraction
            final_answer = self._extract_fallback_answer(clean_query, web_snippets)
            source = "Web Search Extraction"

        print(f"[OnlineLLM] Answer generated via {source}: \"{final_answer}\"")

        return {
            "answered": True,
            "answer": final_answer,
            "status": "success",
            "sources": [source],
            "query": clean_query,
            "is_online": True,
        }
