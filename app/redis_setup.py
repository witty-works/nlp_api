from redis import Redis
from fakeredis import FakeStrictRedis
from app.settings import Settings

class RedisSetup:
    """Class to handle Redis setup and provide Redis connection."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def get_redis_connection(self):
        """Set up and return a Redis connection."""
        if self.settings.redis_host:
            try:
                return Redis(
                    host=self.settings.redis_host,
                    port=self.settings.redis_port,
                    username=self.settings.redis_username,
                    password=self.settings.redis_password,
                    ssl=self.settings.redis_verify_ssl,
                    ssl_cert_reqs="none",
                )
            except Exception as e:
                print(f"Error setting up Redis: {e}")

        return FakeStrictRedis()

def get_user_id(email: str):
    return "dashboard-user-email:" + email.lower()
