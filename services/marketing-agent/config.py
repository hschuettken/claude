"""Configuration for marketing agent service."""

from pydantic_settings import BaseSettings


class MarketingSettings(BaseSettings):
    """Marketing agent settings."""

    # Database
    marketing_db_url: str = "postgresql://homelab:homelab@192.168.0.80:5432/homelab"

    # Ghost CMS
    ghost_url: str = "https://layer8.schuettken.net"
    ghost_admin_api_key: str = ""

    # Service
    marketing_port: int = 8210
    debug: bool = False
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = MarketingSettings()
