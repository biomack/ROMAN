"""
Centralised configuration loaded from .env -> environment variables -> defaults.
"""

import os
from pathlib import Path
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class MattermostConfig:
    url: str
    token: str
    team: str
    channel: str
    bot_name: str
    thread_history_depth: int

    @classmethod
    def from_env(cls) -> "MattermostConfig":
        thread_history_depth = int(os.getenv("MATTERMOST_THREAD_HISTORY_DEPTH", "20"))
        return cls(
            url=os.getenv("MATTERMOST_URL", "").strip(),
            token=os.getenv("MATTERMOST_TOKEN", "").strip(),
            team=os.getenv("MATTERMOST_TEAM", "").strip(),
            channel=os.getenv("MATTERMOST_CHANNEL", "").strip(),
            bot_name=os.getenv("MATTERMOST_BOT_NAME", "").strip(),
            thread_history_depth=max(0, thread_history_depth),
        )


@dataclass
class Config:
    provider: str
    openai_base_url: str
    openai_model: str
    openai_api_key: str
    openai_timeout_seconds: float
    temperature: float
    skills_source_type: str
    skills_dir: str
    skills_git_url: str
    skills_git_branch: str
    skills_git_ref: str
    skills_git_clone_dir: str
    session_ttl_seconds: int
    session_max_messages: int
    reference_file_max_bytes: int
    reference_files_total_max_bytes: int
    metrics_enabled: bool
    metrics_host: str
    metrics_port: int
    mattermost: MattermostConfig

    @classmethod
    def load(cls) -> "Config":
        return cls(
            provider=os.getenv("LLM_PROVIDER", "openai").lower().strip(),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "http://localhost:1234/v1").strip(),
            openai_model=os.getenv("OPENAI_MODEL", "qwen2.5-7b-instruct").strip(),
            openai_api_key=os.getenv("OPENAI_API_KEY", "lm-studio").strip(),
            openai_timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "1200")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.4")),
            skills_source_type=os.getenv("SKILLS_SOURCE_TYPE", "local").lower().strip() or "local",
            skills_dir=os.getenv("SKILLS_DIR", "skills").strip() or "skills",
            skills_git_url=os.getenv("SKILLS_GIT_URL", "").strip(),
            skills_git_branch=os.getenv("SKILLS_GIT_BRANCH", "main").strip() or "main",
            skills_git_ref=os.getenv("SKILLS_GIT_REF", "").strip(),
            skills_git_clone_dir=(
                os.getenv("SKILLS_GIT_CLONE_DIR", ".cache/skills-git").strip()
                or ".cache/skills-git"
            ),
            session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "3600")),
            session_max_messages=int(os.getenv("SESSION_MAX_MESSAGES", "100")),
            reference_file_max_bytes=int(
                os.getenv("REFERENCE_FILE_MAX_BYTES", "32768")
            ),
            reference_files_total_max_bytes=int(
                os.getenv("REFERENCE_FILES_TOTAL_MAX_BYTES", "262144")
            ),
            metrics_enabled=_env_bool("PROMETHEUS_METRICS_ENABLED", True),
            metrics_host=os.getenv("PROMETHEUS_METRICS_HOST", "0.0.0.0").strip(),
            metrics_port=int(os.getenv("PROMETHEUS_METRICS_PORT", "9108")),
            mattermost=MattermostConfig.from_env(),
        )
