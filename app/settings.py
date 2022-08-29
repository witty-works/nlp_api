from typing import Optional, List
from pydantic import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Load environment variables to python objects using pydantic."""

    logging_enabled: bool = False
    logging_config_filename: str = "./logs/error.log"
    logging_config_level: str = "ERROR"
    platform_environment_type: str = "development"
    platform_environment: str = "local"
    languagetool_api: Optional[str]
    languagetool_verify_ssl: bool = True
    platform_relationships: Optional[str]
    api_docs_username: Optional[str]
    api_docs_password: Optional[str]
    api_docs_auth_enabled: bool = False
    instrumentation_key: str = ""
    testing: bool = False
    sentry_dsn: Optional[str]
    sentry_traces_sample_rate: float = 0.2
    sentry_sample_rate: float = 0.2
    text_max_length: int = 1000
    learning_bites_base_url: str = "https://www.witty.works"
    is_prod: bool = False
    terms_of_service: str = "https://www.witty.works/privacy"
    contact: str = "support@witty.works"
    aadb2c_tenant_id: Optional[str]
    aadb2c_client_id: Optional[str]
    aadb2c_policy: Optional[str]
    aadb2c_domain: Optional[str]
    aadb2c_expected_scope: Optional[str]
    redis_host: Optional[str]
    redis_port: Optional[str]
    redis_default_user: Optional[str]
    redis_default_1_1_rules: Optional[str]
    redis_default_rules: Optional[str]
    redis_default_organization_rules: Optional[str]
    slack_signing_secret: Optional[str]
    slack_bot_token: Optional[str]
    slack_organization_id: Optional[str]

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    settings = Settings()
    settings.is_prod = settings.platform_environment_type == "production"
    return settings
