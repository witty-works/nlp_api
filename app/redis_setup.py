from redis import Redis
from fakeredis import FakeStrictRedis
import json
from app.settings import Settings


def set_up_redis(settings: Settings):  # pragma: no cover
    if settings.redis_host:
        try:
            return Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                username=settings.redis_username,
                password=settings.redis_password,
                ssl=settings.redis_verify_ssl,
                ssl_cert_reqs="none",
            )
        except Exception as e:
            pass

    redis = FakeStrictRedis()

    if settings.redis_default_rules:
        rules = json.loads(settings.redis_default_rules)
        key = rules["email"]
        redis.set(key, settings.redis_default_rules)

    if settings.redis_default_organization_rules:
        organization_rules = json.loads(settings.redis_default_organization_rules)
        key = organization_rules["id"]
        redis.set(key, settings.redis_default_organization_rules)

    return redis
