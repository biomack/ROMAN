"""
Unified LLM client interface.

Both OllamaClient and OpenAIClient return a normalised response:

    {
        "message": {
            "role": "assistant",
            "content": "...",
            "tool_calls": [                         # optional / None
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {
                        "name": "tool_name",
                        "arguments": { ... }        # always a dict
                    }
                }
            ]
        }
    }

Each client also transforms outgoing messages to the format its API
expects via _prepare_messages().
"""

from __future__ import annotations

import json
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def _make_call_id() -> str:
    return f"call_{uuid.uuid4().hex[:12]}"


class LLMClient(ABC):
    """Common interface every LLM backend must implement."""

    model: str

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.4,
    ) -> dict:
        ...

    @abstractmethod
    def list_models(self) -> list[str]:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @property
    @abstractmethod
    def provider_label(self) -> str:
        ...


# ======================================================================
# Ollama
# ======================================================================

class OllamaClient(LLMClient):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen2.5:7b"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    @property
    def provider_label(self) -> str:
        return f"Ollama ({self.base_url})"

    def chat(self, messages, tools=None, temperature=0.4):
        payload: dict = {
            "model": self.model,
            "messages": self._prepare_messages(messages),
            "stream": False,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = tools

        logger.debug(
            "Ollama request: model=%s, messages=%d, tools=%d",
            self.model, len(messages), len(tools or []),
        )
        resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        logger.debug("Ollama raw response keys: %s", list(data.keys()))

        msg = data.get("message", {})
        if msg.get("tool_calls"):
            msg["tool_calls"] = [
                self._normalise_tc(tc, i) for i, tc in enumerate(msg["tool_calls"])
            ]
        else:
            msg["tool_calls"] = None
        return {"message": msg}

    def list_models(self):
        resp = requests.get(f"{self.base_url}/api/tags", timeout=10)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]

    def is_available(self):
        try:
            requests.get(f"{self.base_url}/api/tags", timeout=5)
            return True
        except requests.ConnectionError:
            return False

    @staticmethod
    def _prepare_messages(messages: list[dict]) -> list[dict]:
        """Strip OpenAI-specific fields that Ollama doesn't understand."""
        prepared = []
        for msg in messages:
            m = dict(msg)
            m.pop("tool_call_id", None)
            if m.get("tool_calls"):
                m["tool_calls"] = [
                    {"function": tc["function"]} for tc in m["tool_calls"]
                ]
            else:
                m.pop("tool_calls", None)
            prepared.append(m)
        return prepared

    @staticmethod
    def _normalise_tc(tc: dict, index: int = 0) -> dict:
        args = tc.get("function", {}).get("arguments", {})
        if isinstance(args, str):
            args = json.loads(args)
        return {
            "id": _make_call_id(),
            "type": "function",
            "function": {"name": tc["function"]["name"], "arguments": args},
        }


# ======================================================================
# OpenAI-compatible  (LM Studio, OpenRouter, vLLM, llama.cpp, etc.)
# ======================================================================

class OpenAIClient(LLMClient):
    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        model: str = "qwen2.5-7b-instruct",
        api_key: str = "lm-studio",
        timeout: float = 1200.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    @property
    def provider_label(self) -> str:
        return f"OpenAI-compat ({self.base_url})"

    def chat(self, messages, tools=None, temperature=0.4):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict = {
            "model": self.model,
            "messages": self._prepare_messages(messages),
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        logger.debug(
            "OpenAI request: model=%s, messages=%d, tools=%d",
            self.model, len(messages), len(tools or []),
        )
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        usage = data.get("usage", {})
        if usage:
            logger.debug(
                "OpenAI usage: prompt_tokens=%s, completion_tokens=%s, total=%s",
                usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"),
            )

        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})

        tool_calls_raw = msg.get("tool_calls")
        normalised_tcs = None
        if tool_calls_raw:
            normalised_tcs = [self._normalise_tc(tc) for tc in tool_calls_raw]

        return {
            "message": {
                "role": msg.get("role", "assistant"),
                "content": msg.get("content") or "",
                "tool_calls": normalised_tcs,
            }
        }

    def list_models(self):
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            resp = requests.get(f"{self.base_url}/models", headers=headers, timeout=10)
            resp.raise_for_status()
            return [m["id"] for m in resp.json().get("data", [])]
        except Exception:
            return []

    def is_available(self):
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            resp = requests.get(f"{self.base_url}/models", headers=headers, timeout=5)
            return resp.status_code == 200
        except requests.ConnectionError:
            return False

    @staticmethod
    def _prepare_messages(messages: list[dict]) -> list[dict]:
        """Ensure messages conform to OpenAI chat/completions spec."""
        prepared = []
        for msg in messages:
            m = dict(msg)

            if m.get("tool_calls"):
                m["tool_calls"] = [
                    {
                        "id": tc.get("id", _make_call_id()),
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": (
                                json.dumps(tc["function"]["arguments"])
                                if isinstance(tc["function"]["arguments"], dict)
                                else tc["function"]["arguments"]
                            ),
                        },
                    }
                    for tc in m["tool_calls"]
                ]
                if not m.get("content"):
                    m["content"] = None
            else:
                m.pop("tool_calls", None)

            if m["role"] == "tool" and "tool_call_id" not in m:
                m["tool_call_id"] = _make_call_id()

            prepared.append(m)
        return prepared

    @staticmethod
    def _normalise_tc(tc: dict) -> dict:
        fn = tc.get("function", {})
        args = fn.get("arguments", "{}")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        return {
            "id": tc.get("id", _make_call_id()),
            "type": "function",
            "function": {"name": fn.get("name", ""), "arguments": args},
        }


# ======================================================================
# Factory
# ======================================================================

def create_client(
    provider: str,
    *,
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "qwen2.5:7b",
    openai_base_url: str = "http://localhost:1234/v1",
    openai_model: str = "qwen2.5-7b-instruct",
    openai_api_key: str = "lm-studio",
    openai_timeout_seconds: float = 1200.0,
) -> LLMClient:
    if provider == "ollama":
        return OllamaClient(base_url=ollama_base_url, model=ollama_model)
    if provider in ("openai", "lmstudio", "lm-studio", "openrouter", "vllm"):
        return OpenAIClient(
            base_url=openai_base_url,
            model=openai_model,
            api_key=openai_api_key,
            timeout=openai_timeout_seconds,
        )
    raise ValueError(f"Unknown provider '{provider}'. Use 'ollama' or 'openai'.")
