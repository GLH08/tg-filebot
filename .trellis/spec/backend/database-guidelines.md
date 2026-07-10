# State & Persistence

> **This project has no database, no ORM, no migrations.** State is in-memory dicts/dataclasses plus the filesystem. This file documents that real data layer so you don't reach for SQL where none exists.

---

## In-memory state

All runtime state lives on manager instances, not in a DB:

| Container | Location | Purpose |
|-----------|----------|---------|
| `active_downloads: Dict[str, DownloadInfo]` | `DownloadManager` (`download_manager.py:66`) | Active/just-finished downloads keyed by 8-char id |
| `download_queue: deque[QueuedDownload]` | `DownloadManager` (`download_manager.py:67`) | FIFO of downloads waiting for a concurrency slot |
| `retry_registry: Dict[str, Dict]` | `DownloadManager` (`download_manager.py:80`) | "Retry via user account" tokens -> link/chat/msg_id |
| `_files_cache: List[Dict]` + `_cache_time` | `FileManager` (`file_manager.py:25-27`) | TTL-cached directory listing (default 30s) |

State is lost on restart — by design. The only survivor across restarts is the filesystem (next section).

---

## Filesystem as persistence

- **Final files**: `downloads/YYYYMMDD/<filename>` (`download_manager.py:211-213`). This dated folder *is* the durable record; `FileManager` scans it to rebuild state (`file_manager.py:78-122`).
- **In-progress marker**: `<name>.<download_id>.downloading` (`download_manager.py:216`). On completion it is `shutil.move`'d to the final name (`download_manager.py:289`). On failure/cancel the partial file is deleted (`download_manager.py:319,326,611`).
- **Residual scan on startup**: `DownloadManager._scan_residual_downloading_files()` walks `DOWNLOAD_PATH` and logs a warning for every `.downloading` file left behind by a crash (`download_manager.py:117-133`). It does **not** auto-delete — it points the user at `/cleanup`.
- **Telethon session**: `data/bot_session.session` (SQLite, managed by Telethon). Not app data; don't query it directly.

---

## Cache invalidation

`FileManager._files_cache` is invalidated on every mutation via `_invalidate_cache()` (`file_manager.py:303-306`):

- `rename_file` (`file_manager.py:193`)
- `delete_file` (`file_manager.py:231`)
- `cleanup_old_files` when something was deleted (`file_manager.py:277`)
- Cross-module: `DownloadManager` calls `self.file_manager._invalidate_cache()` after a file lands on disk so `/list` sees it immediately (`download_manager.py:308-309`).

If you add any code that writes/removes a file under `DOWNLOAD_PATH`, call `_invalidate_cache()` or the listing stays stale up to `CACHE_TTL` seconds.

---

## Concurrency rules for in-memory state

The state containers are mutated from many async tasks. The established patterns:

1. **Register before the first `await`** — `DownloadManager._start_download` inserts into `active_downloads` *before* any await so `_get_active_count()` can't miss an in-flight download (`download_manager.py:232-233`, comment calls this out explicitly).
2. **Snapshot before iterating** — `WebDashboard.handle_api_status` does `list(self.download_manager.active_downloads.items())` to avoid "dictionary changed size during iteration" (`web.py:180`, comment at `web.py:178-179`).
3. **Lock the queue processor** — `_process_queue` runs under `async with self._lock` (`download_manager.py:443`).
4. **Delayed self-removal** — finished entries are deleted via `_delayed_cleanup(key, 5)` so `/active` can still show the result briefly (`download_manager.py:620-626`, `download_manager.py:336`).

---

## No migrations / no query layer

There is nothing to migrate. If a feature needs durable cross-restart state beyond "files on disk", that is a new design decision — raise it in a task `prd.md` rather than silently introducing SQLite/Redis.
