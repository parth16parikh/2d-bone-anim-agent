"""Runtime settings: models, API access, and the budgets from LLD 3.7.

Secrets come from the environment or from a git-ignored `.env` file in the repository root.
"""

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # the folder that holds pyproject.toml


class Settings(BaseSettings):
    # The repository's .env is found from any working directory; a .env in the current one wins.
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    planner_model: str = "gpt-5.4-mini"
    guard_model: str = "gpt-5.4-nano"

    anthropic_api_key: str | None = None
    anthropic_planner_model: str = "claude-sonnet-5"
    anthropic_guard_model: str = "claude-haiku-4-5-20251001"

    logfire_token: str | None = None

    # Unity delivery (Phase G). The server URL is the MCP endpoint of MCP for Unity.
    unity_mcp_url: str = "http://127.0.0.1:8080/mcp"
    # The Unity project folder (the one with Assets/). A relative path is taken from the
    # repository root, so UNITY_PROJECT_PATH=unity-project works from any working directory.
    unity_project_path: Path | None = None
    unity_timeout: float = 30.0  # seconds to wait for one MCP call
    unity_prefab_dir: str = ""  # where to save prefabs, e.g. Assets/Prefabs/Rigs ("" = do not)

    @field_validator("unity_project_path", mode="after")
    @classmethod
    def _project_relative_to_the_repository(cls, path: Path | None) -> Path | None:
        if path is None:
            return None
        path = path.expanduser()
        return path if path.is_absolute() else PROJECT_ROOT / path

    # The primary provider is tried first; the other one is the failover (LLD 3.13).
    primary_provider: Literal["openai", "anthropic"] = "openai"

    # Per-request budgets (LLD 3.7)
    max_llm_calls: int = 12
    max_seconds: int = 60
    max_total_tokens: int = 150_000
    max_outer_iterations: int = 3
    max_inner_retries: int = 3
    max_tool_calls: int = 15


settings = Settings()
