# 修复照片下载被媒体类型校验拒掉的 bug

## Goal

`_start_download` 的媒体类型校验只接受 `MessageMediaDocument`，直接发照片（`MessageMediaPhoto`）或发指向照片帖的链接时被拒，报"媒体类型 MessageMediaPhoto 不是可下载的文件"。但 `message_handler._extract_filename` 已专门为照片生成 `photo_{ts}.jpg` 文件名，说明照片本应可下载--校验过窄是遗漏。

## Background (已核实)

- Telethon 1.36 `_download_photo` -> `_get_proper_filename(file, 'photo', '.jpg')`：对带 `.downloading` 后缀的临时路径，`os.path.splitext` 取到 `.downloading` 作为扩展名，**不会**追加 `.jpg`，返回原路径。故 `download_media` 返回值 == 传入的 `file_path`，现有 `_start_download` 的 `shutil.move(file_path, final_path)` 重命名逻辑对照片同样成立，无需改重命名。
- 直接发照片：`_extract_filename` 已返回 `photo_{ts}.jpg`，只需放宽校验即可走通。
- 链接指向照片帖：`process_telegram_link` 的文件名抽取只认 `document` 属性，照片落到 `file_from_link_{ts}`（无扩展名）。需补照片分支给 `.jpg` 名。

## Requirements

- `_start_download` 的媒体类型校验接受 `MessageMediaDocument` 与 `MessageMediaPhoto`，仍拒绝 `MessageMediaWebPage` 等不可下载类型。
- `process_telegram_link` 的文件名抽取：消息媒体为 `MessageMediaPhoto` 时，生成 `photo_{ts}.jpg`（与 `_extract_filename` 一致）。
- 文件/视频下载行为不变；不改动重命名与并发逻辑。

## Acceptance Criteria

- [ ] 直接发一张照片给 bot -> 正常下载，保存为 `photo_*.jpg`。
- [ ] 发指向照片帖的 t.me 链接 -> 下载保存为 `photo_*.jpg`（非 `file_from_link_*` 无扩展名）。
- [ ] 直接发文件/视频、发指向文件帖的链接 -> 行为不回归。
- [ ] `MessageMediaWebPage` 仍被拒绝（不被本次放宽影响）。

## Scope (out)

- noforwards 频道直走老号的 UX 优化。
