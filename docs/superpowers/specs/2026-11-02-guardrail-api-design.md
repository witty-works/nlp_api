# Witty GPT as a guardrail API

Date: 2026-11-02
Status: draft, awaiting review

## Goal

Make Witty GPT usable from LLM and agent gateways (LiteLLM, Portkey, Kong,
agentgateway and the like) by exposing it in the shape those gateways already
take third-party guardrails in, and reframe the documentation around that
pattern.

Audience, in order:

1. Developers wiring Witty into a gateway themselves: they need two endpoints
   and integration recipes.
2. Gateway vendors and partners who might list Witty as a guardrail provider:
   they need a small, stable, vendor-neutral contract.

## The pattern, named

What the code and docs call "prompt injection + follow-up prompt" is the
established **input/output guardrail** pattern:

| Step | Established name | Witty today |
| --- | --- | --- |
| Add inclusive-language guidance to the request | prompt decoration / enrichment, pre-call guardrail | default system prompt in `Prompt.handle()` |
| Check the model's answer | output guardrail, post-call check | rule engine via `review_draft()` |
| Ask the model to fix what was flagged | reask / retry with feedback | `ReviewPrompt` with `INCLUDE_PREVIOUS` |

"Prompt injection" names an attack and is retired from all docs and copy.

## Current state

- `/v1.0/write` (client credential) and `/v1.0/prompt` (management auth,
  `user_email` query) both run the whole loop server side: system prompt →
  LLM → check → review prompt → LLM. They share `review_draft()` but differ in
  how they prompt and parse (`parse_json` vs `plain_response`).
- `/debug/prompt` and `/debug/review_prompt` expose parts of it for debugging;
  the review-prompt snapshot tests run through `/debug/review_prompt`.
- Consumers: `/textarea` calls `/v1.0/write`; the dashboard's Witty GPT page
  calls `/v1.0/prompt` (`dashboard/app/Livewire/Prompt.php`). There are no
  consumers outside these two, both ours, so no compatibility period is needed.
- The dashboard reads `inititial_response` (typo), so its "original" side is
  always empty and the diff is computed against nothing.
- `/v1.0/rephrase` (per-alert LLM alternatives, used by the browser extension
  and Word plugin) is a different feature and out of scope.

## Design

### Principles

- The guardrail endpoints never call an LLM. The gateway owns every model call
  and its cost; Witty supplies guidance, verdict and reask text.
- Witty does not block and does not rewrite. What a `fail` means (reask,
  annotate, log, block) is the gateway's decision.
- One implementation: the managed loop in `/v1.0/write` is composed from the
  same functions the guardrail endpoints use.

### Auth and config

Both guardrail endpoints authenticate like `/v2.4/check`: `x-key` or Bearer
resolves to the user/org config, and an optional `config` in the body
overrides it per request. No `llm_alternatives` / `LLM_ACCESS` gate, since no
LLM budget is spent. Metrics are stored as `guardrail_input` and
`guardrail_output`.

### `POST /v1.0/guardrail/input`

Request:

```jsonc
{
  "messages": [
    { "role": "system" | "user" | "assistant" | "tool", "content": "..." }
  ],
  "lang": "auto",          // optional, as in /v2.4/check
  "config": { ... }         // optional overrides
}
```

`content` may be a string or an array of OpenAI-style content parts; only
`text` parts are read, anything else is passed through untouched.

Response:

```jsonc
{
  "action": "modify",
  "messages": [ ... ],      // the input, guidance merged in
  "guidance": "..."         // the bare guidance text
}
```

- Merging: if the first message is `system`, the guidance is appended to its
  content after a blank line; otherwise a new `system` message is prepended.
  Gateways that can only append a system prompt use `guidance` directly.
- Guidance = today's default system prompt (moved out of `Prompt.handle()`
  into a guidance builder) plus config-derived lines: the German gender
  format from `german_gender_ending` and the French one from
  `french_gender_separator`, phrased as "When writing German, …" since the
  output language is not known yet. When `lang` is given, only that
  language's line is added.
- The "do not add 'Sure…' / 'Here is…'" instruction stays out of the guardrail
  guidance: it serves `/v1.0/write`'s need for a bare text and would interfere
  with a gateway's own conversation. `/v1.0/write` adds it itself.

### `POST /v1.0/guardrail/output`

Request:

```jsonc
{
  "response": "the model's text",
  "lang": "auto",
  "config": { ... },
  "threshold": 1            // optional, >= 1
}
```

Response:

```jsonc
{
  "verdict": "pass" | "fail",
  "findings": [ /* ResultOut, as in /v2.4/check */ ],
  "language": "en",
  "limit_reached": false,
  "reask": { "role": "user", "content": "..." }   // only when verdict is fail
}
```

