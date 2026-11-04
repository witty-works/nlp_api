"""When an answer fails the guardrail: limits per level, as a count or a share
of the words checked, and set per API key."""

import pytest

from app.guardrail import failed_on, finding_level
from app.models import GuardrailThreshold, ResultOut
from tests.test_api import set_redis  # noqa: F401  (fixture)
from tests.test_api_keys import client, sync  # noqa: F401  (fixture)
from tests.test_guardrail import llm_calls, post  # noqa: F401  (fixture)

# old, lady: advanced (3.0); chairman: basic (2.0); six words.
MIXED = "The old lady called the chairman."
KEY = "guardrail-key-0123456789abcdef"


def finding(gravity, category="gender-orientation", alternatives=True):
    return ResultOut(
        text="x",
        text_id="x",
        start=0,
        end=1,
        category=category,
        gravity=gravity,
        alternatives=[{"text": "y"}] if alternatives else [],
    )


@pytest.mark.parametrize(
    "gravity, category, level",
    [
        (1.0, "gender-orientation", "openly_discriminating"),
        (2.0, "gender-orientation", "basic"),
        (3.0, "gender-orientation", "advanced"),
        (0.9, "corporate_rules", "corporate_rules"),
        (None, "gender-orientation", None),
    ],
)
def test_finding_level(gravity, category, level):
    assert finding_level(finding(gravity, category)) == level


def test_a_number_is_an_overall_count():
    threshold = GuardrailThreshold.parse(2)
    findings = [finding(2.0), finding(3.0)]

    assert failed_on(findings, 10, threshold) == ["overall"]
    assert failed_on(findings[:1], 10, threshold) == []


def test_findings_without_alternatives_do_not_count():
    threshold = GuardrailThreshold.parse(1)

    assert failed_on([finding(2.0, alternatives=False)], 10, threshold) == []


def test_count_and_ratio_per_level():
    threshold = GuardrailThreshold.parse(
        {"basic": {"count": 2}, "advanced": {"ratio": 0.2}}
    )
    findings = [finding(2.0), finding(3.0)]

    # One basic of two needed; one advanced in five words is 0.2.
    assert failed_on(findings, 5, threshold) == ["advanced"]
    assert failed_on(findings, 6, threshold) == []
    assert failed_on(findings + [finding(2.0)], 6, threshold) == ["basic"]


def test_either_count_or_ratio_is_enough():
    threshold = GuardrailThreshold.parse({"overall": {"count": 5, "ratio": 0.5}})

    assert failed_on([finding(2.0)], 2, threshold) == ["overall"]
    assert failed_on([finding(2.0)] * 5, 100, threshold) == ["overall"]
    assert failed_on([finding(2.0)], 3, threshold) == []


def test_an_empty_threshold_never_fails():
    assert failed_on([finding(1.0)] * 3, 3, GuardrailThreshold.parse({})) == []


def test_a_finding_without_gravity_counts_only_overall():
    threshold = GuardrailThreshold.parse(
        {"overall": {"count": 1}, "basic": {"count": 1}}
    )

    assert failed_on([finding(None)], 10, threshold) == ["overall"]


def test_output_reports_the_levels_it_failed_on(set_redis, llm_calls):  # noqa: F811
    body = post(
        "/v1.0/guardrail/output",
        {
            "response": MIXED,
            "lang": "en",
            "threshold": {"advanced": {"count": 2}, "basic": {"count": 2}},
        },
    ).json()

    assert body["verdict"] == "fail"
    assert body["failed_on"] == ["advanced"]
    # The reask covers every finding, not only the advanced ones.
    assert '"chairman"' in body["reask"]["content"]


def test_output_ratio_is_per_word(set_redis, llm_calls):  # noqa: F811
    def verdict(ratio):
        return post(
            "/v1.0/guardrail/output",
            {"response": MIXED, "lang": "en", "threshold": {"basic": {"ratio": ratio}}},
        ).json()["verdict"]

    # One basic finding in six words.
    assert verdict(0.16) == "fail"
    assert verdict(0.17) == "pass"


