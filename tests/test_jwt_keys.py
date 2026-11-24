"""How the keys that verify a token are found: by issuer and `kid`, fetched at
most once a minute for a `kid` the issuer does not have."""

import asyncio
import base64

import fakeredis
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth_service import AuthError, get_rsa_key, rsa_key_name
from app.redis import Redis
from app.settings import Settings

ISSUER_A = "https://a.example/.well-known/jwks.json"
ISSUER_B = "https://b.example/.well-known/jwks.json"


def b64(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Response:
    def __init__(self, jwks):
        self.status = 200
        self.headers = {}
        self.jwks = jwks

    async def json(self):
        return self.jwks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class Session:
    """An issuer's JWKS endpoint, counting the requests it gets."""

    def __init__(self, keys: dict):
        self.keys = keys
        self.requests = []

    async def get(self, url):
        self.requests.append(url)
        return Response({"keys": self.keys.get(url, [])})


@pytest.fixture
def redis():
    return Redis(
        Settings(_env_file=None), fakeredis.FakeStrictRedis(decode_responses=True)
    )


def key_pair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private.public_key().public_numbers()
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    return pem, {"kid": "k1", "kty": "RSA", "n": b64(numbers.n), "e": b64(numbers.e)}


def token(pem, kid="k1"):
    return jwt.encode({"exp": 2**31}, pem, algorithm="RS256", headers={"kid": kid})


def test_a_key_is_cached_per_issuer(redis):
    pem, jwk = key_pair()
    session = Session({ISSUER_A: [jwk], ISSUER_B: []})

    asyncio.run(get_rsa_key(redis, session, token(pem), ISSUER_A))
    assert redis.db.get(rsa_key_name(ISSUER_A, "k1"))

    # Issuer B has no k1 of its own: A's is not taken for it.
    with pytest.raises(AuthError):
        asyncio.run(get_rsa_key(redis, session, token(pem), ISSUER_B))
    assert session.requests == [ISSUER_A, ISSUER_B]


def test_an_unknown_kid_is_not_fetched_again_at_once(redis):
    pem, jwk = key_pair()
    session = Session({ISSUER_A: [jwk]})

    for _ in range(3):
        with pytest.raises(AuthError):
            asyncio.run(get_rsa_key(redis, session, token(pem, "junk"), ISSUER_A))

    assert session.requests == [ISSUER_A]


@pytest.mark.parametrize("kid", [None, "", "k" * 257])
def test_a_token_without_a_usable_kid_fetches_nothing(redis, kid):
    pem, jwk = key_pair()
    session = Session({ISSUER_A: [jwk]})
    headers = {} if kid is None else {"kid": kid}
    unkeyed = jwt.encode({"exp": 2**31}, pem, algorithm="RS256", headers=headers)

    with pytest.raises(AuthError):
        asyncio.run(get_rsa_key(redis, session, unkeyed, ISSUER_A))
    assert session.requests == []
