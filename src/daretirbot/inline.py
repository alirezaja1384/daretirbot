"""Telegram inline handlers, search, and chosen inline result resolution for aiogram."""

from __future__ import annotations

import logging
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    ChosenInlineResult,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResult,
    InlineQueryResultArticle,
    InputTextMessageContent,
    LinkPreviewOptions,
    Message,
)

from .catalog import CatalogCache, Door, normalize_persian

logger = logging.getLogger(__name__)

router = Router(name="daret_inline")

RANDOM_RESULT_ID = "random_door"
RANDOM_KEYWORDS = {"random", "شانسی", "شانس"}
PAGE_SIZE = 40


def build_door_article_result(door: Door) -> InlineQueryResultArticle:
    """Create an InlineQueryResultArticle for a door showing thumbnail in suggestions and link preview in message."""
    desc = f"🚪 {door.description}" if door.description else "🚪 بزن روش تا درت رو بذاری!"
    return InlineQueryResultArticle(
        id=f"door_{door.slug}",
        title=door.title,
        description=desc,
        thumbnail_url=door.thumb_url,
        input_message_content=InputTextMessageContent(
            message_text=door.build_caption_html(),
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(
                is_disabled=False,
                url=door.url,
                prefer_large_media=True,
            ),
        ),
    )


def build_random_placeholder_result(
    sample_door: Door | None,
) -> InlineQueryResultArticle:
    """Create the random door inline suggestion.

    Uses an article with temporary text and keyboard so chosen_inline_result receives inline_message_id.
    """
    placeholder_text = (
        "🎲 <b>در حال پیدا کردن دَرِت...</b> ⏳\n\n"
        "<i>چند لحظه صبر کن تا درِ شانسیت آماده بشه!</i> ✨"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 یه در شانسی برام بیار 🔄",
                    callback_data="fetch_random_door",
                )
            ]
        ]
    )

    return InlineQueryResultArticle(
        id=RANDOM_RESULT_ID,
        title="🎲 یه در شانسی!",
        description="✨ یه در رندوم و خفن برات انتخاب می‌کنه",
        thumbnail_url=sample_door.thumb_url if sample_door else None,
        input_message_content=InputTextMessageContent(
            message_text=placeholder_text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        ),
        reply_markup=keyboard,
    )


@router.message(CommandStart())
@router.message(Command("help"))
async def handle_start(message: Message, bot: Bot) -> None:
    """Handle /start and /help commands."""
    bot_info = await bot.get_me()
    bot_username = bot_info.username or "daretirbot"

    text = (
        "<b>به ربات دَرِت خوش اومدی!</b> ✨\n\n"
        "کلکسیونی از درهای دست‌ساز باکیفیت و شاهکار، جهت ارائه به افرادی که نیازه "
        "در اسرع وقت درشون رو بذارن! 🚪\n\n"
        "🔍 <b>چطوری می‌تونی استفاده‌ش کنی؟ (حالت اینلاین):</b>\n"
        f"توی هر چت یا گروهی، فقط کافیه آیدی ربات رو تایپ کنی:\n"
        f"👉 <code>@{bot_username} </code>\n\n"
        "💡 بعدش می‌تونی اسم در مورد نظرت رو سرچ کنی (مثلاً «باجه تلفن» یا «پراید») "
        "یا گزینه <b>🎲 یه در شانسی</b> رو انتخاب کنی.\n\n"
        "ℹ️ <b>درباره این پروژه:</b>\n"
        "این ربات یک پروژه مستقل است و پروژه رسمی daret.ir نیست؛ بلکه بر اساس و با الهام از محتوای "
        "وب‌سایت <a href=\"https://daret.ir/\">daret.ir</a> ساخته شده و تمامی حقوق، محتوا و کپی‌رایت "
        "متعلق به سازندگان وب‌سایت دَرِت (<a href=\"https://haashemi.dev/\">haashemi.dev</a>) محفوظ می‌باشد."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚪 دَرِت رو انتخاب کن (اینلاین) 🔍",
                    switch_inline_query_current_chat="",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🌐 دیدن سایت daret.ir 🔗",
                    url="https://daret.ir/",
                )
            ],
        ]
    )

    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.message(
    F.chat.type == "private",
    (F.via_bot != None) | (F.text.contains("daret.ir/door")),
)
async def handle_inline_sent_to_bot(message: Message, bot: Bot) -> None:
    """When a user sends an inline result into the chat with the bot itself."""
    bot_info = await bot.get_me()
    is_our_bot = message.via_bot and message.via_bot.id == bot_info.id
    is_door_text = bool(
        message.text and ("daret.ir/door" in message.text or "درتو" in message.text)
    )

    if is_our_bot or is_door_text or message.via_bot:
        reply_text = (
            "🚪 اگه در این حد نمی‌دونی چطور باید ازش استفاده کنی، شاید بهتر باشه درت خودتو بذاری 🫪"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🚪 برو در یه چت یا گروه دیگه رو بذار! 😆",
                        switch_inline_query="",
                    )
                ]
            ]
        )
        await message.reply(reply_text, reply_markup=keyboard)


