"""Data models, web scraper, and cached catalog for daret.ir doors."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from html import escape as html_escape
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx

logger = logging.getLogger(__name__)

# Regex for slug path validation and Persian normalization
SLUG_PATH_PATTERN = re.compile(r"^/door/([a-zA-Z0-9_-]+)$")
SLUG_PATTERN = SLUG_PATH_PATTERN

# Persian / Arabic normalization mappings (including Tatweel/Kashida \u0640)
DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u0640]")
ARABIC_TO_PERSIAN = str.maketrans(
    {
        "ي": "ی",
        "ك": "ک",
        "ى": "ی",
        "ة": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "ء": "",
    }
)


def normalize_persian(text: str) -> str:
    """Normalize Persian text for search matching."""
    if not text:
        return ""
    # Remove diacritics
    cleaned = DIACRITICS.sub("", text)
    # Map Arabic characters to Persian
    cleaned = cleaned.translate(ARABIC_TO_PERSIAN)
    # Replace ZWNJ (\u200c) with space for token matching
    cleaned = cleaned.replace("\u200c", " ")
    # Lowercase Latin characters
    cleaned = cleaned.lower()
    # Collapse multiple whitespaces
    return " ".join(cleaned.split())


@dataclass(frozen=True)
class Door:
    """Represents a door from daret.ir."""

    slug: str
    title: str
    description: str
    url: str
    image_url: str
    thumb_url: str

    @property
    def search_text(self) -> str:
        """Combined normalized text for searching."""
        return f"{normalize_persian(self.title)} {normalize_persian(self.description)} {self.slug.lower()}"

    def build_caption_html(self) -> str:
        """Generate final Telegram message text using HTML formatting with emojis."""
        escaped_title = html_escape(self.title.strip())
        escaped_desc = html_escape(self.description.strip())
        return (
            f"🚪 <b>{escaped_title}</b>\n\n"
            f"{escaped_desc}\n\n"
            f'حالا برو <a href="{self.url}">درتو</a> بذار! 👇'
        )

    def build_caption_markdown(self) -> str:
        """Generate final Telegram message text in Markdown with emojis."""
        return (
            f"🚪 *{self.title.strip()}*\n\n"
            f"{self.description.strip()}\n\n"
            f"حالا برو [درتو]({self.url}) بذار! 👇"
        )


def clean_html_text(raw_html: str) -> str:
    """Strip HTML tags and unescape text, preserving Persian character adjacency."""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    return " ".join(soup.get_text().split())


def parse_door_html(slug: str, html_content: str, base_url: str) -> Door:
    """Extract door details from its HTML page using BeautifulSoup with resilient semantic matching."""
    base_url = base_url.rstrip("/")
    url = f"{base_url}/door/{slug}"
    image_url = f"{base_url}/doors/{slug}.jpg"
    thumb_url = f"{base_url}/doors/{slug}.jpg"

    soup = BeautifulSoup(html_content, "html.parser")

    # Extract Title:
    # 1. Look for main/article <h1> first, then document <h1>
    title = ""
    main_el = soup.find(["main", "article"])
    h1 = (main_el.find("h1") if main_el else None) or soup.find("h1")
    if h1:
        extracted = " ".join(h1.get_text().split())
        if extracted:
            title = extracted

    # 2. Fallback to Open Graph og:title (property or name)
    if not title:
        og_title = (
            soup.find("meta", attrs={"property": lambda v: bool(v and v.strip().lower() == "og:title")})
            or soup.find("meta", attrs={"name": lambda v: bool(v and v.strip().lower() == "og:title")})
        )
        if og_title and og_title.get("content"):
            extracted = " ".join(og_title["content"].split())
            if extracted:
                title = extracted

    # 3. Fallback to slug-based readable name
    if not title:
        title = f"در {slug.replace('-', ' ')}"

    # Extract Description:
    # Prefer og:description, then meta name="description"
    desc = ""
    og_desc = (
        soup.find("meta", attrs={"property": lambda v: bool(v and v.strip().lower() == "og:description")})
        or soup.find("meta", attrs={"name": lambda v: bool(v and v.strip().lower() == "og:description")})
        or soup.find("meta", attrs={"name": lambda v: bool(v and v.strip().lower() == "description")})
    )
    if og_desc and og_desc.get("content"):
        desc = " ".join(og_desc["content"].split())

    return Door(
        slug=slug,
        title=title,
        description=desc,
        url=url,
        image_url=image_url,
        thumb_url=thumb_url,
    )


class DaretClient:
    """HTTP client for scraping daret.ir."""

    def __init__(
        self,
        base_url: str = "https://daret.ir",
        timeout: float = 15.0,
        concurrency: int = 5,
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.concurrency = max(1, concurrency)
        self._external_client = client
        self._internal_client: httpx.AsyncClient | None = None

    async def get_client(self) -> httpx.AsyncClient:
        """Get or initialize the underlying httpx client."""
        if self._external_client is not None:
            return self._external_client
        if self._internal_client is None or self._internal_client.is_closed:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; DaretBot/1.0; +https://daret.ir)",
                "Accept-Language": "fa,en;q=0.9",
            }
            self._internal_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers=headers,
                follow_redirects=True,
            )
        return self._internal_client

    async def close(self) -> None:
        """Close client sessions."""
        if self._internal_client is not None and not self._internal_client.is_closed:
            await self._internal_client.aclose()

    async def fetch_door_slugs(self) -> list[str]:
        """Fetch the homepage and extract all unique door slugs in order using semantic anchor matching."""
        client = await self.get_client()
        resp = await client.get(self.base_url)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        found_slugs: list[str] = []
        seen: set[str] = set()
        base_parsed = urlparse(self.base_url)

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href:
                continue
            resolved = urljoin(self.base_url, href)
            parsed = urlparse(resolved)
            # Ensure same origin
            if base_parsed.netloc and parsed.netloc and parsed.netloc.lower() != base_parsed.netloc.lower():
                continue
            path = parsed.path.rstrip("/")
            match = SLUG_PATH_PATTERN.fullmatch(path)
            if match:
                slug = match.group(1).lower()
                if slug not in seen:
                    seen.add(slug)
                    found_slugs.append(slug)

        return found_slugs

    async def fetch_door_detail(
        self, slug: str, semaphore: asyncio.Semaphore
    ) -> Door | None:
        """Fetch detail page for a single door with bounded concurrency."""
        async with semaphore:
            client = await self.get_client()
            url = f"{self.base_url}/door/{slug}"
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return parse_door_html(slug, resp.text, self.base_url)
            except (httpx.HTTPError, TimeoutError, OSError) as e:
                logger.warning(
                    "Failed to fetch door detail for %s (%s): %s", slug, url, e
                )
                # Fallback door so catalog isn't broken
                return Door(
                    slug=slug,
                    title=f"در {slug.replace('-', ' ')}",
                    description="",
                    url=url,
                    image_url=f"{self.base_url}/doors/{slug}.jpg",
                    thumb_url=f"{self.base_url}/doors/{slug}.jpg",
                )

    async def fetch_all_doors(self) -> list[Door]:
        """Fetch all doors from daret.ir."""
        slugs = await self.fetch_door_slugs()
        if not slugs:
            logger.warning("No door slugs found on homepage %s", self.base_url)
            return []

        semaphore = asyncio.Semaphore(self.concurrency)
        tasks = [self.fetch_door_detail(slug, semaphore) for slug in slugs]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        doors = [door for door in results if door is not None]
        logger.info("Successfully fetched %d doors from %s", len(doors), self.base_url)
        return doors


class CatalogCache:
    """In-memory cache for doors with TTL and on-demand refresh.

    Checks if the catalog is stale on request, triggering a shared background refresh.
    Waits up to max_wait_seconds; if the refresh takes longer or fails, falls back
    to the stale cache without cancelling the ongoing refresh process.
    """

    def __init__(
        self,
        client: DaretClient,
        ttl_seconds: int = 300,
        max_wait_seconds: float = 5.0,
    ):
        self.client = client
        self.ttl_seconds = max(10, ttl_seconds)
        self.max_wait_seconds = max(0.1, max_wait_seconds)
        self._doors: list[Door] = []
        self._doors_by_slug: dict[str, Door] = {}
        self._last_updated: float = 0.0
        self._refresh_task: asyncio.Task[list[Door]] | None = None

    @property
    def is_expired(self) -> bool:
        """Check if cached doors have exceeded TTL."""
        if not self._doors:
            return True
        return (time.monotonic() - self._last_updated) > self.ttl_seconds

    @property
    def doors_count(self) -> int:
        return len(self._doors)

    def _ensure_refresh_task(self) -> asyncio.Task[list[Door]]:
        """Ensure a single shared refresh task is running."""
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(
                self._run_refresh(), name="daret_catalog_refresh"
            )
        return self._refresh_task

    async def _run_refresh(self) -> list[Door]:
        """Perform scraping and atomically update cache state."""
        try:
            logger.info("Refreshing daret.ir doors catalog...")
            fresh_doors = await self.client.fetch_all_doors()
            if fresh_doors:
                self._doors = fresh_doors
                self._doors_by_slug = {d.slug.lower(): d for d in fresh_doors}
                self._last_updated = time.monotonic()
                logger.info(
                    "Catalog updated with %d doors. Next check after TTL (%ds)",
                    len(fresh_doors),
                    self.ttl_seconds,
                )
            else:
                logger.warning(
                    "Scraper returned 0 doors; keeping existing cache (%d doors)",
                    len(self._doors),
                )
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError, TimeoutError, OSError) as e:
            logger.error(
                "Failed to refresh catalog: %s. Keeping existing cache (%d doors)",
                e,
                len(self._doors),
            )
        except Exception as e:
            logger.exception("Unexpected error refreshing catalog: %s", e)
        finally:
            if self._refresh_task is asyncio.current_task():
                self._refresh_task = None

        return list(self._doors)

    async def refresh(self, force: bool = False) -> list[Door]:
        """Trigger or join single-flight catalog refresh and wait for completion."""
        if force or not self._doors or self.is_expired:
            task = self._ensure_refresh_task()
            try:
                await asyncio.shield(task)
            except Exception:
                pass
        return list(self._doors)

    async def get_doors(self, max_wait_seconds: float | None = None) -> list[Door]:
        """Return cached doors.

        If cache is stale or empty, triggers refresh and waits up to max_wait_seconds.
        If refresh fails or takes longer than the wait cap, falls back to stale cache
        without cancelling the background refresh process.
        """
        # If populated and fresh, return immediately without network access
        if self._doors and not self.is_expired:
            return list(self._doors)

        # Stale or empty: ensure shared refresh task is running
        task = self._ensure_refresh_task()
        wait_cap = (
            self.max_wait_seconds
            if max_wait_seconds is None
            else max(0.0, max_wait_seconds)
        )

        if wait_cap > 0:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=wait_cap)
            except TimeoutError:
                logger.warning(
                    "Catalog refresh took longer than %.1fs cap; serving %s cache while refresh continues in background",
                    wait_cap,
                    "stale" if self._doors else "empty",
                )
            except Exception as e:
                logger.warning(
                    "Catalog refresh encountered error while waiting: %s; serving stale cache",
                    e,
                )

        return list(self._doors)

    def get_doors_sync(self) -> list[Door]:
        """Return currently cached doors without waiting for network."""
        return list(self._doors)

    def get_door_by_slug(self, slug: str) -> Door | None:
        """Find a door by its slug."""
        return self._doors_by_slug.get(slug.lower())

    def get_random_door(self) -> Door | None:
        """Pick a random door from current cache."""
        if not self._doors:
            return None
        import random

        return random.choice(self._doors)

    def search(self, query: str) -> list[Door]:
        """Search doors by title, description, or slug with Persian normalization."""
        if not query or not query.strip():
            return list(self._doors)

        normalized_query = normalize_persian(query)
        tokens = normalized_query.split()
        if not tokens:
            return list(self._doors)

        results: list[tuple[int, Door]] = []
        for door in self._doors:
            searchable = door.search_text
            # Check if all query tokens match
            if all(token in searchable for token in tokens):
                # Calculate simple ranking score (higher is better)
                score = 0
                norm_title = normalize_persian(door.title)
                if normalized_query in norm_title:
                    score += 50
                elif any(token in norm_title for token in tokens):
                    score += 20
                if normalized_query in door.slug:
                    score += 30
                results.append((score, door))

        # Sort by score descending
        results.sort(key=lambda item: item[0], reverse=True)
        return [door for _, door in results]

    async def close(self) -> None:
        """Cancel and await any active in-flight refresh task on shutdown."""
        task = self._refresh_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            self._refresh_task = None
        logger.info("Catalog cache closed")

    def start_background_worker(self) -> None:
        """Deprecated: periodic background worker removed in favor of demand-driven refresh."""
        pass

    async def stop_background_worker(self) -> None:
        """Deprecated alias for close()."""
        await self.close()
