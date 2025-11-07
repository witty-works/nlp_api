"""Validation functions for API versions and client versions.

Also exposes typed version constants.
"""

from fastapi import HTTPException, status
from cmp_version import VersionString
from typing import Final, Literal

from app.models import Client


# Typed API version constants
CHECK_API_VERSION: Final[Literal["2.4"]] = "2.4"
REPHRASE_API_VERSION: Final[Literal["1.0"]] = "1.0"


def rephrase_api_version(version: str) -> None:
    if version != REPHRASE_API_VERSION:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"API version '{version}' not supported, please use version '{REPHRASE_API_VERSION}'."
            ),
        )


def check_api_version(version: str) -> None:
    if version != CHECK_API_VERSION:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"API version '{version}' not supported, please use version '{CHECK_API_VERSION}'."
            ),
        )


def client_version(
    client: Client, minimum_versions: dict[str, str] | None = None
) -> None:
    if not minimum_versions:
        return

    if client.name in minimum_versions and VersionString(
        client.version or "0.0.0"
    ) < VersionString(
        minimum_versions[client.name]
    ):  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Client version '{client.version}' not supported, please use at least '{minimum_versions[client.name]}'.",
        )
