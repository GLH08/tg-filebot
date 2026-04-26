# Implementation Plan: Download File Lifecycle Indicator

## Overview

给下载中的文件添加 `.downloading` 后缀标记，完成时去掉后缀并做重名检测。解决"无法一眼分辨完成/未完成文件"的问题，同时保持现有的唯一性保障机制不变。

## Architecture Decisions

1. **不改目录结构** — 不引入 temp/ 目录，文件直接放在最终 YYYYMMDD 目录，下载中文件名含 `.downloading` 后缀
2. **利用现有 `download_id`** — 8位 UUID 已存在于每个任务，无须新增字段
3. **`_get_unique_filepath()` 调用时机后移** — 从"下载开始时预约"改为"下载完成时确认"，消除提前预约但文件实际不在该位置的无意义调用
4. **`DownloadInfo.filename` 存纯净名** — 供进度消息等展示用，不含 `.downloading`；实际文件路径 `info.path` 含完整后缀

## Changes Summary

| 位置 | 当前行为 | 改动后 |
|------|---------|--------|
| `_start_download()` L205 | `await self._get_unique_filepath()` 预约最终文件名 | 删除，改为生成 `{filename}.{download_id}.downloading` 路径 |
| `_start_download()` L210 | `filename=actual_filename`（已预约的带后缀名） | `filename` 存纯净名（无后缀），供展示用 |
| `_start_download()` 成功分支 | 无重命名，文件已在目标位置 | 去掉 `.downloading` 后缀 → 调用 `_get_unique_filepath()` → `os.rename()` |
| `_cleanup_partial_file()` | 正常删除残留文件 | 无需改动，已通过 `info.path` 找到完整文件名 |
| `_build_progress_message()` | 显示 `info.filename` | 无需改动，`filename` 已是纯净名 |
| `/cancel` 命令 | 通过 `info.path` 删除文件 | 无需改动，`path` 已含完整文件名 |

## Task List

### Phase 1: Core Logic

#### Task 1: Modify `_start_download()` — 生成下载中文件路径

**Description:** 修改文件路径生成逻辑，用 `{filename}.{download_id}.downloading` 替代当前 `_get_unique_filepath()` 调用。

**Acceptance criteria:**
- [ ] 下载开始时，文件以 `原文件名.{8位uuid}.downloading` 命名存在于 YYYYMMDD 目录
- [ ] `info.path` 存完整下载中路径（含后缀），`info.filename` 存纯净名（不含后缀）
- [ ] 删除了下载开始时对 `_get_unique_filepath()` 的调用

**Verification:**
- [ ] 代码审查：确认无多余的 `_get_unique_filepath()` 调用发生在下载开始时
- [ ] 人工验证：转发一个文件，检查磁盘上的文件名是否含 `.downloading` 后缀

**Dependencies:** None

**Files likely touched:**
- `utils/download_manager.py`

**Estimated scope:** Small (1 file, ~15 lines changed)

---

#### Task 2: Modify `_start_download()` — 下载完成时重命名到最终文件名

**Description:** 下载成功完成后，去掉 `.downloading` 后缀，调用 `_get_unique_filepath()` 做重名检测，然后 `os.rename()` 到最终文件名。

**Acceptance criteria:**
- [ ] 下载完成时，文件从 `原名.{id}.downloading` 重命名为最终唯一文件名
- [ ] 已有同名文件时，生成 `(1)`、`(2)` 等后缀（复用现有逻辑）
- [ ] `info.path` 和 `info.relative_path` 在完成后更新为最终路径

**Verification:**
- [ ] 转发一个文件，验证磁盘文件最终名为纯净名称（无 `.downloading`）
- [ ] 连续转发两个同名文件，验证第二个生成 `(1)` 后缀

**Dependencies:** Task 1

**Files likely touched:**
- `utils/download_manager.py`

**Estimated scope:** Small (1 file, ~20 lines changed)

---

### Checkpoint: Core Logic
- [ ] 下载中的文件在磁盘上可见 `.downloading` 后缀
- [ ] 下载完成自动去掉后缀并处理重名
- [ ] `/cancel` 能正确删除带后缀的残留文件
- [ ] 进度消息中显示的是纯净文件名（无后缀）

---

### Phase 2: Cleanup & Safety

#### Task 3: 添加启动时残留检测（可选/建议）

**Description:** 在 `DownloadManager.__init__()` 或 `TelegramFileBot.initialize()` 中扫描 DOWNLOAD_PATH 下所有含 `.downloading` 后缀的文件，向日志输出警告（提供 `/tempcleanup` 命令手动清理）。

**Acceptance criteria:**
- [ ] 程序启动时，若发现任何 `.downloading` 文件，在日志中输出警告信息
- [ ] 警告信息包含文件路径和 download_id（如果有）

**Verification:**
- [ ] 手动在 downloads 目录留下一个 `.downloading` 文件，重启程序，观察日志输出

**Dependencies:** Task 1

**Files likely touched:**
- `utils/download_manager.py`
- `bot.py`（如需在 bot 初始化时调用）

**Estimated scope:** Small (1 file, ~10 lines)

---

### Checkpoint: Cleanup
- [ ] 残留 `.downloading` 文件可被程序检测并警告

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| `os.rename()` 跨文件系统失败 | Medium | Windows 上同一盘符内移动通常没问题；若失败可降级为 `shutil.move()` + 日志警告 |
| 重命名过程中程序崩溃 | Low | 残留文件带 `.downloading` 后缀，下一次启动时会被检测到 |
| `download_id` 冲突（极低概率） | Low | UUID 前8位冲突概率极低，且即使冲突 `_get_unique_filepath()` 兜底 |
| 文件在重命名时被其他程序占用 | Low | `os.rename()` 会抛异常，被 `try/except` 捕获后走失败流程 |

## Open Questions

1. **Task 3（启动残留检测）是否实施？** — 属于锦上添花，可作为独立小任务，也可以先不做，简化第一阶段的改动范围。
2. **`download_id` 出现在用户可见的消息中吗？** — 目前 `info.filename`（纯净名）用于展示，`download_id` 仅在日志和调试场景可见。进度消息里已有 `🔢 Download ID: {id}`，是否需要改动？

## Implementation Order

```
Task 1 → Task 2 → Checkpoint → [Task 3] → Final Check
```

建议先完成 Task 1 + Task 2 并通过 checkpoint，再决定是否做 Task 3。
