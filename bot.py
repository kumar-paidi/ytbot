#!/usr/bin/env python3
"""
YouTube Downloader Telegram Bot
- Quality selection (360p / 720p / 1080p / audio / thumbnail)
- Proper video duration passed to Telegram (fixes 0:00 display)
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path

# Use 'python -m yt_dlp' so it always works on Windows regardless of PATH
YT_DLP = [sys.executable, "-m", "yt_dlp"]

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

MAX_FILE_MB    = 50
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024

# Quality format strings for yt-dlp
QUALITY_FORMATS = {
    "360":  "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best[height<=360]",
    "720":  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
    "1080": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]",
    "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def is_youtube_url(text: str) -> bool:
    return any(x in text for x in ("youtube.com/watch", "youtu.be/", "youtube.com/shorts"))


def human_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


async def run(cmd: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def get_video_info(url: str) -> dict | None:
    code, out, err = await run([*YT_DLP, "--dump-json", "--no-playlist", url])
    if code != 0:
        logger.error("yt-dlp info error: %s", err)
        return None
    try:
        return json.loads(out)
    except Exception:
        return None


def build_info_caption(info: dict) -> str:
    title    = info.get("title", "Unknown")
    uploader = info.get("uploader", "Unknown")
    duration = int(info.get("duration") or 0)
    views    = info.get("view_count", 0) or 0
    mins, secs = divmod(duration, 60)
    return (
        f"🎬 *{title}*\n\n"
        f"👤 {uploader}\n"
        f"⏱️ {mins}:{secs:02d}\n"
        f"👁️ {views:,} views\n\n"
    )


# ── Commands ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 *Welcome to YouTube Downloader Bot!*\n\n"
        "Send me any YouTube link and choose:\n"
        "🎬 Video quality: 360p · 720p · 1080p\n"
        "🎵 Audio only (MP3)\n"
        "🖼️ Thumbnail (JPG)\n\n"
        "Send a link to get started! 🚀",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 *How to use:*\n\n"
        "1️⃣ Paste any YouTube URL\n"
        "2️⃣ Pick quality / format\n"
        "3️⃣ Wait while I download ⏳\n\n"
        "⚠️ Telegram limit: 50 MB per file.",
        parse_mode="Markdown",
    )


# ── URL Handler ───────────────────────────────────────────────────────────────
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = update.message.text.strip()

    if not is_youtube_url(url):
        await update.message.reply_text(
            "❌ That doesn't look like a YouTube link.\n"
            "Please send a valid youtube.com or youtu.be URL."
        )
        return

    context.user_data["url"] = url
    status_msg = await update.message.reply_text("🔍 Fetching video info…")
    info = await get_video_info(url)

    if not info:
        await status_msg.edit_text("❌ Could not fetch video info. Is the link correct?")
        return

    context.user_data["duration"] = int(info.get("duration") or 0)
    context.user_data["title"]    = info.get("title", "video")

    caption = build_info_caption(info) + "Choose format & quality:"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 360p",  callback_data="vid_360"),
            InlineKeyboardButton("🎬 720p",  callback_data="vid_720"),
            InlineKeyboardButton("🎬 1080p", callback_data="vid_1080"),
        ],
        [
            InlineKeyboardButton("⚡ Best Quality", callback_data="vid_best"),
        ],
        [
            InlineKeyboardButton("🎵 Audio Only (MP3)", callback_data="dl_audio"),
        ],
        [
            InlineKeyboardButton("🖼️ Thumbnail (JPG)", callback_data="dl_thumb"),
        ],
        [
            InlineKeyboardButton("📦 Best Video + Thumbnail", callback_data="dl_all"),
        ],
    ])

    await status_msg.edit_text(caption, parse_mode="Markdown", reply_markup=keyboard)


# ── Callback Handler ──────────────────────────────────────────────────────────
async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    url = context.user_data.get("url")
    if not url:
        await query.edit_message_text("⚠️ Session expired. Please send the URL again.")
        return

    action   = query.data
    chat_id  = query.message.chat_id
    duration = context.user_data.get("duration", 0)
    title    = context.user_data.get("title", "video")

    await query.edit_message_text("⏳ Downloading… Please wait.")

    for f in DOWNLOAD_DIR.glob("*"):
        f.unlink(missing_ok=True)

    try:
        if action.startswith("vid_"):
            quality = action.split("_")[1]   # 360 | 720 | 1080 | best
            await download_video(context.bot, chat_id, url, quality, duration, title)

        elif action == "dl_audio":
            await download_audio(context.bot, chat_id, url, duration, title)

        elif action == "dl_thumb":
            await download_thumbnail(context.bot, chat_id, url, title)

        elif action == "dl_all":
            await download_video(context.bot, chat_id, url, "best", duration, title)
            for f in DOWNLOAD_DIR.glob("*.mp4"):
                f.unlink(missing_ok=True)
            await download_thumbnail(context.bot, chat_id, url, title)

    except Exception as e:
        logger.exception("Download error")
        await context.bot.send_message(chat_id, f"❌ Error:\n`{e}`", parse_mode="Markdown")

    await query.edit_message_text("✅ All done!")


# ── Download Functions ────────────────────────────────────────────────────────
async def download_video(bot, chat_id: int, url: str, quality: str, duration: int, title: str) -> None:
    fmt = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["best"])
    out_template = str(DOWNLOAD_DIR / "%(title).60s.%(ext)s")

    label = f"{quality}p" if quality != "best" else "best quality"
    await bot.send_message(chat_id, f"⬇️ Downloading {label} video…")

    code, _, err = await run([
        *YT_DLP,
        "-f", fmt,
        "--merge-output-format", "mp4",
        "--no-playlist",
        "-o", out_template,
        url,
    ])

    if code != 0:
        await bot.send_message(chat_id, f"❌ Video download failed.\n```{err[-400:]}```", parse_mode="Markdown")
        return

    files = list(DOWNLOAD_DIR.glob("*.mp4"))
    if not files:
        await bot.send_message(chat_id, "❌ Video file not found after download.")
        return

    video_path = files[0]
    size = video_path.stat().st_size

    if size > MAX_FILE_BYTES:
        await bot.send_message(
            chat_id,
            f"⚠️ Video is {human_size(size)} — too large for Telegram (max {MAX_FILE_MB} MB).\n"
            "Try 360p or 720p instead."
        )
        return

    await bot.send_message(chat_id, f"📤 Uploading video ({human_size(size)})…")
    with open(video_path, "rb") as vf:
        await bot.send_video(
            chat_id,
            video=vf,
            caption=f"🎬 {title}",
            duration=duration,           # ✅ fixes the 0:00 duration display
            supports_streaming=True,
            width=1280,
            height=720,
        )


async def download_audio(bot, chat_id: int, url: str, duration: int, title: str) -> None:
    out_template = str(DOWNLOAD_DIR / "%(title).60s.%(ext)s")

    await bot.send_message(chat_id, "⬇️ Downloading audio…")

    code, _, err = await run([
        *YT_DLP,
        "-f", "bestaudio/best",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--no-playlist",
        "-o", out_template,
        url,
    ])

    if code != 0:
        await bot.send_message(chat_id, f"❌ Audio download failed.\n```{err[-400:]}```", parse_mode="Markdown")
        return

    files = list(DOWNLOAD_DIR.glob("*.mp3"))
    if not files:
        await bot.send_message(chat_id, "❌ Audio file not found after download.")
        return

    audio_path = files[0]
    size = audio_path.stat().st_size

    if size > MAX_FILE_BYTES:
        await bot.send_message(chat_id, f"⚠️ Audio is {human_size(size)} — too large for Telegram.")
        return

    await bot.send_message(chat_id, f"📤 Uploading audio ({human_size(size)})…")
    with open(audio_path, "rb") as af:
        await bot.send_audio(
            chat_id,
            audio=af,
            title=title,
            duration=duration,           # ✅ shows proper duration in audio player
        )


async def download_thumbnail(bot, chat_id: int, url: str, title: str) -> None:
    out_template = str(DOWNLOAD_DIR / "%(title).60s.%(ext)s")

    await bot.send_message(chat_id, "⬇️ Downloading thumbnail…")

    code, _, err = await run([
        *YT_DLP,
        "--write-thumbnail",
        "--skip-download",
        "--convert-thumbnails", "jpg",
        "--no-playlist",
        "-o", out_template,
        url,
    ])

    if code != 0:
        await bot.send_message(chat_id, f"❌ Thumbnail download failed.\n```{err[-400:]}```", parse_mode="Markdown")
        return

    files = (list(DOWNLOAD_DIR.glob("*.jpg")) +
             list(DOWNLOAD_DIR.glob("*.webp")) +
             list(DOWNLOAD_DIR.glob("*.png")))
    if not files:
        await bot.send_message(chat_id, "❌ Thumbnail file not found.")
        return

    with open(files[0], "rb") as tf:
        await bot.send_photo(chat_id, photo=tf, caption=f"🖼️ {title}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Please set your BOT_TOKEN!")
        print("   Windows: set BOT_TOKEN=your_token_here")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(download_callback))

    logger.info("🤖 Bot is running…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
