"""Configuration for marketing agent service."""

from typing import Optional

from pydantic_settings import BaseSettings


class MarketingSettings(BaseSettings):
    """Marketing agent settings."""

    # Database
    marketing_db_url: str = "postgresql://homelab:homelab@192.168.0.80:5432/homelab"

    # Ghost CMS
    ghost_url: str = "https://layer8.schuettken.net"
    ghost_admin_api_key: str = ""

    # Scout Engine
    searxng_url: str = "http://192.168.0.84:8080"
    nats_url: Optional[str] = None  # Optional: e.g., "nats://nats.default.svc.cluster.local:4222"
    scout_enabled: bool = True

    # Knowledge Graph (Neo4j)
    neo4j_url: str = "bolt://192.168.0.88:7687"  # LXC 340
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""  # Set via .env or secrets

    # Service
    marketing_port: int = 8210
    debug: bool = False
    log_level: str = "INFO"

    # LLM Configuration
    llm_provider: str = "ollama"  # ollama or openai
    llm_model: str = "llama3.1:8b"
    ollama_url: str = "http://192.168.0.23:11434"
    openai_api_key: str = ""

    # Draft Writer Configuration
    draft_max_words: int = 1800
    draft_min_words: int = 1000
    draft_generation_timeout: int = 120  # seconds

    # SynthesisOS Configuration
    synthesis_auto_publish: bool = False  # If True, publish directly; if False, create drafts only

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = MarketingSettings()
