# Ethics screening — details

The short version, and when to read this, is in [AGENTS.md](../AGENTS.md#ethics-screening).

Witty Works screens every feature against the data ethics questions on the
[ethics board page](https://www.witty.works/ethics-board), derived from
the AlgorithmWatch Impact Assessment Tool. Any "yes" flags the change for a
detailed review by the Technology Ethics Board. This service is where those
questions bite hardest: it receives everything people write, it runs
statistical models over it, and it can forward it to third parties.

You cannot do the board's review, and you must not decide on its behalf that a
"yes" is harmless. Your job is to **notice the "yes", stop, and make it
visible**.

## Treat all submitted text as sensitive personal data

People use this service precisely when writing about disability, gender,
sexual orientation, origin, religion or health — the special categories of
personal data (GDPR Art. 9, revDSG Art. 5 c). Assume every `text`, `prompt`,
answer, sentence and context snippet contains such data, and that it names
people. No exception for "it's only a word" or "it's only debug".

## The three screening questions, as they show up in this code

**1.1 Enhanced privacy harm** — does the change touch personal data, or expose
it where it could harm? It is a "yes" if the change:

- stores, caches, logs or counts anything derived from request text, or the
  user's email, API key or `Authorization` header — Redis
  ([app/redis.py](../app/redis.py)), logger calls, Sentry
  ([app/sentry.py](../app/sentry.py)), files, metrics
- sends text to a new destination or a new provider: the LLM
  ([app/prompt.py](../app/prompt.py), `LLM_MODEL`, `LLM_API_BASE`), LanguageTool
  ([app/languagetool.py](../app/languagetool.py), especially the public API), the
  remote context checker (`CONTEXT_CHECKER`), Slack
  ([app/routes/slack.py](../app/routes/slack.py))
- widens what is returned or kept as context (`store_context`, the ±100 chars
  in [app/models.py](../app/models.py)), or changes its default
  (`DEFAULT_USER_STORE_CONTEXT`)
- weakens or bypasses [app/privacy_filter.py](../app/privacy_filter.py), or adds a
  data path that does not go through it
- changes who may use the LLM (`LLM_ACCESS`,
  [app/llm_access.py](../app/llm_access.py)) or who may set `store_context` /
  `llm_alternatives` (`CLIENT_CONFIG_ENABLED`,
  [app/config_manager.py](../app/config_manager.py))
- adds per-user or per-organisation analytics (`team_analytics`, `LOG_METRICS`)

**1.14 Statistical proxy risk** — does the system rely on a statistical model
of human behaviour or personal characteristics? It is a "yes" if the change:

- adds, retrains, replaces or re-thresholds a model whose output decides what
  is flagged or suggested: the SetFit context checker
  ([app/context_checker.py](../app/context_checker.py)), fastText language
  detection ([app/lang_detection.py](../app/lang_detection.py)), spaCy models or
  the lemmatizer mode (`MODELS`, `LEMMATIZER`), the LLM or its prompts
  ([app/review_prompt.py](../app/review_prompt.py),
  [app/guidance.py](../app/guidance.py), [app/guardrail.py](../app/guardrail.py),
  [app/llm_alternatives.py](../app/llm_alternatives.py))
- infers a characteristic of the author or of a person mentioned — gender of a
  referent, whether a noun refers to people
  ([app/gender_format.py](../app/gender_format.py), `test_not_for_people`), age,
  origin, disability — or the author's proficiency
- changes guardrail verdicts, thresholds or gravity in a way that scores a
  person's writing rather than a term

**1.15 Procedural regularity risk** — does the system adapt, so that it no
longer treats new cases like past ones? It is a "yes" if the change:

- makes output depend on usage history: learning from feedback, accepted or
  dismissed suggestions, counts, or anything written back at request time
- tunes thresholds, rankings or rules automatically rather than by a reviewed
  commit
- makes the same text with the same config and the same API key produce
  different results over time, including by moving to a newer or unpinned LLM
  or model version

Rule and data changes made by humans through the rule editor and
`bin/sync_sqlite_data.py` are not adaptive in this sense. They are editorial,
and the board reviews them as such.

## What to do on a "yes"

1. **Stop before implementing** and tell the user which question(s) the change
   triggers and why, citing the file and line. A doubt counts as a "yes":
   if you can argue either way, say so and show both sides. A concern that
   fits none of the three questions is raised the same way. Do not make the change
   "temporarily", "behind a flag" or "for debugging" first.
2. If the user decides to go ahead, add an **Ethics screening** section to the
   PR description that:
   - names the triggered question(s): 1.1 / 1.14 / 1.15
   - answers the relevant detailed questions in brief: privacy outcome
     (2.2.1, 2.10), fairness outcome and how bias is measured (2.2.3, 2.12),
     who is affected (2.8.1), how a finding is explained to the user (2.13),
     the remaining risks and why they are acceptable (2.18, 2.19)
   - says what changes for the public: a new data flow, provider or model
     belongs in the transparency report and the privacy policy
   - records who signed off and why, and any steering (see below)
   - lists what was cut or dropped during review, with the reason, in a
     "Cut or dropped during review" section (see below)
   - ends with "Flagged for Technology Ethics Board review"
3. Prefer the design that makes the answer "no": process in memory, keep
   nothing, filter before any egress, make it opt-in rather than default-on,
   keep it deterministic.

## Record sign-offs and steering

What was decided, and by whom, must be traceable from the PR alone. The PR
description is the public record of this service, so nothing that only
happened in a chat or an agent session counts. Commits stay about the code.

- **Sign-offs**: when someone decides that a flagged change may go ahead,
  name them, give their role (the user, the ethics board, a board member)
  and the reason in the PR's ethics screening section. "Approved" without a
  reason is not a sign-off.
- **Steering**: when an ethics consideration changes a design, record it in
  the PR description, whether a person asked for the change or you proposed
  it and they agreed. Examples: dropping a field that would have been
  logged, making something opt-in, choosing a self-hosted provider over a
  public API. Say what was considered, what was
  chosen and why. Steering that makes the answer "no" matters too: it is
  why the answer is "no".
- **Rejected options**: if a concern was raised and the change went ahead
  anyway, record the concern and why it was outweighed (2.18, 2.19), not
  only the outcome.
- **Cut features**: what was built and then removed, or proposed and not
  built, because of the review, each with the reason, in a "Cut or dropped
  during review" section. Keep apart what the ethics screening cut and what
  fell away for other reasons. A feature removed before the PR leaves no
  trace in the diff, so this section is the only record of it.

Write it for a reader who was not there, such as a board member, an auditor
or a future contributor, and keep it factual.

No "yes"? Say so in one line in the PR description ("Ethics screening: no
trigger") so that a reviewer can see the screening was done.

## Invariants — keep these true

- Request text is not persisted. The exceptions are the context snippet,
  which is opt-out, capped at ±100 chars and privacy-filtered, and the debug
  log described below.
- User text is never used to train or tune a model.
- Every Sentry event passes through `sentry_clean_event_data`, and
  transactions other than `/check` are dropped.
- LLM calls go only through [app/prompt.py](../app/prompt.py), and only for users
  that `LLM_ACCESS` lets through. Asking for `llm_alternatives` must not
  widen that.
- For the rule-based path, the same text with the same config gives the same
  result. Guardrail thresholds are configured, not learned.
- The LanguageTool-compatible `/words/*` endpoints keep no personal
  dictionary.

A change that breaks an invariant is a 1.1/1.14/1.15 "yes" by definition.
Tests guarding these invariants are welcome. Removing or weakening one needs
the same flag.

## Known gaps — do not extend or copy these

These are known gaps, not examples to follow. Do not build on them:

- `store_request_log` / `store_response_log` in
  [app/redis.py](../app/redis.py) keep the **full raw text and the
  `Authorization` header**, unfiltered and with no expiry, for any email in
  `REDIS_LOG_EMAILS`. They are readable through `get_user_logs`
  ([app/routes/config_routes.py](../app/routes/config_routes.py)).
- `LOG_MISSING_DECLENSION` (on by default) logs words from the user's text at
  `error` level ([app/nouns.py](../app/nouns.py)). With Sentry enabled, the
  default logging integration sends those as events, and `before_send` does
  not clean the message.
- `lt_check` logs up to 300 chars of the request at `debug` level
  ([app/routes/lt.py](../app/routes/lt.py)).

When you work near one of these, mention it to the user. Fixing one counts as
a privacy change, so screen it the same way.
