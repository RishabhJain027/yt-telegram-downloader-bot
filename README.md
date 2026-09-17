# YT Media Bot — Telegram YouTube Downloader

A ready-to-run Telegram bot that accepts a YouTube video/Short URL and lets the user choose:

- MP4 360p
- MP4 480p
- MP4 720p
- MP3 128 kbps

The bot uses `python-telegram-bot` for Telegram and `yt-dlp` for media extraction. FFmpeg is installed automatically in the Docker image and is required for merging/converting media.

## Important

Use the bot only with videos/media you are legally allowed to download. Respect YouTube's Terms of Service, copyright, and the rights of content owners.

Telegram's Bot API currently documents a **50 MB limit for `sendDocument`**, so this project intentionally keeps a safety margin and rejects files over the configured limit. citeturn536329search0

## 1. Create your Telegram bot

1. Open Telegram.
2. Open **@BotFather**.
3. Run `/newbot`.
4. Choose a bot name and username.
5. Copy the token BotFather gives you.

Never commit that token to GitHub.

## 2. Windows — easiest setup

Install:

- Python 3.10+ (3.12 recommended)
- FFmpeg on PATH

Then:

```powershell
cd yt_telegram_downloader_bot
copy .env.example .env
notepad .env
```

Put your BotFather token into:

```env
BOT_TOKEN=123456789:YOUR_REAL_TOKEN
```

Then run:

```powershell
.start.bat
```

Or manually:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python bot.py
```

## 3. Linux/macOS

Install Python 3.10+ and FFmpeg, then:

```bash
cp .env.example .env
nano .env
./start.sh
```

## 4. Docker — recommended for a server

Put your real token in `.env`, then:

```bash
docker compose up --build -d
```

View logs:

```bash
docker compose logs -f
```

Stop it:

```bash
docker compose down
```

## 5. Push to GitHub

Do NOT upload `.env`.

```bash
git init
git add .
git commit -m "Add Telegram YouTube media bot"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

The included `.gitignore` protects `.env` and downloaded media.

## 6. Server deployment

This is a long-running polling bot, so GitHub Pages is **not** the runtime. Host the project on a machine/container that can keep the Python process running. Docker is the easiest option.

A typical deployment flow is:

```text
User -> Telegram
     -> Telegram Bot API
     -> bot.py
     -> yt-dlp
     -> YouTube
     -> FFmpeg (if needed)
     -> downloaded MP4/MP3
     -> Telegram Bot API
     -> User
```

## Commands

- `/start`
- `/help`
- `/cancel`

Normal use is simply: **paste a YouTube URL**.

## Project structure

```text
yt_telegram_downloader_bot/
├── bot.py
├── requirements.txt
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── start.bat
├── start.sh
├── downloads/
│   └── .gitkeep
├── tests/
│   └── test_utils.py
└── README.md
```

## Troubleshooting

### `BOT_TOKEN is missing`
Create `.env` from `.env.example` and paste the exact BotFather token.

### `FFmpeg is missing`
Install FFmpeg and make sure `ffmpeg -version` works in your terminal. Docker already installs FFmpeg.

### `Download failed`
Some YouTube videos can be private, unavailable, region-restricted, age-restricted, or otherwise inaccessible to an unauthenticated downloader. Update the packages with:

```bash
pip install -U yt-dlp[default]
```

The yt-dlp project currently supports Python 3.10+ and recommends FFmpeg for tasks that need media merging/post-processing. citeturn536329search1turn536329search2turn536329search3

### Telegram rejects a file as too large
Lower the selected quality or reduce `MAX_FILE_SIZE_MB` in `.env`.

## Security notes

- Keep `BOT_TOKEN` private.
- Do not commit `.env`.
- This bot stores downloads temporarily and deletes them after upload.
- Do not expose a server-side folder containing private user downloads.
