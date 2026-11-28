from redis import Redis as RedisCache
from fakeredis import FakeStrictRedis
import json
from fastapi import Request, HTTPException

from app.settings import Settings
from app.models import MetricsType
import hmac
import hashlib
import re

# What set_api_key stores under when API_KEY_HMAC_KEY is set.
API_KEY_DIGEST = re.compile(r"[0-9a-f]{64}")


class Redis:
    """Redis helper that manages connections, metrics and API keys.

    Provides a thin wrapper around a Redis client with helpers for
    fetching/storing configs, metrics and API keys.
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
        falls back to an in-memory FakeStrictRedis.
        """
        if settings.redis_host:
            redis_db = RedisCache(
                host=settings.redis_host,
                port=settings.redis_port,
                username=settings.redis_username,
                password=settings.redis_password,
                # TLS, with the server's certificate checked: one that is not
                # can be impersonated by anyone on the way, who then reads the
                # keys, emails and configs. A private CA comes from
                # REDIS_SSL_CA_CERTS; without it, the system's.
                ssl=settings.redis_verify_ssl,
                ssl_cert_reqs="required",
                ssl_ca_certs=settings.redis_ssl_ca_certs or None,
                decode_responses=True,
                # RESP2, as before redis-py 8, which opens every connection
                # with HELLO 3 by default: Redis before 6 and some proxies
                # refuse that, and RESP3 changes the shape of some replies.
                protocol=2,
            )
        else:
            redis_db = FakeStrictRedis(decode_responses=True)

        redis = Redis(settings, redis_db)

        # A deployment that runs for one person has no dashboard to mint a key
        # and, without a Redis, nothing that would keep one. Writing it on every
        # start covers both, and is what makes the personal setup work without
        # borrowing the testing variables.
        if settings.default_api_key and settings.default_user_email:
            redis.set_api_key(settings.default_api_key, settings.default_user_email)

        return redis

    def get_user_id(self, email: str) -> str:
        """Generate a Redis key for a user by email."""
        return "dashboard-user-email:" + email.lower()

    def get_organization_key(self, organization_id: str) -> str:
        """The Redis key of an organisation's config. Prefixed, so an id sent
        to the management endpoints names an organisation and no other key."""
        return "dashboard-organization:" + organization_id

    def legacy_organization_configs(self, organization_id: str) -> str | None:
        """An organisation config stored under its bare id, as before the
        prefix: only a JSON object that names this id, so no other key can
        be read through it. `bin.migrate_organization_keys` moves them."""
        try:
            value = self.db.get(organization_id)
            if not isinstance(value, str):
                return None
            configs = json.loads(value)
        except Exception:
            return None
        if isinstance(configs, dict) and str(configs.get("id")) == organization_id:
            return value

        return None

    def set_organization_configs(self, organization_id: str, value: str) -> None:
        self.db.set(self.get_organization_key(organization_id), value)
        if self.legacy_organization_configs(organization_id) is not None:
            self.db.delete(organization_id)

    def delete_organization_configs(self, organization_id: str) -> None:
        self.db.delete(self.get_organization_key(organization_id))
        if self.legacy_organization_configs(organization_id) is not None:
            self.db.delete(organization_id)

    def has_organization_configs(self, organization_id: str) -> bool:
        """Whether an organisation config is stored, where
        fetch_organization_configs_from_redis would find it."""
        return bool(
            self.db.exists(self.get_organization_key(organization_id))
            or self.legacy_organization_configs(organization_id)
        )

    async def fetch_organization_configs_from_redis(
        self,
        organization_id: str,
    ) -> dict:
        """Fetch organization configurations from Redis by organization ID."""
        configs = self.db.get(
            self.get_organization_key(organization_id)
        ) or self.legacy_organization_configs(organization_id)
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
        """Store API usage metrics in Redis by user and host."""
        if not self.settings.log_metrics:
            return

        version = version + " - " if version is not None else "none - "

        user_id = configs["id"] if "id" in configs else "none"
        host = request.headers.get("origin", "none")

        if endpoint == "auth":
            self.db.hincrby(MetricsType.AUTH_COUNTS, version + user_id, 1)
            self.db.hincrby(MetricsType.AUTH_HOST, version + host, 1)
        elif endpoint == "check":
            self.db.hincrby(MetricsType.CHECK_COUNTS, version + user_id, 1)
            self.db.hincrby(MetricsType.CHECK_HOST, version + host, 1)
        elif endpoint == "rephrase":
            self.db.hincrby(MetricsType.REPHRASE_COUNTS, version + user_id, 1)
            self.db.hincrby(MetricsType.REPHRASE_HOST, version + host, 1)
        elif endpoint == "write":
            self.db.hincrby(MetricsType.WRITE_COUNTS, version + user_id, 1)
            self.db.hincrby(MetricsType.WRITE_HOST, version + host, 1)
        elif endpoint == "guardrail_input":
            self.db.hincrby(MetricsType.GUARDRAIL_INPUT_COUNTS, version + user_id, 1)
            self.db.hincrby(MetricsType.GUARDRAIL_INPUT_HOST, version + host, 1)
        elif endpoint == "guardrail_output":
            self.db.hincrby(MetricsType.GUARDRAIL_OUTPUT_COUNTS, version + user_id, 1)
            self.db.hincrby(MetricsType.GUARDRAIL_OUTPUT_HOST, version + host, 1)

    def _hash_api_key(self, api_key: str) -> str:
        """HMAC-SHA256 hash an API key using the configured secret.

        Returns an empty string when no secret is configured, which the callers
        read as "store and look keys up verbatim".
        """
        if not self.settings.api_key_hmac_key:
            return ""

        return hmac.new(
            self.settings.api_key_hmac_key.encode("utf-8"),
            api_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def get_api_key_email(self, api_key: str) -> str | None:
        """The email an API key resolves to, looked up by its HMAC digest when
        API_KEY_HMAC_KEY is set and as written otherwise. With the secret set,
        an entry stored as written does not resolve: Redis must not hold a
        working credential in clear (`bin/api_key.py rehash` converts them).
        """
        return self.db.get(self.api_key_name(api_key))

    def count_plaintext_api_keys(self) -> int:
        """How many API keys Redis holds as written rather than as a digest.

        An entry named like a digest is counted as one: only a key of 64 hex
        characters stored before API_KEY_HMAC_KEY was set looks the same."""
        return sum(
            1
            for name in self.db.scan_iter("api_key:*")
            if not API_KEY_DIGEST.fullmatch(str(name).removeprefix("api_key:"))
        )

    def api_key_name(self, api_key: str) -> str:
        """The Redis entry a key is stored under by set_api_key."""
        return "api_key:" + (self._hash_api_key(api_key) or api_key)

    def set_api_key(
        self, api_key: str, email: str, remove_plaintext: bool = False, db=None
    ) -> None:
        """Store an API key mapping. If HMAC secret exists, store under hashed key.

        If `remove_plaintext` is True, also remove the plaintext key. `db` is a
        pipeline to write through instead of the connection.
        """
        db = self.db if db is None else db
        hashed = self._hash_api_key(api_key)
        if hashed:
            db.set("api_key:" + hashed, email)
            if remove_plaintext:
                db.delete("api_key:" + api_key)
            return

        # No secret configured: store plaintext
        db.set("api_key:" + api_key, email)

    def delete_api_key(self, api_key: str) -> None:
        """Delete an API key mapping. Attempts both hashed and plaintext keys."""
        hashed = self._hash_api_key(api_key)
        if hashed:
            self.db.delete("api_key:" + hashed)

        # Always attempt to delete plaintext key as well
        self.db.delete("api_key:" + api_key)
