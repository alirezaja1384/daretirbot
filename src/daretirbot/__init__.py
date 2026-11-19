"""daretirbot - Telegram inline bot for daret.ir."""

from .catalog import CatalogCache, DaretClient, Door
from .config import Settings, load_settings


def main() -> None:
    """Run the main entrypoint."""
    from .__main__ import main as _main

    _main()


def run_bot(*args, **kwargs):
    """Run bot service."""
    from .__main__ import run_bot as _run_bot

    return _run_bot(*args, **kwargs)


__all__ = [
    "CatalogCache",
    "DaretClient",
    "Door",
    "Settings",
    "load_settings",
    "main",
    "run_bot",
]
