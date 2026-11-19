"""Unit tests for configuration module."""

from pathlib import Path
import tempfile
import unittest

from daretirbot.config import Settings, load_settings


class TestConfig(unittest.TestCase):
    """Test configuration loader."""

    def test_default_settings(self) -> None:
        """Test default values when no env vars are defined."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = Path(tmp_dir) / ".env"
            env_file.write_text("TELEGRAM_API_TOKEN=test_token_123\n")

            settings = load_settings(env_file_path=env_file)
            self.assertEqual(settings.bot_token, "test_token_123")
            self.assertEqual(settings.cache_ttl_seconds, 300)
            self.assertEqual(settings.base_url, "https://daret.ir")
            self.assertEqual(settings.http_timeout, 15.0)
            self.assertEqual(settings.inline_cache_time, 10)
            self.assertEqual(settings.scrape_concurrency, 5)
            self.assertEqual(settings.cache_refresh_max_wait_seconds, 5.0)

    def test_custom_settings(self) -> None:
        """Test custom configuration options."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = Path(tmp_dir) / ".env"
            env_file.write_text(
                "TELEGRAM_API_TOKEN=my_bot_token_abc\n"
                "DOORS_CACHE_TTL_SECONDS=600\n"
                "DOORS_CACHE_REFRESH_MAX_WAIT_SECONDS=2.5\n"
                "DARET_BASE_URL=https://custom.daret.ir/\n"
                "HTTP_TIMEOUT_SECONDS=25.5\n"
                "INLINE_CACHE_TTL_SECONDS=30\n"
                "SCRAPE_CONCURRENCY=8\n"
            )

            settings = load_settings(env_file_path=env_file)
            self.assertEqual(settings.bot_token, "my_bot_token_abc")
            self.assertEqual(settings.cache_ttl_seconds, 600)
            self.assertEqual(settings.cache_refresh_max_wait_seconds, 2.5)
            self.assertEqual(settings.base_url, "https://custom.daret.ir")
            self.assertEqual(settings.http_timeout, 25.5)
            self.assertEqual(settings.inline_cache_time, 30)
            self.assertEqual(settings.scrape_concurrency, 8)

    def test_minimum_bounds(self) -> None:
        """Test that safe minimum bounds are enforced."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = Path(tmp_dir) / ".env"
            env_file.write_text(
                "TELEGRAM_API_TOKEN=tok\n"
                "DOORS_CACHE_TTL_SECONDS=2\n"
                "DOORS_CACHE_REFRESH_MAX_WAIT_SECONDS=-2.0\n"
                "HTTP_TIMEOUT_SECONDS=-5\n"
                "INLINE_CACHE_TTL_SECONDS=-1\n"
                "SCRAPE_CONCURRENCY=-3\n"
            )

            settings = load_settings(env_file_path=env_file)
            self.assertGreaterEqual(settings.cache_ttl_seconds, 10)
            self.assertGreaterEqual(settings.cache_refresh_max_wait_seconds, 0.1)
            self.assertGreaterEqual(settings.http_timeout, 1.0)
            self.assertGreaterEqual(settings.inline_cache_time, 0)
            self.assertGreaterEqual(settings.scrape_concurrency, 1)
