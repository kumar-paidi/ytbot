#!/usr/bin/env python3
"""
YouTube Downloader Telegram Bot - 2GB support via Pyrogram
"""

import os
import sys
import json
import asyncio
import logging
import shutil
import subprocess
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

DOWNLOAD_DIR   = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

# ── Auto-detect yt-dlp ────────────────────────────────────────────────────────
def find_ytdlp():
    # 1. system command
    if shutil.which("yt-dlp"):
        logger.info("yt-dlp found as system command")
        return ["yt-dlp"]
    # 2. python module
    try:
        subprocess.run([sys.executable, "-m", "yt_dlp", "--version"],
                       capture_output=True, check=True)
        logger.info("yt-dlp found as python module")
        return [sys.executable, "-m", "yt_dlp"]
    except Exception:
        pass
    # 3. pip install it now
    logger.warning("yt-dlp not found! Installing now...")
    subprocess.run([sys.executable, "-m", "pip", "install", "yt-dlp", "-q"], check=True)
    logger.info("yt-dlp installed successfully")
    return [sys.executable, "-m", "yt_dlp"]

YT_DLP = find_ytdlp()
logger.info("Using YT_DLP command: %s", YT_DLP)

QUALITY_FORMATS = {
    "360":  "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]",
    "720":  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]",
    "1080": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
    "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
}

# ── Imports ───────────────────────────────────────────────────────────────────
from pyrogram import Client
from telegram import Update, InlineKeyboardButton as TGButton, InlineKeyboardMarkup as TGMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters as tg_filters,
)

# ── Pyrogram client ───────────────────────────────────────────────────────────
pyro = Client(
    "yt_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
    no_updates=True,
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
        logger.error("yt-dlp error (code %s): %s", code, err[:500])
        return None
    try:
        return json.loads(out)
    except Exception as e:
        logger.error("JSON parse error: %s", e)
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

def make_progress(bot, chat_id, status_msg_id, label):
    last = {"pct": -1}
    async def progress(current, total):
        pct = int(current * 100 / total)
        if pct - last["pct"] >= 10:
            last["pct"] = pct
            bar = "▓" * (pct // 10) + "░" * (10 - pct // 10)
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_msg_id,
                    text=f"📤 Uploading {label}… {pct}%\n{bar}"
                )
            except Exception:
                pass
    return progress

# ── Commands ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "there"
    await update.message.reply_text(
        f"Hey {name}! 👋 Welcome to *YouTube Downloader Bot*! 🎉\n\n"
        "I can download anything from YouTube for you!\n\n"
        "🎬 *Video* — 360p, 720p, 1080p or Best\n"
        "🎵 *Audio* — MP3, best quality\n"
        "🖼️ *Thumbnail* — High-res cover image\n"
        "📦 *All in one* — Video + Thumbnail together\n\n"
        "✅ Supports files up to *2 GB*!\n\n"
        "Just send me a YouTube link and let's go! 🚀\n\n"
        "Type /help anytime if you need help 😊",
        parse_mode="Markdown",
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 *Need help? I got you!* 😄\n\n"
        "*How to use me:*\n"
        "1️⃣ Copy any YouTube video link\n"
        "2️⃣ Paste it here and send\n"
        "3️⃣ Pick your quality\n"
        "4️⃣ Sit back and relax ☕\n\n"
        "*Commands:*\n"
        "▪️ /start — Welcome message\n"
        "▪️ /help — This help message\n"
        "▪️ /about — About this bot\n"
        "▪️ /cancel — Cancel current download\n\n"
        "*Supported links:*\n"
        "✅ youtube.com/watch?v=...\n"
        "✅ youtu.be/...\n"
        "✅ youtube.com/shorts/...\n\n"
        "⚠️ Very long videos might take a while. Be patient! ⏳",
        parse_mode="Markdown",
    )

async def about_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *About YouTube Downloader Bot*\n\n"
        "I'm a fast & friendly YouTube downloader! 😎\n\n"
        "⚙️ *Powered by:*\n"
        "▪️ yt-dlp — for downloading\n"
        "▪️ FFmpeg — for merging video & audio\n"
        "▪️ Pyrogram — for 2GB file uploads\n\n"
        "🌟 *Features:*\n"
        "▪️ Up to 2 GB file size\n"
        "▪️ Multiple quality options\n"
        "▪️ Audio extraction (MP3)\n"
        "▪️ Thumbnail download\n"
        "▪️ Upload progress bar 📊",
        parse_mode="Markdown",
    )

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    for f in DOWNLOAD_DIR.glob("*"):
        f.unlink(missing_ok=True)
    await update.message.reply_text(
        "❌ *Cancelled!*\n\n"
        "All downloads stopped and cleared 🗑️\n"
        "Send a new YouTube link whenever you're ready! 😊",
        parse_mode="Markdown",
    )

async def unknown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤔 Hmm, I don't know that command!\n"
        "Try /help to see what I can do 😊"
    )

