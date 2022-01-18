from redis import Redis
from platformshconfig import Config
from fakeredis import FakeStrictRedis


def set_up_redis(settings):
    platform_config = Config()
    if platform_config.is_valid_platform():
        try:
            redis_credentials = platform_config.credentials("rediscache")
            return Redis(redis_credentials["host"], redis_credentials["port"])
        except:
            pass

    return FakeStrictRedis()
