# Logging Guidelines

> stdlib `logging` only. Plain-text one-line format. No structured/JSON logging.

---

## Setup

Configured exactly once in `bot.py` (`bot.py:20-23`):

```python
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
```

Every other module gets its own logger — **never** call `logging.basicConfig` or `logging.getLogger()` (root) elsewhere:

```python
logger = logging.getLogger(__name__)
```

Reference: `config.py:8`, `handlers/auth.py:7`, `utils/download_manager.py:23`, `utils/web.py:7`.

---

## Levels in use

| Level | When | Example |
|-------|------|---------|
| `critical` | Fatal init/runtime failure; process will exit | `logger.critical(f"Initialization failed: {e}", exc_info=True)` (`bot.py:95`) |
| `error` | Unexpected failure, needs a stack trace | `logger.error(f"Download error: {e}", exc_info=True)` (`download_manager.py:323`) |
| `warning` | Recoverable / expected problem; degraded but running | `logger.warning(f"Failed to stat file {full_path}: {e}")` (`file_manager.py:105`) |
| `info` | Lifecycle event worth seeing in normal operation | `logger.info(f"Download completed: {final_filename}, ID: {download_id}")` (`download_manager.py:305`) |
| `debug` | Verbose diagnostic, off by default at INFO level | `logger.debug(f"已刷新消息 file_reference: {filename}")` (`download_manager.py:241`) |

**Rule of thumb**: if it caused a user-visible failure or needs debugging, `error` + `exc_info=True`. If the bot worked around it, `warning`. If it's a normal state transition, `info`.

---

## exc_info discipline

Use `exc_info=True` on `error`/`critical` calls inside `except` blocks so the stack trace lands in the log (`bot.py:95`, `bot.py:147`, `command_handler.py:43`, `download_manager.py:323`, `message_handler.py:113`). Don't pass `exc_info` on `warning`/`info` — those are for expected situations.

---

## Message language

Log messages mix English and Chinese — this is the existing reality, not an accident. Operational/download-layer messages are often Chinese (`download_manager.py:131` `发现未完成的下载残留文件`, `bot.py:207` `连接保活`), while structural ones are English. **Match the surrounding file**: if you're editing `download_manager.py`, follow its bilingual style; don't rewrite existing messages.

---

## What NOT to log

- Credentials: `BOT_TOKEN`, `API_HASH`, `SESSION_STRING`, `WEB_PASSWORD` are loaded into `Config` (`config.py:52-54`) but never logged. Keep it that way.
- Full message content beyond what's needed. `_download_with_retry` logs *metadata* about a `None` result (media type, chat id, fwd flag) rather than dumping the message (`download_manager.py:395-402`) — follow that pattern.
- Per-progress-tick noise: progress callback updates an in-memory struct (`download_manager.py:728-763`); it does **not** log. Only the progress *editor* logs at `debug`/`warning` on failure (`download_manager.py:801,806`).

Telegram `sender_id` values **are** logged for audit (unauthorized user, command errors) — `command_handler.py:44`, `message_handler.py:41`. This is accepted.

---

## FloodWait logging

Always include the required wait in the message so the log explains the pause:

```python
logger.warning(f"FloodWaitError in safe edit message! Pausing for {e.seconds}s ...")
```
(`download_manager.py:903`; also `download_manager.py:412`, `download_manager.py:793`)
