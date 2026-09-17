import asyncio
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

import yt_dlp
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DOWNLOAD_ROOT = Path(os.getenv("DOWNLOAD_DIR", "downloads"))
DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtube-nocookie.com",
}

# One active job per user keeps a single bot instance predictable and protects disk/CPU.
USER_LOCKS: Dict[int, asyncio.Lock] = {}


def get_user_lock(user_id: int) -> asyncio.Lock:
    return USER_LOCKS.setdefault(user_id, asyncio.Lock())


def is_youtube_url(text: str) -> bool:
    try:
        parsed = urlparse(text.strip())
        return parsed.scheme in {"http", "https"} and parsed.netloc.lower() in YOUTUBE_HOSTS
    except Exception:
        return False


def extract_url(text: str) -> Optional[str]:
    match = re.search(r"https?://[^\s<>]+", text or "")
    if not match:
        return None
    return match.group(0).rstrip(".,!?)]}")


def safe_filename(name: str, fallback: str = "download") -> str:
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name).strip()
    name = re.sub(r"\s+", " ", name)
    return (name[:150] or fallback).strip()


def format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def quality_label(quality: str) -> str:
    return {
        "360": "MP4 360p",
        "480": "MP4 480p",
        "720": "MP4 720p",
        "audio": "MP3 128 kbps",
    }.get(quality, quality)


def get_ffmpeg_path() -> Optional[str]:
    if shutil.which("ffmpeg"):
        return None
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def build_ydl_options(quality: str, output_dir: Path):
    common = {
        "outtmpl": str(output_dir / "%(title).120s [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": False,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 60,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "mweb", "tv_embedded"]
            }
        },
    }
    ffmpeg_exe = get_ffmpeg_path()
    if ffmpeg_exe:
        common["ffmpeg_location"] = ffmpeg_exe

    if quality == "audio":
        return {
            **common,
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }
            ],
        }

    height = int(quality)
    # Prefer MP4-compatible streams, then fall back to the best available stream.
    return {
        **common,
        "format": (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={height}]+bestaudio/"
            f"best[height<={height}][ext=mp4]/"
            f"best[height<={height}]/"
            f"best"
        ),
        "merge_output_format": "mp4",
    }


