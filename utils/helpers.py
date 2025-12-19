"""Common utility functions shared across modules."""

from typing import Union


def format_size(size_bytes: Union[int, float]) -> str:
    """Format bytes to human-readable size string.
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        Human-readable size string (e.g., "1.5 MB")
    """
    if size_bytes < 0:
        return "0 B"
    
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    unit_index = 0
    size = float(size_bytes)
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    if unit_index == 0:
        return f"{int(size)} B"
    return f"{size:.1f} {units[unit_index]}"


def format_time(seconds: Union[int, float]) -> str:
    """Format seconds to human-readable time string.
    
    Args:
        seconds: Time in seconds
        
    Returns:
        Human-readable time string (e.g., "2 min 30 sec")
    """
    if seconds < 0:
        return "0 sec"
    
    seconds = int(seconds)
    
    if seconds < 60:
        return f"{seconds} sec"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes} min {secs} sec"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours} hr {minutes} min"


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and invalid characters.
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename safe for filesystem operations
    """
    import os
    import re
    
    # Get basename to prevent path traversal
    filename = os.path.basename(filename)
    
    # Remove or replace invalid characters
    # Windows invalid chars: < > : " / \ | ? *
    invalid_chars = r'[<>:"/\\|?*\x00-\x1f]'
    filename = re.sub(invalid_chars, '_', filename)
    
    # Remove leading/trailing dots and spaces
    filename = filename.strip('. ')
    
    # Ensure filename is not empty
    if not filename:
        filename = 'unnamed_file'
    
    return filename
