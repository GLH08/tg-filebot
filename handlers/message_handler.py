"""Message handlers for processing files and links."""

import logging
from datetime import datetime
from typing import Optional

from telethon import events
from telethon.tl.types import (
    DocumentAttributeFilename,
    MessageMediaPhoto,
    Message
)

from utils.download_manager import DownloadManager
from .auth import is_chat_allowed
import config

logger = logging.getLogger(__name__)


def register_message_handlers(bot, download_manager: DownloadManager) -> None:
    """Register handlers for non-command messages.
    
    Args:
        bot: Telethon client instance
        download_manager: DownloadManager instance
    """

    @bot.on(events.NewMessage)
    async def message_handler(event: Message) -> None:
        """Handle incoming messages with files or links."""
        # Ignore outgoing messages
        if event.out:
            return
        
        # Check chat permissions
        if not is_chat_allowed(event):
            if not event.is_private:
                return  # Silently ignore group messages if not allowed
            logger.warning(f"Ignored message from unauthorized user: {event.sender_id}")
            return

        # Check for media content first
        if event.media:
            await _download_from_message(bot, event, download_manager)
            return

        # Check for Telegram links
        message_text = event.text
        if message_text and _is_telegram_link(message_text):
            await _process_link(bot, event, download_manager, message_text)
            return


def _is_telegram_link(text: str) -> bool:
    """Check if text contains a Telegram link.
    
    Args:
        text: Message text to check
        
    Returns:
        True if contains Telegram link
    """
    return "t.me/" in text or "telegram.me/" in text


async def _download_from_message(
    bot,
    event: Message,
    download_manager: DownloadManager
) -> None:
    """Handle download process for a message with media.
    
    Args:
        bot: Telethon client
        event: Message event with media
        download_manager: DownloadManager instance
    """
    try:
        status_message = await event.respond("⏳ Starting download...")
    except Exception as e:
        logger.error(f"Failed to create status message: {e}")
        return
    
    try:
        filename = _extract_filename(event)
        
        download_id = await download_manager.download_telegram_file(
            bot, event.message, event.chat_id, status_message.id, filename
        )
        
        if download_id:
            await _add_cancel_info(bot, event, status_message, download_id, download_manager)

    except Exception as e:
        logger.error(f"Download error for user {event.sender_id}: {e}", exc_info=True)
        await _safe_edit_message(
            bot, event.chat_id, status_message.id,
            f"❌ Download failed: {e}"
        )


async def _process_link(
    bot,
    event: Message,
    download_manager: DownloadManager,
    link: str
) -> None:
    """Process a Telegram link for download.
    
    Args:
        bot: Telethon client
        event: Message event
        download_manager: DownloadManager instance
        link: Telegram link to process
    """
    try:
        status_message = await event.respond("⏳ Processing Telegram link...")
    except Exception as e:
        logger.error(f"Failed to create status message: {e}")
        return
    
    try:
        await download_manager.process_telegram_link(
            bot, link, event.chat_id, status_message.id
        )
    except Exception as e:
        logger.error(f"Link processing error for user {event.sender_id}: {e}", exc_info=True)
        await _safe_edit_message(
            bot, event.chat_id, status_message.id,
            f"❌ Error processing link: {e}"
        )


def _extract_filename(event: Message) -> str:
    """Extract filename from message media.
    
    Args:
        event: Message event with media
        
    Returns:
        Extracted or generated filename
    """
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    
    # Check if it's a photo
    if isinstance(event.media, MessageMediaPhoto):
        return f"photo_{timestamp}.jpg"
    
    # Check for document with filename attribute
    if hasattr(event.media, 'document') and event.media.document:
        for attribute in event.media.document.attributes:
            if isinstance(attribute, DocumentAttributeFilename) and attribute.file_name:
                return attribute.file_name
    
    return f"file_{timestamp}"


async def _add_cancel_info(
    bot,
    event: Message,
    status_message: Message,
    download_id: str,
    download_manager: DownloadManager
) -> None:
    """Add cancellation info to the status message if download is still active.
    
    Args:
        bot: Telethon client
        event: Original message event
        status_message: Status message to update
        download_id: Download ID
        download_manager: DownloadManager instance
    """
    active_downloads = download_manager.list_active_downloads()
    queued_downloads = download_manager.list_queued_downloads()
    
    is_active = download_id in active_downloads
    is_queued = any(q['download_id'] == download_id for q in queued_downloads)
    
    if is_active or is_queued:
        try:
            current_message = await bot.get_messages(event.chat_id, ids=status_message.id)
            if current_message and current_message.text:
                await bot.edit_message(
                    event.chat_id,
                    status_message.id,
                    f"{current_message.text}\n\nTo cancel: `/cancel {download_id}`"
                )
        except Exception as e:
            logger.warning(f"Could not add cancellation info: {e}")


async def _safe_edit_message(bot, chat_id: int, msg_id: int, text: str) -> None:
    """Safely edit a message, handling errors gracefully.
    
    Args:
        bot: Telethon client
        chat_id: Chat ID
        msg_id: Message ID
        text: New message text
    """
    try:
        await bot.edit_message(chat_id, msg_id, text)
    except Exception as e:
        logger.warning(f"Failed to edit message: {e}")
