"""Entry point for running the daretirbot service."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .catalog import CatalogCache, DaretClient
from .config import Settings, load_settings
from .inline import router

logger = logging.getLogger("daretirbot")


async def run_bot(settings: Settings | None = None) -> None:
    """Initialize resources and start Telegram polling."""
    if settings is None:
        settings = load_settings()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if (
        not settings.bot_token
        or settings.bot_token == "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
    ):
        logger.warning(
            "TELEGRAM_API_TOKEN is missing or using default placeholder. "
            "Please configure a valid token from @BotFather in your .env file."
        )

    # Initialize daret.ir client and cache
    daret_client = DaretClient(
        base_url=settings.base_url,
        timeout=settings.http_timeout,
        concurrency=settings.scrape_concurrency,
    )
    cache = CatalogCache(
        client=daret_client,
        ttl_seconds=settings.cache_ttl_seconds,
        max_wait_seconds=settings.cache_refresh_max_wait_seconds,
    )

    # Pre-warm catalog
    try:
        logger.info("Pre-warming daret.ir catalog on startup...")
        await cache.refresh()
    except Exception as e:
        logger.warning("Initial catalog fetch failed: %s (will fetch on demand)", e)

    # Initialize bot & dispatcher
    bot = Bot(
        token=settings.bot_token or "123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    # Inject shared dependencies
    dp["cache"] = cache
    dp["inline_cache_time"] = settings.inline_cache_time

    try:
        logger.info(
            "Starting Telegram bot polling (updates: message, inline_query, chosen_inline_result, callback_query)..."
        )
        await dp.start_polling(
            bot,
            allowed_updates=[
                "message",
                "inline_query",
                "chosen_inline_result",
                "callback_query",
            ],
        )
    except Exception as e:
        logger.error("Bot polling stopped with error: %s", e)
    finally:
        logger.info("Cleaning up bot resources...")
        await cache.close()
        await daret_client.close()
        await bot.session.close()
        logger.info("Shutdown complete.")


def main() -> None:
    """CLI entrypoint."""
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
