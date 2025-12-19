# TG-FileBot

Telegram 文件下载管理机器人，支持从消息或链接下载文件，提供下载队列、文件管理、自动清理等功能。

## 功能特性

- 从 Telegram 消息/链接下载文件
- 按日期自动整理 (YYYYMMDD)
- 下载队列（超出并发限制自动排队）
- 文件搜索、重命名、删除
- 实时进度显示
- 自动清理过期文件
- 用户权限控制

## 快速开始

### 使用 Docker（推荐）

```bash
# 创建配置文件
cat > .env << EOF
BOT_TOKEN=your_bot_token
API_ID=your_api_id
API_HASH=your_api_hash
ALLOWED_USERS=123456789
EOF

# 使用预构建镜像
docker run -d --name tg-filebot \
  --env-file .env \
  -v ./downloads:/app/downloads \
  ghcr.io/<username>/tg-filebot:latest
```

### 从源码构建

```bash
git clone <repository-url>
cd tg-filebot
cp .env.example .env
# 编辑 .env 配置
docker compose up -d
```

## 命令列表

| 命令 | 说明 |
|------|------|
| `/start` | 帮助信息 |
| `/list [页码]` | 列出文件 |
| `/search <关键词>` | 搜索文件 |
| `/rename <索引> <新名>` | 重命名 |
| `/delete <索引>` | 删除文件 |
| `/cancel <ID>` | 取消下载 |
| `/active` | 活动下载 |
| `/queue` | 下载队列 |
| `/stats` | 统计信息 |
| `/autocleanup <天数>` | 清理旧文件 |

## 配置项

| 变量 | 必填 | 默认值 | 说明 |
|------|:----:|--------|------|
| `BOT_TOKEN` | ✅ | - | Bot Token |
| `API_ID` | ✅ | - | API ID |
| `API_HASH` | ✅ | - | API Hash |
| `ALLOWED_USERS` | ✅ | - | 允许的用户 ID |
| `MAX_CONCURRENT_DOWNLOADS` | | 5 | 最大并发数 |
| `AUTO_CLEANUP_DAYS` | | 0 | 自动清理天数 |
| `ALLOW_GROUP_MESSAGES` | | false | 允许群组使用 |

## 项目结构

```
tg-filebot/
├── bot.py              # 入口
├── config.py           # 配置
├── handlers/           # 处理器
│   ├── auth.py
│   ├── command_handler.py
│   └── message_handler.py
└── utils/              # 工具
    ├── helpers.py
    ├── download_manager.py
    └── file_manager.py
```

## License

MIT
