from redis import Redis as RedisCache
from fakeredis import FakeStrictRedis
import json
from fastapi import Request, HTTPException
from pydantic import BaseModel
import datetime

from app.settings import Settings
from app.models import MetricsType, CheckRequestIn
import hmac
import hashlib


class Redis:
    """Redis helper that manages connections, metrics, and request logs.

    Provides a thin wrapper around a Redis client with helpers for
    fetching/storing configs, metrics, and per-user request/response logs.
    """

    settings: Settings
    db: RedisCache

    def __init__(self, settings: Settings, redis_db: RedisCache):
        self.settings = settings
        self.db = redis_db

    @staticmethod
    def factory(settings: Settings):
        """Create and return a Redis client based on settings.

        Uses a real Redis connection when redis_host is configured; otherwise
        falls back to an in-memory FakeStrictRedis. When testing_api_key is
        present, a test key is preloaded for convenience during local tests.
        """
        if settings.redis_host:
            redis_db = RedisCache(
                host=settings.redis_host,
                port=settings.redis_port,
                username=settings.redis_username,
                password=settings.redis_password,
                ssl=settings.redis_verify_ssl,
                ssl_cert_reqs="none",
                decode_responses=True,
            )
        else:
            redis_db = FakeStrictRedis(decode_responses=True)
            if settings.testing_api_key:
                redis_db.set(
                    "api_key:" + settings.testing_api_key, settings.testing_email
                )

        return Redis(settings, redis_db)

    def get_user_id(self, email: str) -> str:
        """Generate a Redis key for a user by email."""
        return "dashboard-user-email:" + email.lower()

    def get_log_id(self, user_email: str | None) -> str:
        """Generate a Redis key for user logs."""
        return "log-" + self.get_user_id(user_email if user_email else "none")

    def get_log_key(self, user_email: str | None) -> str | None:
        """Get the log key for a user if they are in the debug list."""
        key = self.get_log_id(user_email)
        if user_email is None:
            user_email = "none"

        debug_emails = self.db.lrange("debug_emails", 0, -1)
        return key if user_email.encode() in debug_emails else None

    async def fetch_organization_configs_from_redis(
        self,
        organization_id: str,
    ) -> dict:
        """Fetch organization configurations from Redis by organization ID."""
        configs = self.db.get(organization_id)
        if not configs:
            raise HTTPException(
                status_code=404, detail="Organization configs not found"
            )

        return json.loads(configs)

    async def fetch_user_configs_from_redis(
        self,
        email: str,
    ) -> dict:
        """Fetch user configurations from Redis by email."""
        configs = self.db.get(self.get_user_id(email))
        if not configs:
            raise HTTPException(status_code=404, detail="User configs not found")

        return json.loads(configs)

    def store_metrics(
        self, request: Request, configs: dict, version: str | None, endpoint: str
    ) -> None:
        """Store API usage metrics in Redis by user, plan, and host."""
        if not self.settings.log_metrics:
            return

        version = version + " - " if version is not None else "none - "

        if "id" in configs:
            user_id = configs["id"]
            plan = None if "plan" not in configs else configs["plan"]
            if (
                "organization_config" in configs
                and "trial_ends_at" in configs["organization_config"]
                and configs["organization_config"]["trial_ends_at"] is not None
            ):
                plan = "witty_trial"
        else:
            user_id = "none"
            plan = "none"

        host = request.headers.get("origin", "none")

        if endpoint == "auth":
            self.db.hincrby(MetricsType.AUTH_COUNTS, version + user_id, 1)
            self.db.hincrby(MetricsType.AUTH_PLANS, version + plan, 1)
            self.db.hincrby(MetricsType.AUTH_HOST, version + host, 1)
        elif endpoint == "check":
            self.db.hincrby(MetricsType.CHECK_COUNTS, version + user_id, 1)
            self.db.hincrby(MetricsType.CHECK_PLANS, version + plan, 1)
            self.db.hincrby(MetricsType.CHECK_HOST, version + host, 1)
        elif endpoint == "rephrase":
            self.db.hincrby(MetricsType.REPHRASE_COUNTS, version + user_id, 1)
            self.db.hincrby(MetricsType.REPHRASE_PLANS, version + plan, 1)
            self.db.hincrby(MetricsType.REPHRASE_HOST, version + host, 1)

    def get_user_logs(
        self,
        user_email: str | None,
    ) -> list:
        """Retrieve all logged requests/responses for a user."""
        results = []

        data = self.db.lrange(self.get_log_id(user_email), 0, -1)
        if data is not None:
            data.reverse()
            for result in data:
                result = json.loads(result)
                results.append(result)

        return results

    def store_request_log(
        self,
        check_request_in: CheckRequestIn,
        user_email: str | None,
        request: Request,
        configs: dict,
        version: str | None,
        endpoint: str,
    ) -> None:
        """Log a request to Redis for debugging purposes."""
        key = self.get_log_key(user_email)
        if key is None:
            return

        data = {
            "type": "request",
            "date": datetime.datetime.now().isoformat(),
            "plan": check_request_in.config.plan,
            "text": check_request_in.text,
            "auth_token": request.headers.get("Authorization", None),
            "configs": configs,
            "version": version,
            "endpoint": endpoint,
        }

        self.db.lpush(key, json.dumps(data))

    def store_response_log(
        self,
        user_email: str | None,
        results: BaseModel,
    ) -> None:
        """Log a response to Redis for debugging purposes."""
        key = self.get_log_key(user_email)
        if key is None:
            return

        data = {
            "type": "response",
            "results": results.model_dump(),
        }

        self.db.lpush(key, json.dumps(data))

    def _hash_api_key(self, api_key: str) -> str:
        """HMAC-SHA256 hash an API key using configured secret.

        Uses `settings.api_key_hmac_key` if present, otherwise `settings.secret_key`.
        If no secret is configured, return empty string.
        """
        secret = getattr(self.settings, "api_key_hmac_key", None) or getattr(
            self.settings, "secret_key", None
        )
        if not secret:
            return ""

        return hmac.new(
            secret.encode("utf-8"), api_key.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def get_api_key_email(self, api_key: str) -> str | None:
        """Retrieve the email associated with an API key.

        If HMAC secret is configured, the API key is HMACed before lookup.
        Falls back to plaintext lookup if no secret configured.
        """
        hashed = self._hash_api_key(api_key)
        if hashed:
            val = self.db.get("api_key:" + hashed)
            if val:
                return val

        # Fallback to plaintext lookup for backward compatibility
        return self.db.get("api_key:" + api_key)

    def set_api_key(
        self, api_key: str, email: str, remove_plaintext: bool = False
    ) -> None:
        """Store an API key mapping. If HMAC secret exists, store under hashed key.

        If `remove_plaintext` is True, also remove the plaintext key.
        """
        hashed = self._hash_api_key(api_key)
        if hashed:
            self.db.set("api_key:" + hashed, email)
            if remove_plaintext:
                self.db.delete("api_key:" + api_key)
            return

        # No secret configured: store plaintext
        self.db.set("api_key:" + api_key, email)

    def delete_api_key(self, api_key: str) -> None:
        """Delete an API key mapping. Attempts both hashed and plaintext keys."""
        hashed = self._hash_api_key(api_key)
        if hashed:
            self.db.delete("api_key:" + hashed)

        # Always attempt to delete plaintext key as well
        self.db.delete("api_key:" + api_key)
