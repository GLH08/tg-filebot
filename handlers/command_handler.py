"""Command handlers for the Telegram File Bot."""

import logging
from typing import Callable, Awaitable, Any, List

from telethon import events, Button
from telethon.tl.types import Message

from utils.download_manager import DownloadManager
from utils.file_manager import FileManager
from .auth import is_user_allowed, is_chat_allowed
import config

logger = logging.getLogger(__name__)


def register_command_handlers(
    bot,
    file_manager: FileManager,
    download_manager: DownloadManager
) -> None:
    """Register all command handlers with the bot.
    
    Args:
        bot: Telethon client instance
        file_manager: FileManager instance
        download_manager: DownloadManager instance
    """
    
    def create_command_handler(pattern: str) -> Callable:
        """Decorator factory for command handlers with auth and error handling."""
        def decorator(handler_func: Callable[..., Awaitable[Any]]) -> Callable:
            @bot.on(events.NewMessage(pattern=pattern))
            async def command_wrapper(event: Message) -> None:
                if not is_chat_allowed(event):
                    await event.respond("⛔ You are not authorized to use this bot.")
                    raise events.StopPropagation
                
                try:
                    await handler_func(event)
                except Exception as e:
                    logger.error(
                        f"Command '{pattern}' error for user {event.sender_id}: {e}",
                        exc_info=True
                    )
                    await event.respond(f"❌ An unexpected error occurred: {str(e)}")
                finally:
                    raise events.StopPropagation
            return command_wrapper
        return decorator

    @bot.on(events.NewMessage(pattern='/start'))
    async def start_command(event: Message) -> None:
        """Handle /start command - show help message."""
        if not is_chat_allowed(event):
            await event.respond("⛔ You are not authorized to use this bot.")
            return
        
        help_text = """
📥 **Telegram File Manager Bot** 📥

This bot helps you manage file downloads.

**Commands:**
- `/start` - Show this help message
- `/list [page]` - List downloaded files (paginated)
- `/search <query>` - Search files by name
- `/rename <index> <new_name>` - Rename a file
- `/delete <index>` - Delete a file
- `/cancel <download_id>` - Cancel an active/queued download
- `/active` - View active downloads
- `/queue` - View queued downloads
- `/stats` - View download statistics
- `/cleanup` - Clean up completed downloads

**Usage:**
- Send files directly to download
- Forward messages with files
- Send public Telegram post links to download

Files are stored in a `YYYYMMDD` dated folder structure.
        """
        await event.respond(help_text)
        raise events.StopPropagation

    @create_command_handler(r'/list(?: (\d+))?')
    async def list_command(event: Message) -> None:
        """Handle /list command - list downloaded files with pagination."""
        page = 1
        is_callback = hasattr(event, 'data') and event.data

        if is_callback:
            page = int(event.data.decode('utf-8').split('_')[1])
        elif event.pattern_match.group(1):
            page = int(event.pattern_match.group(1))

        page_size = 10
        files = file_manager.list_files()

        if not files:
            message = "📂 No files have been downloaded yet."
            if is_callback:
                await event.edit(message)
            else:
                await event.respond(message)
            return

        total_pages = (len(files) + page_size - 1) // page_size
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * page_size
        paged_files = files[start_idx:start_idx + page_size]

        response = f"📂 **Downloaded Files** (Page {page}/{total_pages}):\n\n"
        for idx, file_info in enumerate(paged_files, start_idx + 1):
            response += f"{idx}. `{file_info['relative_path']}`\n"
            response += f"   Size: {file_info['size']}\n\n"

        buttons = _build_pagination_buttons(page, total_pages)
        
        if is_callback:
            await event.edit(response, buttons=buttons or None)
        else:
            await event.respond(response, buttons=buttons or None)

    @create_command_handler(r'/search (.+)')
    async def search_command(event: Message) -> None:
        """Handle /search command - search files by name."""
        query = event.pattern_match.group(1).strip()
        
        if not query:
            await event.respond("❌ Please provide a search query.\nUsage: `/search <query>`")
            return
        
        files = file_manager.search_files(query)
        
        if not files:
            await event.respond(f"🔍 No files found matching: `{query}`")
            return
        
        response = f"🔍 **Search Results for:** `{query}`\n\n"
        for idx, file_info in enumerate(files[:20], 1):  # Limit to 20 results
            response += f"{idx}. `{file_info['relative_path']}`\n"
            response += f"   Size: {file_info['size']}\n\n"
        
        if len(files) > 20:
            response += f"\n_...and {len(files) - 20} more results_"
        
        await event.respond(response)

    @create_command_handler(r'/rename (\d+) (.+)')
    async def rename_command(event: Message) -> None:
        """Handle /rename command - rename a file by index."""
        index = int(event.pattern_match.group(1))
        new_name = event.pattern_match.group(2).strip()
        
        result = file_manager.rename_file(index - 1, new_name)
        if result['success']:
            await event.respond(f"✅ File renamed to: `{result['new_relative_path']}`")
        else:
            await event.respond(f"❌ Error: {result['message']}")

    @create_command_handler(r'/delete (\d+)')
    async def delete_command(event: Message) -> None:
        """Handle /delete command - delete a file by index."""
        index = int(event.pattern_match.group(1))
        result = file_manager.delete_file(index - 1)
        if result['success']:
            await event.respond(f"✅ File deleted: `{result['deleted_path']}`")
        else:
            await event.respond(f"❌ Error: {result['message']}")

    @create_command_handler(r'/cancel (\S+)')
    async def cancel_command(event: Message) -> None:
        """Handle /cancel command - cancel an active or queued download."""
        download_id = event.pattern_match.group(1)
        result = download_manager.cancel_download(download_id)
        
        if result['success']:
            if result.get('was_queued'):
                await event.respond(f"✅ Queued download cancelled: `{result['filename']}`")
            else:
                await event.respond(f"✅ Download cancelled: `{result['filename']}`")
        else:
            await event.respond(f"❌ Error: {result['message']}")

    @create_command_handler(r'/active')
    async def active_downloads_command(event: Message) -> None:
        """Handle /active command - show active downloads."""
        downloads = download_manager.list_active_downloads()
        total_active = len(download_manager.active_downloads)
        max_concurrent = download_manager.max_concurrent_downloads
        
        if not downloads:
            response = "📥 No active downloads.\n\n"
            response += f"📊 **Status**: {total_active}/{max_concurrent} slots used"
            await event.respond(response)
            return
        
        response = f"📥 **Active Downloads** ({len(downloads)}):\n\n"
        for idx, (download_id, info) in enumerate(downloads.items(), 1):
            percentage = int(info['downloaded'] * 100 / max(info['size'], 1))
            response += f"{idx}. `{info['filename']}`\n"
            response += f"   Progress: {percentage}%, ID: `{download_id}`\n\n"
        
        response += f"📊 **Slots**: {total_active}/{max_concurrent} used\n"
        response += "To cancel: `/cancel <download_id>`"
        await event.respond(response)

    @create_command_handler(r'/queue')
    async def queue_command(event: Message) -> None:
        """Handle /queue command - show queued downloads."""
        queued = download_manager.list_queued_downloads()
        
        if not queued:
            await event.respond("📋 No downloads in queue.")
            return
        
        response = f"📋 **Download Queue** ({len(queued)} items):\n\n"
        for item in queued:
            response += f"#{item['position']}. `{item['filename']}`\n"
            response += f"   ID: `{item['download_id']}`\n\n"
        
        response += "To cancel: `/cancel <download_id>`"
        await event.respond(response)

    @create_command_handler(r'/stats')
    async def stats_command(event: Message) -> None:
        """Handle /stats command - show download statistics."""
        stats = file_manager.get_stats()
        active = len(download_manager.list_active_downloads())
        queued = len(download_manager.list_queued_downloads())
        
        response = "📊 **Download Statistics**\n\n"
        response += f"📁 Total Files: {stats['total_files']}\n"
        response += f"💾 Total Size: {stats['total_size']}\n"
        response += f"⏬ Active Downloads: {active}\n"
        response += f"📋 Queued Downloads: {queued}\n"
        response += f"🔢 Max Concurrent: {download_manager.max_concurrent_downloads}"
        
        await event.respond(response)

    @create_command_handler(r'/cleanup')
    async def cleanup_command(event: Message) -> None:
        """Handle /cleanup command - clean up completed downloads."""
        before_count = len(download_manager.active_downloads)
        download_manager._cleanup_completed_downloads()
        after_count = len(download_manager.active_downloads)
        cleaned = before_count - after_count
        
        if cleaned > 0:
            await event.respond(
                f"✅ Cleaned up {cleaned} completed download(s).\n"
                f"📊 **Slots**: {after_count}/{download_manager.max_concurrent_downloads} used"
            )
        else:
            await event.respond(
                f"ℹ️ No completed downloads to clean up.\n"
                f"📊 **Slots**: {after_count}/{download_manager.max_concurrent_downloads} used"
            )

    @create_command_handler(r'/autocleanup(?: (\d+))?')
    async def autocleanup_command(event: Message) -> None:
        """Handle /autocleanup command - clean up old files."""
        days_str = event.pattern_match.group(1)
        
        if not days_str:
            if config.AUTO_CLEANUP_DAYS > 0:
                await event.respond(
                    f"ℹ️ Auto cleanup is set to {config.AUTO_CLEANUP_DAYS} days.\n"
                    f"Use `/autocleanup <days>` to clean files older than specified days."
                )
            else:
                await event.respond(
                    "ℹ️ Auto cleanup is disabled.\n"
                    "Use `/autocleanup <days>` to clean files older than specified days."
                )
            return
        
        days = int(days_str)
        if days <= 0:
            await event.respond("❌ Days must be a positive number.")
            return
        
        result = file_manager.cleanup_old_files(days)
        
        if result['success']:
            if result['deleted_count'] > 0:
                await event.respond(
                    f"✅ Cleaned up {result['deleted_count']} file(s) older than {days} days."
                )
            else:
                await event.respond(f"ℹ️ No files older than {days} days found.")
        else:
            await event.respond(f"❌ Error: {result['message']}")

    # Pagination callback handler
    @bot.on(events.CallbackQuery(pattern=b"page_(\\d+)"))
    async def page_callback_handler(event) -> None:
        """Handle pagination button clicks."""
        if not is_user_allowed(event.sender_id):
            await event.answer("⛔ You are not authorized to use this bot.")
            return
        
        await list_command(event)
        await event.answer()


def _build_pagination_buttons(page: int, total_pages: int) -> List[List[Button]]:
    """Build pagination buttons for file listing.
    
    Args:
        page: Current page number
        total_pages: Total number of pages
        
    Returns:
        List of button rows
    """
    if total_pages <= 1:
        return []
    
    buttons: List[List[Button]] = []
    row: List[Button] = []
    max_buttons = 5

    if page > 1:
        row.append(Button.inline("◀️ Prev", f"page_{page - 1}"))

    start_page = max(1, min(page - max_buttons // 2, total_pages - max_buttons + 1))
    end_page = min(total_pages, start_page + max_buttons - 1)

    for p in range(start_page, end_page + 1):
        if p == page:
            row.append(Button.inline(f"[{p}]", f"page_{p}"))
        else:
            row.append(Button.inline(str(p), f"page_{p}"))

    if page < total_pages:
        row.append(Button.inline("Next ▶️", f"page_{page + 1}"))
    
    if row:
        buttons.append(row)
    
    return buttons
