"""Telegram File Manager Bot - Main entry point."""

import os
import sys
import logging
import asyncio
from typing import Optional

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import Config, ConfigError
from utils.download_manager import DownloadManager
from utils.file_manager import FileManager
from utils.web import WebDashboard
from handlers.command_handler import register_command_handlers
from handlers.message_handler import register_message_handlers

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class TelegramFileBot:
    """Main bot class that manages the Telegram client and handlers."""
    
    def __init__(self):
        self.bot_client: Optional[TelegramClient] = None
        self.user_client: Optional[TelegramClient] = None
        self.main_client: Optional[TelegramClient] = None
        self.fallback_client: Optional[TelegramClient] = None
        self.download_manager: Optional[DownloadManager] = None
        self.file_manager: Optional[FileManager] = None
        self.web_dashboard: Optional[WebDashboard] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._keepalive_task: Optional[asyncio.Task] = None
    
    def initialize(self) -> bool:
        """Initialize the bot components.
        
        Returns:
            True if initialization successful, False otherwise
        """
        try:
            # Validate configuration
            Config.validate()
            
            # 按凭据创建客户端：BOT_TOKEN → bot_client，SESSION_STRING → user_client（老号）
            if Config.BOT_TOKEN:
                os.makedirs('data', exist_ok=True)
                self.bot_client = TelegramClient(
                    os.path.join('data', 'bot_session'),
                    Config.API_ID,
                    Config.API_HASH
                )
            if Config.SESSION_STRING:
                self.user_client = TelegramClient(
                    StringSession(Config.SESSION_STRING),
                    Config.API_ID,
                    Config.API_HASH
                )

            # 主客户端（收命令、发/改进度消息）：优先 bot，否则老号
            self.main_client = self.bot_client or self.user_client
            # 回退下载客户端：仅当两者都配置（双客户端模式）时才有独立老号
            self.fallback_client = self.user_client if (self.bot_client and self.user_client) else None

            if self.bot_client and self.user_client:
                logger.info("Configured: DUAL mode (bot UI + user-account fallback downloader)")
            elif self.user_client:
                logger.info("Configured: USER mode (single user account)")
            else:
                logger.info("Configured: BOT mode (single bot account)")
            
            # Initialize managers
            self.download_manager = DownloadManager()
            self.file_manager = FileManager(
                base_dir=Config.DOWNLOAD_PATH,
                cache_ttl=Config.CACHE_TTL
            )
            
            # Create downloads directory
            os.makedirs(Config.DOWNLOAD_PATH, exist_ok=True)
            
            logger.info("Bot components initialized successfully")
            return True
            
        except ConfigError as e:
            logger.critical(f"Configuration error: {e}")
            return False
        except Exception as e:
            logger.critical(f"Initialization failed: {e}", exc_info=True)
            return False
    
    async def start(self) -> None:
        """Start the bot and begin listening for messages."""
        if not self.main_client:
            logger.error("Bot not initialized. Call initialize() first.")
            return

        try:
            # 启动各客户端
            if self.bot_client:
                await self.bot_client.start(bot_token=Config.BOT_TOKEN)
                logger.info("Connected as Bot Account.")
            if self.user_client:
                await self.user_client.start()
                logger.info("Connected as User Account (老号).")

            # 把「消息客户端」(主)、「回退下载客户端」(老号)、文件管理器交给下载管理器
            self.download_manager.messaging_client = self.main_client
            self.download_manager.fallback_client = self.fallback_client
            self.download_manager.file_manager = self.file_manager

            # 处理器只注册在主客户端上；老号是静默后台，不接收指令
            register_command_handlers(
                self.main_client,
                self.file_manager,
                self.download_manager
            )
            register_message_handlers(self.main_client, self.download_manager)
            
            # Start auto-cleanup task if configured
            if Config.AUTO_CLEANUP_DAYS > 0:
                self._cleanup_task = asyncio.create_task(self._auto_cleanup_loop())
            
            # 启动连接保活任务，防止长时间闲置导致 DC 连接陈旧
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())
            
            # Start the web dashboard (Default port 8080)
            self.web_dashboard = WebDashboard(
                self.download_manager,
                port=int(os.getenv('WEB_PORT', 8080)),
                password=os.getenv('WEB_PASSWORD', '')
            )
            await self.web_dashboard.start()
            
            logger.info("Bot started successfully and is now listening for messages")
            
            # Run until the main client disconnects
            await self.main_client.run_until_disconnected()

        except Exception as e:
            logger.critical(f"Bot runtime error: {e}", exc_info=True)
            raise
        finally:
            # Only stop if not already stopped
            if self.main_client and self.main_client.is_connected():
                await self.stop()
    
    async def stop(self) -> None:
        """Stop the bot and clean up resources."""
        logger.info("Stopping bot...")
        
        # Cancel cleanup task
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # 取消保活任务
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
                
        # Stop web dashboard
        if self.web_dashboard:
            await self.web_dashboard.stop()
        
        # Disconnect all clients
        for client in (self.bot_client, self.user_client):
            if client and client.is_connected():
                await client.disconnect()

        logger.info("Bot stopped")
    
    async def _auto_cleanup_loop(self) -> None:
        """Background task for automatic file cleanup."""
        while True:
            try:
                # Run cleanup once per day
                await asyncio.sleep(24 * 60 * 60)
                
                if Config.AUTO_CLEANUP_DAYS > 0:
                    result = self.file_manager.cleanup_old_files(Config.AUTO_CLEANUP_DAYS)
                    if result['deleted_count'] > 0:
                        logger.info(
                            f"Auto-cleanup: deleted {result['deleted_count']} files "
                            f"older than {Config.AUTO_CLEANUP_DAYS} days"
                        )
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Auto-cleanup error: {e}")
                await asyncio.sleep(60 * 60)  # Wait an hour on error
    
    async def _keepalive_loop(self) -> None:
        """每 30 分钟对每个客户端发送轻量级请求，保持 DC 连接活跃，防止长时间闲置后连接陈旧。"""
        while True:
            try:
                await asyncio.sleep(30 * 60)  # 30 分钟
                for name, client in (('bot', self.bot_client), ('user', self.user_client)):
                    if not client:
                        continue
                    try:
                        if client.is_connected():
                            me = await client.get_me()
                            logger.debug(f"连接保活[{name}]: OK (id: {me.id})")
                        else:
                            logger.warning(f"连接保活[{name}]: 连接已断开，尝试重连...")
                            await client.connect()
                    except Exception as e:
                        logger.warning(f"连接保活[{name}]失败: {e}，尝试重连...")
                        try:
                            await client.disconnect()
                            await client.connect()
                            logger.info(f"连接保活[{name}]: 重连成功")
                        except Exception as reconn_err:
                            logger.error(f"连接保活[{name}]: 重连失败: {reconn_err}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"连接保活循环异常: {e}")


def main() -> int:
    """Main entry point.
    
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    logger.info("Starting Telegram File Manager Bot...")
    
    bot = TelegramFileBot()
    
    if not bot.initialize():
        logger.critical("Failed to initialize bot. Exiting.")
        return 1
    
    try:
        asyncio.run(bot.start())
        return 0
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        return 0
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
