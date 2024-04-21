from redis import Redis
from fakeredis import FakeStrictRedis
from app.settings import Settings


def get_user_id(email: str):
    return "dashboard-user-email:" + email.lower()


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

    return FakeStrictRedis()
