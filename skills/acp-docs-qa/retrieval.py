from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import urlsplit, urlunsplit

LOGGER = logging.getLogger(__name__)
HEADING_RE = re.compile(r"^(#{1,3})\s+(.*\S)\s*$")
TOKEN_RE = re.compile(r"[a-zA-Zа-яА-Я0-9_]{2,}")


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    source_file: str
    section: str
    score: float


@dataclass(frozen=True)
class MarkdownChunk:
    text: str
    source_file: str
    section: str


@dataclass(frozen=True)
class RetrievalConfig:
    repo_url: str
    git_username: str
    git_token: str
    local_repo_dir: Path
    cache_dir: Path
    embedding_model: str | None
    docs_subdir: str = "docs"
    default_top_k: int = 5
    min_score: float = 0.20

    @classmethod
    def from_env(cls) -> "RetrievalConfig":
        raw_repo_url = os.getenv(
            "ACP_DOCS_REPO_URL",
            "https://gitea.acp.astracloud.ru/astracloud/infrastructure.git",
        )
        docs_subdir = os.getenv("ACP_DOCS_DOCS_SUBDIR", "docs")
        repo_url, docs_subdir = cls._normalize_repo_url_and_docs_subdir(
            raw_repo_url, docs_subdir
        )
        local_repo_dir = Path(
            os.getenv("ACP_DOCS_LOCAL_REPO_DIR", ".cache/acp-docs-repo")
        ).resolve()
        cache_dir = Path(
            os.getenv("ACP_DOCS_INDEX_CACHE_DIR", ".cache/acp-docs-index")
        ).resolve()
        return cls(
            repo_url=repo_url,
            git_username=os.getenv("ACP_DOCS_GIT_USERNAME", ""),
            git_token=os.getenv("ACP_DOCS_GIT_TOKEN", ""),
            local_repo_dir=local_repo_dir,
            cache_dir=cache_dir,
            embedding_model=(os.getenv("ACP_DOCS_EMBEDDING_MODEL", "").strip() or None),
            docs_subdir=docs_subdir,
            default_top_k=int(os.getenv("ACP_DOCS_TOP_K", "5")),
            min_score=float(os.getenv("ACP_DOCS_MIN_SCORE", "0.20")),
        )

    @staticmethod
    def _normalize_repo_url_and_docs_subdir(
        repo_url: str, docs_subdir: str
    ) -> tuple[str, str]:
        parsed = urlsplit(repo_url)
        path = parsed.path or ""
        marker = "/src/branch/"
        if marker not in path:
            return repo_url, docs_subdir

        repo_path, tail = path.split(marker, 1)
        # tail format: "<branch>/<optional/docs/path>"
        tail_parts = [part for part in tail.split("/") if part]
        inferred_docs = ""
        if len(tail_parts) >= 2:
            inferred_docs = "/".join(tail_parts[1:])
        normalized_path = repo_path
        if not normalized_path.endswith(".git"):
            normalized_path = f"{normalized_path}.git"
        normalized_url = urlunsplit(
            (parsed.scheme, parsed.netloc, normalized_path, parsed.query, parsed.fragment)
        )
        if inferred_docs and docs_subdir == "docs":
            return normalized_url, inferred_docs
        return normalized_url, docs_subdir