def test_ratio_counts_every_part_of_a_long_answer(
    set_redis, llm_calls
):  # noqa: F811
    """Past TEXT_MAX_LENGTH every part is checked, so the findings and the
    words of all of them make the ratio: one in three here."""
    text = "The chairman called. " * 100

    def verdict(ratio):
        return post(
            "/v1.0/guardrail/output",
            {"response": text, "lang": "en", "threshold": {"basic": {"ratio": ratio}}},
        ).json()

    assert verdict(0.3)["verdict"] == "fail"
    assert verdict(0.3)["limit_reached"] is False
    assert verdict(0.34)["verdict"] == "pass"


def test_a_pass_has_no_failed_on(set_redis, llm_calls):  # noqa: F811
    body = post(
        "/v1.0/guardrail/output", {"response": MIXED, "lang": "en", "threshold": {}}
    ).json()

    assert body["verdict"] == "pass"
    assert "failed_on" not in body


@pytest.mark.parametrize(
    "threshold",
    [
        {"severe": {"count": 1}},
        {"basic": {}},
        {"basic": {"count": 0}},
        {"basic": {"ratio": 0}},
        {"basic": {"ratio": 1.5}},
        0,
    ],
)
def test_an_invalid_threshold_is_refused(set_redis, llm_calls, threshold):  # noqa: F811
    response = post(
        "/v1.0/guardrail/output",
        {"response": MIXED, "lang": "en", "threshold": threshold},
    )

    assert response.status_code == 422


def key_output(client, threshold=None):  # noqa: F811
    body = {"response": MIXED, "lang": "en"}
    if threshold is not None:
        body["threshold"] = threshold
    return client.post(
        "/v1.0/guardrail/output", json=body, headers={"x-key": KEY}
    ).json()


def test_a_keys_forced_threshold_wins(client, llm_calls):  # noqa: F811
    sync(
        client,
        {
            "email": "guard@example.org",
            "key": KEY,
            "force": {"guardrail_threshold": {"openly_discriminating": {"count": 1}}},
        },
    )

    # The request asks for any finding to fail; the key's policy only fails on
    # openly discriminating language, of which there is none.
    assert key_output(client, threshold=1)["verdict"] == "pass"


def test_a_keys_suggested_threshold_is_the_default(client, llm_calls):  # noqa: F811
    sync(
        client,
        {
            "email": "guard@example.org",
            "key": KEY,
            "config": {"guardrail_threshold": {"advanced": {"count": 3}}},
        },
    )

    assert key_output(client)["verdict"] == "pass"
    assert key_output(client, threshold=1)["verdict"] == "fail"


LITELLM = "/v1.0/guardrail/litellm/beta/litellm_basic_guardrail_api"


def litellm(client, **params):  # noqa: F811
    return client.post(
        LITELLM,
        json={
            "texts": [MIXED],
            "input_type": "response",
            "additional_provider_specific_params": {"lang": "en", **params},
        },
        headers={"x-key": KEY},
    ).json()


def test_a_keys_forced_litellm_policy_wins(client, llm_calls):  # noqa: F811
    sync(
        client,
        {
            "email": "guard@example.org",
            "key": KEY,
            "force": {"guardrail_on_fail": "block", "guardrail_explain": False},
        },
    )

    body = litellm(client, on_fail="annotate", explain=True)

    assert body["action"] == "BLOCKED"
    assert "(" not in body["blocked_reason"]


def test_litellm_threshold_goes_through_the_config(client, llm_calls):  # noqa: F811
    sync(client, {"email": "guard@example.org", "key": KEY})

    assert litellm(client, threshold={"advanced": {"count": 3}})["action"] == "NONE"
    assert litellm(client)["action"] == "GUARDRAIL_INTERVENED"
