from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_service():
    path = Path(__file__).resolve().parent / "qa_service.py"
    spec = importlib.util.spec_from_file_location("acp_docs_qa_service", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load service from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AcpDocsQaService()


def main() -> None:
    service = _load_service()
    query = "Как публикуется документация?"
    answer = service.ask(query)
    print(answer)


if __name__ == "__main__":
    main()
