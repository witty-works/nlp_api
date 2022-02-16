from typing import Optional, List
from pydantic import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Load environment variables to python objects using pydantic."""

    logging_enabled: bool = False
    logging_config_filename: str = "./logs/error.log"
    logging_config_level: str = "ERROR"
    platform_environment: str = "local"
    languagetool_api: Optional[str]
    languagetool_verify_ssl: bool = True
    platform_relationships: Optional[str]
    api_docs_username: Optional[str]
    api_docs_password: Optional[str]
    api_docs_auth_enabled: bool = False
    instrumentation_key: str = ""
    testing: bool = False
    maximum_text_length: int = 1000
    read_rules_from_redis: bool = False
    sentry_dsn: Optional[str]
    sentry_traces_sample_rate: float = 0.2
    sentry_sample_rate: float = 0.2
    text_max_length: int = 1000
    learning_bites_base_url: str = "https://www.witty.works"

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()
