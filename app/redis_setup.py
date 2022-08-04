from redis import Redis
from platformshconfig import Config
from fakeredis import FakeStrictRedis
import json


def set_up_redis(settings):
    platform_config = Config()
    if platform_config.is_valid_platform():
        try:
            redis_credentials = platform_config.credentials("rediscache")
            return Redis(redis_credentials["host"], redis_credentials["port"])
        except:
            pass

    redis = FakeStrictRedis()

    if settings.redis_default_rules:  # pragma: no cover
        rules = json.loads(settings.redis_default_rules)
        key = rules["id"]
        redis.set(key, settings.redis_default_rules)

    if settings.redis_default_1_1_rules:  # pragma: no cover
        organization_object = json.loads(settings.redis_default_1_1_rules)
        key = organization_object["id"]
        redis.set(key, settings.redis_default_1_1_rules)
        for user in organization_object["users"]:
            redis.set(user, key)

    if settings.redis_default_organization_rules:  # pragma: no cover
        organization_rules = json.loads(settings.redis_default_organization_rules)
        key = organization_rules["id"]
        redis.set(key, settings.redis_default_organization_rules)

    return redis
