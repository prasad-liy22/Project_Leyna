"""Application settings.

Everything is driven by environment variables (or a local ``.env`` file) so the
same code runs locally and in production without edits.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Ollama Cloud -------------------------------------------------------
    ollama_api_key: str = Field(
        default="",
        description="Bearer token for ollama.com (create one at "
        "https://ollama.com/settings/keys).",
    )
    ollama_base_url: str = Field(
        default="https://ollama.com",
        description="Base URL of the Ollama API. Point this at "
        "http://localhost:11434 for a local Ollama server.",
    )
    # NOTE: `gemma4:31b-cloud` works against ollama.com directly. The name from
    # `curl https://ollama.com/api/tags` (e.g. ``gemma4:31b``) works too, while
    # the Ollama app/CLI uses ``gemma4:cloud``.
    ollama_model: str = Field(default="gemma4:31b-cloud")

    # --- Assistant behaviour ------------------------------------------------
    system_prompt: str = Field(
        default="You are Leyna, a warm, concise and helpful personal assistant.",
        description="Default system prompt used when a request does not "
        "provide its own.",
    )

    # --- HTTP ---------------------------------------------------------------
    request_timeout: float = Field(
        default=120.0,
        description="Timeout in seconds for a single upstream request.",
    )

    # --- CORS ---------------------------------------------------------------
    cors_origins: str = Field(
        default="*",
        description="Comma-separated list of allowed origins, or '*' for any. "
        "Set to your frontend URL(s) in production.",
    )

    # --- Web UI -------------------------------------------------------------
    web_dir: str = Field(
        default=str(Path(__file__).resolve().parents[2] / "web" / "dist"),
        description="Directory holding the built Tailwind web UI, served at "
        "'/'. Defaults to <repo>/web/dist. Rebuild it with "
        "'cd web && npm run build'.",
    )

    # --- Debug --------------------------------------------------------------
    debug_enabled: bool = Field(
        default=True,
        description="Expose the /debug routes (logs, usage, API key). "
        "Set to false in production.",
    )
    admin_token: str = Field(
        default="",
        description="When set, /debug routes require a matching X-Admin-Token "
        "header. Leave empty for open access during local development.",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Allowed origins as a list, for the CORS middleware."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def chat_url(self) -> str:
        """Full URL of the Ollama chat endpoint."""
        return f"{self.ollama_base_url.rstrip('/')}/api/chat"

    @property
    def is_configured(self) -> bool:
        """Whether an API key has been provided."""
        return bool(self.ollama_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    """Return cached settings (read once per process)."""
    return Settings()