def download_media(url: str, quality: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    opts = build_ydl_options(quality, output_dir)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        requested_title = info.get("title", "download") if isinstance(info, dict) else "download"
        requested_id = info.get("id", "file") if isinstance(info, dict) else "file"

    candidates = [p for p in output_dir.iterdir() if p.is_file()]
    if not candidates:
        raise RuntimeError("Download completed but no output file was found.")

    output = max(candidates, key=lambda p: p.stat().st_mtime)
    extension = output.suffix.lower()
    if extension not in {".mp4", ".mp3", ".m4a", ".webm"}:
        output_name = safe_filename(f"{requested_title} [{requested_id}]") + extension
        output = output.rename(output_dir / output_name)
    return output


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 <b>YT Media Bot</b>\n\n"
        "Send me a YouTube video/Short URL and I’ll show download options.\n\n"
        "🎬 MP4: 360p / 480p / 720p\n"
        "🎵 MP3: 128 kbps\n\n"
        "<i>Use this only for content you have the right to download.</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "<b>How to use</b>\n\n"
        "1. Paste a YouTube URL.\n"
        "2. Choose MP4 or MP3.\n"
        "3. Wait for the download to finish.\n\n"
        "Commands:\n"
        "/start — start the bot\n"
        "/help — show this help\n"
        "/cancel — cancel the current job"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["cancel_requested"] = True
    await update.message.reply_text("🛑 I’ll stop the next possible stage of your current download.")


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = extract_url(update.message.text or "")
    if not url or not is_youtube_url(url):
        await update.message.reply_text("Please send a valid YouTube URL (youtube.com or youtu.be).")
        return

    context.user_data["pending_url"] = url
    keyboard = [
        [
            InlineKeyboardButton("🎬 360p", callback_data="quality:360"),
            InlineKeyboardButton("🎬 480p", callback_data="quality:480"),
            InlineKeyboardButton("🎬 720p", callback_data="quality:720"),
        ],
        [InlineKeyboardButton("🎵 MP3 128k", callback_data="quality:audio")],
    ]
    await update.message.reply_text(
        "Choose a format:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def choose_quality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    url = context.user_data.get("pending_url")
    if not url or not is_youtube_url(url):
        await query.edit_message_text("That download request expired. Send the YouTube URL again.")
        return

    quality = query.data.split(":", 1)[1]
    user = update.effective_user
    if not user:
        await query.edit_message_text("Could not identify the Telegram user.")
        return

    lock = get_user_lock(user.id)
    if lock.locked():
        await query.edit_message_text("⏳ You already have a download running. Please wait for it to finish.")
        return

    await query.edit_message_text(f"⏳ Starting {quality_label(quality)}…")
    status_message = await query.message.reply_text("🔎 Reading video information…")
    context.user_data["cancel_requested"] = False

    async with lock:
        job_dir = Path(tempfile.mkdtemp(prefix=f"tg_{user.id}_", dir=DOWNLOAD_ROOT))
        try:
            is_audio = quality == "audio"
            chat_action = ChatAction.UPLOAD_VOICE if is_audio else ChatAction.UPLOAD_VIDEO
            await context.bot.send_chat_action(chat_id=query.message.chat_id, action=chat_action)
            await status_message.edit_text(f"⬇️ Downloading {quality_label(quality)}…")

            loop = asyncio.get_running_loop()
            task = loop.run_in_executor(None, download_media, url, quality, job_dir)
            file_path = await task

            if context.user_data.get("cancel_requested"):
                await status_message.edit_text("🛑 Download cancelled.")
                return

            await status_message.edit_text(
                f"✅ Downloaded: <b>{safe_filename(file_path.stem)}</b>\n"
                f"Size: {format_bytes(file_path.stat().st_size)}\n\n"
                f"⬆️ Uploading to Telegram…",
                parse_mode="HTML",
            )

            with file_path.open("rb") as media_file:
                ext = file_path.suffix.lower()
                if ext in {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg"} or is_audio:
                    await query.message.reply_audio(
                        audio=media_file,
                        filename=file_path.name,
                        title=file_path.stem,
                        caption=f"🎵 {quality_label(quality)}",
                        read_timeout=600,
                        write_timeout=600,
                        connect_timeout=60,
                        pool_timeout=60,
                    )
                elif ext in {".mp4", ".mov", ".mkv", ".webm"}:
                    await query.message.reply_video(
                        video=media_file,
                        filename=file_path.name,
                        caption=f"🎬 {quality_label(quality)}",
                        supports_streaming=True,
                        read_timeout=600,
                        write_timeout=600,
                        connect_timeout=60,
                        pool_timeout=60,
                    )
                else:
                    await query.message.reply_document(
                        document=media_file,
                        filename=file_path.name,
                        caption=f"✅ {quality_label(quality)}",
                        read_timeout=600,
                        write_timeout=600,
                        connect_timeout=60,
                        pool_timeout=60,
                    )

            await status_message.edit_text("✅ Done! Send another YouTube link anytime.")

        except yt_dlp.utils.DownloadError as exc:
            detail = str(exc).strip().splitlines()[-1] if str(exc).strip() else "Unknown yt-dlp error"
            await status_message.edit_text(
                "❌ Download failed.\n\n"
                f"<code>{safe_filename(detail, 'yt-dlp error')[:900]}</code>\n\n"
                "The video may be unavailable, age-restricted, private, or geo-blocked.",
                parse_mode="HTML",
            )
        except FileNotFoundError as exc:
            await status_message.edit_text(
                "❌ FFmpeg is missing on the server. Install FFmpeg and restart the bot.\n"
                f"<code>{safe_filename(str(exc))}</code>",
                parse_mode="HTML",
            )
        except TelegramError as exc:
            err_msg = str(exc)
            if "Request Entity Too Large" in err_msg or "File is too big" in err_msg:
                await status_message.edit_text(
                    "❌ Telegram's cloud Bot API rejected the upload because it exceeds Telegram's 50 MB bot limit.\n\n"
                    "💡 <i>Tip: For long videos, choose a lower quality (like 360p/480p) or MP3 audio to stay under 50 MB.</i>",
                    parse_mode="HTML",
                )
            else:
                await status_message.edit_text(
                    f"❌ Telegram upload error:\n<code>{safe_filename(err_msg)[:900]}</code>",
                    parse_mode="HTML",
                )
        except Exception as exc:
            await status_message.edit_text(
                "❌ Something went wrong.\n\n"
                f"<code>{safe_filename(str(exc), 'unexpected error')[:900]}</code>",
                parse_mode="HTML",
            )
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
            context.user_data.pop("pending_url", None)
            context.user_data["cancel_requested"] = False


async def start_health_check(app: Application) -> None:
    port_str = os.getenv("PORT")
    if not port_str:
        return
    try:
        port = int(port_str)

        async def handle_client(reader, writer):
            try:
                await reader.read(1024)
                response = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK"
                writer.write(response)
                await writer.drain()
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

        server = await asyncio.start_server(handle_client, "0.0.0.0", port)
        print(f"Health check server running on port {port}")
    except Exception as e:
        print(f"Health check server notice: {e}")


def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing. Set BOT_TOKEN in .env or environment variables."
        )

    application = ApplicationBuilder().token(BOT_TOKEN).post_init(start_health_check).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CallbackQueryHandler(choose_quality, pattern=r"^quality:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    return application


def main() -> None:
    app = build_application()
    print("YT Media Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
