"""
Document Ingestion Module for ProAssist AI RAG
Loads and extracts text and metadata from .txt, .md, .pdf, and .docx files.
"""

import os
import sys
import re
import difflib
from pathlib import Path
from rag import config as rag_config


class DocumentLoader:
    """Loads and parses raw documents into structured page/section records."""

    def __init__(self, supported_extensions: list = None):
        self.supported_extensions = supported_extensions or rag_config.SUPPORTED_EXTENSIONS

    def load_document(self, file_path: str | Path) -> list[dict]:
        """
        Loads a single document and returns a list of page/section dicts.
        Returns:
            list of dicts: [
                {
                    "source": filename,
                    "file_path": str(file_path),
                    "file_type": ext,
                    "page": page_number (int or None),
                    "text": extracted_text,
                    "metadata": {...}
                }, ...
            ]
        """
        p = Path(file_path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Document file not found: {p}")

        ext = p.suffix.lower()
        if ext not in self.supported_extensions:
            raise ValueError(f"Unsupported file type '{ext}'. Supported: {self.supported_extensions}")

        try:
            if ext in [".txt", ".md"]:
                return self._load_text(p)
            elif ext == ".pdf":
                return self._load_pdf(p)
            elif ext == ".docx":
                return self._load_docx(p)
            else:
                raise ValueError(f"No parser available for '{ext}'")
        except Exception as e:
            print(f"[DocumentLoader ERROR] Failed to load {p.name}: {e}")
            raise

    def _load_text(self, path: Path) -> list[dict]:
        """Loads plain text or markdown file."""
        encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
        content = ""
        for enc in encodings:
            try:
                content = path.read_text(encoding=enc).strip()
                break
            except (UnicodeDecodeError, LookupError):
                continue

        if not content:
            return []

        return [{
            "source": path.name,
            "file_path": str(path),
            "file_type": path.suffix.lower(),
            "page": 1,
            "text": content,
            "metadata": {"size_bytes": path.stat().st_size}
        }]

    def _load_pdf(self, path: Path) -> list[dict]:
        """Loads PDF document using pypdf or PyMuPDF, extracting page numbers."""
        docs = []

        # Attempt PyMuPDF (fitz) first for high-speed extraction if available
        try:
            import fitz
            doc = fitz.open(str(path))
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text().strip()
                if text:
                    docs.append({
                        "source": path.name,
                        "file_path": str(path),
                        "file_type": ".pdf",
                        "page": page_num + 1,
                        "text": text,
                        "metadata": {"page_number": page_num + 1, "total_pages": len(doc)}
                    })
            doc.close()
            return docs
        except ImportError:
            pass

        # Fallback to pypdf
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            total_pages = len(reader.pages)
            for page_num, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                text = text.strip()
                if text:
                    docs.append({
                        "source": path.name,
                        "file_path": str(path),
                        "file_type": ".pdf",
                        "page": page_num + 1,
                        "text": text,
                        "metadata": {"page_number": page_num + 1, "total_pages": total_pages}
                    })
            return docs
        except Exception as e:
            raise RuntimeError(f"Error reading PDF file {path.name}: {e}")

    def _load_docx(self, path: Path) -> list[dict]:
        """Loads Microsoft Word .docx file extracting paragraphs."""
        try:
            import docx
            doc = docx.Document(str(path))
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            full_text = "\n\n".join(paragraphs)
            if not full_text:
                return []

            return [{
                "source": path.name,
                "file_path": str(path),
                "file_type": ".docx",
                "page": 1,
                "text": full_text,
                "metadata": {"paragraph_count": len(paragraphs)}
            }]
        except Exception as e:
            raise RuntimeError(f"Error reading DOCX file {path.name}: {e}")

    def load_directory(self, dir_path: str | Path = None) -> list[dict]:
        """
        Recursively discovers and loads all supported documents in the directory.
        """
        target_dir = Path(dir_path or rag_config.KNOWLEDGE_DIR).resolve()
        if not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)
            return []

        all_pages = []
        files = [p for p in target_dir.rglob("*") if p.is_file() and p.suffix.lower() in self.supported_extensions]

        print(f"[DocumentLoader] Discovered {len(files)} supported documents in {target_dir}")
        for file_path in files:
            try:
                pages = self.load_document(file_path)
                all_pages.extend(pages)
                print(f"  [+] Loaded '{file_path.name}' ({len(pages)} sections/pages)")
            except Exception as e:
                print(f"  [-] Skipped '{file_path.name}' due to error: {e}")

        return all_pages

    def find_user_documents(self, query_name: str = None, extensions: list = None) -> list[Path]:
        """
        Discovers documents in the user's environment (knowledge_dir, Desktop, Documents, Downloads).
        If query_name is provided, matches files containing query keywords or closest stem matches.
        Returns sorted list of matching Path objects (highest relevance / most recent first).
        """
        # Determine extensions filter: if user said "pdf", restrict to .pdf
        is_pdf_requested = bool(query_name and "pdf" in query_name.lower())
        if is_pdf_requested and not extensions:
            target_exts = {".pdf"}
        else:
            target_exts = set(extensions or self.supported_extensions)

        candidate_dirs = [
            rag_config.KNOWLEDGE_DIR,
            Path.home() / "Desktop",
            Path.home() / "OneDrive" / "Desktop",
            Path.home() / "Downloads",
            Path.home() / "Documents",
            Path.home() / "OneDrive" / "Documents",
            Path.cwd(),
        ]

        seen_names = set()
        all_discovered = []

        for c_dir in candidate_dirs:
            if not c_dir.exists():
                continue
            try:
                for item in c_dir.iterdir():
                    if item.is_file() and item.suffix.lower() in target_exts:
                        if item.name in seen_names:
                            continue
                        seen_names.add(item.name)
                        all_discovered.append(item)
            except Exception:
                continue

        if not query_name:
            all_discovered.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
            return all_discovered

        # Check direct path
        try:
            p_direct = Path(query_name).resolve()
            if p_direct.is_file():
                return [p_direct]
        except Exception:
            pass

        # Check exact filename match
        q_str = str(query_name).strip().strip("\"'")
        for item in all_discovered:
            if item.name.lower() == q_str.lower():
                return [item]

        # Clean query: strip extensions first, then punctuation, then stop words
        clean_q = re.sub(r"\.(pdf|docx|doc|txt|md)\b", " ", q_str, flags=re.IGNORECASE)
        clean_q = re.sub(r"[^\w\s]", " ", clean_q)
        stop_words = {
            "the", "a", "an", "pdf", "pdfs", "file", "files", "document", "documents",
            "in", "on", "at", "explorer", "that", "exists", "exist", "present", "all",
            "my", "some", "any", "is", "are", "of", "to", "from", "show", "summarize",
            "summary", "read", "check", "open", "launch", "start", "view", "test",
            "inspect", "what", "which", "who", "where", "how", "tell", "me", "about",
            "can", "you", "please", "could", "would"
        }
        keywords = [w for w in clean_q.lower().split() if w not in stop_words and len(w) >= 2]

        if not keywords:
            # Generic request (e.g. "the pdf", "files in file explorer") -> sort by most recent mtime
            all_discovered.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
            return all_discovered

        scored = []
        clean_query_phrase = "".join(keywords)
        joined_query_phrase = " ".join(keywords)

        for item in all_discovered:
            name_lower = item.stem.lower()
            clean_name = re.sub(r"[^\w]", "", name_lower)
            tokens_in_name = set(re.findall(r"[a-z0-9]+", name_lower))

            score = 0
            # Exact stem match or exact clean match
            if clean_name == clean_query_phrase or name_lower == joined_query_phrase:
                score += 1000

            # Substring matches
            if clean_query_phrase and clean_query_phrase in clean_name:
                score += 300
            elif clean_name and clean_name in clean_query_phrase:
                score += 300

            # Token overlap
            common_tokens = set(keywords) & tokens_in_name
            if common_tokens:
                score += len(common_tokens) * 60

            # Keyword partial substring matches
            for k in keywords:
                if k in name_lower:
                    score += 30

            # Fuzzy similarity
            ratio = difflib.SequenceMatcher(None, joined_query_phrase, name_lower).ratio()
            if ratio > 0.4:
                score += int(ratio * 150)

            if score > 0:
                scored.append((score, item))

        if scored:
            scored.sort(key=lambda x: (x[0], x[1].stat().st_mtime if x[1].exists() else 0), reverse=True)
            return [item for _, item in scored]

        # Fallback if no scores: return all discovered sorted by most recent
        all_discovered.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        return all_discovered


if __name__ == "__main__":
    loader = DocumentLoader()
    print("=" * 65)
    print(f"  PROASSIST AI - DOCUMENT INGESTION DIAGNOSTIC")
    print(f"  Knowledge Directory: {rag_config.KNOWLEDGE_DIR}")
    print("=" * 65)
    loaded_docs = loader.load_directory()
    print(f"\n[Result] Extracted {len(loaded_docs)} total document pages/sections.")
