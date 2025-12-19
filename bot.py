"""Telegram File Manager Bot - Main entry point."""

import os
import sys
import logging
import asyncio
from typing import Optional

from telethon import TelegramClient

from config import Config, ConfigError
from utils.download_manager import DownloadManager
from utils.file_manager import FileManager
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
        self._cleanup_task: Optional[asyncio.Task] = None
    
    def initialize(self) -> bool:
        """Initialize the bot components.
        
        Returns:
            True if initialization successful, False otherwise
        """
        try:
            # Validate configuration
            Config.validate()
            
            # Initialize the Telethon client
            self.client = TelegramClient(
                'bot_session',
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
            # Start the client
            await self.client.start(bot_token=Config.BOT_TOKEN)
            
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
