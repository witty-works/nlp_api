"""What reaches Sentry: no credential, and request text only through the
privacy filter (AGENTS.md, 1.1)."""

from sentry_sdk.scrubber import EventScrubber

from app.sentry import (
    SENTRY_DENYLIST,
    sentry_clean_event_data,
    sentry_filter_transactions,
)


def event(path="/v1.0/guardrail/output", **request):
    return {
        "request": {
            "url": "https://nlp.example" + path,
            "headers": {"x-key": "a-real-key-0123456789", "user-agent": "curl"},
            "query_string": "api_key=a-real-key-0123456789&email=jane@acme.example",
            "data": {
                "response": "Call jane@acme.example at 0791234567",
                "messages": [{"role": "user", "content": "see https://x.example/a"}],
            },
            **request,
        }
    }


def test_an_error_event_carries_no_key_and_only_filtered_text():
    cleaned = sentry_clean_event_data(event(), {})
    request = cleaned["request"]

    assert "x-key" not in request["headers"]
    assert request["headers"]["user-agent"] == "curl"
    assert "query_string" not in request
    assert "jane@acme.example" not in str(request["data"])
    assert "0791234567" not in str(request["data"])
    assert "x.example" not in str(request["data"])


def test_a_transaction_carries_no_key_either():
    cleaned = sentry_filter_transactions(event("/v2.4/check"), {})

    assert "x-key" not in cleaned["request"]["headers"]
    assert "query_string" not in cleaned["request"]


def test_other_transactions_are_dropped():
    assert sentry_filter_transactions(event("/v1.0/write"), {}) is None


def test_the_scrubber_knows_the_key_header():
    """Sentry's own scrubbing, which runs on every event, removes the headers
    and fields named in the denylist; `x-key` is not among its defaults."""
    scrubbed = event()
    scrubbed["request"]["data"] = {"apiKey": "a-real-key-0123456789"}
    EventScrubber(denylist=SENTRY_DENYLIST).scrub_event(scrubbed)

    assert "a-real-key" not in str(scrubbed["request"]["headers"])
    assert "a-real-key" not in str(scrubbed["request"]["data"])
