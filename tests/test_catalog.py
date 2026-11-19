"""Unit tests for catalog scraper, parsing, normalization, and cache."""

import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
import httpx

from daretirbot.catalog import (
    CatalogCache,
    DaretClient,
    Door,
    clean_html_text,
    normalize_persian,
    parse_door_html,
)


def test_normalize_persian() -> None:
    """Test Persian normalization handles Arabic letters, diacritics, and ZWNJ."""
    # Arabic Yeh and Kaf
    assert normalize_persian("يك در پاكيزه") == "یک در پاکیزه"
    # ZWNJ removal/spacing
    assert normalize_persian("باجه\u200cی تلفن") == "باجه ی تلفن"
    # Diacritics
    assert normalize_persian("دَرِت") == "درت"
    # Lowercase & trimming
    assert normalize_persian("  Phone-Booth Door  ") == "phone-booth door"


def test_door_caption_formatting() -> None:
    """Verify caption format matching the specification with emojis."""
    door = Door(
        slug="phone-booth",
        title="در باجه تلفن‌!",
        description="باجه‌ی قرمز با کلی شیشه‌ی کوچیک. تلفنش سکه می‌خوره و دیگه هیچ‌کس سکه نداره.",
        url="https://daret.ir/door/phone-booth",
        image_url="https://daret.ir/doors/phone-booth.jpg",
        thumb_url="https://daret.ir/doors/phone-booth.jpg",
    )

    caption_html = door.build_caption_html()
    expected_html = (
        "🚪 <b>در باجه تلفن‌!</b>\n\n"
        "باجه‌ی قرمز با کلی شیشه‌ی کوچیک. تلفنش سکه می‌خوره و دیگه هیچ‌کس سکه نداره.\n\n"
        'حالا برو <a href="https://daret.ir/door/phone-booth">درتو</a> بذار! 👇'
    )
    assert caption_html == expected_html

    caption_md = door.build_caption_markdown()
    expected_md = (
        "🚪 *در باجه تلفن‌!*\n\n"
        "باجه‌ی قرمز با کلی شیشه‌ی کوچیک. تلفنش سکه می‌خوره و دیگه هیچ‌کس سکه نداره.\n\n"
        "حالا برو [درتو](https://daret.ir/door/phone-booth) بذار! 👇"
    )
    assert caption_md == expected_md


def test_parse_door_html() -> None:
    """Test extracting door data from sample HTML."""
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta property="og:title" content="در باجه تلفن" />
        <meta property="og:description" content="باجه‌ی قرمز با کلی شیشه‌ی کوچیک. تلفنش سکه می‌خوره و دیگه هیچ‌کس سکه نداره." />
        <meta property="og:image" content="https://daret.ir/social/phone-booth.jpg" />
    </head>
    <body>
        <h1>در <!-- -->باجه تلفن<!-- -->\u200c!</h1>
    </body>
    </html>
    """
    door = parse_door_html("phone-booth", sample_html, "https://daret.ir")
    assert door.slug == "phone-booth"
    assert door.title == "در باجه تلفن‌!"
    assert "تلفنش سکه می‌خوره" in door.description
    assert door.url == "https://daret.ir/door/phone-booth"
    assert door.image_url == "https://daret.ir/doors/phone-booth.jpg"


def test_clean_html_text() -> None:
    """Test stripping tags and comments."""
    text = "<div>در <!-- -->کانتینر<!-- -->\u200c! </div>"
    assert clean_html_text(text) == "در کانتینر‌!"


def test_parse_door_html_resilience() -> None:
    """Test resilient parsing with reordered attributes, nested tags, entities, and semantic main tag."""
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta content="توضیحات استاندارد" name="description" />
        <meta content="توضیحات اوپن‌گراف با کیفیت &amp; جذاب" property="og:description" />
        <meta content="در باجه تلفن" property="og:title" />
    </head>
    <body>
        <header>
            <h1>عنوان هدر سایت</h1>
        </header>
        <main>
            <div class="wrapper depth-3 random-class">
                <h1>در <span class="badge">باجه</span> <em>تلفن</em><!-- comment -->&nbsp;قدیمی</h1>
            </div>
        </main>
    </body>
    </html>
    """
    door = parse_door_html("phone-booth", sample_html, "https://daret.ir")
    assert door.slug == "phone-booth"
    assert door.title == "در باجه تلفن قدیمی"
    assert door.description == "توضیحات اوپن‌گراف با کیفیت & جذاب"


