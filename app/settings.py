from typing import Optional
from functools import lru_cache
import json
import base64
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.models import LangType
from platformshconfig import Config


class Settings(BaseSettings):
    """Load environment variables into Python objects using Pydantic."""

    logging_enabled: bool = False
    logging_config_filename: str = "./logs/error.log"
    logging_config_level: str = "ERROR"
    platform_environment_type: str = "development"
    platform_environment: str = "local"
    languagetool_api: Optional[str] = "https://api.languagetoolplus.com/v2"
    languagetool_verify_ssl: bool = True
    languagetool_username: Optional[str] = ""
    languagetool_api_key: Optional[str] = ""
    platform_relationships: Optional[str] = ""
    api_docs_username: Optional[str] = ""
    api_docs_password: Optional[str] = ""
    # Guards /docs and the development helpers: /save_openapi_json, /lemmatize,
    # /tokenize, /parse-word-types and /debug/*. Separate from the switch below
    # because reading the schema and minting a credential are not the same
    # risk. (/openapi.json is served unguarded either way.)
    api_docs_auth_enabled: bool = False
    # Guards the endpoints that create or read credentials and configuration, or
    # act on a named user's behalf: /api_key, /user/configs,
    # /organization/configs, /user/logs, /settings, /lt and /v1.0/prompt.
    # Defaults to on so an unconfigured deployment is closed rather than open.
    management_auth_enabled: bool = True
    testing: bool = False
    sentry_dsn: Optional[str] = ""
    sentry_traces_sample_rate: float = 0.0
    sentry_sample_rate: float = 0.0
    sentry_profiles_sample_rate: float = 0.0
    text_max_length: int = 1000
    is_prod: bool = False
    terms_of_service: str = ""
    contact: str = ""

    aadb2c_tenant_id: Optional[str] = ""
    aadb2c_client_id: Optional[str] = ""
    aadb2c_policy: Optional[str] = ""
    aadb2c_domain: Optional[str] = ""
    aadb2c_expected_scope: Optional[str] = ""

    office_sso_client_id: Optional[str] = ""
    office_sso_expected_scope: Optional[str] = ""

    # Dashboard-issued access tokens (Laravel Passport). Unlike the Microsoft
    # issuers these carry neither a `tid` nor a B2C policy, so they are verified
    # against a plain JWKS document looked up by the token header's `kid`.
    dashboard_client_id: Optional[str] = ""
    dashboard_url: Optional[str] = ""
    dashboard_jwks_url: Optional[str] = ""
    dashboard_issuer: Optional[str] = ""
    dashboard_expected_scope: Optional[str] = ""

    sso_configs: dict[str, dict[str, Optional[str]]] = {}

    redis_host: Optional[str] = ""
    redis_port: Optional[str] = ""
    redis_username: Optional[str] = ""
    redis_password: Optional[str] = ""
    redis_log_emails: Optional[str] = ""
    redis_verify_ssl: bool = True
    api_key_hmac_key: Optional[str] = ""
    testing_api_key: Optional[str] = ""
    testing_email: Optional[str] = ""
    testing_rules: Optional[str] = ""
    testing_organization_rules: Optional[str] = ""

    # Dashboard-less deployments: users authenticate with an API key and there
    # is no SyncUserToNlpApi job to populate their config in Redis. When this is
    # enabled, such a user falls back to the defaults below instead of being
    # rejected with a 403.
    default_user_config_enabled: bool = False
    default_user_store_context: bool = True
    default_user_llm_alternatives: bool = False

    # Let a request decide `store_context` and `llm_alternatives` for itself. A
    # `force` rule in a synced user or organisation config still wins, and
    # `llm_access` below overrules both, so this only hands control to the
    # client where nothing else has an opinion. Off by default: with a
    # dashboard, those two are the dashboard's call.
    client_config_enabled: bool = False

    # Whether a request has to resolve to a user before any text is checked.
    # With it off the API answers anyone who can reach it, which is a deliberate
    # choice for a private deployment and a bad one for a public host.
    require_auth: bool = True

    slack_enabled: bool = False
    slack_signing_secret: Optional[str] = ""
    slack_bot_token: Optional[str] = ""
    slack_organization_id: Optional[str] = ""
    alternatives_max_count: int = 5

    # Context Checker Configuration
    context_checker_local: bool = False

    # Remote API configuration per language (used when local models unavailable)
    # Format: {"en": {"url": "...", "api_key": "..."}, "de": {...}, "fr": {...}}
    context_checker: dict[str, dict[str, str]] = {}

    models: list = [
        "en_core_web_lg",
        "de_core_news_lg",
        "fr_core_news_lg",
    ]
    minimum_version_web_ext: Optional[str] = ""
    minimum_version_word_plugin: Optional[str] = ""
    minimum_versions: dict[str, str] = {}
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    import_from_dump: bool = True
    log_missing_declension: bool = True
    log_metrics: Optional[bool] = False
    aws_region_name: Optional[str] = ""
    aws_key: Optional[str] = ""
    aws_secret_key: Optional[str] = ""
    aws_model_id: Optional[str] = "mistral.mixtral-8x7b-instruct-v0:1"

    def jwks_url(self) -> str:
        """Resolve the dashboard's JWKS document, RFC 8615 path by default."""
        if self.dashboard_jwks_url:
            return self.dashboard_jwks_url

        if not self.dashboard_url:
            raise ValueError(
                "DASHBOARD_CLIENT_ID is set but neither DASHBOARD_URL nor "
                "DASHBOARD_JWKS_URL is, so dashboard tokens cannot be verified"
            )

        return self.dashboard_url.rstrip("/") + "/.well-known/jwks.json"

    @staticmethod
    def factory():
        """Construct a fully initialized Settings instance.

        Populates derived fields (is_prod, minimum_versions,
        platform relationship overrides, and Redis credentials) based on
        environment variables and Platform.sh configuration.
        """
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
                "client_id": settings.office_sso_client_id,
                "expected_scope": settings.office_sso_expected_scope,
            },
        }

        if settings.dashboard_client_id:
            settings.sso_configs["dashboard"] = {
                "client_id": settings.dashboard_client_id,
                "jwks_url": settings.jwks_url(),
                # Passport does not emit an `iss` claim, so issuer verification
                # is opt-in: setting DASHBOARD_ISSUER turns it into a hard
                # requirement and tokens without the claim are then rejected.
                "issuer": settings.dashboard_issuer or None,
                "expected_scope": settings.dashboard_expected_scope or None,
            }

        if settings.minimum_version_web_ext:
            settings.minimum_versions["web-ext"] = settings.minimum_version_web_ext

        if settings.minimum_version_word_plugin:
            settings.minimum_versions["word-plugin"] = (
                settings.minimum_version_word_plugin
            )

        if settings.platform_relationships:
            settings.platform_relationships = json.loads(
                base64.b64decode(settings.platform_relationships)
            )

            if "languagetool" in settings.platform_relationships:
                endpoint = settings.platform_relationships["languagetool"][0]
                settings.languagetool_api = (
                    f"{endpoint['scheme']}://{endpoint['host']}:{endpoint['port']}/v2"
                )
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.factory()


def reset_settings_cache() -> None:
    """Clear the cached settings instance (primarily for tests)."""
    try:
        get_settings.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass
