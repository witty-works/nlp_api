"""
Prompt Routes
/v1.0/write, Witty GPT's managed loop for our own clients: the guardrail
guidance, an LLM draft, the guardrail review and, where it fails, the reask.
"""

import difflib
import json
import re
from typing import Union

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import HTTPBearer
from fastapi.security.api_key import APIKeyHeader

from app.context import AppContext
from app.dependencies import get_app_context
from app.guardrail import review
from app.guidance import BARE_TEXT_INSTRUCTION, guidance
from app.models import (
    CheckRequestIn,
    Client,
    EditOut,
    PromptOut,
    Result,
    WriteRequestIn,
)
from app.version_validators import REPHRASE_API_VERSION, client_version
from app.prompt import llm_error
from app.llm_access import LlmRefused, llm_user

router = APIRouter()


# Room for a rewritten text of about the length WriteRequestIn accepts, on top
# of LLM_MAX_TOKENS, which a reasoning model may spend thinking first.
WRITE_TEXT_TOKENS = 1500


@router.post(
    f"/v{REPHRASE_API_VERSION}/write",
    response_model=Union[PromptOut, Result],
    response_model_exclude_none=True,
    dependencies=[
        Depends(HTTPBearer(auto_error=False)),
        Depends(APIKeyHeader(name="x-key", auto_error=False)),
    ],
)
async def post_write(
    request: Request,
    response: Response,
    write_request_in: WriteRequestIn,
    context: AppContext = Depends(get_app_context),
) -> PromptOut | Result:
    """Write a text, or change the given one, as the prompt says, then review it.

    The managed loop, built on the guardrail endpoints: the model gets the
    guidance of /v1.0/guardrail/input, its draft the review of
    /v1.0/guardrail/output, and a failing draft goes back with the reask.
    The caller is whoever the credential resolves to, gated like
    /v1.0/rephrase.
    """
    client_version(
        Client.parse(write_request_in.client), context.settings.minimum_versions
    )

    try:
        _, configs = await llm_user(
            request, write_request_in, context, "LLM use not enabled on user"
        )
    except LlmRefused as refused:
        response.status_code = refused.status_code
        return Result.factory(refused.message)

    context.redis.store_metrics(request, configs, REPHRASE_API_VERSION, "write")

    # Witty checks this much of a text at once, so a longer draft would only be
    # reviewed in part; the model is asked to stay inside it, and a draft that
    # does not is reported through `limit_reached`.
    length = f" Keep the result under {context.settings.text_max_length} characters."
    # A longer text could only come back shortened, which a request to fix
    # its typos would not expect; refused instead.
    if len(write_request_in.text) > context.settings.text_max_length:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return Result.factory(
            f"The text is longer than {context.settings.text_max_length}"
            " characters, the most a prompt can rewrite"
        )
    if write_request_in.text.strip():
        user_prompt = (
            "Apply the instruction to the text below. Respond with the complete"
            " revised text only, in the language of the text unless the"
            " instruction asks for another, and keep its paragraph breaks."
            f"{length}\n\n"
            f"Instruction:\n{write_request_in.prompt}\n\n"
            f"Text:\n{write_request_in.text}"
        )
    else:
        user_prompt = (
            f"{write_request_in.prompt}\n\nRespond with the text only.{length}"
        )

    system_prompt = (
        guidance(write_request_in.config, write_request_in.lang)
        + "\n\n"
        + BARE_TEXT_INSTRUCTION
    )
    max_tokens = context.settings.llm_max_tokens + WRITE_TEXT_TOKENS
    try:
        draft = plain_response(
            await context.prompt.handle(
                user_prompt, system_prompt, None, 0.4, max_tokens=max_tokens
            )
        )
        check_request_in = CheckRequestIn(
            text=draft,
            lang=write_request_in.lang,
            client=write_request_in.client,
            config=write_request_in.config,
        )
        outcome = await review(check_request_in, configs, context)
        reviewed_response = None
        if outcome.reask is not None:
            reviewed_response = plain_response(
                await context.prompt.handle(
                    outcome.reask["content"], max_tokens=max_tokens
                )
            )
    except Exception as error:
        # The caller gets the kind of failure, the operator the whole story: a
        # wrong LLM_API_BASE or an expired provider key ends up here too.
        response.status_code, headers, message = llm_error(error, "/v1.0/write")
        response.headers.update(headers)
        return Result.factory(message)

    if outcome.language is None:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return Result.factory("Language could not be determined")

    return PromptOut(
        initial_response=draft,
        reviewed_response=reviewed_response or None,
        check_results=outcome.findings,
        limit_reached=outcome.limit_reached,
        edits=word_edits(draft, reviewed_response) if reviewed_response else None,
    )


def word_edits(before: str, after: str) -> list[EditOut]:
    """Word diff of the draft against its review, as the dashboard shows it.

    Words and the whitespace between them are the units, so joining the
    non-deleted parts gives `after` back and the non-inserted ones `before`.
    """
    a = [token for token in re.split(r"(\s+)", before) if token]
    b = [token for token in re.split(r"(\s+)", after) if token]

    edits: list[EditOut] = []

    def add(op: str, tokens: list[str]) -> None:
        if not tokens:
            return

        if edits and edits[-1].op == op:
            edits[-1].text += "".join(tokens)
        else:
            edits.append(EditOut(op=op, text="".join(tokens)))

    # No autojunk: it would treat the frequent tokens (spaces, "the") as noise
    # in any text over 200 words and scatter the diff.
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            add("equal", a[i1:i2])
        else:
            add("delete", a[i1:i2])
            add("insert", b[j1:j2])

    return edits


def plain_response(answer: str) -> str:
    """The model's answer as the text itself.

    The review prompt hands the draft over as a JSON string, and models tend to
    answer in kind. Unlike parse_json this leaves braces in prose alone.
    """
    answer = answer.strip()
    if len(answer) >= 2 and answer.startswith('"') and answer.endswith('"'):
        try:
            decoded = json.loads(answer)
        except ValueError:
            return answer

        if isinstance(decoded, str):
            return decoded.strip()

    return answer
