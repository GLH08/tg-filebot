"""File management utilities for listing, renaming, and deleting downloaded files."""

import os
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from .helpers import format_size, sanitize_filename

logger = logging.getLogger(__name__)


class FileManager:
    """Manages downloaded files with caching and CRUD operations."""
    
    def __init__(self, base_dir: str = 'downloads', cache_ttl: int = 30):
        """Initialize the FileManager.
        
        Args:
            base_dir: Base directory for downloaded files
            cache_ttl: Cache time-to-live in seconds
        """
        self.base_dir = base_dir
        self._files_cache: Optional[List[Dict[str, Any]]] = None
        self._cache_time: float = 0
        self._cache_ttl = cache_ttl
    
    def list_files(
        self, 
        offset: int = 0, 
        limit: Optional[int] = None,
        search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List all downloaded files with optional pagination and search.
        
        Args:
            offset: Starting index for pagination
            limit: Maximum number of files to return
            search: Optional search string to filter files by name
            
        Returns:
            List of file info dictionaries
        """
        current_time = time.time()
        
        # Use cached results if available and fresh
        if self._files_cache is not None and current_time - self._cache_time < self._cache_ttl:
            files = self._files_cache
        else:
            files = self._scan_files()
            self._files_cache = files
            self._cache_time = current_time
        
        # Apply search filter
        if search:
            search_lower = search.lower()
            files = [f for f in files if search_lower in f['filename'].lower()]
        
        # Apply pagination
        if limit:
            return files[offset:offset + limit]
        elif offset:
            return files[offset:]
        return files
    
    def search_files(self, query: str) -> List[Dict[str, Any]]:
        """Search files by name.
        
        Args:
            query: Search query string
            
        Returns:
            List of matching file info dictionaries
        """
        return self.list_files(search=query)
    
    def _scan_files(self) -> List[Dict[str, Any]]:
        """Scan the downloads directory for files.
        
        Returns:
            List of file info dictionaries sorted by modification time
        """
        files: List[Dict[str, Any]] = []
        
        if not os.path.exists(self.base_dir):
            return files
        
        for root, _, filenames in os.walk(self.base_dir):
            for filename in filenames:
                full_path = os.path.join(root, filename)
                
                # Skip partial downloads or non-files
                if not os.path.isfile(full_path) or filename.endswith('.partial'):
                    continue
                
                relative_path = os.path.relpath(full_path, self.base_dir)
                
                try:
                    stat_info = os.stat(full_path)
                    size_bytes = stat_info.st_size
                    size = format_size(size_bytes)
                    modified_time = stat_info.st_mtime
                except OSError as e:
                    logger.warning(f"Failed to stat file {full_path}: {e}")
                    size = "Unknown"
                    size_bytes = 0
                    modified_time = 0
                
                files.append({
                    'full_path': full_path,
                    'relative_path': relative_path,
                    'filename': filename,
                    'size': size,
                    'size_bytes': size_bytes,
                    'modified_time': modified_time
                })
        
        # Sort by modification time (newest first)
        files.sort(key=lambda x: x['modified_time'], reverse=True)
        
        return files
    
    def get_file_by_index(self, index: int) -> Optional[Dict[str, Any]]:
        """Get file info by index.
        
        Args:
            index: Zero-based file index
            
        Returns:
            File info dictionary or None if not found
        """
        files = self.list_files()
        if 0 <= index < len(files):
            return files[index]
        return None
    
    def _is_safe_path(self, path: str) -> bool:
        """Check if a path is within the base directory.
        
        Args:
            path: Path to check
            
        Returns:
            True if path is safe, False otherwise
        """
        try:
            real_base = os.path.realpath(self.base_dir)
            real_path = os.path.realpath(path)
            return real_path.startswith(real_base + os.sep) or real_path == real_base
        except (OSError, ValueError):
            return False
    
    def rename_file(self, index: int, new_name: str) -> Dict[str, Any]:
        """Rename a file by its index.
        
        Args:
            index: Zero-based file index
            new_name: New filename
            
        Returns:
            Result dictionary with success status and message
        """
        # Sanitize the new name
        safe_new_name = sanitize_filename(new_name)
        if not safe_new_name or safe_new_name in ('.', '..'):
            return {'success': False, 'message': 'Invalid new name provided.'}
        
        files = self.list_files()
        
        if not files:
            return {'success': False, 'message': 'No files found'}
        
        if index < 0 or index >= len(files):
            return {'success': False, 'message': f'Invalid index: {index + 1}'}
        
        file_info = files[index]
        
        # Verify file is within base directory
        if not self._is_safe_path(file_info['full_path']):
            return {'success': False, 'message': 'Security error: invalid file path'}
        
        dir_name = os.path.dirname(file_info['full_path'])
        new_full_path = os.path.join(dir_name, safe_new_name)
        
        if os.path.exists(new_full_path):
            return {'success': False, 'message': f'Target file already exists: {safe_new_name}'}
        
        try:
            os.rename(file_info['full_path'], new_full_path)
            new_relative_path = os.path.relpath(new_full_path, self.base_dir)
            
            self._invalidate_cache()
            
            logger.info(f"Renamed file: {file_info['relative_path']} -> {new_relative_path}")
            
            return {
                'success': True,
                'new_path': new_full_path,
                'new_relative_path': new_relative_path
            }
        except OSError as e:
            logger.error(f"Failed to rename file: {e}")
            return {'success': False, 'message': str(e)}
    
    def delete_file(self, index: int) -> Dict[str, Any]:
        """Delete a file by its index.
        
        Args:
            index: Zero-based file index
            
        Returns:
            Result dictionary with success status and message
        """
        files = self.list_files()
        
        if not files:
            return {'success': False, 'message': 'No files found'}
        
        if index < 0 or index >= len(files):
            return {'success': False, 'message': f'Invalid index: {index + 1}'}
        
        file_info = files[index]
        
        # Verify file is within base directory
        if not self._is_safe_path(file_info['full_path']):
            return {'success': False, 'message': 'Security error: invalid file path'}
        
        try:
            os.remove(file_info['full_path'])
            self._invalidate_cache()
            
            logger.info(f"Deleted file: {file_info['relative_path']}")
            
            return {
                'success': True,
                'deleted_path': file_info['relative_path']
            }
        except OSError as e:
            logger.error(f"Failed to delete file: {e}")
            return {'success': False, 'message': str(e)}
    
    def cleanup_old_files(self, days: int) -> Dict[str, Any]:
        """Delete files older than specified days.
        
        Args:
            days: Number of days to keep files
            
        Returns:
            Result dictionary with count of deleted files
        """
        if days <= 0:
            return {'success': False, 'message': 'Days must be positive', 'deleted_count': 0}
        
        cutoff_time = datetime.now() - timedelta(days=days)
        cutoff_timestamp = cutoff_time.timestamp()
        
        files = self.list_files()
        deleted_count = 0
        errors = []
        
        for file_info in files:
            if file_info['modified_time'] < cutoff_timestamp:
                # Verify path is safe before deletion
                if not self._is_safe_path(file_info['full_path']):
                    errors.append(f"{file_info['filename']}: invalid path")
                    continue
                
                try:
                    os.remove(file_info['full_path'])
                    deleted_count += 1
                    logger.info(f"Auto-cleanup deleted: {file_info['relative_path']}")
                except OSError as e:
                    errors.append(f"{file_info['filename']}: {e}")
        
        if deleted_count > 0:
            self._invalidate_cache()
        
        # Clean up empty directories
        self._cleanup_empty_dirs()
        
        return {
            'success': True,
            'deleted_count': deleted_count,
            'errors': errors if errors else None
        }
    
    def _cleanup_empty_dirs(self) -> None:
        """Remove empty directories in the downloads folder."""
        if not os.path.exists(self.base_dir):
            return
        
        for root, dirs, files in os.walk(self.base_dir, topdown=False):
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                        logger.debug(f"Removed empty directory: {dir_path}")
                except OSError:
                    pass
    
    def _invalidate_cache(self) -> None:
        """Invalidate the file cache."""
        self._files_cache = None
        self._cache_time = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about downloaded files.
        
        Returns:
            Dictionary with file statistics
        """
        files = self.list_files()
        total_size = sum(f['size_bytes'] for f in files)
        
        return {
            'total_files': len(files),
            'total_size': format_size(total_size),
            'total_size_bytes': total_size
        }
