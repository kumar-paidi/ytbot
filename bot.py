#!/usr/bin/env python3
"""
YouTube Downloader Telegram Bot - 2GB support via Pyrogram
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
API_ID         = int(os.getenv("API_ID", "0"))
API_HASH       = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB (Pyrogram limit)

import shutil
YT_DLP = ["yt-dlp"] if shutil.which("yt-dlp") else [sys.executable, "-m", "yt_dlp"]

QUALITY_FORMATS = {
    "360":  "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]",
    "720":  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]",
    "1080": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
    "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
}

# ── Imports ───────────────────────────────────────────────────────────────────
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram import Update, InlineKeyboardButton as TGButton, InlineKeyboardMarkup as TGMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters as tg_filters,
)

# ── Pyrogram client (for large file uploads) ──────────────────────────────────
pyro = Client(
    "yt_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
    no_updates=True,   # we only use it for uploading, not receiving
)

# ── Helpers ───────────────────────────────────────────────────────────────────
def is_youtube_url(text: str) -> bool:
    return any(x in text for x in ("youtube.com/watch", "youtu.be/", "youtube.com/shorts"))

def human_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"

async def run(cmd):
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")

async def get_video_info(url: str):
    code, out, err = await run([*YT_DLP, "--dump-json", "--no-playlist", url])
    if code != 0:
        return None
    try:
        return json.loads(out)
    except Exception:
        return None

def build_caption(info: dict) -> str:
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

# ── Progress callback for Pyrogram uploads ────────────────────────────────────
def make_progress(bot, chat_id, status_msg_id, label):
    last = {"pct": -1}
    async def progress(current, total):
        pct = int(current * 100 / total)
        if pct - last["pct"] >= 10:
            last["pct"] = pct
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_msg_id,
                    text=f"📤 Uploading {label}… {pct}%"
                )
            except Exception:
                pass
    return progress

# ── Commands ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome to YouTube Downloader Bot!*\n\n"
        "Send me any YouTube link and choose:\n"
        "🎬 Video: 360p · 720p · 1080p · Best\n"
        "🎵 Audio only (MP3)\n"
        "🖼️ Thumbnail (JPG)\n\n"
        "✅ Supports files up to *2 GB*!\n\n"
        "Send a link to get started! 🚀",
        parse_mode="Markdown",
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How to use:*\n\n"
        "1️⃣ Paste any YouTube URL\n"
        "2️⃣ Pick quality / format\n"
        "3️⃣ Wait while I download ⏳\n\n"
        "✅ Up to 2 GB supported!",
        parse_mode="Markdown",
    )

# ── URL Handler ───────────────────────────────────────────────────────────────
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not is_youtube_url(url):
        await update.message.reply_text("❌ Please send a valid YouTube link.")
        return

    context.user_data["url"] = url
    status = await update.message.reply_text("🔍 Fetching video info…")
    info = await get_video_info(url)

    if not info:
        await status.edit_text("❌ Could not fetch video info.")
        return

    context.user_data["duration"] = int(info.get("duration") or 0)
    context.user_data["title"]    = info.get("title", "video")

    caption = build_caption(info) + "Choose format & quality:"
    keyboard = TGMarkup([
        [
            TGButton("🎬 360p",  callback_data="vid_360"),
            TGButton("🎬 720p",  callback_data="vid_720"),
            TGButton("🎬 1080p", callback_data="vid_1080"),
        ],
        [TGButton("⚡ Best Quality", callback_data="vid_best")],
        [TGButton("🎵 Audio Only (MP3)", callback_data="dl_audio")],
        [TGButton("🖼️ Thumbnail (JPG)", callback_data="dl_thumb")],
        [TGButton("📦 Best Video + Thumbnail", callback_data="dl_all")],
    ])
    await status.edit_text(caption, parse_mode="Markdown", reply_markup=keyboard)

# ── Callback Handler ──────────────────────────────────────────────────────────
async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    url = context.user_data.get("url")
    if not url:
        await query.edit_message_text("⚠️ Session expired. Send the URL again.")
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
            quality = action.split("_")[1]
            await download_video(context.bot, chat_id, url, quality, duration, title, query.message.message_id)
        elif action == "dl_audio":
            await download_audio(context.bot, chat_id, url, duration, title, query.message.message_id)
        elif action == "dl_thumb":
            await download_thumbnail(context.bot, chat_id, url, title)
        elif action == "dl_all":
            await download_video(context.bot, chat_id, url, "best", duration, title, query.message.message_id)
            for f in DOWNLOAD_DIR.glob("*.mp4"):
                f.unlink(missing_ok=True)
            await download_thumbnail(context.bot, chat_id, url, title)
    except Exception as e:
        logger.exception("Download error")
        await context.bot.send_message(chat_id, f"❌ Error:\n`{e}`", parse_mode="Markdown")

    await query.edit_message_text("✅ All done!")

# ── Download Functions ────────────────────────────────────────────────────────
async def download_video(bot, chat_id, url, quality, duration, title, status_msg_id):
    fmt = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["best"])
    out_template = str(DOWNLOAD_DIR / "%(title).60s.%(ext)s")
    label = f"{quality}p" if quality != "best" else "best quality"

    await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id,
                                 text=f"⬇️ Downloading {label} video…")

    code, _, err = await run([
        *YT_DLP, "-f", fmt,
        "--merge-output-format", "mp4",
        "--no-playlist", "-o", out_template, url,
    ])

    if code != 0:
        await bot.send_message(chat_id, f"❌ Download failed.\n```{err[-400:]}```", parse_mode="Markdown")
        return

    files = list(DOWNLOAD_DIR.glob("*.mp4"))
    if not files:
        await bot.send_message(chat_id, "❌ File not found after download.")
        return

    video_path = files[0]
    size = video_path.stat().st_size

    if size > MAX_FILE_BYTES:
        await bot.send_message(chat_id, f"⚠️ File is {human_size(size)} — too large even for 2GB limit!")
        return

    await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id,
                                 text=f"📤 Uploading video ({human_size(size)})… 0%")

    progress = make_progress(bot, chat_id, status_msg_id, "video")

    async with pyro:
        await pyro.send_video(
            chat_id=chat_id,
            video=str(video_path),
            caption=f"🎬 {title}",
            duration=duration,
            supports_streaming=True,
            progress=progress,
        )


async def download_audio(bot, chat_id, url, duration, title, status_msg_id):
    out_template = str(DOWNLOAD_DIR / "%(title).60s.%(ext)s")

    await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id,
                                 text="⬇️ Downloading audio…")

    code, _, err = await run([
        *YT_DLP, "-f", "bestaudio/best",
        "--extract-audio", "--audio-format", "mp3",
        "--audio-quality", "0",
        "--no-playlist", "-o", out_template, url,
    ])

    if code != 0:
        await bot.send_message(chat_id, f"❌ Audio failed.\n```{err[-400:]}```", parse_mode="Markdown")
        return

    files = list(DOWNLOAD_DIR.glob("*.mp3"))
    if not files:
        await bot.send_message(chat_id, "❌ Audio file not found.")
        return

    audio_path = files[0]
    size = audio_path.stat().st_size

    await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id,
                                 text=f"📤 Uploading audio ({human_size(size)})… 0%")

    progress = make_progress(bot, chat_id, status_msg_id, "audio")

    async with pyro:
        await pyro.send_audio(
            chat_id=chat_id,
            audio=str(audio_path),
            title=title,
            duration=duration,
            progress=progress,
        )


async def download_thumbnail(bot, chat_id, url, title):
    out_template = str(DOWNLOAD_DIR / "%(title).60s.%(ext)s")
    await bot.send_message(chat_id, "⬇️ Downloading thumbnail…")

    code, _, err = await run([
        *YT_DLP, "--write-thumbnail", "--skip-download",
        "--convert-thumbnails", "jpg",
        "--no-playlist", "-o", out_template, url,
    ])

    if code != 0:
        await bot.send_message(chat_id, f"❌ Thumbnail failed.\n```{err[-400:]}```", parse_mode="Markdown")
        return

    files = (list(DOWNLOAD_DIR.glob("*.jpg")) +
             list(DOWNLOAD_DIR.glob("*.webp")) +
             list(DOWNLOAD_DIR.glob("*.png")))
    if not files:
        await bot.send_message(chat_id, "❌ Thumbnail not found.")
        return

    with open(files[0], "rb") as tf:
        await bot.send_photo(chat_id, photo=tf, caption=f"🖼️ {title}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN not set!")
        return
    if not SESSION_STRING:
        print("❌ SESSION_STRING not set!")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(download_callback))

    logger.info("🤖 Bot running with 2GB support!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
