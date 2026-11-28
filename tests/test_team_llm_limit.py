"""The per-team limit on LLM requests per minute (Prompt._count_request), and
where a request's team and limit come from."""

import asyncio
import contextvars

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app import managed_keys
from app.config_manager import fetch_user_organization_configs
from app.main import app
from app.prompt import LlmUnavailable, Prompt, llm_error
from app.request_team import key_team, team_limit
from app.settings import Settings
from tests.test_llm_calls import answer


@pytest.fixture
def prompt(monkeypatch):
    calls = []

    async def acompletion(**kwargs):
        calls.append(kwargs)
        return answer("ok")

    monkeypatch.setattr("app.prompt.litellm.acompletion", acompletion)
    monkeypatch.setattr("app.prompt.time.time", lambda: 1_000_040.0)  # 20 s in

    def make(**settings):
        return Prompt(Settings(llm_model="openai/test", **settings), fakeredis.FakeStrictRedis())

    make.calls = calls
    return make


def run_as(team, limit, coroutine):
    """Run a coroutine in a context whose request belongs to `team`."""
    context = contextvars.copy_context()
    context.run(team_limit.set, (team, limit) if team else None)
    return context.run(asyncio.run, coroutine)


def test_team_limit_refuses_over_budget(prompt):
    llm = prompt()

    for _ in range(2):
        assert run_as("t1", 2, llm.handle("hi")) == "ok"
    with pytest.raises(LlmUnavailable) as refused:
        run_as("t1", 2, llm.handle("hi"))

    assert len(prompt.calls) == 2
    assert refused.value.retry_after == 40
    status, headers, message = llm_error(refused.value, "/test")
    assert (status, headers) == (503, {"Retry-After": "40"})
    assert "team" in message
    # Another team has its own budget.
    assert run_as("t2", 2, llm.handle("hi")) == "ok"


def test_no_team_limit_without_a_team(prompt):
    llm = prompt()

    for _ in range(5):
        assert run_as(None, None, llm.handle("hi")) == "ok"


def test_team_limit_applies_without_a_global_limit(prompt):
    llm = prompt(llm_max_requests_per_minute=0)

    run_as("t1", 1, llm.handle("hi"))
    with pytest.raises(LlmUnavailable):
        run_as("t1", 1, llm.handle("hi"))


def test_team_refusal_does_not_consume_global_budget(prompt):
    llm = prompt(llm_max_requests_per_minute=2)

    run_as("t1", 1, llm.handle("hi"))
    for _ in range(3):
        with pytest.raises(LlmUnavailable):
            run_as("t1", 1, llm.handle("hi"))

    # One of the two global requests is left for another team.
    assert run_as("t2", 5, llm.handle("hi")) == "ok"


def test_global_refusal_does_not_consume_team_budget(prompt):
    """Calls the deployment's limit refuses never reach the provider, so they
    leave the team's budget as it was for when the deployment frees up."""
    llm = prompt(llm_max_requests_per_minute=1)

    assert run_as("t1", 2, llm.handle("hi")) == "ok"
    for _ in range(3):
        with pytest.raises(LlmUnavailable) as refused:
            run_as("t1", 2, llm.handle("hi"))
        assert "LLM_MAX_REQUESTS_PER_MINUTE" in str(refused.value)

    assert int(llm.redis_db.get("llm_requests:team:t1:16667")) == 1


EMAIL = "jane@acme.example"


@pytest.fixture
def client(monkeypatch):
    with TestClient(app) as test_client:
        monkeypatch.setattr(app.state.context.settings, "api_key_hmac_key", "a-secret")
        test_client.post(
            "/organization/configs",
            json={"id": "team-a", "name": "A", "config": {}, "llm_requests_per_minute": 7},
        )
        test_client.post("/organization/configs", json={"id": "team-b", "name": "B", "config": {}})
        test_client.post(
            "/user/configs",
            json={"id": "jane", "name": "Jane", "email": EMAIL, "config": {},
                  "organization_id": "team-a", "teams": ["team-a", "team-b"]},
        )
        yield test_client
        db = app.state.context.redis.db
        for pattern in ("managed_key*", "dashboard-organization:team-*"):
            for name in list(db.scan_iter(pattern)):
                db.delete(name)
        db.delete(app.state.context.redis.get_user_id(EMAIL))


def configs_in(team_of_key):
    """The team limit a request ends up with, for a key of `team_of_key`
    (None: a request without a managed key, as OAuth sends)."""
    async def resolve():
        key_team.set(team_of_key)
        await fetch_user_organization_configs(EMAIL, app.state.context, True)
        return team_limit.get()

    return contextvars.copy_context().run(asyncio.run, resolve())


def test_oauth_and_key_requests_share_the_team_budget(client):
    assert configs_in(None) == ("team-a", 7)
    assert configs_in("team-a") == ("team-a", 7)


def test_team_without_limit_sets_none(client):
    assert configs_in("team-b") is None


def test_limit_must_be_positive(client):
    response = client.post(
        "/organization/configs",
        json={"id": "team-c", "name": "C", "config": {}, "llm_requests_per_minute": 0},
    )

    assert response.status_code == 422
