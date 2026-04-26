# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TG-FileBot is a Telegram file download management bot built with Python and Telethon. It downloads files from Telegram messages/links, organizes them by date, and provides queue management with concurrent downloads.

## Commands

### Running the Bot
```bash
# Install dependencies
pip install -r requirements.txt

# Create .env file from template
cp .env.example .env
# Edit .env with BOT_TOKEN, API_ID, API_HASH, ALLOWED_USERS

# Run directly
python bot.py

# Run with Docker
docker compose up -d
```

### Environment Variables
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BOT_TOKEN` | Yes* | - | Telegram Bot Token |
| `SESSION_STRING` | Yes* | - | User session string (for user mode) |
| `API_ID` | Yes | - | Telegram API ID |
| `API_HASH` | Yes | - | Telegram API Hash |
| `ALLOWED_USERS` | Yes | - | Allowed user IDs (comma-separated) |
| `MAX_CONCURRENT_DOWNLOADS` | | 3 | Max parallel downloads |
| `AUTO_CLEANUP_DAYS` | | 0 | Auto-delete files older than N days |
| `ALLOW_GROUP_MESSAGES` | | false | Allow bot usage in groups |
| `DOWNLOAD_TIMEOUT` | | 7200 | Download timeout in seconds |
| `WEB_PORT` | | 8080 | Web dashboard port |

*Either BOT_TOKEN (bot mode) or SESSION_STRING (user mode) is required.

## Architecture

### Core Components

**bot.py** - Entry point
- `TelegramFileBot` class initializes Telethon client, managers, and web dashboard
- Supports both bot mode (via BOT_TOKEN) and user mode (via SESSION_STRING)
- Runs auto-cleanup loop and keepalive loop as background tasks

**config.py** - Configuration
- `Config` class loads and validates environment variables
- Provides module-level backward-compatible exports
- Validates credentials on first use

**handlers/** - Message processing
- `command_handler.py` - Decorator-based command registration with auth checks
- `message_handler.py` - Media downloads, link extraction, forwarded message handling
- `auth.py` - User/chat authorization checks

**utils/** - Business logic
- `download_manager.py` - Download queue with concurrency control, retry logic, progress tracking
- `file_manager.py` - File CRUD with caching (TTL-based), YYYYMMDD folder organization
- `web.py` - aiohttp web dashboard with `/api/status` endpoint
- `helpers.py` - `format_size()`, `format_time()`, `sanitize_filename()`

### Key Patterns

**Command Handler Registration** - Uses decorator factory `create_command_handler(pattern)` that wraps handlers with auth checks and error handling.

**Download Queue** - `DownloadManager` uses `max_concurrent_downloads` to limit parallelism. When full, downloads go to a `deque` queue. Queue processor starts queued downloads as slots free up.

**File Organization** - Downloads stored in `YYYYMMDD` dated subdirectories under `DOWNLOAD_PATH`. File listing is cached with configurable TTL.

**Download Flow**:
1. `download_telegram_file()` checks concurrency limit
2. If full → add to queue, return download_id
3. If available → `_start_download()` → `_download_with_retry()` with file_reference refresh
4. Progress updates via `_update_progress()` task

**Auth Flow**:
- Private chats: check `is_user_allowed(sender_id)`
- Group chats: only if `ALLOW_GROUP_MESSAGES=true`

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Show help message |
| `/list [page]` | List downloaded files (paginated) |
| `/search <query>` | Search files by name |
| `/rename <index> <new_name>` | Rename file by index |
| `/delete <index>` | Delete file by index |
| `/cancel <download_id>` | Cancel active/queued download |
| `/active` | Show active downloads |
| `/queue` | Show queued downloads |
| `/stats` | Show download statistics |
| `/cleanup` | Clean up completed downloads |
| `/autocleanup <days>` | Delete files older than N days |
