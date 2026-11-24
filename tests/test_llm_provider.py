"""The named LLM provider adapters (LLM_PROVIDER)."""

import litellm
import pytest

from app.llm_provider import LlmTextRefused, provider_for
from app.settings import Settings


def fake_response(model, headers=None):
    response = type("Response", (), {})()
    response.model = model
    response.choices = []
    response._hidden_params = {"additional_headers": headers or {}}
    return response


def test_unknown_provider_names_the_known_ones():
    with pytest.raises(ValueError, match="openai-compatible.*litellm-proxy"):
        provider_for(Settings(llm_provider="nope"))


def test_task_extra_body_merges_over_the_global_one():
    settings = Settings(
        llm_extra_body={"a": 1, "b": 1},
        llm_task_extra_body={"rephrase": {"b": 2}},
    )
    provider = provider_for(settings)
    assert provider.call_params("rephrase")["extra_body"] == {"a": 1, "b": 2}
    assert provider.call_params("write")["extra_body"] == {"a": 1, "b": 1}


def test_no_extra_body_is_sent_when_there_is_none():
    assert "extra_body" not in provider_for(Settings()).call_params("rephrase")


def test_litellm_proxy_reads_the_served_model_header():
    response = fake_response(
        "qwen3.8-flash-next",
        {"llm_provider-x-litellm-model-name": "openai/Qwen3.8-Flash-Next-oQ4e-mtp"},
    )
    provider = provider_for(Settings(llm_provider="litellm-proxy"))
    assert provider.served_model(response) == "openai/Qwen3.8-Flash-Next-oQ4e-mtp"


def test_a_missing_header_is_an_unknown_model():
    provider = provider_for(Settings(llm_provider="litellm-proxy"))
    assert provider.served_model(fake_response("x")) is None
    # LiteLLM moved or dropped its hidden parameters: unknown, not a crash.
    bare = type("Response", (), {"model": "x"})()
    assert provider.served_model(bare) is None


def test_default_adapter_reads_the_body_model():
    response = fake_response("gpt-test-2026-01-01")
    assert provider_for(Settings()).served_model(response) == "gpt-test-2026-01-01"


def test_default_adapter_still_recognises_proxy_guardrails():
    error = litellm.BadRequestError(
        message="blocked",
        model="m",
        llm_provider="openai",
        body={"provider_specific_fields": {"guardrail_name": "pii"}},
    )
    assert isinstance(provider_for(Settings()).classify_error(error), LlmTextRefused)


def test_same_model_is_an_exact_comparison():
    provider = provider_for(Settings())
    assert provider.same_model("a/b", "a/b")
    assert not provider.same_model("a/b", "a/B")


def test_a_real_litellm_response_carries_the_served_model_header():
    """Through the real litellm.acompletion against a local server that
    answers as a LiteLLM proxy does: fails if LiteLLM stops passing the
    response headers on where response_header reads them."""
    import asyncio
    import http.server
    import json
    import threading

    from app.prompt import Prompt

    class Proxy(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = json.dumps(
                {
                    "id": "1",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "alias",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("x-litellm-model-name", "openai/Real-Model")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        prompt = Prompt(
            Settings(
                llm_provider="litellm-proxy",
                llm_model="openai/alias",
                llm_api_base=f"http://127.0.0.1:{server.server_address[1]}/v1",
                llm_api_key="test-key",
            )
        )
        answer = asyncio.run(prompt.answer("hi"))
    finally:
        server.shutdown()
    assert answer.text == "ok"
    assert answer.served_model == "openai/Real-Model"


def test_task_extra_body_merges_one_level_deep():
    """A task's fields add to a global object field rather than replace it."""
    settings = Settings(
        llm_extra_body={"chat_template_kwargs": {"a": 1}, "x": 1},
        llm_task_extra_body={"rephrase": {"chat_template_kwargs": {"b": 2}}},
    )
    assert provider_for(settings).call_params("rephrase")["extra_body"] == {
        "chat_template_kwargs": {"a": 1, "b": 2},
        "x": 1,
    }


ARN_MODEL = (
    "bedrock/arn:aws:bedrock:eu-central-1:123456789012:inference-profile/eu.model"
)


def test_a_model_name_hides_the_aws_account_in_an_arn():
    from app.llm_provider import public_model_name

    shown = public_model_name(ARN_MODEL)
    assert "123456789012" not in shown
    assert shown.startswith("bedrock/arn:aws:bedrock:eu-central-1:")
    assert shown.endswith(":inference-profile/eu.model")


def test_a_model_name_is_capped():
    from app.llm_provider import public_model_name

    assert len(public_model_name("m" * 1000)) <= 200
    assert public_model_name(None) is None
