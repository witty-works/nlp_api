# https://github.com/425show/fastapi_microsoft_identity/blob/e98f1ff4a86e436b2d6d874738ff655fe1a63e54/LICENSE
""" The MIT License (MIT)

Copyright (c) 2021 Christos Matskas

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
 """

from fastapi import Request
import jwt
import rsa as pyrsa
import rsa.pem as pyrsa_pem
import base64
import struct


class AuthError(Exception):
    def __init__(self, error_msg: str, status_code: int):
        super().__init__(error_msg)

        self.error_msg = error_msg
        self.status_code = status_code


def get_token_auth_header(request: Request):
    auth = request.headers.get("Authorization", None)
    return get_token_(auth)


def get_unverified_token_claims(request: Request):
    token = get_token_auth_header(request)
    return get_unverified_token_claims_(token)


async def get_rsa_key(redis, session, token, url):
    unverified_header = jwt.get_unverified_header(token)
    key = "rsa_pem:" + unverified_header["kid"]
    rsa_key = redis.get(key)
    if rsa_key:
        return rsa_key

    rsa_key = await get_rsa_key_(session, unverified_header["kid"], url)

    redis.set(key, rsa_key)

    return rsa_key


async def decode_b2c_jwt(
    redis,
    session,
    request: Request,
    tenant_id: str,
    client_id: str,
    scope: str,
    b2c_domain_name: str,
    b2c_policy_name: str,
):
    token = get_token_auth_header(request)
    issuer = f"https://{b2c_domain_name}.b2clogin.com/{tenant_id}/v2.0/".lower()
    audience = client_id

    key_url = f"https://{b2c_domain_name}.b2clogin.com/{b2c_domain_name}.onmicrosoft.com/{b2c_policy_name}/discovery/v2.0/keys"
    rsa_key = await get_rsa_key(redis, session, token, key_url)

    return decode_jwt_(token, rsa_key, issuer, audience, scope)


async def decode_jwt(
    redis, session, request: Request, tenant_id: str, client_id: str, scope: str
):
    token = get_token_auth_header(request)
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    audience = f"{client_id}"

    key_url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    rsa_key = await get_rsa_key(redis, session, token, key_url)

    return decode_jwt_(token, rsa_key, issuer, audience, scope)


def decode_jwt_(
    token: str,
    rsa_key: dict,
    issuer: str,
    audience: str,
    scope: str,
):
    try:
        claims = jwt.decode(
            token, rsa_key, algorithms=["RS256"], audience=audience, issuer=issuer
        )
    except jwt.ExpiredSignatureError:
        raise AuthError("Token error: The token has expired", 401)
    except jwt.InvalidIssuerError:
        raise AuthError("Token error: Please check the issuer", 401)
    except jwt.InvalidAudienceError:
        raise AuthError("Token error: Please check the audience", 401)
    except jwt.InvalidIssuedAtError:
        raise AuthError("Token error: iat claim is not a number", 401)
    except Exception:
        raise AuthError("Token error: Unable to parse authentication", 401)

    validate_scope_(scope, claims)

    return claims


def validate_scope_(required_scope: str, claims: dict):
    ## check to ensure that either a valid scope is present in the token
    if claims.get("scp") is None:
        raise AuthError(
            "IDW10201: No scope was found in the bearer token",
            403,
        )

    if not claims.get("scp"):
        raise AuthError("IDW10201: No scope claim was found in the bearer token", 403)

    # the scp claim is a space delimited string
    token_scopes = claims["scp"].split()
    for token_scope in token_scopes:
        if token_scope.lower() == required_scope.lower():
            return True

    raise AuthError(
        f'IDW10203: The "scope" or "scp" claim does not contain scopes {required_scope} or was not found',
        403,
    )


def get_token_(auth: str):
    if not auth:
        raise AuthError("Authentication error: Authorization header is missing", 401)

    parts = auth.split()

    if parts[0].lower() != "bearer":
        raise AuthError(
            "Authentication error: Authorization header must start with ' Bearer'", 401
        )
    elif len(parts) == 1:
        raise AuthError("Authentication error: Token not found", 401)
    elif len(parts) > 2:
        raise AuthError(
            "Authentication error: Authorization header must be 'Bearer <token>'", 401
        )

    token = parts[1]
    return token


def get_unverified_token_claims_(token: str):
    return jwt.decode(token, options={"verify_signature": False})


# Copied from https://github.com/mpdavis/python-jose/blob/master/jose/utils.py - MIT License
def int_arr_to_long(arr):
    return int("".join(["%02x" % byte for byte in arr]), 16)


# Copied from https://github.com/mpdavis/python-jose/blob/master/jose/utils.py - MIT License
def base64_to_long(data):
    if isinstance(data, str):
        data = data.encode("ascii")

    # urlsafe_b64decode will happily convert b64encoded data
    _d = base64.urlsafe_b64decode(bytes(data) + b"==")
    return int_arr_to_long(struct.unpack("%sB" % len(_d), _d))


# Inspired by https://github.com/mpdavis/python-jose/blob/master/jose/backends/rsa_backend.py - MIT License
def convert_to_pem(n, e):
    rsa_key = pyrsa.PublicKey(e=base64_to_long(e), n=base64_to_long(n))
    der = rsa_key.save_pkcs1(format="DER")
    return pyrsa_pem.save_pem(der, pem_marker="RSA PUBLIC KEY")


async def get_rsa_key_(session, kid, url):
    async with session.get(url) as r:
        if r.status != 200:  # pragma: no cover
            error = await r.text()
            raise AuthError("Fetching RSA key resulted: " + error, 400)

        jwks = await r.json()
        for key in jwks["keys"]:
            if key["kid"] == kid:
                return convert_to_pem(key["n"], key["e"])

    raise AuthError("Unable to fetch RSA key", 400)
