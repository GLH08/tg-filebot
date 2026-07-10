"""Message handlers for processing files and links."""

import logging
import re
from datetime import datetime
from typing import Optional, List

from telethon import events, Button
from telethon.tl.types import (
    DocumentAttributeFilename,
    MessageMediaPhoto,
    MessageMediaWebPage,
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

        # Enhanced logging for forwarded messages
        if event.message.fwd_from:
            fwd = event.message.fwd_from
            fwd_source = getattr(fwd, 'from_id', None) or getattr(fwd, 'from_name', None)
            logger.info(f"收到转发消息: fwd_from={fwd_source}, type={type(fwd_source)}")
            if not event.media:
                logger.warning(f"转发消息无媒体内容: text_preview='{event.raw_text[:20]}'")
                await event.respond("⚠️ 该转发消息似乎没有携带媒体文件。这可能是 Telegram 的版权保护限制，或者转发时未包含附件。")

        # Check for media content first.
        # MessageMediaWebPage is a link preview attached to this message itself
        # (e.g. when the user sends a t.me link as text) - it is not a file, so
        # skip it and let the text-link branch below parse the actual link.
        if event.media and not isinstance(event.media, MessageMediaWebPage):
            await _download_from_message(bot, event, download_manager)
            return

        # Check for Telegram links
        message_text = event.text
        if message_text:
            links = _extract_telegram_links(message_text)
            if links:
                await _process_links(bot, event, download_manager, links)
                return


def _extract_telegram_links(text: str) -> List[str]:
    """Extract all Telegram links from text.
    
    Args:
        text: Message text to parse
        
    Returns:
        List of found Telegram links
    """
    if not text:
        return []
    # 正则匹配基本的 https://t.me/... 链接，并过滤末尾可能粘连的中文句号或括号等非URL字符
    # 末尾可选捕获 ?comment=/?thread= 等查询串（评论/话题链接），否则会被截断丢失
    pattern = r'https?://(?:t\.me|telegram\.me)/[a-zA-Z0-9_/%+-]+(?:\?[a-zA-Z0-9_=&]+)?'
    return re.findall(pattern, text)


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


async def _process_links(
    bot,
    event: Message,
    download_manager: DownloadManager,
    links: List[str]
) -> None:
    """Process one or multiple Telegram links for download.
    
    Args:
        bot: Telethon client
        event: Message event
        download_manager: DownloadManager instance
        links: List of Telegram links to process
    """
    multi = len(links) > 1
    success_count = 0
    fail_count = 0

    for i, link in enumerate(links):
        # 每个链接单独创建状态消息，避免并发下载时进度互相覆盖
        try:
            label = f" {i + 1}/{len(links)}" if multi else ""
            status_message = await event.respond(f"⏳ Processing link{label}...\n{link}")
        except Exception as e:
            logger.error(f"Failed to create status message: {e}")
            fail_count += 1
            continue

        try:
            download_id = await download_manager.process_telegram_link(
                bot, link, event.chat_id, status_message.id
            )
            if download_id:
                success_count += 1
            else:
                fail_count += 1
                # 双客户端模式：@bot 下载失败 → 提供「用老号重试」按钮
                if download_manager.fallback_client is not None:
                    token = download_manager.register_retry(link, event.chat_id, status_message.id)
                    try:
                        await bot.edit_message(
                            event.chat_id, status_message.id,
                            f"❌ @bot 无法下载该链接（可能是禁止转发/私有频道）。\n{link}\n\n"
                            f"👇 点下方用老号重试：",
                            buttons=[Button.inline("🔁 用老号重试", f"userretry_{token}".encode())]
                        )
                    except Exception as e:
                        logger.warning(f"挂重试按钮失败: {e}")
        except Exception as e:
            logger.error(f"Link processing error for user {event.sender_id} on {link}: {e}", exc_info=True)
            fail_count += 1
            await _safe_edit_message(
                bot, event.chat_id, status_message.id,
                f"❌ Error processing link ({i + 1}): {e}\n{link}"
            )

    if multi:
        await event.respond(
            f"✅ Batch processing complete!\n"
            f"Successfully added: {success_count}\n"
            f"Failed: {fail_count}"
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
