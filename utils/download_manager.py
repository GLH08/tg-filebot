"""Download management for Telegram files with queue support and progress tracking."""

import os
import asyncio
import time
import logging
import uuid
import re
import shutil
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from collections import deque

from telethon import TelegramClient
from telethon.tl.types import Message, MessageMediaDocument, PeerChannel
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import GetDiscussionMessageRequest

import config
from .helpers import format_size, format_time, sanitize_filename

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
    last_edit_time: float = field(default_factory=time.time)
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
        self.max_concurrent_downloads = max(1, config.MAX_CONCURRENT_DOWNLOADS)
        self.max_retries = max(1, config.MAX_RETRIES)
        self.last_global_update: float = 0
        self.global_update_interval = 1
        self._queue_processor_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        # 双客户端：messaging_client 恒为主客户端(发/改消息)，fallback_client 为老号(回退下载)
        self.messaging_client: Optional[TelegramClient] = None
        self.fallback_client: Optional[TelegramClient] = None
        # 「用老号重试」登记表：token -> {link, chat_id, status_msg_id, ts}
        self.retry_registry: Dict[str, Dict[str, Any]] = {}
        # 可选：文件管理器引用，下载完成后失效其列表缓存（由 bot 注入）
        self.file_manager = None

        # 启动时扫描残留的 .downloading 文件
        self._scan_residual_downloading_files()
    
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

    def _scan_residual_downloading_files(self) -> None:
        """扫描残留的 .downloading 文件并记录警告日志."""
        base_dir = config.DOWNLOAD_PATH
        if not os.path.exists(base_dir):
            return

        for root, _, filenames in os.walk(base_dir):
            for fn in filenames:
                if fn.endswith('.downloading'):
                    # 尝试从文件名中提取 download_id
                    parts = fn.rsplit('.', 2)  # 拆成 filename.id.downloading
                    download_id = parts[-2] if len(parts) >= 3 else 'unknown'
                    full_path = os.path.join(root, fn)
                    logger.warning(
                        f"发现未完成的下载残留文件: {full_path} "
                        f"(download_id: {download_id})。如需清理请使用 /cleanup 命令。"
                    )

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
        # 净化文件名，防止路径穿越（Telegram 文件名可能含 ../ 或绝对路径）
        filename = sanitize_filename(filename)

        today = datetime.now().strftime('%Y%m%d')
        download_path = os.path.join(config.DOWNLOAD_PATH, today)
        os.makedirs(download_path, exist_ok=True)

        # 生成下载中文件名：{原文件名}.{download_id}.downloading
        temp_filename = f"{filename}.{download_id}.downloading"
        file_path = os.path.join(download_path, temp_filename)
        relative_path = os.path.relpath(file_path, config.DOWNLOAD_PATH)

        key = download_id
        download_info = DownloadInfo(
            download_id=download_id,
            filename=filename,          # 存纯净名（无后缀），用于展示
            path=file_path,             # 含 .downloading 后缀的完整路径
            relative_path=relative_path,
            status='downloading',
            chat_id=chat_id,
            status_msg_id=status_msg_id,
            message=message
        )
        # 立即登记占位：使 _get_active_count() 即时计入本任务，闭合
        # 「检查并发数 → 登记」之间的竞态（到这里为止无 await）
        self.active_downloads[key] = download_info

        # 刷新消息对象，获取最新的 file_reference，防止长时间闲置后过期
        try:
            refreshed = await client.get_messages(message.chat_id, ids=message.id)
            if refreshed and refreshed.media:
                message = refreshed
                download_info.message = message
                logger.debug(f"已刷新消息 file_reference: {filename}")
            else:
                logger.warning(f"消息刷新后无媒体内容，使用原始消息: {filename}")
        except Exception as e:
            logger.warning(f"消息刷新失败，使用原始消息: {e}")

        # 验证媒体类型：仅支持 MessageMediaDocument（实际文件），拒绝 WebPage 等不可下载类型
        if not isinstance(message.media, MessageMediaDocument):
            media_type = type(message.media).__name__
            logger.warning(f"不支持的媒体类型 {media_type}，跳过下载: {filename}")
            del self.active_downloads[key]
            await self._safe_edit_message(
                client, chat_id, status_msg_id,
                f"⚠️ **无法下载**\n\n"
                f"**文件:** `{filename}`\n"
                f"**原因:** 媒体类型 `{media_type}` 不是可下载的文件。\n"
                f"请确保发送的是实际文件链接，而非网页预览。"
            )
            return None

        await self._safe_edit_message(
            client, chat_id, status_msg_id,
            f"⏬ Downloading: `{filename}`\n"
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

                    # 去掉 .downloading 后缀，调用 _get_unique_filepath() 生成最终文件名
                    base_name = filename
                    final_path = await self._get_unique_filepath(download_path, base_name)
                    final_filename = os.path.basename(final_path)
                    final_relative = os.path.relpath(final_path, config.DOWNLOAD_PATH)

                    # 如果临时路径和最终路径不同，执行重命名
                    if file_path != final_path:
                        shutil.move(file_path, final_path)
                        logger.info(f"Renamed: {os.path.basename(file_path)} -> {final_filename}")

                    # 更新 DownloadInfo
                    info.filename = final_filename
                    info.path = final_path
                    info.relative_path = final_relative
                    info.status = 'completed'
                    info.size = file_size
                    info.downloaded = file_size

                    await self._send_completion_message(
                        client, chat_id, status_msg_id, final_relative, file_size
                    )

                    logger.info(f"Download completed: {final_filename}, ID: {download_id}")

                    # 新文件落盘后失效文件列表缓存，使 /list 立刻可见
                    if self.file_manager is not None:
                        self.file_manager._invalidate_cache()
            
            return download_id
            
        except asyncio.CancelledError:
            logger.info(f"Download cancelled: {filename}, ID: {download_id}")
            await self._safe_edit_message(
                client, chat_id, status_msg_id,
                f"🛑 Download cancelled: `{filename}`"
            )
            self._cleanup_partial_file(file_path)
            return None
            
        except Exception as e:
            logger.error(f"Download error: {e}", exc_info=True)
            if key in self.active_downloads:
                self.active_downloads[key].status = 'failed'
            self._cleanup_partial_file(file_path)
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
        """下载文件，包含重试逻辑、连接恢复和 File Reference 刷新。
        
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
                # 非首次重试时，仅刷新 file_reference（绝不断开共享连接！）
                if attempt > 0:
                    logger.info(f"重试前刷新 file_reference (attempt {attempt + 1}/{self.max_retries})")
                    try:
                        refreshed = await client.get_messages(message.chat_id, ids=message.id)
                        if refreshed and refreshed.media:
                            message = refreshed
                            logger.debug("重试前已刷新消息 file_reference")
                    except Exception as ref_err:
                        logger.warning(f"重试前刷新消息失败: {ref_err}")

                download_task = asyncio.create_task(
                    client.download_media(
                        message,
                        file_path,
                        progress_callback=lambda d, t: self._progress_callback(d, t, download_id)
                    )
                )
                
                if download_id in self.active_downloads:
                    self.active_downloads[download_id].task = download_task
                
                try:
                    # 加入超时控制，防止无限卡死
                    result = await asyncio.wait_for(download_task, timeout=config.DOWNLOAD_TIMEOUT)
                except asyncio.TimeoutError:
                    if not download_task.done():
                        download_task.cancel()
                    logger.error(f"下载超时: 耗时超过 {config.DOWNLOAD_TIMEOUT} 秒")
                    raise Exception(f"下载失败 - 超时 (超过 {config.DOWNLOAD_TIMEOUT} 秒)")
                
                # 增强诊断：download_media 返回 None
                if result is None:
                    peer_id = getattr(message, 'peer_id', None)
                    chat_info = getattr(peer_id, 'channel_id', getattr(peer_id, 'chat_id', 'unknown')) if peer_id else 'unknown'
                    logger.warning(
                        f"download_media 返回 None | "
                        f"media 类型: {type(message.media).__name__} | "
                        f"chat: {chat_info} | "
                        f"fwd_from: {message.fwd_from is not None} | "
                        f"noforwards: {getattr(message, 'noforwards', 'N/A')} | "
                        f"attempt: {attempt + 1}/{self.max_retries}"
                    )
                    raise Exception("下载失败 - download_media 返回 None")
                
                if not os.path.exists(result):
                    raise Exception(f"下载失败 - 文件未保存到: {result}")
                
                return result
                
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
                # 加大退避时间：5s, 10s, 20s, 30s
                wait_time = min(5 * (2 ** attempt), 30)
                logger.warning(f"下载尝试 {attempt + 1} 失败: {e}，{wait_time}s 后重试...")
                await asyncio.sleep(wait_time)
        
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
    
    def register_retry(self, link: str, chat_id: int, status_msg_id: int) -> str:
        """登记一次「用老号重试」，返回短 token 供按钮回调取回。顺带清理过期条目。"""
        now = time.time()
        # 清理 1 小时前的陈旧登记
        for t in [t for t, v in self.retry_registry.items() if now - v.get('ts', 0) > 3600]:
            del self.retry_registry[t]

        token = uuid.uuid4().hex[:8]
        self.retry_registry[token] = {
            'link': link,
            'chat_id': chat_id,
            'status_msg_id': status_msg_id,
            'ts': now,
        }
        return token

    async def retry_download_via_fallback(self, token: str) -> bool:
        """按 token 用回退客户端（老号）重下登记的链接。token 不存在返回 False。"""
        entry = self.retry_registry.pop(token, None)
        if entry is None:
            return False

        if self.fallback_client is None:
            await self._safe_edit_message(
                self.messaging_client, entry['chat_id'], entry['status_msg_id'],
                "❌ 未配置老号（SESSION_STRING），无法用用户账号重试。"
            )
            return True

        await self._safe_edit_message(
            self.messaging_client, entry['chat_id'], entry['status_msg_id'],
            "🔁 正在用老号重试下载..."
        )
        # 老号作为下载客户端；进度/消息仍经 messaging_client（@bot）发送
        await self.process_telegram_link(
            self.fallback_client, entry['link'], entry['chat_id'], entry['status_msg_id']
        )
        return True

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
        match = re.search(r't\.me/(c/)?([a-zA-Z0-9_]+)/(\d+)(?:\?comment=(\d+))?', link)
        if not match:
            await self._safe_edit_message(
                client, chat_id, status_msg_id,
                "❌ Invalid Telegram link format"
            )
            return None

        is_private, channel, message_id, comment_id = match.groups()
        message_id = int(message_id)
        comment_id = int(comment_id) if comment_id else None

        try:
            # 私有频道链接 (t.me/c/<id>/<msg>)：数字 ID 需构造 PeerChannel，不能当用户名解析
            # 注意：仅 User 模式且账号是该频道成员时可访问（Bot 模式无法访问私有频道）
            if is_private:
                entity = PeerChannel(int(channel))
            else:
                entity = await client.get_entity(channel)

            if comment_id is not None:
                # 评论链接 (?comment=N)：目标文件在频道关联讨论群的第 N 条消息，
                # 需先由频道帖子解析出讨论群，再取该评论消息（同样需 User 模式且有权访问）
                message = await self._get_comment_message(client, entity, message_id, comment_id)
                if message is None:
                    await self._safe_edit_message(
                        client, chat_id, status_msg_id,
                        "❌ 无法定位评论内容（该帖可能未开启评论，或账号无权访问讨论群）"
                    )
                    return None
            else:
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
    
    async def _get_comment_message(
        self,
        client: TelegramClient,
        channel_entity,
        post_id: int,
        comment_id: int
    ) -> Optional[Message]:
        """解析频道帖子的关联讨论群，返回该评论 (comment_id) 对应的消息对象。

        通过 GetDiscussionMessageRequest 由「频道 + 帖子号」定位讨论群，
        再按 comment_id 取讨论群里的具体评论消息。失败返回 None。
        """
        try:
            disc = await client(GetDiscussionMessageRequest(peer=channel_entity, msg_id=post_id))
            if not disc.messages:
                logger.warning(f"讨论群解析为空 (post={post_id})")
                return None
            group_peer = disc.messages[0].peer_id
            return await client.get_messages(group_peer, ids=comment_id)
        except Exception as e:
            logger.warning(f"解析评论消息失败 (post={post_id}, comment={comment_id}): {e}")
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
        else:
            min_progress = min(256 * 1024, (total or 1) * 0.01)
            significant = abs(downloaded - info.last_downloaded) >= min_progress
        
        if total and downloaded == total:
            significant = True
        
        if significant:
            info.downloaded = downloaded
            if total and total > 0:
                info.size = total
            
            # 当开始收到数据时，退出初始化阶段
            if info.initial_phase and downloaded > 0:
                info.initial_phase = False
            
            current_time = time.time()
            elapsed = current_time - info.last_update_time
            if elapsed >= 0.1:
                downloaded_since = downloaded - info.last_downloaded
                if elapsed > 0:
                    info.speed = downloaded_since / elapsed
                info.last_update_time = current_time
                info.last_downloaded = downloaded
    
    async def _update_progress(self, client: TelegramClient, download_id: str) -> None:
        """定期更新 Telegram 对话框中的进度消息。
        
        使用独立的 last_edit_time 追踪消息编辑时间，
        避免与速度计算的 last_update_time 互相干扰。
        FloodWait 恢复后采用动态退避策略，防止连环限流。
        """
        min_edit_interval = 5.0  # 编辑消息的最小时间间隔（秒）
        client = self.messaging_client or client  # 进度消息始终经主客户端发送
        try:
            while download_id in self.active_downloads:
                info = self.active_downloads[download_id]
                
                if info.status == 'downloading':
                    message = self._build_progress_message(info)
                    
                    if message != info.last_message:
                        current_time = time.time()
                        time_since_last_edit = current_time - info.last_edit_time
                        
                        if time_since_last_edit >= min_edit_interval:
                            try:
                                await client.edit_message(info.chat_id, info.status_msg_id, message)
                                info.last_message = message
                                info.last_edit_time = current_time
                                # 成功编辑后，逐步恢复正常间隔
                                min_edit_interval = max(5.0, min_edit_interval * 0.7)
                            except FloodWaitError as e:
                                logger.warning(f"FloodWaitError on progress update: {e.seconds}s pause required.")
                                await asyncio.sleep(e.seconds)
                                # FloodWait 恢复后，加大间隔防止连环触发
                                min_edit_interval = max(30.0, e.seconds * 0.3)
                                logger.info(f"FloodWait recovered. Next edit interval set to {min_edit_interval:.0f}s.")
                                continue
                            except Exception as e:
                                if "not modified" not in str(e).lower():
                                    logger.debug(f"Edit message failed: {e}")
                
                # 根据文件大小动态调整轮询间隔
                if info.initial_phase:
                    await asyncio.sleep(3)
                elif info.size > 500 * 1024 * 1024:
                    await asyncio.sleep(10)
                elif info.size > 100 * 1024 * 1024:
                    await asyncio.sleep(7)
                else:
                    await asyncio.sleep(5)
                    
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
        """安全地编辑消息（优先用消息客户端/主客户端），处理异常并在 FloodWait 后自动重试一次。"""
        client = self.messaging_client or client
        for attempt in range(2):  # 最多尝试 2 次（首次 + FloodWait 后重试 1 次）
            try:
                await client.edit_message(chat_id, msg_id, text)
                return True
            except FloodWaitError as e:
                logger.warning(f"FloodWaitError in safe edit message! Pausing for {e.seconds}s (attempt {attempt + 1}/2).")
                await asyncio.sleep(e.seconds + 2)  # 额外等 2 秒缓冲
                if attempt == 1:
                    return False
            except Exception as e:
                error_str = str(e).lower()
                if "not modified" not in error_str:
                    logger.warning(f"Failed to edit message: {e}")
                return False
        return False
