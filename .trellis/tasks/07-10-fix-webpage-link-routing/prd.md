# 修复 t.me 链接被 WebPage 预览短路的下载路由 bug

## Goal

用户把 `https://t.me/<channel>/<id>` 作为纯文本发送时，Telegram 会给这条消息本身附一个 `MessageMediaWebPage` 链接预览。`message_handler.py` 先判 `if event.media:` 再判文本链接，导致带预览的链接消息被当成"待下载媒体"丢进 `_download_from_message`，在 `_start_download` 被 `MessageMediaDocument` 类型校验拒掉（报"媒体类型 MessageMediaWebPage 不是可下载的文件"），链接根本没被解析。

## Requirements

- `message_handler.py` 的 `message_handler` 中，`MessageMediaWebPage`（链接预览，本就不可下载）不得触发媒体下载分支，应落到下面的文本链接解析分支。
- 对真实文件（`MessageMediaDocument`）和照片（`MessageMediaPhoto`）的转发/直发下载行为不变。
- 不改 `download_manager.py`、`process_telegram_link` 的链接解析逻辑。

## Acceptance Criteria

- [ ] 发送 `https://t.me/cabianpindao/158`（带 WebPage 预览）时，bot 进入 `_process_links` 而非 `_download_from_message`。
- [ ] 不再出现 `媒体类型 MessageMediaWebPage 不是可下载的文件` 错误。
- [ ] 直接转发一个文件给 bot，仍正常下载（回归不破）。

## Scope (out)

- 照片被 `_start_download` 类型校验拒掉的独立 bug（`MessageMediaPhoto` 不被接受）--单独处理。
- noforwards 频道直走老号、跳过 bot 重试等待的 UX 优化--单独处理。
