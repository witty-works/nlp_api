"""Test the configured language model on known cases.

Runs rephrasing cases against the model the deployment is configured with,
through the API itself (in-process), so the answer checks apply exactly as
for a user. A case fails when the API drops a suggestion, a suggestion
contains a string the case forbids, or the request fails; the run fails, too,
when the model that answered is not LLM_EXPECTED_MODEL. Reads the same
environment as the API. Calls are made one at a time, paced below
LLM_MAX_REQUESTS_PER_MINUTE (at least 1.1 s apart). See docs/llm-models.md.

    uv run python -m bin.llm_check
    uv run python -m bin.llm_check --repeat 3 --cases tests/llm_check

The key in the environment variable named by --api-key-env (DEFAULT_API_KEY
by default) is sent as x-key and never printed.
"""

import argparse
import json
import os
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

DEFAULT_CASES = ["tests/test_rephrase", "tests/llm_check"]


@dataclass
class Case:
    name: str
    body: dict
    forbidden: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    name: str
    passed: bool
    reason: str | None
    served_model: str | None
    # The API's answer; only a 200 says which model answered.
    status: int = 200


def load_cases(directories: list[pathlib.Path]) -> list[Case]:
    """Every <directory>/<case>/input.json, with its forbidden.json if any."""
    cases = []
    for directory in directories:
        for case_dir in sorted(path for path in directory.iterdir() if path.is_dir()):
            forbidden_file = case_dir / "forbidden.json"
            cases.append(
                Case(
                    name=case_dir.name,
                    body=json.loads((case_dir / "input.json").read_text()),
                    forbidden=(
                        json.loads(forbidden_file.read_text())
                        if forbidden_file.exists()
                        else []
                    ),
                )
            )
    return cases


def check_case(case: Case, status: int, payload) -> str | None:
    """Why the case failed, or None."""
    if status != 200 or not isinstance(payload, dict):
        return f"status {status}"
    results = payload.get("results") or {}
    missing = [
        alternative["text"]
        for alternative in case.body["alternatives"]
        if alternative["text"] not in results
    ]
    if missing:
        return "no suggestion for: " + ", ".join(missing)
    for alternative, sentence in results.items():
        for forbidden in case.forbidden:
            if forbidden in sentence:
                return f"{forbidden!r} in the suggestion for {alternative!r}"
    return None


def run(
    cases: list[Case],
    repeat: int,
    client,
    headers: dict,
    pause: float,
    sleep: Callable[[float], None] = time.sleep,
) -> list[CaseResult]:
    """Each case `repeat` times, `pause` seconds between calls."""
    results = []
    first = True
    for case in cases:
        for attempt in range(repeat):
            if not first:
                sleep(pause)
            first = False
            response = client.post("/v1.0/rephrase", json=case.body, headers=headers)
            try:
                payload = response.json()
            except ValueError:
                payload = None
            name = case.name if repeat == 1 else f"{case.name}#{attempt + 1}"
            reason = check_case(case, response.status_code, payload)
            served = payload.get("model") if isinstance(payload, dict) else None
            results.append(
                CaseResult(name, reason is None, reason, served, response.status_code)
            )
    return results


def context_settings_expected_model() -> str:
    from app.settings import Settings

    return Settings().llm_expected_model


def pause_seconds() -> float:
    from app.settings import Settings

    limit = Settings().llm_max_requests_per_minute
    return max(1.1, 60 / limit) if limit > 0 else 1.1


def main(
    argv: list[str] | None = None,
    client_factory: Callable | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--api-key-env", default="DEFAULT_API_KEY")
    parser.add_argument("--cases", nargs="+", default=DEFAULT_CASES)
    args = parser.parse_args(argv)

    key = os.environ.get(args.api_key_env)
    if not key:
        print(f"{args.api_key_env} is not set", file=sys.stderr)
        return 2
    headers = {"x-key": key}
    cases = load_cases([pathlib.Path(directory) for directory in args.cases])

    if client_factory is not None:
        results = run(cases, args.repeat, client_factory(), headers, 0, sleep)
    else:
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            results = run(cases, args.repeat, client, headers, pause_seconds(), sleep)

    for result in results:
        print(
            "PASS" if result.passed else "FAIL",
            result.name,
            result.served_model or "unknown",
            result.reason or "",
        )
    passed = sum(result.passed for result in results)
    print(f"{passed}/{len(results)} passed")

    failed = passed < len(results)
    expected = context_settings_expected_model()
    if expected:
        # A failed request (an overloaded provider's 503) names no model; it
        # already fails its case and is no evidence of another model.
        others = {
            r.served_model
            for r in results
            if r.status == 200 and r.served_model != expected
        }
        if others:
            print(
                "answered by "
                + ", ".join(sorted(model or "unknown" for model in others))
                + f", not LLM_EXPECTED_MODEL {expected}"
            )
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
