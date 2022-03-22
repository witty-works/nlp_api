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

    if settings.redis_default_rules:
        organization_object = json.loads(settings.redis_default_rules)
        redis.set("witty.works", settings.redis_default_rules)
        redis.set(organization_object["users"][0], "witty.works")

    return redis
