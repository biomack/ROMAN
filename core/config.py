"""
Centralised configuration loaded from .env → environment variables → defaults.
"""

import logging
import os
from pathlib import Path
from dataclasses import dataclass

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@dataclass
class MCPServerConfig:
    name: str
    url: str
    transport: str  # "sse" or "http"

    @classmethod
    def from_env(cls, prefix: str) -> "MCPServerConfig | None":
        url = os.getenv(f"{prefix}_URL", "").strip()
        if not url:
            return None
        return cls(
            name=os.getenv(f"{prefix}_NAME", prefix.lower()).strip(),
            url=url,
            transport=os.getenv(f"{prefix}_TRANSPORT", "sse").lower().strip(),
        )


@dataclass
class Config:
    provider: str
    ollama_base_url: str
    ollama_model: str
    openai_base_url: str
    openai_model: str
    openai_api_key: str
    temperature: float
    skills_dir: str
    api_host: str
    api_port: int
    kafka_enabled: bool
    kafka_bootstrap_servers: str
    kafka_events_topic: str
    kafka_outbox_topic: str
    kafka_consumer_group: str
    session_ttl_seconds: int
    session_max_messages: int
    reference_file_max_bytes: int
    reference_files_total_max_bytes: int
    mattermost_enabled: bool
    mattermost_url: str
    mattermost_token: str
    supervisor_interval_seconds: int
    supervisor_services: list[str]
    mcp_servers: dict[str, MCPServerConfig]

    @classmethod
    def load(cls) -> "Config":
        supervisor_services_raw = os.getenv("SUPERVISOR_SERVICES", "")
        supervisor_services = [
            item.strip() for item in supervisor_services_raw.split(",") if item.strip()
        ]

        mcp_servers: dict[str, MCPServerConfig] = {}
        mcp_server_names = os.getenv("MCP_SERVERS", "").strip()
        logger.debug(f"MCP_SERVERS env var: '{mcp_server_names}'")
        if mcp_server_names:
            for prefix in mcp_server_names.split(","):
                prefix = prefix.strip().upper()
                if prefix:
                    server_cfg = MCPServerConfig.from_env(f"MCP_{prefix}")
                    if server_cfg:
                        mcp_servers[server_cfg.name] = server_cfg
                        logger.info(
                            f"Loaded MCP server config: {server_cfg.name} -> "
                            f"{server_cfg.url} ({server_cfg.transport})"
                        )
                    else:
                        logger.warning(f"MCP server config not found for prefix: MCP_{prefix}")

        return cls(
            provider=os.getenv("LLM_PROVIDER", "ollama").lower().strip(),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip(),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b").strip(),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "http://localhost:1234/v1").strip(),
            openai_model=os.getenv("OPENAI_MODEL", "qwen2.5-7b-instruct").strip(),
            openai_api_key=os.getenv("OPENAI_API_KEY", "lm-studio").strip(),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.4")),
            skills_dir=os.getenv("SKILLS_DIR", "skills").strip(),
            api_host=os.getenv("API_HOST", "0.0.0.0").strip(),
            api_port=int(os.getenv("API_PORT", "8000")),
            kafka_enabled=os.getenv("KAFKA_ENABLED", "false").lower() == "true",
            kafka_bootstrap_servers=os.getenv(
                "KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"
            ).strip(),
            kafka_events_topic=os.getenv("KAFKA_EVENTS_TOPIC", "agent-events").strip(),
            kafka_outbox_topic=os.getenv("KAFKA_OUTBOX_TOPIC", "agent-outbox").strip(),
            kafka_consumer_group=os.getenv(
                "KAFKA_CONSUMER_GROUP", "llm-new-skils-worker"
            ).strip(),
            session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "3600")),
            session_max_messages=int(os.getenv("SESSION_MAX_MESSAGES", "100")),
            reference_file_max_bytes=int(
                os.getenv("REFERENCE_FILE_MAX_BYTES", "32768")
            ),
            reference_files_total_max_bytes=int(
                os.getenv("REFERENCE_FILES_TOTAL_MAX_BYTES", "262144")
            ),
            mattermost_enabled=os.getenv("MATTERMOST_ENABLED", "false").lower() == "true",
            mattermost_url=os.getenv("MATTERMOST_URL", "").strip(),
            mattermost_token=os.getenv("MATTERMOST_TOKEN", "").strip(),
            supervisor_interval_seconds=int(
                os.getenv("SUPERVISOR_INTERVAL_SECONDS", "60")
            ),
            supervisor_services=supervisor_services,
            mcp_servers=mcp_servers,
        )
