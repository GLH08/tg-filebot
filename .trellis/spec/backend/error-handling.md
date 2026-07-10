# Error Handling

> How errors are caught, logged, and surfaced to the user in this Telegram bot.

---

## The one custom exception

`ConfigError` (`config.py:14`) is the only project-defined exception, raised by `Config.validate()` on missing credentials. `bot.py` catches it at init and returns a non-zero exit code (`bot.py:91-93`).

There are no other custom exception classes. Everything else uses built-in `Exception` or Telethon errors (`FloodWaitError`).

---

## Expected failures return result dicts, not raises

Manager methods that can fail on normal input return `{'success': bool, 'message': str, ...}` instead of raising. Callers in `command_handler.py` branch on `result['success']` and format a user reply.

Reference: `FileManager.rename_file` (`file_manager.py:154-204`), `FileManager.delete_file` (`file_manager.py:206-241`), `DownloadManager.cancel_download` (`download_manager.py:473-517`).

```python
result = file_manager.rename_file(index - 1, new_name)
if result['success']:
    await event.respond(f"✅ File renamed to: `{result['new_relative_path']}`")
else:
    await event.respond(f"❌ Error: {result['message']}")
```
(`command_handler.py:157-161`)

---

## Command handler wrapping

Every `/command` is wrapped by `create_command_handler(pattern)` (`command_handler.py:31-51`):

1. Auth check — unauthorized -> respond `⛔` + `raise events.StopPropagation`.
2. `try` the handler; on `Exception` log with `exc_info=True` and respond `❌ An unexpected error occurred: {str(e)}`.
3. `finally: raise events.StopPropagation` — every command stops further propagation, success or failure.

`/start` is the exception: it's registered directly with its own inline auth check rather than the decorator (`command_handler.py:53-85`).

---

## Download error lifecycle

`DownloadManager._start_download` (`download_manager.py:198-338`) separates three cases:

| Caught | Action |
|--------|--------|
| `asyncio.CancelledError` | Log info, edit message `🛑 cancelled`, cleanup partial file, return `None` (`download_manager.py:313-320`) |
| generic `Exception` | `logger.error(..., exc_info=True)`, set `status='failed'`, cleanup partial file, edit message `❌ Download failed`, return `None` (`download_manager.py:322-331`) |
| (finally) | cancel the progress-update task, schedule `_delayed_cleanup`, kick `_process_queue` (`download_manager.py:333-338`) |

`_download_with_retry` (`download_manager.py:340-439`) adds retry-specific handling:

- `FloodWaitError` -> `await asyncio.sleep(e.seconds)`, retry; re-raise on last attempt (`download_manager.py:410-426`).
- `asyncio.CancelledError` -> re-raise immediately, do not swallow (`download_manager.py:428-429`).
- other `Exception` -> exponential backoff `min(5 * 2**attempt, 30)` (5/10/20/30s); re-raise on last attempt (`download_manager.py:431-437`).

---

## Safe message edits

Editing the same Telegram message can raise `FloodWaitError` or "message not modified". Two helpers wrap this:

- `DownloadManager._safe_edit_message` (`download_manager.py:889-912`): retries once after `FloodWaitError` (sleeps `e.seconds + 2`); swallows other exceptions, logging a warning unless the error is "not modified" (suppressed silently).
- `message_handler._safe_edit_message` (`message_handler.py:243-255`): simpler single-attempt swallow-and-warn.

Always route user-facing status updates through `_safe_edit_message`; never call `client.edit_message` directly from download logic.

---

## Logging at the point of failure

- `logger.error(..., exc_info=True)` for unexpected failures — the stack trace is the value (`command_handler.py:43`, `download_manager.py:323`, `bot.py:95`).
- `logger.warning(...)` for recoverable/expected issues — FloodWait, message refresh failure, unauthorized user, residual files (`download_manager.py:245`, `file_manager.py:105`).
- Do not log and re-raise the same thing at multiple layers; log once where you handle it.

---

## Anti-patterns to avoid

- **Don't disconnect the shared Telegram client to "recover"** — `_download_with_retry` refreshes `file_reference` instead (`download_manager.py:360-369`, comment: "绝不断开共享连接"). Disconnecting breaks every other in-flight download on that client.
- **Don't raise from manager methods for normal "not found" cases** — return a result dict so the command handler can render a clean `❌` reply.
- **Don't leave partial files on failure** — always call `_cleanup_partial_file` in the failure path (`download_manager.py:319,326`).
