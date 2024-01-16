from typing import Optional, List
from functools import lru_cache
import json
import base64
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.models import LangType
from platformshconfig import Config


class Settings(BaseSettings):
    """Load environment variables to python objects using pydantic."""

    logging_enabled: bool = False
    logging_config_filename: str = "./logs/error.log"
    logging_config_level: str = "ERROR"
    platform_environment_type: str = "development"
    platform_environment: str = "local"
    languagetool_api: str = "https://lt.default.api.witty.works/v2"
    languagetool_verify_ssl: bool = True
    platform_relationships: Optional[str] = ""
    api_docs_username: Optional[str] = ""
    api_docs_password: Optional[str] = ""
    api_docs_auth_enabled: bool = False
    instrumentation_key: str = ""
    testing: bool = False
    sentry_dsn: Optional[str] = ""
    sentry_traces_sample_rate: float = 0.0
    sentry_sample_rate: float = 0.0
    sentry_profiles_sample_rate: float = 0.0
    text_max_length: int = 1000
    is_prod: bool = False
    terms_of_service: str = "https://www.witty.works/privacy"
    contact: str = "support@witty.works"

    aadb2c_tenant_id: Optional[str] = ""
    aadb2c_client_id: Optional[str] = ""
    aadb2c_policy: Optional[str] = ""
    aadb2c_domain: Optional[str] = ""
    aadb2c_expected_scope: Optional[str] = ""

    office_sso_tenant_id: Optional[str] = ""
    office_sso_client_id: Optional[str] = ""
    office_sso_expected_scope: Optional[str] = ""

    sso_configs: dict = {}

    redis_host: Optional[str] = ""
    redis_port: Optional[str] = ""
    redis_username: Optional[str] = ""
    redis_password: Optional[str] = ""
    redis_default_user: Optional[str] = ""
    redis_default_rules: Optional[str] = ""
    redis_default_organization_rules: Optional[str] = ""
    redis_verify_ssl: bool = True
    slack_signing_secret: Optional[str] = ""
    slack_bot_token: Optional[str] = ""
    slack_organization_id: Optional[str] = ""
    alternatives_max_count: int = 5
    context_checker: dict = {}
    context_checker_url: Optional[str] = ""
    context_checker_api_key: Optional[str] = ""
    context_checker_url_de: Optional[str] = ""
    context_checker_api_key_de: Optional[str] = ""
    models: List = ["en_core_web_lg", "de_core_news_lg"]
    fasttext: bool = True
    minimum_version_web_ext: Optional[str] = ""
    minimum_version_word_plugin: Optional[str] = ""
    minimum_versions: dict = {}
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    import_from_dump: bool = True
    log_missing_declension: bool = True


@lru_cache()
def get_settings():
    settings = Settings()
    settings.is_prod = settings.platform_environment_type == "production"

    settings.sso_configs = {
        "aadb2c": {
            "tenant_id": settings.aadb2c_tenant_id,
            "client_id": settings.aadb2c_client_id,
            "policy": settings.aadb2c_policy,
            "domain": settings.aadb2c_domain,
            "expected_scope": settings.aadb2c_expected_scope,
        },
        "office_sso": {
            "tenant_id": settings.office_sso_tenant_id,
            "client_id": settings.office_sso_client_id,
            "expected_scope": settings.office_sso_expected_scope,
        },
    }

    if settings.minimum_version_web_ext:
        settings.minimum_versions["web-ext"] = settings.minimum_version_web_ext

    if settings.minimum_version_word_plugin:
        settings.minimum_versions["word-plugin"] = settings.minimum_version_word_plugin

    if settings.context_checker_url and settings.context_checker_api_key:
        settings.context_checker[LangType.EN] = {
            "url": settings.context_checker_url,
            "api_key": settings.context_checker_api_key,
        }

    if settings.context_checker_url_de and settings.context_checker_api_key_de:
        settings.context_checker[LangType.DE] = {
            "url": settings.context_checker_url_de,
            "api_key": settings.context_checker_api_key_de,
        }

    if settings.platform_relationships:
        settings.platform_relationships = json.loads(
            base64.b64decode(settings.platform_relationships)
        )

        if "languagetool" in settings.platform_relationships:
            endpoint = settings.platform_relationships["languagetool"][0]
            settings.languagetool_api = "%(scheme)s://%(host)s:%(port)d/v2" % endpoint
            settings.languagetool_verify_ssl = False

    if (
        settings.platform_relationships
        and "rediscache" in settings.platform_relationships
    ):
        platform_config = Config()
        redis_credentials = platform_config.credentials("rediscache")

        settings.redis_host = redis_credentials["host"]
        settings.redis_port = redis_credentials["port"]
        settings.redis_verify_ssl = False

    return settings
