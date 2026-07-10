# Directory Structure

> How this Telegram bot project is organized. Flat two-package Python layout; no `src/` dir.

---

## Layout

```
tg-filebot/
├── bot.py                 # Entry point: TelegramFileBot class + background loops
├── config.py              # Config class (env load/validate) + module-level compat exports
├── gen_session.py         # One-off script: prints a SESSION_STRING for user mode
├── handlers/              # Telethon event handlers (thin: auth + dispatch)
│   ├── __init__.py
│   ├── auth.py            # is_user_allowed / is_chat_allowed / get_user_display_name
│   ├── command_handler.py # register_command_handlers + create_command_handler decorator
│   └── message_handler.py # register_message_handlers, link extraction, media download
├── utils/                 # Business logic (fat: state, IO, web)
│   ├── __init__.py
│   ├── download_manager.py  # DownloadManager + DownloadInfo/QueuedDownload dataclasses
│   ├── file_manager.py      # FileManager: CRUD, TTL cache, cleanup
│   ├── helpers.py           # format_size / format_time / sanitize_filename
│   └── web.py               # WebDashboard (aiohttp)
├── downloads/             # Runtime: YYYYMMDD/ dated subdirs (gitignored)
├── data/                  # Runtime: Telethon session DBs (gitignored)
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## Where new code goes

| Adding | Put it in | Reference |
|--------|-----------|-----------|
| A new `/command` | `handlers/command_handler.py`, inside `register_command_handlers` via `@create_command_handler(r'/name ...')` | `command_handler.py:31,87` |
| A non-command message behavior | `handlers/message_handler.py` | `message_handler.py:22` |
| Domain logic (download, file, web) | A new `utils/<thing>.py` module + class | `utils/download_manager.py:62` |
| A pure formatting/sanitization helper | `utils/helpers.py` | `utils/helpers.py` |
| Config knob | `config.py` `Config` class attr + parse in `Config.load()` | `config.py:19,49` |

**Handlers stay thin, utils stay fat.** Handlers parse the event and call a manager; managers own state and IO. See `command_handler.py` (delegates to `FileManager`/`DownloadManager`) vs `download_manager.py` (owns the download lifecycle).

---

## Module conventions

- Every module starts with a one-line docstring: `"""<purpose>."""` (`bot.py:1`, `config.py:1`, `utils/helpers.py:1`).
- Module-level `logger = logging.getLogger(__name__)` in every module that logs (`config.py:8`, `handlers/auth.py:7`, `utils/download_manager.py:23`).
- `__init__.py` files are empty markers (`handlers/__init__.py`, `utils/__init__.py`).
- Telethon clients are created in `bot.py` and passed down by dependency injection (`bot.py:79-83`, `bot.py:119-124`); `utils/` and `handlers/` never construct their own client.

---

## Runtime directories

- `downloads/YYYYMMDD/<file>` — dated subdirs created per download day (`download_manager.py:211-213`).
- In-progress files use a `.downloading` suffix: `<filename>.<download_id>.downloading` (`download_manager.py:216`), renamed to the final name on completion (`download_manager.py:289`).
- `data/bot_session` — Telethon session DB for bot mode (`bot.py:55`).
- `downloads/` and `data/` are runtime-only (gitignored); do not commit contents.
