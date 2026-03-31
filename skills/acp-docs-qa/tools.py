from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Annotated

from core.tool_registry import tool


def _load_service_class():
    module_path = Path(__file__).resolve().parent / "qa_service.py"
    spec = importlib.util.spec_from_file_location("acp_docs_qa_service", str(module_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load qa_service.py from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["acp_docs_qa_service"] = module
    spec.loader.exec_module(module)
    service_cls = getattr(module, "AcpDocsQaService", None)
    if service_cls is None:
        raise ImportError("AcpDocsQaService is not defined in qa_service.py")
    return service_cls


ACP_DOCS_QA_SERVICE = _load_service_class()()


@tool("Answer ACP/XaaS documentation questions with retrieval-first RAG")
def ask_acp_docs(
    query: Annotated[str, "User question in Russian about ACP/XaaS docs"],
) -> str:
    return ACP_DOCS_QA_SERVICE.ask(query)