class MarkdownRetriever:
    def __init__(self, config: RetrievalConfig) -> None:
        self.config = config
        self._encoder = None
        self._index = None
        self._metadata: list[MarkdownChunk] = []

    def search(self, query: str, *, top_k: int | None = None) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        effective_top_k = top_k or self.config.default_top_k
        LOGGER.info("ACP docs search started: query=%r top_k=%s", query, effective_top_k)
        self._ensure_index()
        if not self._metadata:
            LOGGER.warning("ACP docs search: metadata is empty")
            return []
        if not self.config.embedding_model:
            hits = self._search_lexical(query, top_k=effective_top_k)
            LOGGER.info("ACP docs lexical retrieval returned %s chunks", len(hits))
            return hits
        assert self._index is not None
        assert self._encoder is not None

        query_vector = self._encode([query])
        scores, indices = self._index.search(query_vector, effective_top_k)

        hits: list[RetrievedChunk] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            if float(score) < self.config.min_score:
                continue
            chunk = self._metadata[int(idx)]
            hits.append(
                RetrievedChunk(
                    text=chunk.text,
                    source_file=chunk.source_file,
                    section=chunk.section,
                    score=float(score),
                )
            )
        LOGGER.info("ACP docs embedding retrieval returned %s chunks", len(hits))
        return hits

    def _ensure_index(self) -> None:
        LOGGER.info("Ensuring ACP docs index")
        self._sync_repo()
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)
        fingerprint = self._build_repo_fingerprint()
        fingerprint_path = self.config.cache_dir / "fingerprint.txt"
        index_path = self.config.cache_dir / "index.faiss"
        metadata_path = self.config.cache_dir / "metadata.json"

        if fingerprint_path.exists() and metadata_path.exists():
            if fingerprint_path.read_text(encoding="utf-8").strip() == fingerprint:
                if self.config.embedding_model:
                    if index_path.exists():
                        self._load_cached(index_path=index_path, metadata_path=metadata_path)
                        return
                else:
                    raw = json.loads(metadata_path.read_text(encoding="utf-8"))
                    self._metadata = [MarkdownChunk(**item) for item in raw]
                    LOGGER.info("Loaded ACP docs metadata cache: %s chunks", len(self._metadata))
                    return

        chunks = self._load_and_chunk_markdown()
        self._build_index(chunks)
        if self.config.embedding_model and self._index is not None:
            import faiss

            faiss.write_index(self._index, str(index_path))
        metadata_payload = [
            {
                "text": chunk.text,
                "source_file": chunk.source_file,
                "section": chunk.section,
            }
            for chunk in self._metadata
        ]
        metadata_path.write_text(
            json.dumps(metadata_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        fingerprint_path.write_text(fingerprint, encoding="utf-8")
        LOGGER.info("ACP docs index rebuilt and cached: %s chunks", len(self._metadata))

    def _load_cached(self, *, index_path: Path, metadata_path: Path) -> None:
        import faiss
        from sentence_transformers import SentenceTransformer

        self._index = faiss.read_index(str(index_path))
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        self._metadata = [MarkdownChunk(**item) for item in raw]
        if self._encoder is None:
            self._encoder = SentenceTransformer(self.config.embedding_model)

    def _build_index(self, chunks: Sequence[MarkdownChunk]) -> None:
        self._metadata = list(chunks)
        if not self.config.embedding_model:
            self._index = None
            return
        if not self._metadata:
            import faiss

            self._index = faiss.IndexFlatIP(1)
            return

        import faiss

        embeddings = self._encode([chunk.text for chunk in self._metadata])
        dim = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings)
        self._index = index

    def _encode(self, texts: Sequence[str]):
        import numpy as np
        from sentence_transformers import SentenceTransformer

        if self._encoder is None:
            self._encoder = SentenceTransformer(self.config.embedding_model)
        vectors = self._encoder.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)

    def _sync_repo(self) -> None:
        repo_dir = self.config.local_repo_dir
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        if (repo_dir / ".git").exists():
            LOGGER.info("ACP docs repo sync: fetch/reset %s", repo_dir)
            self._run_git(["-C", str(repo_dir), "fetch", "--depth", "1", "origin", "main"])
            self._run_git(["-C", str(repo_dir), "reset", "--hard", "origin/main"])
            return

        repo_url = self._build_repo_url_with_credentials(self.config.repo_url)
        LOGGER.info("ACP docs repo sync: clone %s -> %s", self.config.repo_url, repo_dir)
        self._run_git(["clone", "--depth", "1", repo_url, str(repo_dir)])

    def _run_git(self, args: list[str]) -> None:
        command = ["git", *args]
        LOGGER.debug("Running git command: %s", " ".join(command))
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            LOGGER.error(
                "Git command failed (%s): stdout=%s stderr=%s",
                completed.returncode,
                completed.stdout.strip(),
                completed.stderr.strip(),
            )
            raise RuntimeError(
                f"Git command failed: {' '.join(command)}\n"
                f"stdout: {completed.stdout}\n"
                f"stderr: {completed.stderr}"
            )

    def _build_repo_url_with_credentials(self, url: str) -> str:
        username = self.config.git_username
        token = self.config.git_token
        if not username or not token:
            return url
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            return url
        netloc = f"{username}:{token}@{parsed.netloc}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

    def _build_repo_fingerprint(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self._docs_root_dir().rglob("*.md")):
            stat = path.stat()
            rel = path.relative_to(self.config.local_repo_dir).as_posix()
            digest.update(rel.encode("utf-8"))
            digest.update(str(stat.st_size).encode("utf-8"))
            digest.update(str(int(stat.st_mtime)).encode("utf-8"))
        return digest.hexdigest()

    def _load_and_chunk_markdown(self) -> list[MarkdownChunk]:
        markdown_paths = sorted(self._docs_root_dir().rglob("*.md"))
        all_chunks: list[MarkdownChunk] = []
        for path in markdown_paths:
            all_chunks.extend(self._chunk_markdown_file(path))
        LOGGER.info("Built %s markdown chunks", len(all_chunks))
        return all_chunks

    def _chunk_markdown_file(self, path: Path) -> list[MarkdownChunk]:
        rel_file = path.relative_to(self.config.local_repo_dir).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()

        chunks: list[MarkdownChunk] = []
        heading_stack: list[str] = []
        buffer: list[str] = []
        current_section = "Введение"

        def flush() -> None:
            if not buffer:
                return
            body = "\n".join(buffer).strip()
            buffer.clear()
            if not body:
                return
            chunks.append(
                MarkdownChunk(
                    text=body,
                    source_file=rel_file,
                    section=current_section,
                )
            )

        for line in lines:
            match = HEADING_RE.match(line)
            if match:
                flush()
                level = len(match.group(1))
                heading_text = match.group(2).strip()
                heading_stack[:] = heading_stack[: level - 1]
                heading_stack.append(heading_text)
                current_section = " > ".join(heading_stack)
                buffer.append(line)
                continue
            buffer.append(line)

        flush()
        return chunks

    def _docs_root_dir(self) -> Path:
        root = self.config.local_repo_dir
        docs_subdir = self.config.docs_subdir.strip().strip("/")
        if not docs_subdir:
            return root
        candidate = root / docs_subdir
        return candidate if candidate.exists() else root

    def _search_lexical(self, query: str, *, top_k: int) -> list[RetrievedChunk]:
        query_tokens = set(TOKEN_RE.findall(query.lower()))
        if not query_tokens:
            return []
        results: list[RetrievedChunk] = []
        query_lc = query.lower()
        for chunk in self._metadata:
            text_lc = chunk.text.lower()
            text_tokens = set(TOKEN_RE.findall(text_lc))
            if not text_tokens:
                continue
            overlap = len(query_tokens & text_tokens)
            if overlap == 0 and query_lc not in text_lc:
                continue
            score = overlap / max(1, len(query_tokens))
            if query_lc in text_lc:
                score += 0.20
            if score < self.config.min_score:
                continue
            results.append(
                RetrievedChunk(
                    text=chunk.text,
                    source_file=chunk.source_file,
                    section=chunk.section,
                    score=float(score),
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]
