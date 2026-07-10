# Backend Development Guidelines

> Coding conventions for TG-FileBot — a Telethon-based Telegram file download bot. These specs describe the codebase as it is today, backed by real files.

---

## Pre-Development Checklist

Before writing code in this layer, confirm:

- [ ] You know whether the change touches `handlers/` (thin dispatch) or `utils/` (business logic) — see [directory-structure.md](./directory-structure.md).
- [ ] If it writes/removes files under `DOWNLOAD_PATH`, you'll call `FileManager._invalidate_cache()` — see [state-and-persistence](./database-guidelines.md#cache-invalidation).
- [ ] If it adds a Telegram status update, you'll route it through `_safe_edit_message` — see [error-handling.md](./error-handling.md#safe-message-edits).
- [ ] If it handles a filename, it goes through `sanitize_filename()` — see [quality-guidelines.md](./quality-guidelines.md#security-patterns-non-negotiable).

---

## Guidelines Index

| Guide | Description |
|-------|-------------|
| [Directory Structure](./directory-structure.md) | Module layout, where new code goes, runtime dirs |
| [State & Persistence](./database-guidelines.md) | No DB — in-memory dicts + filesystem; cache invalidation; concurrency |
| [Error Handling](./error-handling.md) | Result dicts, command wrapping, download retry lifecycle, safe edits |
| [Logging Guidelines](./logging-guidelines.md) | stdlib logging, levels, exc_info, what not to log |
| [Quality Guidelines](./quality-guidelines.md) | Required/security/concurrency patterns, review checklist |

---

## Quality Check

Before reporting a change done, verify:

- [ ] Type hints + docstrings on any new public function.
- [ ] No credentials (`BOT_TOKEN`, `API_HASH`, `SESSION_STRING`, `WEB_PASSWORD`) in log lines.
- [ ] No `client.disconnect()` introduced in recovery paths.
- [ ] Status-message edits throttled (≥5s) and wrapped in `_safe_edit_message`.
- [ ] Manual run: `python bot.py` against a real `.env`; confirm command/link works and the file lands in `downloads/YYYYMMDD/`.
- [ ] No automated tests exist — do not claim "tests pass". State how you verified manually.

---

**Language**: Spec docs are written in English; quoted log strings keep their original (sometimes Chinese) form, matching the codebase.
