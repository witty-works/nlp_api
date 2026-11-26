"""Per-request state that follows a request into the LLM calls it makes."""

from contextvars import ContextVar

# The team of the managed key a request came with (app/managed_keys.py), which
# takes the place of the person's licence team for the request.
key_team: ContextVar[str | None] = ContextVar("key_team", default=None)
