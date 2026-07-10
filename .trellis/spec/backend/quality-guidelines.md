# Quality Guidelines

> What "done" looks like for code in this repo. There is currently no automated test suite and no linter config — these are the human conventions that keep the codebase consistent.

---

## Required patterns

- **Type hints** on every function/method signature (`Optional`, `List`, `Dict`, `Any`, `Union`, `Callable`, `Awaitable` from `typing`). Reference: `config.py:49`, `download_manager.py:140`, `file_manager.py:29`.
- **Docstrings** on public functions/methods with `Args:` / `Returns:` sections. Reference: `utils/helpers.py:6-14`, `download_manager.py:148-158`.
- **`dataclass`** for structured value objects, not loose dicts. `DownloadInfo` and `QueuedDownload` (`download_manager.py:26-59`).
- **Module docstring + module logger** at the top of every module (see [directory-structure.md](./directory-structure.md)).
- **Dependency injection** for clients/managers — handlers and managers receive their dependencies as args; they don't import a global client (`bot.py:119-124`).

---

## Security patterns (non-negotiable)

- **Filenames go through `sanitize_filename()`** before any filesystem write. It takes `os.path.basename` then strips `<>:"/\\|?*` and control chars (`utils/helpers.py:57-84`). Applied in `download_manager.py:209`.
- **Path-traversal check before rename/delete** — `FileManager._is_safe_path()` compares `os.path.realpath` against `base_dir` and is called before every `os.rename`/`os.remove` (`file_manager.py:138-152`, used at `file_manager.py:180,226,265`).
- **Constant-time secret comparison** — `WebDashboard._check_auth` uses `hmac.compare_digest`, not `==` (`web.py:45`).
- **Auth at every entry point** — command handlers via `is_chat_allowed` (`command_handler.py:36`); callback queries via `is_user_allowed` (`command_handler.py:301,312`); messages via `is_chat_allowed` (`message_handler.py:38`).

---

## Concurrency patterns

- **`asyncio.Lock`** guards multi-step state mutations — `_process_queue` runs under `async with self._lock` (`download_manager.py:443`).
- **Snapshot dicts before iterating** when another task may mutate them (`web.py:180`).
- **Register-then-await**: insert into `active_downloads` before the first `await` so concurrency accounting is race-free (`download_manager.py:232`).
- **Fire-and-forget cleanup** via `asyncio.create_task(self._delayed_cleanup(...))` rather than blocking the response path (`download_manager.py:336`).

---

## Telegram-specific rules

- **Never disconnect a shared client to "recover"** a download — refresh `file_reference` via `get_messages` instead (`download_manager.py:360-369`). Disconnecting kills every other in-flight download on that client.
- **Throttle message edits** — progress edits wait ≥5s between edits and back off dynamically after `FloodWaitError` (`download_manager.py:772,791,796`). Never edit in a tight loop.
- **Always use `_safe_edit_message`** for status updates so `FloodWaitError` / "not modified" don't crash the handler (`download_manager.py:889`).
- **Stop propagation** at the end of every command handler (`command_handler.py:49`).
- **`MessageMediaWebPage` is a link preview, not a file** - when a user sends a t.me link as text, Telegram attaches this preview to the sender's own message. In `message_handler`, skip it in the media check so the message reaches link parsing (`message_handler.py:58`); otherwise it hits the `MessageMediaDocument`-only check in `_start_download` and fails with "媒体类型 MessageMediaWebPage 不是可下载的文件".

---

## Testing & verification

- **No test suite exists today** (no `tests/`, no `pytest` in `requirements.txt`). This is known tech debt, not a pattern to follow — do not claim "tests pass" when none exist.
- **Manual verification** is the current bar: run `python bot.py` against a real `.env`, exercise the affected command/link type, confirm the status message and `downloads/YYYYMMDD/` output.
- **Lint/type-check**: no tooling configured. Match existing style by reading neighbors rather than introducing a new tool in a feature PR.

---

## Code review checklist

- [ ] New filename handled by `sanitize_filename()`? Path checked by `_is_safe_path()` if it renames/deletes?
- [ ] Every new `/command` wrapped in `create_command_handler` and ends with `StopPropagation`?
- [ ] Auth check present on any new entry point (command, callback, message path)?
- [ ] Filesystem mutation followed by `FileManager._invalidate_cache()`?
- [ ] No `client.disconnect()` in recovery paths?
- [ ] Message edits throttled / routed through `_safe_edit_message`?
- [ ] Type hints + docstring on new public functions?
- [ ] No credentials or full message bodies in log lines?
