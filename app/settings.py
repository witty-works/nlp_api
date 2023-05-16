from typing import Optional, List
from pydantic import BaseSettings
from functools import lru_cache
import json
import base64


class Settings(BaseSettings):
    """Load environment variables to python objects using pydantic."""

    logging_enabled: bool = False
    logging_config_filename: str = "./logs/error.log"
    logging_config_level: str = "ERROR"
    platform_environment_type: str = "development"
    platform_environment: str = "local"
    languagetool_api: str = "https://lt.default.api.witty.works/v2"
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
    redis_username: Optional[str]
    redis_password: Optional[str]
    redis_default_user: Optional[str]
    redis_default_rules: Optional[str]
    redis_default_organization_rules: Optional[str]
    redis_verify_ssl: bool = True
    slack_signing_secret: Optional[str]
    slack_bot_token: Optional[str]
    slack_organization_id: Optional[str]
    alternatives_max_count: int = 5
    context_checker_url: Optional[str]
    context_checker_api_key: Optional[str]
    models: List = ["en_core_web_lg", "de_core_news_lg"]
    langs: List = ["en", "de"]
    language_endpoint_enabled_de: bool = False
    language_endpoint_enabled_en: bool = False
    language_endpoint_url_de: Optional[str]
    language_endpoint_url_en: Optional[str]
    language_endpoint_urls: Optional[dict]
    fasttext: bool = True

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    settings = Settings()
    settings.is_prod = settings.platform_environment_type == "production"

    settings.language_endpoint_urls = {
        "de": settings.language_endpoint_url_de,
        "en": settings.language_endpoint_url_en,
    }

    if settings.platform_relationships:
        settings.platform_relationships = json.loads(
            base64.b64decode(settings.platform_relationships)
        )

        for lang in settings.language_endpoint_urls:
            if lang not in settings.platform_relationships:
                continue

            endpoint = settings.platform_relationships[lang][0]
            settings.language_endpoint_urls[lang] = (
                "%(scheme)s://%(host)s:%(port)d" % endpoint
            )

        if "languagetool" in settings.platform_relationships:
            endpoint = settings.platform_relationships["languagetool"][0]
            settings.languagetool_api = "%(scheme)s://%(host)s:%(port)d/v2" % endpoint
            settings.languagetool_verify_ssl = False

    return settings
