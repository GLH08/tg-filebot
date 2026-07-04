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
        self.client: Optional[TelegramClient] = None
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
            
            # Initialize the Telethon client
            if Config.SESSION_STRING:
                session = StringSession(Config.SESSION_STRING)
                logger.info("Configured to use USER mode (via StringSession)")
            else:
                session_path = os.path.join('data', 'bot_session')
                os.makedirs('data', exist_ok=True)
                session = session_path
                logger.info("Configured to use BOT mode (via bot_token)")

            self.client = TelegramClient(
                session,
                Config.API_ID,
                Config.API_HASH
            )
            
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
        if not self.client:
            logger.error("Bot not initialized. Call initialize() first.")
            return
        
        try:
            # Start the client based on mode
            if Config.SESSION_STRING:
                await self.client.start()
                logger.info("Connected as User Account.")
            else:
                await self.client.start(bot_token=Config.BOT_TOKEN)
                logger.info("Connected as Bot Account.")
            
            # Register handlers
            register_command_handlers(
                self.client,
                self.file_manager,
                self.download_manager
            )
            register_message_handlers(self.client, self.download_manager)
            
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
            
            # Run until disconnected
            await self.client.run_until_disconnected()
            
        except Exception as e:
            logger.critical(f"Bot runtime error: {e}", exc_info=True)
            raise
        finally:
            # Only stop if not already stopped
            if self.client and self.client.is_connected():
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
        
        # Disconnect client
        if self.client and self.client.is_connected():
            await self.client.disconnect()
        
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
        """每 30 分钟发送轻量级请求，保持 DC 连接活跃，防止长时间闲置后连接陈旧。"""
        while True:
            try:
                await asyncio.sleep(30 * 60)  # 30 分钟
                if self.client and self.client.is_connected():
                    me = await self.client.get_me()
                    logger.debug(f"连接保活: OK (bot id: {me.id})")
                else:
                    logger.warning("连接保活: 连接已断开，尝试重连...")
                    await self.client.connect()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"连接保活失败: {e}，尝试重连...")
                try:
                    await self.client.disconnect()
                    await self.client.connect()
                    logger.info("连接保活: 重连成功")
                except Exception as reconn_err:
                    logger.error(f"连接保活: 重连失败: {reconn_err}")


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
