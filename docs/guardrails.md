# Witty GPT as a Guardrail

Witty GPT steers language models towards inclusive language. It is an
**input/output guardrail**: it plugs in around a model call that something else
makes, such as an LLM or agent gateway, an application, or an agent framework.
The guardrail endpoints never call a model themselves. Every model call, and
every provider key, stays with the caller.

It is **user assistance, not policy enforcement**. It makes inclusive language
the default, flags what slips through and explains why, for people and models
that mean well. Someone who sets out to get around it can, see
[Limits](#limits). Witty stays stateless and stores no prompt or answer; where
an organisation wants a record, that is its gateway's log.

## The pattern

| Step | Common names | Witty endpoint |
| --- | --- | --- |
| Add inclusive-language guidance to the request | prompt decoration, prompt enrichment, pre-call guardrail | `POST /v1.0/guardrail/input` |
| Check the model's answer | output guardrail, post-call check | `POST /v1.0/guardrail/output` |
| Ask the model to fix what was flagged | reask, retry with feedback | the `reask` message in the output check's answer |

Older Witty material calls the first step "prompt injection". That term names
an attack on LLM applications and is not used any more.

[`/v1.0/write`](./api.md#core-endpoints) runs all three steps inside Witty,
model call included. `/textarea` uses it.

## Authentication and configuration

The endpoints take the same credentials as `/v2.4/check`: an `x-key` header or
an OAuth2 Bearer token. Where both arrive, the `x-key` decides and the token is
not looked at: some gateways (agentgateway, Portkey with `forwardHeaders`)
forward their client's own `Authorization` header, an LLM key, next to the
`x-key` they add for Witty. More than one `x-key` header is a `400`: which one
applies would otherwise depend on header order. The key's user and organization configuration applies,
including custom rules and the gender format. An optional `config` in the body
overrides it per request, as on `/v2.4/check`. Unlike `/v2.4/check`, a request
that resolves to no user gets a `401` rather than an empty answer: a guardrail
that passed everything on a mistyped key would look like one that works. A
deployment with `REQUIRE_AUTH=false` answers anyone, and so do the guardrail
endpoints, with the default configuration.

The endpoints are not gated by `llm_alternatives` or `LLM_ACCESS`, since they
spend no LLM budget.

### The guardrail's policy, per key

Three config fields hold the guardrail's policy:

| Field | Meaning | Default |
| --- | --- | --- |
| `guardrail_threshold` | When an answer fails, see [Thresholds](#thresholds) | the first finding with alternatives |
| `guardrail_on_fail` | LiteLLM only: `annotate` or `block` | `annotate` |
| `guardrail_explain` | LiteLLM only: whether the note explains each finding | `true` |

They layer like every other config field. A request sets them through its
`config`, or through the shorthands `threshold` (output endpoint) and
`threshold`, `on_fail`, `explain` (LiteLLM params). A key's `config` is the
default where the request says nothing, and its `force`, like a force in a
user's or organisation's config synced from the dashboard, wins over the
request. So an operator who wants every integration on the same policy
forces it on the key. That keeps honest integrations consistent; it is not a
barrier against a caller who means to get around the check (see
[Limits](#limits)):

```yaml
# api_keys.yaml
- email: gateway@acme.example
  key: …
  force:
    guardrail_threshold:
      openly_discriminating: { count: 1 }
      basic: { count: 3 }
      advanced: { ratio: 0.05 }
    guardrail_on_fail: block
```

## `POST /v1.0/guardrail/input`

Send the chat messages you are about to send to the model, in OpenAI format.
You get them back with Witty's guidance merged in.

```bash
curl -X POST 'http://127.0.0.1:8000/v1.0/guardrail/input' \
  -H 'x-key: your-api-key' \
  -H 'Content-Type: application/json' \
  -d '{
  "messages": [{"role": "user", "content": "Write a short job ad for a developer."}],
  "lang": "en"
}'
```

```jsonc
{
  "action": "modify",
  "messages": [
    {
      "role": "system",
      "content": "You are an expert in inclusive language.\nKeep gender equality in mind and avoid language that is needlessly gendered (f.e. use truly gender neutral nouns, avoid pronouns).\nDo not make biased assumptions.\n…"
    },
    { "role": "user", "content": "Write a short job ad for a developer." }
  ],
  "guidance": "You are an expert in inclusive language.\n…"
}
```

- If the first message is a `system` message, the guidance is appended to it
  after a blank line. A `content` given as content parts gets an extra `text`
  part. Otherwise a new `system` message is put in front.
- Every other message comes back exactly as sent, including tool calls, names
  and a `null` content.
- `guidance` is the bare text, for callers that can only append a system
  prompt of their own.
- The guidance names the gender form the configuration asks for, such as
  "Lehrer\*in" for `german_gender_ending: "*in"` or "étudiant·e" for
  `french_gender_separator: "·"`. Before the model has answered, its language
  is rarely known, so without a `lang` both the German and the French line are
  added. With `lang`, only that language's line is (none for English). There
  is no line for the Inklusivum: models cannot write it reliably, and the
  output check brings it in where it applies.

## `POST /v1.0/guardrail/output`

Send the model's answer: the part of it a person will read.

```bash
curl -X POST 'http://127.0.0.1:8000/v1.0/guardrail/output' \
  -H 'x-key: your-api-key' \
  -H 'Content-Type: application/json' \
  -d '{"response": "The chairman called the policemen.", "lang": "en"}'
```

```jsonc
{
  "verdict": "fail",
  "findings": [
    {
      "text": "chairman",
      "start": 4,
      "end": 12,
      "category": "gender-orientation",
      "label": "Gender + Orientation: Generic masculine",
      "alternatives": [{ "text": "chair" }, { "text": "chairperson" } /* … */],
      "explanation": { "text": "Generally provokes a mental image of men" /* … */ }
      // … the same result objects as /v2.4/check
    }
    // … "policemen"
  ],
  "language": "en",
  "limit_reached": false,
  "reask": {
    "role": "user",
    "content": "You are an expert in inclusive language. You are tasked with editing the \"previous response\".\nThe \"previous response\" is the following JSON string: \"The chairman called the policemen.\"…\nBelow is the \"issues list\":\n[{\"issue\": \"chairman\", \"alternatives\": [{\"alt\": \"chair\"}, …]}, …]"
  }
}
```

An answer with nothing to fix:

```json
{"verdict": "pass", "findings": [], "language": "en", "limit_reached": false}
```

- `verdict` is `fail` when the findings with alternatives reach a limit of
  the threshold, see [Thresholds](#thresholds). `threshold` is optional; the
  default fails on the first one. On a fail, `failed_on` lists the levels
  whose limit was reached.
  `findings` lists everything that was found, actionable or not.
- More `verdict` values may be added later. Treat any value other than
  `pass` as not passing. A `fail` is an ordinary `200` answer, never an error
  status: several gateways read a non-2xx answer as the guardrail failing
  and may let the request through.
- `reask` is only there on a `fail`. It is a ready-to-send `user` message that
  quotes the answer, so it works whether or not you send the conversation
  before it again. The model's reply to it is the corrected answer.
- The check never refuses. An answer longer than `TEXT_MAX_LENGTH` (1000
  characters by default) is checked in parts of that length, and the
  findings' `start` and `end` point into the whole answer. Past 20000
  characters, as much as the `/textarea` editor checks, the rest goes
  unchecked and `limit_reached` is `true`; the answer is not failed for it.
  One whose language cannot be told, an empty one among them, passes with
  `language: null`.
- Like the review in `/v1.0/write`, the output check leaves out the
  categories `communal`, `d_and_i`, `emotional_security`, `inclusive` and
  `orthography`, which `/v2.4/check` reports. It does not ask LanguageTool
  either: no spelling, grammar or style findings, and a LanguageTool outage
  does not affect it.

## Thresholds

`threshold` (or the config's `guardrail_threshold`) is a number, or a limit
per level:

```jsonc
"threshold": {
  "overall":               { "ratio": 0.1 },
  "corporate_rules":       { "count": 1 },
  "openly_discriminating": { "count": 1 },
  "basic":                 { "count": 3 },
  "advanced":              { "ratio": 0.05 }
}
```

| Level | Findings |
| --- | --- |
| `overall` | every finding with alternatives |
| `corporate_rules` | the organisation's own term rules |
| `openly_discriminating` | gravity below 1.5 |
| `basic` | gravity 1.5 to 2.5 |
| `advanced` | gravity above 2.5 |

- A limit has a `count` (at least 1), a `ratio` (above 0, at most 1), or
  both; whichever is reached first fails the answer. `ratio` is findings per
  word of the text that was checked: past 20000 characters, the unchecked
  rest does not count.
- The answer fails when any one limit is reached. A level without a limit
  never fails it, and `{}` never fails at all: a check that only reports.
- A number `n` is `{"overall": {"count": n}}`.
- Only findings with alternatives count, and a finding without a gravity
  counts towards `overall` only. To leave whole categories out, disable them
  in the config, as on `/v2.4/check`.
- The reask covers every finding with alternatives, not only those of the
  levels that failed: the model should fix the whole answer. Findings without
  alternatives go in too, with their explanation, for the model to rephrase.

## `GET /v1.0/guardrail/guidance`

The bare guidance text that `/v1.0/guardrail/input` adds, for gateways and
deployments that can only set a fixed system prompt (Kong's prompt decorator,
an Azure API Management policy, a prompt map). It follows the key's
configuration like the input endpoint does; `lang` (optional) limits the
gender line to that language.

```bash
curl 'http://127.0.0.1:8000/v1.0/guardrail/guidance?lang=de' -H 'x-key: your-api-key'
```

```json
{"guidance": "You are an expert in inclusive language.\n…\nWhen writing German, form gender-inclusive person nouns like \"Lehrer*in\"."}
```

A fixed copy does not follow later changes to the configuration or the
guidance; fetch it again after those.

## Errors

| Status | When |
| --- | --- |
| `401` | The credential resolves to no user, while `REQUIRE_AUTH` is on. |
| `400` | More than one `x-key` header. |
| `403` | A Bearer token that is not accepted. |
| `422` | The body does not validate: no `messages`, a threshold with an unknown level or an invalid limit, an unknown `lang`, or for LiteLLM an unknown `on_fail`. |

## Acting on a fail

The larger risk than a missed term is people leaving the review to the
machine. A guardrail that quietly corrects the answer invites that, and Witty
has gaps in its rules like any checker. The best integration therefore keeps
every finding in front of the person who sends the text, where they can act
on it: show the final text in the [Witty editor](https://github.com/witty-works/browser-extension/tree/dev/packages/editor),
which underlines every issue with its explanation, as `/textarea` does after
a reask. The options below are for where that is not possible.

The two endpoints above never block and never rewrite. What a `fail` means is up to you (the [LiteLLM adapter](#litellm) offers `annotate` and `block` for you to choose from):

- **Reask, and show what Witty changed.** Send `reask` to the model and use
  its answer. Showing Witty's influence takes three pieces: the model's first
  answer, the findings with their explanations (what Witty sent back, and
  why), and the corrected answer, with a word diff between the two answers
  for the edits. That is what `/v1.0/write` returns and `/textarea` shows.
  Witty is stateless and never sees the corrected answer, so keeping the
  pieces together is the caller's job. Once is enough: the findings explain
  the change, and the final text gets checked where it is shown, the way the
  `/textarea` editor underlines it through `/v2.4/check`.
- **Annotate.** Show the answer unchanged, with the findings and their
  explanations.
- **Log.** Record the verdict and findings for review, and change nothing.
- **Block.** Refuse the answer. Rarely the right call for language that is
  merely not inclusive.

## What to send

Only text a person will read: final answers, and messages an agent is about to
send, post or publish. Tool calls, JSON and code get no useful findings, and a
rewrite of them would break them. Send their human-readable parts or nothing.

## Streaming

The output check needs the whole answer. Either buffer the stream before
showing it, or show it as it streams, check it once it is complete, and
annotate it afterwards.

## LiteLLM

The LiteLLM proxy can call Witty through its
[Generic Guardrail API](https://docs.litellm.ai/docs/adding_provider/generic_guardrail_api)
(a beta feature). Witty answers it at
`/v1.0/guardrail/litellm/beta/litellm_basic_guardrail_api`; LiteLLM adds the
`/beta/…` part to `api_base` itself.

Tested on 2026-11-02 with the LiteLLM proxy 1.106.6 and 1.83.7 in front of a
model, against a running Witty. **The guidance needs LiteLLM 1.104 or later**:
1.83 ignores the conversation Witty returns, so the model never sees the
guidance, and nothing reports it (from LiteLLM's source, 1.102 and earlier
behave the same; 1.103 was not checked). The answer check works on both.

```yaml
guardrails:
  - guardrail_name: "witty"
    litellm_params:
      guardrail: generic_guardrail_api
      mode: [pre_call, post_call]
      # Without this, the guardrail only runs for requests that name it
      # ("guardrails": ["witty"] in the request body).
      default_on: true
      api_base: https://witty.example.org/v1.0/guardrail/litellm
      # Witty reads its key from x-key. LiteLLM's own `api_key` would be
      # sent as x-api-key, which Witty does not read.
      headers:
        x-key: "your-witty-api-key"
      # Check a streamed answer once, when it is complete (LiteLLM 1.106).
      streaming_end_of_stream_only: true
      additional_provider_specific_params:
        lang: auto        # or en, de, fr, de-CH, …
        # A key that forces guardrail_threshold, guardrail_on_fail or
        # guardrail_explain overrules these three.
        threshold: 1      # or per level, see Thresholds
        on_fail: annotate # or block
        explain: true     # say why, not only what (the default)
```

`guardrails` is a top-level key of the proxy config, next to `model_list`.
Older LiteLLM documentation nests it under `litellm_settings`, which 1.106
refuses to start with. LiteLLM 1.106 also refuses to start without a master
key (`LITELLM_MASTER_KEY`).

- **`pre_call`** adds the guidance to the conversation. A conversation that
  already carries it, such as the next turn of a chat that keeps its messages,
  is left alone. **Send a system message of your own** if your messages carry
  fields beyond the standard ones: where there is none, Witty adds one, and
  LiteLLM then sends the model the conversation as it came back from Witty,
  which has been through LiteLLM's message types and has lost any field they
  do not declare (a user message's `name`, `provider_specific_fields`).
- **`post_call`** checks each text of the answer. Where one fails, `annotate`
  appends Witty's findings to it, each with its explanation, such as
  `[Witty] "chairman" → chair / chairperson / … (Generally provokes a mental image of men); "policemen" → …`.
  `explain: false` leaves the explanations out, for a shorter note. In
  LiteLLM the answer itself stays as the model wrote it, so the note is
  where Witty's influence shows.
  `block` makes LiteLLM refuse the answer with the findings as the error
  message: HTTP 400 on LiteLLM 1.106, 500 on 1.83.
- LiteLLM does not reask. To have the model correct its answer, call
  `/v1.0/guardrail/output` from your application or agent and send its `reask`,
  or let `/v1.0/write` run the whole loop.
- **Streaming.** The note of `annotate` never reaches a client that streams:
  the text has been sent by the time the check is done. For the note, don't
  stream. With `streaming_end_of_stream_only: true`, LiteLLM 1.106 checks a
  streamed answer once at the end, and `block` sends the whole answer followed
  by an error event. Without it, and always on 1.83, LiteLLM checks every few
  chunks while the answer streams, and `block` cuts it off midway.
- LiteLLM fails closed by default: while Witty cannot be reached, requests
  through this guardrail fail with HTTP 500. `unreachable_fallback: fail_open`
  lets them through unchecked when Witty is unreachable (timeouts, 502, 503,
  504), but not when Witty refuses the key. LiteLLM 1.106 also has
  `fail_on_error: false`, which skips the guardrail on any error; 1.83 does
  not know it.

## Limits

The guardrail assists; it cannot stop a caller, or a user instructing the
model, who sets out to get around it. Known ways:

- **The request decides what is not forced:** `lang`, `config` (disabling
  categories, for example) and `threshold` (`{}` never fails). `force` on the
  key keeps integrations consistent, but whoever controls the request can
  still pick the language.
- **Text the check cannot read:** a wrong `lang`, invisible characters inside
  words, letters from another script that look the same.
- **Text the check does not see:** answers in tool calls or structured output,
  and anything past 20000 characters (`limit_reached`).
- **Streaming:** the text has reached the client before the check of the
  whole answer is done, so neither a note nor a block can take it back.
- **Ratios dilute:** filler words lower findings per word. A ratio is there
  to keep the guardrail from flagging so much that people switch it off; use
  `count` for the levels that matter most.

Logs of requests, answers and guardrail results are the gateway's to keep,
not Witty's.

## Other gateways

Gateways that call an external HTTP guardrail and map its answer to a decision
of their own can use `/v1.0/guardrail/input` and `/v1.0/guardrail/output`
directly: block or flag on `verdict`, and reask in your application. There are
no ready-made recipes for them yet.
