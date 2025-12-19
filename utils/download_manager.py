"""Download management for Telegram files with queue support and progress tracking."""

import os
import asyncio
import time
import logging
import uuid
import re
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from collections import deque

from telethon import TelegramClient
from telethon.tl.types import Message
from telethon.errors import FloodWaitError

import config
from .helpers import format_size, format_time

logger = logging.getLogger(__name__)


@dataclass
class DownloadInfo:
    """Information about an active or queued download."""
    download_id: str
    filename: str
    path: str
    relative_path: str
    size: int = 0
    downloaded: int = 0
    speed: float = 0
    status: str = 'pending'  # pending, downloading, completed, failed, cancelled, waiting
    start_time: float = field(default_factory=time.time)
    last_update_time: float = field(default_factory=time.time)
    last_downloaded: int = 0
    last_message: str = ''
    task: Optional[asyncio.Task] = None
    initial_phase: bool = True
    rate_limited: bool = False
    chat_id: int = 0
    status_msg_id: int = 0
    message: Optional[Message] = None


@dataclass
class QueuedDownload:
    """A download waiting in the queue."""
    download_id: str
    client: TelegramClient
    message: Message
    chat_id: int
    status_msg_id: int
    filename: str
    added_time: float = field(default_factory=time.time)


class DownloadManager:
    """Manages file downloads with concurrency control and queue support."""
    
    def __init__(self):
        self.active_downloads: Dict[str, DownloadInfo] = {}
        self.download_queue: deque[QueuedDownload] = deque()
        self.update_interval = 3
        self.max_concurrent_downloads = config.MAX_CONCURRENT_DOWNLOADS
        self.max_retries = config.MAX_RETRIES
        self.last_global_update: float = 0
        self.global_update_interval = 1
        self._queue_processor_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
    
    async def _get_unique_filepath(self, directory: str, filename: str) -> str:
        """Generate a unique filename to avoid overwriting existing files.
        
        Args:
            directory: Target directory
            filename: Desired filename
            
        Returns:
            Unique file path
        """
        original_filepath = os.path.join(directory, filename)
        
        if not os.path.exists(original_filepath):
            return original_filepath
        
        name, ext = os.path.splitext(filename)
        counter = 1
        
        while True:
            new_filename = f"{name} ({counter}){ext}"
            new_filepath = os.path.join(directory, new_filename)
            
            if not os.path.exists(new_filepath):
                return new_filepath
            
            counter += 1
            if counter > 1000:  # Safety limit
                new_filename = f"{name}_{uuid.uuid4().hex[:8]}{ext}"
                return os.path.join(directory, new_filename)
    
    def _get_active_count(self) -> int:
        """Get count of actively downloading items."""
        return sum(1 for d in self.active_downloads.values() 
                   if d.status in ('downloading', 'waiting'))
    
    async def download_telegram_file(
        self,
        client: TelegramClient,
        message: Message,
        chat_id: int,
        status_msg_id: int,
        filename: str
    ) -> Optional[str]:
        """Download a file from a Telegram message.
        
        Args:
            client: Telethon client instance
            message: Message containing the file
            chat_id: Chat ID for status updates
            status_msg_id: Message ID for status updates
            filename: Desired filename
            
        Returns:
            Download ID if started/queued, None on failure
        """
        self._cleanup_completed_downloads()
        
        download_id = str(uuid.uuid4())[:8]
        
        # Check if we can start immediately or need to queue
        if self._get_active_count() >= self.max_concurrent_downloads:
            # Add to queue
            queued = QueuedDownload(
                download_id=download_id,
                client=client,
                message=message,
                chat_id=chat_id,
                status_msg_id=status_msg_id,
                filename=filename
            )
            self.download_queue.append(queued)
            
            queue_position = len(self.download_queue)
            await self._safe_edit_message(
                client, chat_id, status_msg_id,
                f"📋 **Queued for Download**\n\n"
                f"**File:** `{filename}`\n"
                f"**Position:** #{queue_position}\n"
                f"**Download ID:** `{download_id}`\n\n"
                f"Download will start automatically when a slot is available.\n"
                f"To cancel: `/cancel {download_id}`"
            )
            
            # Start queue processor if not running
            if self._queue_processor_task is None or self._queue_processor_task.done():
                self._queue_processor_task = asyncio.create_task(self._process_queue())
            
            logger.info(f"Download queued: {filename}, ID: {download_id}, position: {queue_position}")
            return download_id
        
        # Start download immediately
        return await self._start_download(client, message, chat_id, status_msg_id, filename, download_id)
    
    async def _start_download(
        self,
        client: TelegramClient,
        message: Message,
        chat_id: int,
        status_msg_id: int,
        filename: str,
        download_id: str
    ) -> Optional[str]:
        """Start the actual download process."""
        today = datetime.now().strftime('%Y%m%d')
        download_path = os.path.join(config.DOWNLOAD_PATH, today)
        os.makedirs(download_path, exist_ok=True)
        
        file_path = await self._get_unique_filepath(download_path, filename)
        relative_path = os.path.relpath(file_path, config.DOWNLOAD_PATH)
        actual_filename = os.path.basename(file_path)
        
        key = download_id
        download_info = DownloadInfo(
            download_id=download_id,
            filename=actual_filename,
            path=file_path,
            relative_path=relative_path,
            status='downloading',
            chat_id=chat_id,
            status_msg_id=status_msg_id,
            message=message
        )
        
        self.active_downloads[key] = download_info
        
        await self._safe_edit_message(
            client, chat_id, status_msg_id,
            f"⏬ Downloading: `{actual_filename}`\n"
            f"🔄 Initializing download...\n"
            f"🔢 Download ID: `{download_id}`"
        )
        
        update_task = asyncio.create_task(
            self._update_progress(client, download_id)
        )
        
        try:
            result = await self._download_with_retry(
                client, message, file_path, download_id
            )
            
            if result and key in self.active_downloads:
                info = self.active_downloads[key]
                if info.status != 'cancelled':
                    file_size = os.path.getsize(result) if os.path.exists(result) else 0
                    info.status = 'completed'
                    info.size = file_size
                    info.downloaded = file_size
                    
                    await self._send_completion_message(
                        client, chat_id, status_msg_id, relative_path, file_size
                    )
                    
                    logger.info(f"Download completed: {actual_filename}, ID: {download_id}")
            
            return download_id
            
        except asyncio.CancelledError:
            logger.info(f"Download cancelled: {actual_filename}, ID: {download_id}")
            await self._safe_edit_message(
                client, chat_id, status_msg_id,
                f"🛑 Download cancelled: `{actual_filename}`"
            )
            self._cleanup_partial_file(file_path)
            return None
            
        except Exception as e:
            logger.error(f"Download error: {e}", exc_info=True)
            if key in self.active_downloads:
                self.active_downloads[key].status = 'failed'
            await self._safe_edit_message(
                client, chat_id, status_msg_id,
                f"❌ Download failed: {str(e)}"
            )
            return None
            
        finally:
            update_task.cancel()
            # Schedule cleanup
            asyncio.create_task(self._delayed_cleanup(key, 5))
            # Process queue after download completes
            asyncio.create_task(self._process_queue())
    
    async def _download_with_retry(
        self,
        client: TelegramClient,
        message: Message,
        file_path: str,
        download_id: str
    ) -> Optional[str]:
        """Download with retry logic for rate limits.
        
        Args:
            client: Telethon client
            message: Message with file
            file_path: Target file path
            download_id: Download ID for tracking
            
        Returns:
            Downloaded file path or None
        """
        for attempt in range(self.max_retries):
            try:
                download_task = asyncio.create_task(
                    client.download_media(
                        message,
                        file_path,
                        progress_callback=lambda d, t: self._progress_callback(d, t, download_id)
                    )
                )
                
                if download_id in self.active_downloads:
                    self.active_downloads[download_id].task = download_task
                
                result = await download_task
                
                if result and os.path.exists(result):
                    return result
                raise Exception("Download failed - file not saved")
                
            except FloodWaitError as e:
                wait_time = e.seconds
                logger.warning(f"Rate limited, waiting {wait_time}s (attempt {attempt + 1}/{self.max_retries})")
                
                if download_id in self.active_downloads:
                    info = self.active_downloads[download_id]
                    info.status = 'waiting'
                    await self._safe_edit_message(
                        client, info.chat_id, info.status_msg_id,
                        f"⏳ Rate limited. Waiting {wait_time} seconds...\n"
                        f"Attempt {attempt + 1}/{self.max_retries}"
                    )
                
                await asyncio.sleep(wait_time)
                
                if attempt == self.max_retries - 1:
                    raise
                    
            except asyncio.CancelledError:
                raise
                
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise
                logger.warning(f"Download attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        return None
    
    async def _process_queue(self) -> None:
        """Process queued downloads when slots become available."""
        async with self._lock:
            while self.download_queue and self._get_active_count() < self.max_concurrent_downloads:
                queued = self.download_queue.popleft()
                
                # Update queue positions for remaining items
                for i, item in enumerate(self.download_queue):
                    try:
                        await self._safe_edit_message(
                            item.client, item.chat_id, item.status_msg_id,
                            f"📋 **Queued for Download**\n\n"
                            f"**File:** `{item.filename}`\n"
                            f"**Position:** #{i + 1}\n"
                            f"**Download ID:** `{item.download_id}`\n\n"
                            f"To cancel: `/cancel {item.download_id}`"
                        )
                    except Exception:
                        pass
                
                # Start the queued download
                asyncio.create_task(
                    self._start_download(
                        queued.client,
                        queued.message,
                        queued.chat_id,
                        queued.status_msg_id,
                        queued.filename,
                        queued.download_id
                    )
                )
    
    def cancel_download(self, download_id: str) -> Dict[str, Any]:
        """Cancel an active or queued download.
        
        Args:
            download_id: Download ID to cancel
            
        Returns:
            Result dictionary
        """
        # Check active downloads
        if download_id in self.active_downloads:
            info = self.active_downloads[download_id]
            
            if info.task and not info.task.done():
                info.task.cancel()
            
            info.status = 'cancelled'
            self._cleanup_partial_file(info.path)
            
            del self.active_downloads[download_id]
            logger.info(f"Cancelled active download: {download_id}")
            
            return {
                'success': True,
                'filename': info.filename,
                'download_id': download_id
            }
        
        # Check queue
        for queued in list(self.download_queue):
            if queued.download_id == download_id:
                self.download_queue.remove(queued)
                logger.info(f"Cancelled queued download: {download_id}")
                
                return {
                    'success': True,
                    'filename': queued.filename,
                    'download_id': download_id,
                    'was_queued': True
                }
        
        return {
            'success': False,
            'message': f"No download found with ID: {download_id}"
        }
    
    def list_active_downloads(self) -> Dict[str, Dict[str, Any]]:
        """List all active downloads.
        
        Returns:
            Dictionary of active download info
        """
        self._cleanup_completed_downloads()
        
        return {
            info.download_id: {
                'filename': info.filename,
                'downloaded': info.downloaded,
                'size': info.size,
                'status': info.status,
                'speed': info.speed
            }
            for info in self.active_downloads.values()
            if info.status in ('downloading', 'waiting')
        }
    
    def list_queued_downloads(self) -> List[Dict[str, Any]]:
        """List all queued downloads.
        
        Returns:
            List of queued download info
        """
        return [
            {
                'download_id': q.download_id,
                'filename': q.filename,
                'position': i + 1,
                'queued_time': q.added_time
            }
            for i, q in enumerate(self.download_queue)
        ]
    
    def _cleanup_completed_downloads(self) -> None:
        """Clean up completed, failed, or cancelled downloads."""
        current_time = time.time()
        to_remove = []
        
        for key, info in self.active_downloads.items():
            if info.status == 'cancelled':
                to_remove.append(key)
            elif info.status in ('completed', 'failed'):
                if current_time - info.start_time > 30:
                    to_remove.append(key)
        
        for key in to_remove:
            if key in self.active_downloads:
                logger.debug(f"Cleaning up download: {key}")
                del self.active_downloads[key]
    
    def _cleanup_partial_file(self, file_path: str) -> None:
        """Remove a partial download file."""
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Removed partial file: {file_path}")
            except OSError as e:
                logger.error(f"Failed to remove partial file: {e}")
    
    async def _delayed_cleanup(self, key: str, delay: float) -> None:
        """Clean up download info after a delay."""
        await asyncio.sleep(delay)
        if key in self.active_downloads:
            status = self.active_downloads[key].status
            if status in ('completed', 'failed', 'cancelled'):
                del self.active_downloads[key]
    
    async def process_telegram_link(
        self,
        client: TelegramClient,
        link: str,
        chat_id: int,
        status_msg_id: int
    ) -> Optional[str]:
        """Process a Telegram link to download its content.
        
        Args:
            client: Telethon client
            link: Telegram message link
            chat_id: Chat ID for status updates
            status_msg_id: Message ID for status updates
            
        Returns:
            Download ID if successful
        """
        match = re.search(r't\.me/(?:c/)?([a-zA-Z0-9_]+)/(\d+)', link)
        if not match:
            await self._safe_edit_message(
                client, chat_id, status_msg_id,
                "❌ Invalid Telegram link format"
            )
            return None
        
        channel, message_id = match.groups()
        message_id = int(message_id)
        
        try:
            entity = await client.get_entity(channel)
            message = await client.get_messages(entity, ids=message_id)
            
            if not message or not message.media:
                await self._safe_edit_message(
                    client, chat_id, status_msg_id,
                    "❌ No media found in the linked message"
                )
                return None
            
            filename = f"file_from_link_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            if hasattr(message.media, 'document'):
                for attr in message.media.document.attributes:
                    if hasattr(attr, 'file_name') and attr.file_name:
                        filename = attr.file_name
                        break
            
            return await self.download_telegram_file(
                client, message, chat_id, status_msg_id, filename
            )
            
        except Exception as e:
            logger.error(f"Link processing error: {e}", exc_info=True)
            await self._safe_edit_message(
                client, chat_id, status_msg_id,
                f"❌ Error processing link: {str(e)}"
            )
            return None
    
    def _progress_callback(self, downloaded: int, total: int, download_id: str) -> None:
        """Callback to track download progress."""
        if download_id not in self.active_downloads:
            return
        
        info = self.active_downloads[download_id]
        if info.status == 'cancelled':
            return
        
        # Determine if update is significant
        if info.downloaded < 1024 * 1024:  # First 1MB
            significant = True
            if downloaded > 0 and info.initial_phase:
                info.initial_phase = False
        else:
            min_progress = min(256 * 1024, (total or 1) * 0.01)
            significant = abs(downloaded - info.last_downloaded) >= min_progress
        
        if total and downloaded == total:
            significant = True
        
        if significant:
            info.downloaded = downloaded
            if total and total > 0:
                info.size = total
            
            current_time = time.time()
            elapsed = current_time - info.last_update_time
            if elapsed >= 0.1:
                downloaded_since = downloaded - info.last_downloaded
                if elapsed > 0:
                    info.speed = downloaded_since / elapsed
                info.last_update_time = current_time
                info.last_downloaded = downloaded
    
    async def _update_progress(self, client: TelegramClient, download_id: str) -> None:
        """Periodically update progress messages."""
        try:
            while download_id in self.active_downloads:
                info = self.active_downloads[download_id]
                
                if info.rate_limited:
                    await asyncio.sleep(5)
                    continue
                
                if info.status == 'downloading':
                    message = self._build_progress_message(info)
                    
                    if message != info.last_message:
                        current_time = time.time()
                        if current_time - self.last_global_update >= self.global_update_interval:
                            success = await self._safe_edit_message(
                                client, info.chat_id, info.status_msg_id, message
                            )
                            if success:
                                info.last_message = message
                                self.last_global_update = current_time
                            elif "flood" in str(success).lower() if success else False:
                                info.rate_limited = True
                                break
                
                # Dynamic sleep based on file size
                if info.initial_phase:
                    await asyncio.sleep(1)
                elif info.size > 500 * 1024 * 1024:
                    await asyncio.sleep(3)
                elif info.size > 100 * 1024 * 1024:
                    await asyncio.sleep(2)
                else:
                    await asyncio.sleep(1)
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Progress updater error: {e}")
    
    def _build_progress_message(self, info: DownloadInfo) -> str:
        """Build the progress message string."""
        if info.initial_phase and info.downloaded == 0:
            return (
                f"⏬ Downloading: `{info.filename}`\n"
                f"🔄 Establishing connection...\n"
                f"⏱️ This might take a moment for large files\n"
                f"🔢 Download ID: `{info.download_id}`"
            )
        
        percentage = int(info.downloaded * 100 / max(info.size, 1)) if info.size > 0 else 0
        bar_length = 20
        filled = int(bar_length * percentage / 100)
        bar = '█' * filled + '░' * (bar_length - filled)
        
        speed_str = f"{format_size(info.speed)}/s"
        
        eta = "unknown"
        if info.speed > 0 and info.size > info.downloaded:
            remaining = info.size - info.downloaded
            eta = format_time(remaining / info.speed)
        
        msg = (
            f"⏬ Downloading: `{info.filename}`\n"
            f"🔄 Progress: |{bar}| {percentage}%\n"
            f"📊 {format_size(info.downloaded)}"
        )
        
        if info.size > 0:
            msg += f" of {format_size(info.size)}\n"
        else:
            msg += " downloaded\n"
        
        msg += f"🚀 Speed: {speed_str}"
        if info.size > 0 and info.speed > 0:
            msg += f", ETA: {eta}\n"
        else:
            msg += "\n"
        
        msg += f"🔢 Download ID: `{info.download_id}`"
        
        return msg
    
    async def _send_completion_message(
        self,
        client: TelegramClient,
        chat_id: int,
        status_msg_id: int,
        relative_path: str,
        file_size: int
    ) -> None:
        """Send download completion message."""
        date_part = os.path.dirname(relative_path)
        filename_part = os.path.basename(relative_path)
        
        formatted_date = date_part
        if date_part and len(date_part) == 8:
            try:
                formatted_date = f"{date_part[0:4]}-{date_part[4:6]}-{date_part[6:8]}"
            except (IndexError, ValueError):
                pass
        
        await self._safe_edit_message(
            client, chat_id, status_msg_id,
            f"✅ **Download Complete**\n\n"
            f"**File:** `{filename_part}`\n"
            f"**Folder:** {formatted_date}\n"
            f"**Size:** {format_size(file_size)}\n"
            f"**Path:** `{relative_path}`"
        )
    
    async def _safe_edit_message(
        self,
        client: TelegramClient,
        chat_id: int,
        msg_id: int,
        text: str
    ) -> bool:
        """Safely edit a message, handling errors gracefully."""
        try:
            await client.edit_message(chat_id, msg_id, text)
            return True
        except Exception as e:
            error_str = str(e).lower()
            if "not modified" not in error_str:
                logger.warning(f"Failed to edit message: {e}")
            return False
