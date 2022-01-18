from redis import Redis
from platformshconfig import Config
from fakeredis import FakeStrictRedis


def set_up_redis(settings):
    platform_config = Config()
    if platform_config.is_valid_platform():
        redis_credentials = platform_config.credentials("rediscache")
        if redis_credentials:
            return Redis(redis_credentials["host"], redis_credentials["port"])

    return FakeStrictRedis()
