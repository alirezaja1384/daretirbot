"""Configuration module for Daret Telegram Bot using python-decouple."""

from dataclasses import dataclass
from pathlib import Path
from decouple import Config, RepositoryEnv, config as global_config


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment or .env file."""

    bot_token: str
    cache_ttl_seconds: int = 300
    base_url: str = "https://daret.ir"
    http_timeout: float = 15.0
    inline_cache_time: int = 10
    scrape_concurrency: int = 5


def load_settings(env_file_path: Path | str | None = None) -> Settings:
    """Load settings using python-decouple.

    If env_file_path is provided and exists, uses RepositoryEnv for isolated reading,
    otherwise uses the standard global decouple.config.
    """
    cfg = global_config
    if env_file_path:
        env_path = Path(env_file_path)
        if env_path.is_file():
            cfg = Config(RepositoryEnv(str(env_path)))

    token = cfg("TELEGRAM_API_TOKEN", default="").strip()
    cache_ttl = cfg("DOORS_CACHE_TTL_SECONDS", default=300, cast=int)
    base_url = cfg("DARET_BASE_URL", default="https://daret.ir").rstrip("/")
    http_timeout = cfg("HTTP_TIMEOUT_SECONDS", default=15.0, cast=float)
    inline_cache_time = cfg("INLINE_CACHE_TTL_SECONDS", default=10, cast=int)
    scrape_concurrency = cfg("SCRAPE_CONCURRENCY", default=5, cast=int)

    return Settings(
        bot_token=token,
        cache_ttl_seconds=max(10, cache_ttl),
        base_url=base_url,
        http_timeout=max(1.0, http_timeout),
        inline_cache_time=max(0, inline_cache_time),
        scrape_concurrency=max(1, scrape_concurrency),
    )
