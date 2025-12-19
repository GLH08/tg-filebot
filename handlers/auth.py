"""User authentication and authorization module."""

import logging

import config

logger = logging.getLogger(__name__)


def is_user_allowed(user_id: int) -> bool:
    """Check if a user is authorized to use the bot.
    
    Args:
        user_id: Telegram user ID to check
        
    Returns:
        True if user is allowed, False otherwise
    """
    if not config.ALLOWED_USERS:
        return False
    
    return user_id in config.ALLOWED_USERS


def is_chat_allowed(event) -> bool:
    """Check if the chat context is allowed for bot interaction.
    
    Args:
        event: Telethon event object
        
    Returns:
        True if chat is allowed, False otherwise
    """
    # Always allow private chats for authorized users
    if event.is_private:
        return is_user_allowed(event.sender_id)
    
    # Check group permission
    if config.ALLOW_GROUP_MESSAGES:
        return is_user_allowed(event.sender_id)
    
    return False


def get_user_display_name(event) -> str:
    """Get a display name for logging purposes.
    
    Args:
        event: Telethon event object
        
    Returns:
        User display string
    """
    sender_id = getattr(event, 'sender_id', 'unknown')
    return f"user:{sender_id}"