# ── URL Handler ───────────────────────────────────────────────────────────────
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if not is_youtube_url(url):
        await update.message.reply_text(
            "🤔 That doesn't look like a YouTube link!\n\n"
            "Please send a link like:\n"
            "`https://youtube.com/watch?v=...`\n"
            "`https://youtu.be/...`",
            parse_mode="Markdown",
        )
        return

    context.user_data["url"] = url
    status = await update.message.reply_text("🔍 Fetching video info… hang tight! ⏳")
    info = await get_video_info(url)

    if not info:
        await status.edit_text(
            "😕 Oops! Couldn't fetch video info.\n\n"
            "Please check:\n"
            "▪️ Is the link correct?\n"
            "▪️ Is the video public?\n"
            "▪️ Try again in a moment!\n\n"
            "Or use /cancel to reset."
        )
        return

    context.user_data["duration"] = int(info.get("duration") or 0)
    context.user_data["title"]    = info.get("title", "video")

    caption = build_caption(info) + "👇 Choose format & quality:"
    keyboard = TGMarkup([
        [
            TGButton("🎬 360p",  callback_data="vid_360"),
            TGButton("🎬 720p",  callback_data="vid_720"),
            TGButton("🎬 1080p", callback_data="vid_1080"),
        ],
        [TGButton("⚡ Best Quality (Recommended)", callback_data="vid_best")],
        [TGButton("🎵 Audio Only — MP3", callback_data="dl_audio")],
        [TGButton("🖼️ Thumbnail Only — JPG", callback_data="dl_thumb")],
        [TGButton("📦 Best Video + Thumbnail", callback_data="dl_all")],
    ])
    await status.edit_text(caption, parse_mode="Markdown", reply_markup=keyboard)

# ── Callback Handler ──────────────────────────────────────────────────────────
async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Got it! Starting download… 🚀")

    url = context.user_data.get("url")
    if not url:
        await query.edit_message_text("⚠️ Session expired! Please send the YouTube link again 😊")
        return

    action   = query.data
    chat_id  = query.message.chat_id
    duration = context.user_data.get("duration", 0)
    title    = context.user_data.get("title", "video")

    await query.edit_message_text("⏳ Starting download… please wait! ☕")

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
        await context.bot.send_message(
            chat_id,
            f"😵 Something went wrong!\n\n`{e}`\n\nTry /cancel to reset.",
            parse_mode="Markdown"
        )

    await query.edit_message_text("✅ All done! Enjoy! 🎉\n\nSend another link anytime 😊")

# ── Download Functions ────────────────────────────────────────────────────────
async def download_video(bot, chat_id, url, quality, duration, title, status_msg_id):
    fmt   = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["best"])
    label = f"{quality}p" if quality != "best" else "best quality"
    out_template = str(DOWNLOAD_DIR / "%(title).60s.%(ext)s")

    await bot.edit_message_text(
        chat_id=chat_id, message_id=status_msg_id,
        text=f"⬇️ Downloading {label} video… please wait! ☕"
    )

    code, _, err = await run([
        *YT_DLP, "-f", fmt,
        "--merge-output-format", "mp4",
        "--no-playlist", "-o", out_template, url,
    ])

    if code != 0:
        await bot.send_message(chat_id, f"😕 Download failed!\n```{err[-400:]}```", parse_mode="Markdown")
        return

    files = list(DOWNLOAD_DIR.glob("*.mp4"))
    if not files:
        await bot.send_message(chat_id, "😕 File not found after download. Try again!")
        return

    video_path = files[0]
    size = video_path.stat().st_size

    if size > MAX_FILE_BYTES:
        await bot.send_message(chat_id,
            f"😬 File is {human_size(size)} — too large!\n"
            "Try a lower quality like 360p or 720p."
        )
        return

    await bot.edit_message_text(
        chat_id=chat_id, message_id=status_msg_id,
        text=f"📤 Uploading video ({human_size(size)})… 0%\n░░░░░░░░░░"
    )

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

    await bot.edit_message_text(
        chat_id=chat_id, message_id=status_msg_id,
        text="⬇️ Downloading audio… please wait! 🎵"
    )

    code, _, err = await run([
        *YT_DLP, "-f", "bestaudio/best",
        "--extract-audio", "--audio-format", "mp3",
        "--audio-quality", "0",
        "--no-playlist", "-o", out_template, url,
    ])

    if code != 0:
        await bot.send_message(chat_id, f"😕 Audio download failed!\n```{err[-400:]}```", parse_mode="Markdown")
        return

    files = list(DOWNLOAD_DIR.glob("*.mp3"))
    if not files:
        await bot.send_message(chat_id, "😕 Audio file not found. Try again!")
        return

    audio_path = files[0]
    size = audio_path.stat().st_size

    await bot.edit_message_text(
        chat_id=chat_id, message_id=status_msg_id,
        text=f"📤 Uploading audio ({human_size(size)})… 0%\n░░░░░░░░░░"
    )

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
    await bot.send_message(chat_id, "⬇️ Downloading thumbnail… 🖼️")

    code, _, err = await run([
        *YT_DLP, "--write-thumbnail", "--skip-download",
        "--convert-thumbnails", "jpg",
        "--no-playlist", "-o", out_template, url,
    ])

    if code != 0:
        await bot.send_message(chat_id, f"😕 Thumbnail failed!\n```{err[-400:]}```", parse_mode="Markdown")
        return

    files = (list(DOWNLOAD_DIR.glob("*.jpg")) +
             list(DOWNLOAD_DIR.glob("*.webp")) +
             list(DOWNLOAD_DIR.glob("*.png")))
    if not files:
        await bot.send_message(chat_id, "😕 Thumbnail not found.")
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
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("help",   help_cmd))
    app.add_handler(CommandHandler("about",  about_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, handle_url))
    app.add_handler(MessageHandler(tg_filters.COMMAND, unknown_cmd))
    app.add_handler(CallbackQueryHandler(download_callback))

    logger.info("🤖 Bot running with 2GB support!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
