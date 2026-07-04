# TG-FileBot 双客户端下载架构 — 设计文档

日期：2026-07-04

## 目标

保留 `@bot` 作为唯一交互入口。当 `@bot` 因频道限制（禁止转发 / 私有 / 限制保存内容）下载失败时，允许用户点击按钮，由后台的「老号」用户账号接手下载该链接。核心是**最小化老号（高危账号）的使用面**。

## 已定决策

1. **Bot 优先，失败才回退老号**——不按输入类型分流，一律先由 @bot 尝试。
2. **回退需按钮确认**——@bot 失败后给出「🔁 用老号重试」按钮，用户点击才动用老号（不自动）。
3. **重试仅作用于链接**——转发文件落在「用户↔@bot」私聊里，老号是另一账号无法访问；且受保护内容本就只能以链接形式发来，故此约束不影响实际使用。
4. **同进程双客户端**——两个 Telethon client 共享事件循环；老号为静默后台，**不注册任何消息处理器**（不接收指令）。

## 模式矩阵（向后兼容）

| BOT_TOKEN | SESSION_STRING | 模式 | 行为 |
|:--:|:--:|---|---|
| ✓ | ✗ | 纯 Bot（现状） | 链接失败无重试按钮 |
| ✗ | ✓ | 纯用户（现状） | 单客户端全包，无需按钮 |
| ✓ | ✓ | **双客户端（新）** | @bot 收命令+正常下载；链接失败→「🔁 用老号重试」按钮 |

## 组件与改动

- **config.py**：BOT_TOKEN 与 SESSION_STRING 可同时存在（validate 已兼容，无需改）。
- **bot.py**：建并启动 `bot_client`（有 BOT_TOKEN）与 `user_client`（有 SESSION_STRING）；`main_client` = bot 优先否则 user；`fallback_client` = user（仅双模式）；handlers 只注册在 main；keepalive 覆盖两者；`run_until_disconnected(main)`；把 messaging/fallback client 交给 download_manager。
- **download_manager.py**：
  - `messaging_client`（发/改所有状态消息，恒 = main）与「下载用 client」（正常 = main，回退 = 老号）分离。
  - `_safe_edit_message` / `_update_progress` / `_send_completion_message` 一律用 `self.messaging_client`。
  - 下载方法接收「下载 client」参数（download_media / get_messages / get_entity / GetDiscussionMessage 走它）。
  - 重试注册表 `retry_registry: {token: {link, chat_id, status_msg_id, ts}}`，带 TTL 清理；`register_retry()` / `retry_download_via_fallback()`。
- **message_handler.py**：`_process_links` 中链接失败且为双模式 → 注册 token，把该状态消息编辑为带「🔁 用老号重试」inline 按钮（仅 bot 账号能发 inline 按钮，双模式下 messaging=bot，成立）。
- **command_handler.py**：新增 `CallbackQuery(pattern=b"userretry_...")` 处理器：鉴权 → 取 token → `download_manager.retry_download_via_fallback` → answer。

## 数据流（回退路径）

用户发链接给 @bot → @bot 尝试下载（下载 client = bot）→ 失败(None) → 注册 token + 消息挂按钮 → 用户点按钮 → 回调用 fallback（老号）重跑 `process_telegram_link`（下载 client = 老号，消息 client = bot）→ 成功→完成消息；失败→错误提示。

## 错误处理

- 非双模式：不挂按钮。
- token 过期/不存在：回调 answer「重试已过期，请重新发送链接」。
- 老号非成员/无权：错误消息提示「确保老号已加入该频道/讨论群」。
- 老号也失败：显示错误，不再回退。

## 测试

- **离线**：`py_compile` 全部；配置矩阵（bot-only / user-only / dual 的 main/fallback 判定）；token 注册/取用/过期与按钮 data 解析逻辑。
- **需真机（用户自测）**：老号真实下载受保护/私有/评论链接。

## 范围外（YAGNI）

独立进程/IPC；自动回退；转发文件的老号重试；多老号轮换；单账号限速（可后续加）。