@router.inline_query()
async def handle_inline_query(
    inline_query: InlineQuery,
    cache: CatalogCache,
    inline_cache_time: int = 10,
) -> None:
    """Handle inline queries with search, pagination, and random option."""
    query = inline_query.query.strip()
    norm_query = normalize_persian(query)

    # Ensure cache has doors
    doors = await cache.get_doors()
    if not doors:
        article = InlineQueryResultArticle(
            id="empty_catalog",
            title="⏳ در حال آماده‌سازی لیست درها...",
            description="🔄 یه چند لحظه دیگه دوباره امتحان کن.",
            input_message_content=InputTextMessageContent(
                message_text="⏳ داریم لیست درها رو آماده می‌کنیم... یه کوچولو بعد دوباره امتحان کن! 🚪",
            ),
        )
        await inline_query.answer(
            results=[article],
            cache_time=5,
            is_personal=True,
        )
        return

    # Parse pagination offset
    try:
        offset = int(inline_query.offset) if inline_query.offset else 0
    except ValueError:
        offset = 0

    results: list[InlineQueryResult] = []
    is_random_requested = any(kw in norm_query for kw in RANDOM_KEYWORDS)
    is_empty_query = not query

    # Only show the random suggestion on the first page
    if offset == 0 and (is_empty_query or is_random_requested):
        sample_door = cache.get_random_door()
        results.append(build_random_placeholder_result(sample_door))

    # If the user specifically typed a random keyword, don't overwhelm with search results
    if is_random_requested and not is_empty_query:
        await inline_query.answer(
            results=results,
            cache_time=inline_cache_time,
            is_personal=True,
        )
        return

    # Perform search or return all doors
    matched_doors = cache.search(query)

    # Slice doors for current page
    paged_doors = matched_doors[offset : offset + PAGE_SIZE]
    for door in paged_doors:
        results.append(build_door_article_result(door))

    # Determine next offset
    next_offset = ""
    if offset + PAGE_SIZE < len(matched_doors):
        next_offset = str(offset + PAGE_SIZE)

    await inline_query.answer(
        results=results,
        cache_time=inline_cache_time,
        is_personal=True if (is_empty_query or is_random_requested) else False,
        next_offset=next_offset,
    )


@router.chosen_inline_result(F.result_id == RANDOM_RESULT_ID)
async def handle_random_chosen(
    chosen_result: ChosenInlineResult,
    bot: Bot,
    cache: CatalogCache,
) -> None:
    """When random door is selected, edit the placeholder message to a random door."""
    inline_msg_id = chosen_result.inline_message_id
    if not inline_msg_id:
        logger.warning(
            "chosen_inline_result for %s arrived without inline_message_id",
            chosen_result.result_id,
        )
        return

    door = cache.get_random_door()
    if not door:
        logger.warning("No door available in cache to fulfill random request")
        return

    logger.info("Resolving random inline door: %s (%s)", door.slug, door.title)
    try:
        await bot.edit_message_text(
            inline_message_id=inline_msg_id,
            text=door.build_caption_html(),
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(
                is_disabled=False,
                url=door.url,
                prefer_large_media=True,
            ),
            reply_markup=None,  # Remove the placeholder button
        )
    except Exception as e:
        logger.error("Failed to edit inline message text for random door: %s", e)


@router.callback_query(F.data == "fetch_random_door")
async def handle_random_callback(
    callback: CallbackQuery,
    bot: Bot,
    cache: CatalogCache,
) -> None:
    """Fallback if Telegram inline feedback was delayed or disabled."""
    inline_msg_id = callback.inline_message_id
    if not inline_msg_id:
        await callback.answer("پیام پیدا نشد! ❌", show_alert=False)
        return

    door = cache.get_random_door()
    if not door:
        await callback.answer("فعلاً دری پیدا نشد! ⚠️", show_alert=True)
        return

    try:
        await bot.edit_message_text(
            inline_message_id=inline_msg_id,
            text=door.build_caption_html(),
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(
                is_disabled=False,
                url=door.url,
                prefer_large_media=True,
            ),
            reply_markup=None,
        )
        await callback.answer("دَرِت پیدا شد! 🎉🚪")
    except Exception as e:
        logger.error("Callback edit_message_text error: %s", e)
        await callback.answer("خطا توی بروزرسانی در! ⚠️", show_alert=False)
