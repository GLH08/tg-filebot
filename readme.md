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

### 方式一：Docker Compose 部署（推荐）

1. 创建部署目录并下载配置文件：

```bash
mkdir tg-filebot && cd tg-filebot

# 下载 docker-compose 文件
curl -O https://raw.githubusercontent.com/GLH08/tg-filebot/main/docker-compose.ghcr.yml

# 下载环境变量模板
curl -O https://raw.githubusercontent.com/GLH08/tg-filebot/main/.env.example
mv .env.example .env
```

2. 编辑 `.env` 文件配置：

```bash
BOT_TOKEN=your_bot_token
API_ID=your_api_id
API_HASH=your_api_hash
ALLOWED_USERS=123456789
```

3. 启动服务：

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

4. 查看日志：

```bash
docker compose -f docker-compose.ghcr.yml logs -f
```

### 方式二：Docker Run

```bash
# 创建配置文件
cat > .env << EOF
BOT_TOKEN=your_bot_token
API_ID=your_api_id
API_HASH=your_api_hash
ALLOWED_USERS=123456789
EOF

# 运行容器
docker run -d --name tg-filebot \
  --env-file .env \
  -v ./downloads:/app/downloads \
  --restart unless-stopped \
  ghcr.io/glh08/tg-filebot:latest
```

### 方式三：从源码构建

```bash
git clone https://github.com/GLH08/tg-filebot.git
cd tg-filebot
cp .env.example .env
# 编辑 .env 配置
docker compose up -d
```

## 更新升级

```bash
# Docker Compose 方式
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d

# Docker Run 方式
docker pull ghcr.io/glh08/tg-filebot:latest
docker stop tg-filebot && docker rm tg-filebot
# 重新运行 docker run 命令
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
| `ALLOWED_USERS` | ✅ | - | 允许的用户 ID（逗号分隔） |
| `MAX_CONCURRENT_DOWNLOADS` | | 5 | 最大并发数 |
| `AUTO_CLEANUP_DAYS` | | 0 | 自动清理天数（0=禁用） |
| `ALLOW_GROUP_MESSAGES` | | false | 允许群组使用 |

## 镜像标签

| 标签 | 说明 |
|------|------|
| `latest` | 最新稳定版 |
| `main` | main 分支最新构建 |
| `x.y.z` | 指定版本号 |
| `xxxxxxx` | 指定提交哈希 |

## License

MIT
