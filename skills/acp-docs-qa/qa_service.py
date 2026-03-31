from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path


def _load_module(module_filename: str, module_name: str):
    path = Path(__file__).resolve().parent / module_filename
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {module_filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_retrieval_module = _load_module("retrieval.py", "acp_docs_retrieval")
_llm_module = _load_module("llm_client.py", "acp_docs_llm")

MarkdownRetriever = _retrieval_module.MarkdownRetriever
RetrievalConfig = _retrieval_module.RetrievalConfig
AnswerGenerator = _llm_module.AnswerGenerator
LlmConfig = _llm_module.LlmConfig


class AcpDocsQaService:
    """
    High-level façade that enforces RAG flow:
    1) retrieve relevant chunks
    2) generate answer strictly from retrieved context
    """

    def __init__(self) -> None:
        self._retriever = MarkdownRetriever(RetrievalConfig.from_env())
        self._answer_generator = AnswerGenerator(LlmConfig.from_env())
        self._lock = threading.Lock()

    def ask(self, query: str) -> str:
        with self._lock:
            context_chunks = self._retriever.search(query)
            return self._answer_generator.generate(query, context_chunks)
