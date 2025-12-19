"""Configuration management for the Telegram File Bot."""

import os
import logging
from typing import List, Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()


class ConfigError(Exception):
    """Raised when configuration validation fails."""
    pass


class Config:
    """Application configuration container."""
    
    # Bot Credentials
    BOT_TOKEN: str = ""
    API_ID: int = 0
    API_HASH: str = ""
    
    # User Authorization
    ALLOWED_USERS: List[int] = []
    
    # Bot Settings
    DOWNLOAD_PATH: str = "downloads"
    MAX_CONCURRENT_DOWNLOADS: int = 5
    CACHE_TTL: int = 30
    UPDATE_INTERVAL: int = 1
    
    # Group Support
    ALLOW_GROUP_MESSAGES: bool = False
    
    # Auto Cleanup
    AUTO_CLEANUP_DAYS: int = 0
    
    # Retry Settings
    MAX_RETRIES: int = 3
    
    _validated: bool = False
    
    @classmethod
    def load(cls) -> None:
        """Load configuration from environment variables."""
        cls.BOT_TOKEN = os.getenv('BOT_TOKEN', '')
        cls.API_HASH = os.getenv('API_HASH', '')
        
        # Parse API_ID
        api_id_str = os.getenv('API_ID', '')
        if api_id_str:
            try:
                cls.API_ID = int(api_id_str)
            except ValueError:
                cls.API_ID = 0
        
        # Parse ALLOWED_USERS
        raw_allowed_users = os.getenv('ALLOWED_USERS', '')
        cls.ALLOWED_USERS = []
        if raw_allowed_users:
            for user_id in raw_allowed_users.split(','):
                user_id = user_id.strip()
                if user_id:
                    try:
                        cls.ALLOWED_USERS.append(int(user_id))
                    except ValueError:
                        logger.warning(f"Invalid user ID in ALLOWED_USERS: {user_id}")
        
        # Bot Settings
        cls.DOWNLOAD_PATH = os.getenv('DOWNLOAD_PATH', 'downloads')
        cls.MAX_CONCURRENT_DOWNLOADS = cls._parse_int('MAX_CONCURRENT_DOWNLOADS', 5)
        cls.CACHE_TTL = cls._parse_int('CACHE_TTL', 30)
        cls.UPDATE_INTERVAL = cls._parse_int('UPDATE_INTERVAL', 1)
        
        # Group Support
        cls.ALLOW_GROUP_MESSAGES = os.getenv('ALLOW_GROUP_MESSAGES', 'false').lower() == 'true'
        
        # Auto Cleanup
        cls.AUTO_CLEANUP_DAYS = cls._parse_int('AUTO_CLEANUP_DAYS', 0)
        
        # Retry Settings
        cls.MAX_RETRIES = cls._parse_int('MAX_RETRIES', 3)
    
    @classmethod
    def _parse_int(cls, env_var: str, default: int) -> int:
        """Safely parse an integer from environment variable.
        
        Args:
            env_var: Environment variable name
            default: Default value if parsing fails
            
        Returns:
            Parsed integer or default value
        """
        value = os.getenv(env_var, '')
        if not value:
            return default
        try:
            return int(value)
        except ValueError:
            logger.warning(f"Invalid integer for {env_var}: '{value}', using default: {default}")
            return default
    
    @classmethod
    def validate(cls) -> None:
        """Validate essential configuration variables.
        
        Raises:
            ConfigError: If required configuration is missing or invalid
        """
        if cls._validated:
            return
        
        # Load config first
        cls.load()
        
        missing_vars = []
        
        if not cls.BOT_TOKEN:
            missing_vars.append("BOT_TOKEN")
        if not cls.API_ID:
            missing_vars.append("API_ID")
        if not cls.API_HASH:
            missing_vars.append("API_HASH")
        
        if missing_vars:
            raise ConfigError(f"Missing essential environment variables: {', '.join(missing_vars)}")
        
        if not cls.ALLOWED_USERS:
            logger.warning(
                "ALLOWED_USERS is not set. The bot will not respond to anyone. "
                "Set ALLOWED_USERS to enable bot access."
            )
        
        if cls.MAX_CONCURRENT_DOWNLOADS < 1:
            logger.warning("MAX_CONCURRENT_DOWNLOADS must be at least 1, setting to 1")
            cls.MAX_CONCURRENT_DOWNLOADS = 1
        
        cls._validated = True
        logger.info("Configuration validated successfully")


# Create a singleton instance for backward compatibility
config = Config()


# Backward compatibility - expose as module-level variables
def _get_bot_token() -> str:
    return Config.BOT_TOKEN

def _get_api_id() -> int:
    return Config.API_ID

def _get_api_hash() -> str:
    return Config.API_HASH

def _get_allowed_users() -> List[int]:
    return Config.ALLOWED_USERS

def _get_download_path() -> str:
    return Config.DOWNLOAD_PATH

def _get_max_concurrent_downloads() -> int:
    return Config.MAX_CONCURRENT_DOWNLOADS


# For backward compatibility, load config on import
Config.load()

BOT_TOKEN = Config.BOT_TOKEN
API_ID = Config.API_ID
API_HASH = Config.API_HASH
ALLOWED_USERS = Config.ALLOWED_USERS
DOWNLOAD_PATH = Config.DOWNLOAD_PATH
MAX_CONCURRENT_DOWNLOADS = Config.MAX_CONCURRENT_DOWNLOADS
CACHE_TTL = Config.CACHE_TTL
UPDATE_INTERVAL = Config.UPDATE_INTERVAL
ALLOW_GROUP_MESSAGES = Config.ALLOW_GROUP_MESSAGES
AUTO_CLEANUP_DAYS = Config.AUTO_CLEANUP_DAYS
MAX_RETRIES = Config.MAX_RETRIES
