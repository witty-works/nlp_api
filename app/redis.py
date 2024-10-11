from redis import Redis as RedisCache
from fakeredis import FakeStrictRedis
import json
from fastapi import Request, HTTPException

from app.settings import Settings
from app.models import MetricsType


"""Class to handle Redis setup and provide Redis connection."""


class Redis:
    settings: Settings
    db: RedisCache

    def __init__(self, settings: Settings, redis_db: RedisCache):
        self.settings = settings
        self.db = redis_db

    @staticmethod
    def factory(settings: Settings):
        """Set up and return a Redis connection."""
        if settings.redis_host:
            redis_db = RedisCache(
                host=settings.redis_host,
                port=settings.redis_port,
                username=settings.redis_username,
                password=settings.redis_password,
                ssl=settings.redis_verify_ssl,
                ssl_cert_reqs="none",
            )
        else:
            redis_db = FakeStrictRedis()

        return Redis(settings, redis_db)

    def get_user_id(self, email: str):
        return "dashboard-user-email:" + email.lower()

    async def fetch_organization_configs_from_redis(
        self,
        organization_id: str,
    ) -> dict:
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
        configs = self.db.get(self.get_user_id(email))
        if not configs:
            raise HTTPException(status_code=404, detail="User configs not found")

        return json.loads(configs)

    def store_metrics(
        self, request: Request, configs: dict, version: str | None, endpoint: str
    ):
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
