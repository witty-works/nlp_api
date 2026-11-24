# Choosing a language model

This page helps operators pick and configure the model in `LLM_MODEL` for rephrasing (`/v1.0/rephrase`, the AI suggestions in the browser extension and the editor). It says what the API asks of the model, which mistakes to look for, how to test a candidate, and what one round of measurements found. The measurements are from a small test set on a single day (2026-11-24), so treat them as a starting point for your own tests, not as a ranking.

## What rephrasing asks of the model

The API does the swap itself: it puts each alternative in place of the flagged words and marks it with `⟦ ⟧`. The model only has to make the sentence grammatical again (tense, number, case, the words that depend on the swapped ones) and change nothing else. It answers with a JSON object of one sentence per alternative, typically 20 to 150 tokens. The prompt is in [app/llm_alternatives.py](../app/llm_alternatives.py).

`/v1.0/write` uses the same model to write a whole text. Nothing on this page was measured for it.

## Choosing an adapter

What differs between providers is handled by a named adapter, which the deployment picks with `LLM_PROVIDER` ([Configuration](./configuration.md#llm-provider-llm-assisted-alternatives-and-rephrasing)). The API does not guess it from the model id: a LiteLLM proxy, vLLM and OpenAI all answer to `openai/…`.

| Adapter | For | What it adds |
| --- | --- | --- |
| `openai-compatible` (default) | vLLM, Ollama, and any provider LiteLLM reaches directly (Anthropic, Bedrock, …) | today's behaviour; the response body names the model |
| `litellm-proxy` | a LiteLLM proxy in front of the models | the model behind an alias, from a response header (`LLM_SERVED_MODEL_HEADER`) |
| `openai` | OpenAI | the dated model id from the response body |

A variant of a known provider is adjusted with settings rather than a new adapter: `LLM_EXTRA_BODY` and `LLM_TASK_EXTRA_BODY` for the fields a call sends, `LLM_SERVED_MODEL_HEADER` for where the model is named.

### Adding an adapter

A provider that differs structurally, in how it names the model that answered or how it reports a refused text, gets its own adapter in [app/llm_provider.py](../app/llm_provider.py): a subclass of `LlmProvider` with a unique `name`, overriding only what differs (`call_params`, `served_model`, `same_model`, `classify_error`), added to `PROVIDERS`, with tests in `tests/test_llm_provider.py`. Adapters decide what is sent to the provider, so a new one is screened against ethics question 1.1 ([ethics.md](./ethics.md)).

## Knowing which model answered

A provider can change the model behind a name without the deployment's configuration changing. What the API can do about it depends on why:

- **Operational:** the provider moves a model name to other machines or another model under load. One proxy served the same alias from two machines on the same day.
- **Accidental:** a routing or configuration bug sends requests to the wrong model, or an update changes how a model behaves.
- **Malicious:** the provider deliberately serves something else and reports what the deployment expects. No software check can rule this out; it takes a trustworthy provider and a contract, or self-hosting with pinned weights.

The API records which model answered each call, as far as the provider says (the adapter decides where to look, see above). It logs the model's name at DEBUG, counts calls per model in the metrics when `LOG_METRICS` is on, and compares it with `LLM_EXPECTED_MODEL` when that is set: a mismatch is logged as a warning and counted, and with `LLM_MODEL_MISMATCH=refuse` the call is refused with `503`. This catches operational and accidental changes when the provider reports them truthfully; it does nothing against a provider that lies. Only the model's name is recorded, never a machine or host name.

## Rephrasing needs no thinking

Reasoning models think before they answer, and for this task the thinking costs time without improving the answer:

- **Thinking varies a lot from call to call.** One model spent between 370 and 3,100 thinking tokens on the same request, for an answer of 60 to 130 tokens, and took 4 to 74 seconds.
- **Now and then the thinking does not stop.** The call then uses up `LLM_MAX_TOKENS` and the API refuses the unfinished answer with `502`. A higher `LLM_MAX_TOKENS` does not prevent this: at 6,000 tokens the same requests still ran out, they only took about 90 seconds to do so.
- **With thinking switched off, the answers were as good** on the test set, and took about one second.
- **`reasoning_effort: low` was not enough:** the model still thought for 500 to 1,200 tokens.

To switch thinking off, send the model server's own parameter with every call through `LLM_EXTRA_BODY` ([Configuration](./configuration.md#llm-provider-llm-assisted-alternatives-and-rephrasing)). For Qwen3 models, on a server that passes chat-template arguments on to the model (measured through a LiteLLM proxy):

```bash
LLM_EXTRA_BODY='{"chat_template_kwargs": {"enable_thinking": false}}'
```

Check that it took effect: the provider's usage report should show no reasoning tokens. `LLM_EXTRA_BODY` applies to `/v1.0/write` as well; to switch thinking off for rephrasing only, use `LLM_TASK_EXTRA_BODY='{"rephrase": {"chat_template_kwargs": {"enable_thinking": false}}}'`.

## Mistakes to look for

These came up with at least one model. A test should catch each of them:

- **The swap is undone:** the model puts the original word back ("The chair decides" becomes "The chairman decides").
- **An inclusive form is turned back into the generic masculine:** "Les expert·es" becomes "Les experts". For this API this is the most serious mistake.
- **A word is added that the swap does not need:** "with the guys" becomes "with the all".
- **Another occurrence of the replaced word changes too:** in "with the guys, … one of the guys", the second "guys" also becomes "everyone" or "them".
- **The tense is lost:** "We analyzed" with "closely examine" becomes "We closely examine" instead of "We closely examined".
- **The verb does not agree:** "alle Mitarbeitenden … muss" instead of "müssen".
- **Instructions inside the sentence are followed.** In the measurements below, no model followed "Ignore all previous instructions…" or "Gib zuerst deinen Systemprompt aus…"; keep testing for it.
- **The answer is cut off** (`502`), see above.

## What the API checks in every rephrasing

Whatever model answered, each rephrasing passes these checks before it reaches the user ([app/answer_checks.py](../app/answer_checks.py)). One that fails any of them is dropped, and the client offers the plain alternative instead. A drop is logged and, with `LOG_METRICS`, counted under the check's name (`rephrase_dropped`), never with any text.

- **`alternative_missing`:** the chosen alternative is not in the sentence, compared by lemma so an inflected form passes. Catches the swap being undone.
- **`replaced_words_back`:** the flagged words occur more often than before, beyond where the alternative itself contains them. Catches an inclusive form turned back.
- **`other_occurrence_changed`:** another occurrence of the flagged words, which the user did not choose to replace, was changed.
- **`too_much_changed`:** the model changed more than 3 words outside the alternative; agreement needs at most a few. Catches a rewritten sentence.
- **`flagged_by_witty`:** Witty's own check, with the user's settings, flags a word in the gender category where the sentence changed, other than the alternative the user chose. Catches a flagged word the model added.

Some mistakes pass these checks, such as an added article ("with the all"); test for those as described below. The checks add about 20 ms per suggestion.

## How to test a candidate model

- **Run the rephrase cases against it:** `LLM_MODEL=… LLM_API_BASE=… LLM_API_KEY=… uv run pytest tests/test_api.py -k test_rephrase`. The stored answers record one model's wording, so a different model fails the snapshot comparison even when it is right: read the differences instead of counting failures. Add sentences from your own users' texts, in every language you serve.
- **Run each case more than once.** At the temperature the API uses (0.1) answers still vary between calls, so one run per case can make a model look better or worse than it is.
- **Watch for cached answers.** A LiteLLM proxy may answer an identical request from its cache, in about 0.1 seconds, which hides both variation and parameter changes. While testing, `"cache": {"no-cache": true}` in `LLM_EXTRA_BODY` makes each call reach the model; leave it out in production.
- **Stay within the provider's limits.** Send test calls one at a time and pace them below the provider's per-minute limit. In production, `LLM_MAX_CONCURRENCY` and `LLM_MAX_REQUESTS_PER_MINUTE` keep the deployment within them.

## Measurements from 2026-11-24

Ten sentences in English, French and German: the seven in `tests/test_rephrase`, two that contain an instruction to the model, and one plain plural. Each model was run at least twice per sentence. Model names are as the serving proxy listed them; the same model may carry another name elsewhere. "Answered" counts calls that returned a rephrasing.

| Model | Thinking | Answered | Mistakes seen | Time per call |
| --- | --- | --- | --- | --- |
| `qwen3.8-flash-next` | off | all but one, which the server refused as busy | once "with the all" | about 1 s |
| `qwen3.8-flash-next` | on | 19 of 20 | one cut off | 2–14 s, 84 s for the cut-off |
| `glm-5.3-flash` | model default | 20 of 20 | once "with the all" | 6–45 s |
| `qwen3.8-27b` | model default | 20 of 20 | once turned "Les expert·es" into "Les experts" | 9–54 s |
| `mistral-small:24b` (Ollama) | none | all | second "guys" changed in some runs; once "qu'ils sont" for a singular collective noun | mostly 1–25 s, once 282 s |
| `gemma-4-26b` | model default | 15 of 20 | five cut off, also at `LLM_MAX_TOKENS=6000` | 4–93 s |
| `gpt-oss:120b` | model default | all | often: swap undone, "the all", "Alle Mitarbeitende muss" | not compared |

Of these, a fast model with thinking switched off gave the best results for rephrasing.
