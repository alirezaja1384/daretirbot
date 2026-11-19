"""Unit tests for inline message formatting and handlers."""

import unittest
from unittest.mock import AsyncMock, MagicMock

try:
    import aiogram
    from aiogram.types import (
        ChosenInlineResult,
        InlineQuery,
        InlineQueryResultArticle,
        InputTextMessageContent,
    )
    from daretirbot.inline import (
        RANDOM_RESULT_ID,
        build_door_article_result,
        build_random_placeholder_result,
        handle_inline_query,
        handle_inline_sent_to_bot,
        handle_random_chosen,
    )

    AIOGRAM_AVAILABLE = True
except ImportError:
    AIOGRAM_AVAILABLE = False

from daretirbot.catalog import CatalogCache, Door


class TestInline(unittest.IsolatedAsyncioTestCase):
    """Test inline query formatting and logic."""

    def setUp(self) -> None:
        self.door = Door(
            slug="phone-booth",
            title="در باجه تلفن‌!",
            description="باجه‌ی قرمز با کلی شیشه‌ی کوچیک. تلفنش سکه می‌خوره و دیگه هیچ‌کس سکه نداره.",
            url="https://daret.ir/door/phone-booth",
            image_url="https://daret.ir/doors/phone-booth.jpg",
            thumb_url="https://daret.ir/doors/phone-booth.jpg",
        )

    def test_door_caption_structure(self) -> None:
        """Verify caption satisfies the prompt requirements with emojis."""
        caption = self.door.build_caption_html()
        self.assertIn("🚪 <b>در باجه تلفن‌!</b>", caption)
        self.assertIn("باجه‌ی قرمز با کلی شیشه‌ی کوچیک", caption)
        self.assertIn(
            'حالا برو <a href="https://daret.ir/door/phone-booth">درتو</a> بذار! 👇',
            caption,
        )

    @unittest.skipUnless(AIOGRAM_AVAILABLE, "aiogram is required for this test")
    def test_build_door_article_result(self) -> None:
        """Test InlineQueryResultArticle generation with thumbnail and link preview."""
        result = build_door_article_result(self.door)
        self.assertIsInstance(result, InlineQueryResultArticle)
        self.assertEqual(result.id, "door_phone-booth")
        self.assertEqual(result.thumbnail_url, "https://daret.ir/doors/phone-booth.jpg")
        self.assertEqual(result.title, "در باجه تلفن‌!")
        self.assertIsInstance(result.input_message_content, InputTextMessageContent)
        self.assertIn("<b>در باجه تلفن‌!</b>", result.input_message_content.message_text)
        self.assertFalse(result.input_message_content.link_preview_options.is_disabled)
        self.assertEqual(
            result.input_message_content.link_preview_options.url,
            "https://daret.ir/door/phone-booth",
        )

    @unittest.skipUnless(AIOGRAM_AVAILABLE, "aiogram is required for this test")
    def test_build_random_placeholder_result(self) -> None:
        """Test random placeholder result has thumbnail, keyboard, and placeholder text."""
        result = build_random_placeholder_result(self.door)
        self.assertIsInstance(result, InlineQueryResultArticle)
        self.assertEqual(result.id, RANDOM_RESULT_ID)
        self.assertEqual(result.thumbnail_url, "https://daret.ir/doors/phone-booth.jpg")
        self.assertIn("در حال پیدا کردن دَرِت", result.input_message_content.message_text)
        self.assertIsNotNone(result.reply_markup)
        self.assertEqual(len(result.reply_markup.inline_keyboard), 1)

    @unittest.skipUnless(AIOGRAM_AVAILABLE, "aiogram is required for this test")
    async def test_handle_inline_query_empty_shows_random_first(self) -> None:
        """Empty query displays random option first, followed by doors."""
        mock_cache = MagicMock(spec=CatalogCache)
        mock_cache.get_doors = AsyncMock(return_value=[self.door])
        mock_cache.get_random_door.return_value = self.door
        mock_cache.search.return_value = [self.door]

        mock_inline_query = MagicMock(spec=InlineQuery)
        mock_inline_query.query = ""
        mock_inline_query.offset = ""
        mock_inline_query.answer = AsyncMock()

        await handle_inline_query(mock_inline_query, mock_cache, inline_cache_time=10)

        mock_inline_query.answer.assert_called_once()
        _, kwargs = mock_inline_query.answer.call_args
        results = kwargs["results"]
        self.assertGreaterEqual(len(results), 2)
        # First result is random placeholder
        self.assertEqual(results[0].id, RANDOM_RESULT_ID)
        # Second is the door article
        self.assertEqual(results[1].id, "door_phone-booth")

    @unittest.skipUnless(AIOGRAM_AVAILABLE, "aiogram is required for this test")
    async def test_handle_random_chosen_edits_text_and_link_preview(self) -> None:
        """Chosen inline result for random door edits text with door preview and removes keyboard."""
        mock_bot = MagicMock()
        mock_bot.edit_message_text = AsyncMock()

        mock_cache = MagicMock(spec=CatalogCache)
        mock_cache.get_random_door.return_value = self.door

        chosen_result = MagicMock(spec=ChosenInlineResult)
        chosen_result.result_id = RANDOM_RESULT_ID
        chosen_result.inline_message_id = "test_inline_msg_id"

        await handle_random_chosen(chosen_result, mock_bot, mock_cache)

        mock_bot.edit_message_text.assert_called_once()
        _, kwargs = mock_bot.edit_message_text.call_args
        self.assertEqual(kwargs["inline_message_id"], "test_inline_msg_id")
        self.assertIn("<b>در باجه تلفن‌!</b>", kwargs["text"])
        self.assertEqual(kwargs["link_preview_options"].url, "https://daret.ir/door/phone-booth")
        self.assertIsNone(kwargs["reply_markup"])

    @unittest.skipUnless(AIOGRAM_AVAILABLE, "aiogram is required for this test")
    async def test_handle_inline_sent_to_bot(self) -> None:
        """User sending an inline result directly to the bot receives funny reply."""
        mock_bot = MagicMock()
        mock_bot_user = MagicMock()
        mock_bot_user.id = 999
        mock_bot.get_me = AsyncMock(return_value=mock_bot_user)

        mock_message = MagicMock()
        mock_message.via_bot = mock_bot_user
        mock_message.text = "🚪 در باجه تلفن‌!"
        mock_message.reply = AsyncMock()

        await handle_inline_sent_to_bot(mock_message, mock_bot)

        mock_message.reply.assert_called_once()
        reply_args, _ = mock_message.reply.call_args
        self.assertIn("اگه در این حد نمی‌دونی", reply_args[0])
        self.assertIn("بذاری", reply_args[0])