- `verdict` is `fail` when at least `threshold` findings carry alternatives
  (the findings `ReviewPrompt` can act on). `findings` lists all findings.
  Default 1 matches today's `min_changes=0`.
- `reask.content` is `ReviewPrompt.handle(..., ReviewType.INCLUDE_PREVIOUS,
  response)`: it quotes the response, so it works whether or not the gateway
  resends the conversation.
- A `response` longer than `TEXT_MAX_LENGTH` is checked up to the limit and
  reported with `limit_reached: true`, never refused: a guardrail must not
  break the gateway's answer.
- Language that cannot be determined: `verdict: "pass"`, empty `findings`,
  `language: null`. Same reasoning.
- Only the text a human will read should be sent. Tool calls and structured
  output are the gateway's to filter; the docs say so.

### `/v1.0/write`, the managed loop

Keeps its request and `PromptOut` response unchanged. Internally:

1. system prompt = guardrail guidance (for the request's config) + the
   bare-text instruction;
2. LLM draft;
3. output check (`threshold` 1);
4. on `fail`, the reask is sent to the LLM; `edits` diffs draft and review.

Auth gains a second path: management auth (as `/v1.0/prompt` uses today) plus
a `user_email` query parameter, for the dashboard. The client-credential path
is unchanged. In both cases `llm_alternatives` and `LLM_ACCESS` gate it as
now. `/v1.0/write` stays in the management-endpoint list in
`docs/configuration.md` for the `user_email` path.

Side effect: `/textarea` and the dashboard get the config-aware guidance too.

### Removed

- `/v1.0/prompt` and its `prompt()` helper; the `parse_json` path goes with it
  if nothing else uses it.
- `/debug/prompt` and `/debug/review_prompt`; the guardrail endpoints expose
  the same information.

### Dashboard

`Prompt.php` calls `/v1.0/write?user_email=…` with `{"prompt": <user prompt>}`
and no `client`: `/v1.0/write` checks client versions, and a bare name
without `name:version` parses as an unversioned web-ext. It reads
`initial_response`, and validates the prompt at the 1000 characters `/write`
accepts. The `inititial_response` bug goes away with the change. Using the
server's `edits` instead of `DiffHelper` is possible but not part of this
work.

## Documentation

NLP API:

- New `docs/guardrails.md`: the pattern and its names, the two endpoints with
  examples, what `fail` can mean (reask once, annotate, log), filtering
  tool calls and structured output, streaming (the output check needs the
  whole text: buffer, or check after delivery and annotate), and integration
  recipes for LiteLLM, Portkey and Kong. Each recipe is checked against the
  gateway's current documentation when written, and states the gateway version
  it was written against.
- `docs/api.md`: core table lists `/v1.0/guardrail/input` and
  `/v1.0/guardrail/output` first; `/v1.0/write` described as the managed loop
  built on them and used by our own clients; `/v1.0/prompt` and the two debug
  rows removed.
- `docs/technical-notes.md`: "Witty GPT Algorithm" rewritten in guardrail
  terms.
- `README.md`: the "prompt injection and automatic follow-ups" bullet becomes
  "inclusive-language guardrail for LLM and agent gateways", linking
  `docs/guardrails.md`.
- `docs/configuration.md`: LLM route and management-endpoint lists updated.

Dashboard: `README.md` Witty GPT section mentions `/v1.0/write`.

Website: `witty-gpt.php` and the en/de blog posts on ChatGPT are reviewed for
"prompt injection" wording; the product page gains a short "works with your
LLM gateway" section linking the API docs. Copy changes only.

## Testing

- Guardrail input: system message present / absent, content as string and as
  parts (non-text parts untouched), guidance lines per gender config and per
  `lang`, auth required, no LLM call made.
- Guardrail output: pass with no findings, fail with reask, `threshold` above
  the number of actionable findings passes, findings without alternatives do
  not count, over-length response gives `limit_reached` rather than an error,
  undetermined language passes, no LLM call made.
- The review-prompt snapshot tests (`tests/test_review_prompt`) move from
  `/debug/review_prompt` to `/guardrail/output`'s `reask`. The snapshots
  change: the debug route defaulted to `EXPLAIN_EDITS`, the reask uses
  `INCLUDE_PREVIOUS` (quotes the response, no explanations); cases that
  returned `WITTYNOCHANGES` now have no `reask`. Regenerated and reviewed.
- `/v1.0/write`: existing tests kept; new tests for the management-auth +
  `user_email` path, and that its system prompt contains the guardrail
  guidance.
- `/v1.0/prompt` and debug-prompt tests removed or folded into the above.
- Dashboard: feature test for the Witty GPT component against a faked
  `/v1.0/write` response.

## Out of scope

- OpenAI-compatible proxy mode, MCP tool, packaged gateway plugins.
- Blocking, Witty-side rewriting, streaming checks.
- Org custom rules / preferred terms in the guidance.
- `/v1.0/rephrase`.