def test_parse_door_html_fallbacks() -> None:
    """Test title and description fallbacks when elements are absent."""
    # Fallback to og:title when h1 is absent
    html_without_h1 = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="og:title" content="در شیشه‌ای فروشگاه" />
    </head>
    <body><p>محتوا بدون تیتر</p></body>
    </html>
    """
    door_og = parse_door_html("glass-door", html_without_h1, "https://daret.ir")
    assert door_og.title == "در شیشه‌ای فروشگاه"
    assert door_og.description == ""

    # Fallback to slug-based title when no h1 or og:title exists
    html_empty = "<html><body></body></html>"
    door_fallback = parse_door_html("revolving-door", html_empty, "https://daret.ir")
    assert door_fallback.title == "در revolving door"
    assert door_fallback.description == ""


class TestAsyncCatalog(IsolatedAsyncioTestCase):
    """Async tests for scraper and cache."""

    async def test_daret_client_fetch_slugs(self) -> None:
        """Test extracting slugs from homepage with mock transport."""
        homepage_html = """
        <div>
            <a href="/door/toilet">توالت</a>
            <a href="/door/manhole">منهول</a>
            <a href="/door/toilet">توالت تکراری</a>
            <a href="/about">درباره</a>
            <a href="/door/phone-booth">باجه تلفن</a>
        </div>
        """

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=homepage_html)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = DaretClient(base_url="https://daret.ir", client=http_client)
            slugs = await client.fetch_door_slugs()
            self.assertEqual(slugs, ["toilet", "manhole", "phone-booth"])

    async def test_daret_client_fetch_slugs_resilience(self) -> None:
        """Test semantic anchor matching ignores external URLs, subpaths, and non-anchor matches."""
        homepage_html = """
        <div>
            <!-- Non-anchor mention of door -->
            <p>متن معمولی شامل /door/fake نباید شناسایی شود</p>
            <script>const x = "/door/in-script";</script>
            <!-- Same-origin relative and absolute URLs -->
            <a href="/door/elevator/">آسانسور با اسلش انتهایی</a>
            <a href="https://daret.ir/door/saloon">کابویی مطلق</a>
            <a href="/door/bank?utm_source=home#card">بانک با کوئری و فرگمنت</a>
            <!-- Invalid paths and external origins -->
            <a href="/door/toilet/subpath">مسیر تودرتو</a>
            <a href="https://evil.com/door/malicious">سایت دیگر</a>
            <a href="/door/">بدون اسلاگ</a>
            <a href="javascript:void(0)">لینک جاوااسکریپت</a>
        </div>
        """

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=homepage_html)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = DaretClient(base_url="https://daret.ir", client=http_client)
            slugs = await client.fetch_door_slugs()
            self.assertEqual(slugs, ["elevator", "saloon", "bank"])

    async def test_catalog_cache_search_and_refresh(self) -> None:
        """Test cache search, Persian normalization matching, and TTL behavior."""
        doors = [
            Door(
                slug="phone-booth",
                title="در باجه تلفن‌!",
                description="باجه‌ی قرمز با کلی شیشه‌ی کوچیک.",
                url="https://daret.ir/door/phone-booth",
                image_url="https://daret.ir/doors/phone-booth.jpg",
                thumb_url="https://daret.ir/doors/phone-booth.jpg",
            ),
            Door(
                slug="pride",
                title="در پراید",
                description="پراید صبا مدل ۸۴ نقره‌ای.",
                url="https://daret.ir/door/pride",
                image_url="https://daret.ir/doors/pride.jpg",
                thumb_url="https://daret.ir/doors/pride.jpg",
            ),
        ]

        mock_client = AsyncMock(spec=DaretClient)
        mock_client.fetch_all_doors.return_value = doors

        cache = CatalogCache(client=mock_client, ttl_seconds=300)
        self.assertTrue(cache.is_expired)

        cached_doors = await cache.get_doors()
        self.assertEqual(len(cached_doors), 2)
        self.assertFalse(cache.is_expired)

        # Search with exact and normalized queries
        self.assertEqual(len(cache.search("باجه تلفن")), 1)
        self.assertEqual(cache.search("باجه تلفن")[0].slug, "phone-booth")

        # Search by description
        self.assertEqual(len(cache.search("نقره‌ای")), 1)
        self.assertEqual(cache.search("نقره‌ای")[0].slug, "pride")

        # Search with Arabic kaf/yeh should still match
        self.assertEqual(len(cache.search("پرایـد")), 1)

        # Random door
        random_door = cache.get_random_door()
        self.assertIn(random_door, doors)

        # Get door by slug
        self.assertEqual(cache.get_door_by_slug("PRIDE"), doors[1])
        self.assertIsNone(cache.get_door_by_slug("non-existent"))

    async def test_cache_failure_preserves_existing_data(self) -> None:
        """If scraper fails on subsequent refresh, previous cache is preserved."""
        doors = [
            Door(
                slug="saloon",
                title="در کابویی",
                description="در چوبی غرب وحشی.",
                url="https://daret.ir/door/saloon",
                image_url="https://daret.ir/doors/saloon.jpg",
                thumb_url="https://daret.ir/doors/saloon.jpg",
            )
        ]
        mock_client = AsyncMock(spec=DaretClient)
        mock_client.fetch_all_doors.return_value = doors

        cache = CatalogCache(client=mock_client, ttl_seconds=1)
        await cache.refresh()
        self.assertEqual(cache.doors_count, 1)

        # Simulate network failure
        mock_client.fetch_all_doors.side_effect = httpx.ConnectError(
            "Connection failed"
        )
        cache._last_updated = 0.0
        self.assertTrue(cache.is_expired)

        # Refresh should not wipe cache
        res = await cache.refresh()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].slug, "saloon")

    async def test_stale_cache_refreshed_on_request(self) -> None:
        """When cache is stale, get_doors triggers refresh on-demand."""
        initial_doors = [
            Door(
                slug="old-door",
                title="در قدیمی",
                description="قدیمی",
                url="https://daret.ir/door/old-door",
                image_url="https://daret.ir/doors/old-door.jpg",
                thumb_url="https://daret.ir/doors/old-door.jpg",
            )
        ]
        fresh_doors = [
            Door(
                slug="new-door",
                title="در جدید",
                description="جدید",
                url="https://daret.ir/door/new-door",
                image_url="https://daret.ir/doors/new-door.jpg",
                thumb_url="https://daret.ir/doors/new-door.jpg",
            )
        ]
        mock_client = AsyncMock(spec=DaretClient)
        mock_client.fetch_all_doors.return_value = fresh_doors

        cache = CatalogCache(client=mock_client, ttl_seconds=10)
        cache._doors = initial_doors
        cache._doors_by_slug = {"old-door": initial_doors[0]}
        cache._last_updated = 0.0  # Force stale
        self.assertTrue(cache.is_expired)

        result = await cache.get_doors()
        self.assertEqual(result, fresh_doors)
        self.assertFalse(cache.is_expired)
        mock_client.fetch_all_doors.assert_called_once()

    async def test_timeout_fallback_to_stale_and_refresh_survives(self) -> None:
        """If refresh exceeds wait cap, get_doors returns stale cache, and refresh task continues."""
        stale_doors = [
            Door(
                slug="stale-door",
                title="در قدیمی",
                description="قدیمی",
                url="https://daret.ir/door/stale-door",
                image_url="https://daret.ir/doors/stale-door.jpg",
                thumb_url="https://daret.ir/doors/stale-door.jpg",
            )
        ]
        fresh_doors = [
            Door(
                slug="fresh-door",
                title="در تازه",
                description="تازه",
                url="https://daret.ir/door/fresh-door",
                image_url="https://daret.ir/doors/fresh-door.jpg",
                thumb_url="https://daret.ir/doors/fresh-door.jpg",
            )
        ]

        async def slow_fetch() -> list[Door]:
            await asyncio.sleep(0.15)
            return fresh_doors

        mock_client = AsyncMock(spec=DaretClient)
        mock_client.fetch_all_doors.side_effect = slow_fetch

        cache = CatalogCache(client=mock_client, ttl_seconds=10, max_wait_seconds=0.03)
        cache._doors = stale_doors
        cache._doors_by_slug = {"stale-door": stale_doors[0]}
        cache._last_updated = 0.0
        self.assertTrue(cache.is_expired)

        # Call get_doors with small wait cap
        result = await cache.get_doors(max_wait_seconds=0.03)
        # Should return stale doors immediately without waiting for slow fetch
        self.assertEqual(result, stale_doors)
        # Verify the background task is still running (was not cancelled)
        self.assertIsNotNone(cache._refresh_task)
        self.assertFalse(cache._refresh_task.done())

        # Wait for the background task to complete
        await asyncio.sleep(0.18)
        # Now cache should be updated with fresh doors
        self.assertEqual(cache.get_doors_sync(), fresh_doors)
        self.assertFalse(cache.is_expired)

    async def test_concurrent_requests_share_refresh_task(self) -> None:
        """Multiple concurrent requests when stale share the single in-flight refresh task."""
        doors = [
            Door(
                slug="shared-door",
                title="در مشترک",
                description="توضیح",
                url="https://daret.ir/door/shared-door",
                image_url="https://daret.ir/doors/shared-door.jpg",
                thumb_url="https://daret.ir/doors/shared-door.jpg",
            )
        ]

        async def slow_fetch() -> list[Door]:
            await asyncio.sleep(0.05)
            return doors

        mock_client = AsyncMock(spec=DaretClient)
        mock_client.fetch_all_doors.side_effect = slow_fetch

        cache = CatalogCache(client=mock_client, ttl_seconds=10, max_wait_seconds=1.0)
        cache._last_updated = 0.0
        self.assertTrue(cache.is_expired)

        # Concurrent requests
        res1, res2 = await asyncio.gather(cache.get_doors(), cache.get_doors())
        self.assertEqual(res1, doors)
        self.assertEqual(res2, doors)
        # Underlying scraper called exactly once
        mock_client.fetch_all_doors.assert_called_once()
        await cache.close()
