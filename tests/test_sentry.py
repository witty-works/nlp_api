"""What reaches Sentry: no credential, no request body, no local variables,
and log and exception messages only through the privacy filter (AGENTS.md,
1.1). The user's text reaches Sentry in none of them."""

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


def test_an_error_event_carries_no_key_and_no_body():
    cleaned = sentry_clean_event_data(event(), {})
    request = cleaned["request"]

    assert "x-key" not in request["headers"]
    assert request["headers"]["user-agent"] == "curl"
    assert "query_string" not in request
    # Not filtered, gone: the filter catches emails and numbers, not the
    # sentences people write about themselves.
    assert "data" not in request


def test_stack_frames_carry_no_local_variables():
    frame = {"function": "checked_results", "vars": {"sentence": "My son is autistic"}}
    cleaned = sentry_clean_event_data(
        {"exception": {"values": [{"stacktrace": {"frames": [frame]}}]}}, {}
    )
    frame = cleaned["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert "vars" not in frame
    assert frame["function"] == "checked_results"


def test_exception_messages_go_through_the_filter():
    cleaned = sentry_clean_event_data(
        {
            "exception": {
                "values": [{"type": "ValueError", "value": "bad jane@acme.example"}]
            }
        },
        {},
    )
    value = cleaned["exception"]["values"][0]
    assert value["type"] == "ValueError"
    assert "jane@acme.example" not in value["value"]


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


def test_log_messages_go_through_the_filter():
    """An ERROR log line becomes an event of its own; whatever a line quotes
    reaches Sentry only filtered."""
    cleaned = sentry_clean_event_data(
        {
            "message": "mail jane@acme.example",
            "logentry": {
                "message": "noun missing for %s",
                "params": ["jane@acme.example", 791234567],
                "formatted": "noun missing for jane@acme.example",
            },
            "breadcrumbs": {
                "values": [{"message": "call 0791234567", "category": "nlp_api"}]
            },
        },
        {},
    )

    assert "jane@acme.example" not in str(cleaned)
    assert "0791234567" not in str(cleaned)
    assert cleaned["logentry"]["message"] == "noun missing for %s"
    assert cleaned["breadcrumbs"]["values"][0]["category"] == "nlp_api"
