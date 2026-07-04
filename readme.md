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
| `MAX_CONCURRENT_DOWNLOADS` | | 3 | 最大并发数 |
| `AUTO_CLEANUP_DAYS` | | 0 | 自动清理天数（0=禁用） |
| `ALLOW_GROUP_MESSAGES` | | false | 允许群组使用 |
| `WEB_PORT` | | 8080 | Web 面板端口 |
| `WEB_PASSWORD` | | - | Web 面板访问密码（HTTP Basic Auth）；留空则无鉴权 |

## 用户模式（下载受保护 / 评论区文件）

默认 **Bot 模式**无法下载开启了「限制保存内容」的频道文件，也无法访问私有频道。改用 **User 模式**（以真实账号登录）可解决，代价是需自行承担 Telegram ToS/版权方面的风险，且滥用可能导致账号被限制。

1. 安装 telethon 后生成 SESSION_STRING：

   ```bash
   pip install telethon
   python gen_session.py
   ```

   按提示输入 API_ID / API_HASH / 手机号（含国家码）/ 验证码（如有两步验证再输密码），末尾会打印一串 SESSION_STRING。

2. 填入 `.env`（**务必保密，等同账号凭据**）：

   ```bash
   SESSION_STRING=1Bxxxxxxxx...
   ```

   - **留空 BOT_TOKEN** → 纯用户模式：所有操作都由老号完成，你直接私聊老号发链接。
   - **保留 BOT_TOKEN** → **双客户端模式（推荐，见下）**。

3. 登录的账号必须能看到目标频道（私有频道需已加入）。

> 评论区链接（`t.me/频道/帖子?comment=编号`）指向的是关联讨论群里的文件，已支持解析；同样需要老号能访问该讨论群。

### 双客户端模式（推荐）

同时配置 `BOT_TOKEN`（你的 @bot）和 `SESSION_STRING`（老号）时启用：

- 平时你**只跟 @bot 交互**，发链接或转发文件，@bot 正常下载。
- 遇到**禁止转发/私有频道**的链接、@bot 下载失败时，消息下会出现「🔁 用老号重试」按钮；**点一下**才由后台老号接手下载，进度仍显示在 @bot 里。
- 好处：保留熟悉的 @bot 用法，且老号（高危账号）**只在你点按钮时才动用**，暴露最小。
- 建议老号用一个**注册较久、可弃用**的小号，并让它**先加入目标频道及其讨论群**。

## 镜像标签

| 标签 | 说明 |
|------|------|
| `latest` | 最新稳定版 |
| `main` | main 分支最新构建 |
| `x.y.z` | 指定版本号 |
| `xxxxxxx` | 指定提交哈希 |

## License

MIT
