from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI


NO_ANSWER_TEXT = "Ответ не найден в документации"


class ChunkLike(Protocol):
    text: str
    source_file: str
    section: str
    score: float


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    model: str
    api_key: str
    max_tokens: int = 1000
    temperature: float = 0.0
    max_context_chars: int = 12000
    max_chunk_chars: int = 1800

    @classmethod
    def from_env(cls) -> "LlmConfig":
        return cls(
            base_url=os.getenv("OPENAI_BASE_URL", "http://localhost:1234/v1"),
            model=os.getenv("OPENAI_MODEL", "openai/gpt-oss-20b"),
            api_key=os.getenv("OPENAI_API_KEY", "lm-studio"),
            max_tokens=int(os.getenv("ACP_DOCS_LLM_MAX_TOKENS", "1000")),
            temperature=0.0,
            max_context_chars=int(os.getenv("ACP_DOCS_MAX_CONTEXT_CHARS", "12000")),
            max_chunk_chars=int(os.getenv("ACP_DOCS_MAX_CHUNK_CHARS", "1800")),
        )


class AnswerGenerator:
    def __init__(self, config: LlmConfig) -> None:
        self._config = config
        self._client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key or "lm-studio",
        )

    def generate(self, query: str, context: list[ChunkLike]) -> str:
        if not context:
            return self._format_no_answer()

        context_block = self._render_context(
            context,
            max_context_chars=self._config.max_context_chars,
            max_chunk_chars=self._config.max_chunk_chars,
        )
        prompt = (
            "Вопрос пользователя:\n"
            f"{query}\n\n"
            "Контекст документации:\n"
            f"{context_block}\n\n"
            "Требования:\n"
            "1) Отвечай строго на основе Контекста документации.\n"
            "2) Не добавляй внешние знания.\n"
            "3) Если информации недостаточно, верни JSON с short_answer и details равными "
            f"\"{NO_ANSWER_TEXT}\".\n"
            "4) Если в контексте есть команды/шаги, обязательно добавь их в поле example.\n"
            "5) Ответ должен быть только в JSON формате:\n"
            "{\"short_answer\": \"...\", \"details\": \"...\", \"example\": \"...\", \"source\": \"...\"}"
        )

        response = self._client.chat.completions.create(
            model=self._config.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты технический ассистент по документации ACP/XaaS. "
                        "Температура 0, без домыслов, только контекст."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
        )
        raw_text = self._extract_text(response)
        payload = self._safe_json(raw_text)
        if payload is None:
            return self._format_no_answer()
        return self._format_output(
            short_answer=str(payload.get("short_answer", "")).strip() or NO_ANSWER_TEXT,
            details=str(payload.get("details", "")).strip() or NO_ANSWER_TEXT,
            example=str(payload.get("example", "")).strip() or "Нет примера",
            source=str(payload.get("source", "")).strip() or "Источник не указан",
        )

    def _extract_text(self, response: object) -> str:
        choices = getattr(response, "choices", [])
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        if message is None:
            return ""
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content.strip()
        return str(content).strip()

    @staticmethod
    def _safe_json(raw_text: str) -> dict | None:
        text = raw_text.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _render_context(
        chunks: list[ChunkLike],
        *,
        max_context_chars: int,
        max_chunk_chars: int,
    ) -> str:
        blocks: list[str] = []
        total_chars = 0
        for idx, chunk in enumerate(chunks, start=1):
            chunk_text = chunk.text
            if len(chunk_text) > max_chunk_chars:
                chunk_text = chunk_text[:max_chunk_chars] + "\n...<truncated>"
            block = (
                f"[{idx}] file={chunk.source_file}; section={chunk.section}; score={chunk.score:.3f}\n"
                f"{chunk_text}"
            )
            projected = total_chars + len(block) + (2 if blocks else 0)
            if projected > max_context_chars:
                break
            blocks.append(block)
            total_chars = projected
        return "\n\n".join(blocks)

    def _format_no_answer(self) -> str:
        return self._format_output(
            short_answer=NO_ANSWER_TEXT,
            details=NO_ANSWER_TEXT,
            example="Нет примера",
            source="Источник не найден",
        )

    @staticmethod
    def _format_output(
        *,
        short_answer: str,
        details: str,
        example: str,
        source: str,
    ) -> str:
        return (
            "Краткий ответ:\n"
            f"{short_answer}\n\n"
            "Подробности:\n"
            f"{details}\n\n"
            "Пример:\n"
            f"{example}\n\n"
            "Источник:\n"
            f"{source}"
        )
