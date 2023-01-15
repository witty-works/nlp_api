from redis import Redis
from platformshconfig import Config
from fakeredis import FakeStrictRedis
import json


def set_up_redis(settings):  # pragma: no cover
    if settings.platform_relationships and "rediscache" in settings.platform_relationships:
        platform_config = Config()
        redis_credentials = platform_config.credentials("rediscache")

        settings.redis_host = redis_credentials["host"]
        settings.redis_port = redis_credentials["port"]

    if settings.redis_host:
        try:
            return Redis(host=settings.redis_host, port=settings.redis_port)
        except Exception as e:
            pass

    redis = FakeStrictRedis()

    if settings.redis_default_rules:
        rules = json.loads(settings.redis_default_rules)
        key = rules["email"]
        redis.set(key, settings.redis_default_rules)

    if settings.redis_default_1_1_rules:
        organization_object = json.loads(settings.redis_default_1_1_rules)
        key = organization_object["id"]
        redis.set(key, settings.redis_default_1_1_rules)
        for user in organization_object["users"]:
            redis.set(user, key)

    if settings.redis_default_organization_rules:
        organization_rules = json.loads(settings.redis_default_organization_rules)
        key = organization_rules["id"]
        redis.set(key, settings.redis_default_organization_rules)

    return redis
