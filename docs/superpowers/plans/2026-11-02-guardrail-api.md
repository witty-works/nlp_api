# Witty GPT Guardrail API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose Witty GPT as two LLM-free guardrail endpoints (`/v1.0/guardrail/input`, `/v1.0/guardrail/output`), rebuild `/v1.0/write` on them, retire `/v1.0/prompt` and the debug prompt routes, and reframe the docs. The dashboard is a follow-up.

**Architecture:** A new `app/guardrail.py` holds the three primitives (guidance text, message merge, output review). A new `app/routes/guardrail.py` exposes them; `app/routes/prompt.py` keeps only `/v1.0/write`, composed from the same primitives. The dashboard is left for a follow-up.

**Tech Stack:** Python 3.12, FastAPI, pydantic v2, pytest + pytest-snapshot (NLP API); PHP static site (website).

**Spec:** `docs/superpowers/specs/2026-11-02-guardrail-api-design.md`

## Global Constraints

- Guardrail endpoints never call an LLM; tests assert `litellm.acompletion` is not called.
- Guardrail endpoints authenticate like `/v2.4/check` (`x-key` / Bearer / `X-TESTING-AUTH` in tests) but answer `401` when no user or config resolves — a guardrail must not silently pass on a bad key.
- No `llm_alternatives` / `LLM_ACCESS` gate on guardrail endpoints; `/v1.0/write` keeps both gates.
- The output check never refuses on length or undetected language: `limit_reached: true` / `verdict: "pass"` instead.
- Route version prefix: `REPHRASE_API_VERSION` (`1.0`).
- "Prompt injection" does not appear in any doc or copy after this work.
- `/v1.0/rephrase` and `Prompt.handle()`'s default system prompt (used by `llm_alternatives.py`) keep the same wording; only the indentation whitespace of the old triple-quoted string goes.
- Language parameters (`LangWithAutoType`) map to a language by their first two letters (`de-CH` → German); `auto` or absent means "not known yet".
- Work on a `feature/guardrail-api` branch in `nlp_api-flexible` (from `dev`). Commit messages carry no Claude co-author trailer.
- Run NLP API tests with `pdm run pytest`.

## Review Focus

- Assistant messages with `content: null` (tool-call turns) or extra keys (`tool_calls`, `name`) must round-trip through `/guardrail/input` untouched — Task 2 test `test_input_passes_other_messages_through`.
- A system message whose `content` is a parts array gets the guidance as an appended `{"type": "text"}` part, not string concatenation — Task 1 test `test_merge_into_parts_system_message`.
- An empty `response` must give `verdict: "pass"`, not a 422 — Task 3 test `test_output_empty_response_passes`.
- `threshold` of 0 or below is a 422 validation error, not "always fail" — Task 3 test `test_output_rejects_threshold_below_one`.
- An unknown key gets `401`, never `verdict: "pass"` — Task 2 and Task 3 tests `test_*_requires_a_user`.

---

### Task 1: Guidance and message merge primitives

**Files:**
- Create: `app/guardrail.py`
- Modify: `app/prompt.py:132-144` (default system prompt built from the new constants)
- Test: `tests/test_guardrail.py`

**Interfaces:**
- Produces:
  - `BASE_GUIDANCE: str` — today's default system prompt minus its last paragraph ("Follow instructions without mentioning them…"), dedented and stripped.
  - `BARE_TEXT_INSTRUCTION: str` — that last paragraph, stripped.
  - `guidance(config: Config, lang: LangWithAutoType | None = None) -> str`
  - `merge_guidance(messages: list[dict], text: str) -> list[dict]` — returns a new list; input not mutated.

- [ ] **Step 1: Write the failing tests** in `tests/test_guardrail.py`:
  - `test_guidance_has_base_text`: `guidance(Config())` starts with `BASE_GUIDANCE`.
  - `test_guidance_lines_per_language`: with `Config()` and `lang=None` or `auto`, contains `"When writing German"` and `"When writing French"`; with `lang=de` and `lang=de-CH` only German; `fr` only French; `en` and `en-US` neither.
  - `test_guidance_german_example`: `Config(german_gender_ending=GermanGenderEndingType.COLON)` → contains `"Lehrer:in"`.
  - `test_guidance_inklusivum_has_no_german_line`: `german_gender_ending=INKLUSIVUM` → no `"When writing German"`.
  - `test_merge_appends_to_system_message`: `[{"role":"system","content":"Be brief."},{"role":"user","content":"Hi"}]` → first content == `"Be brief.\n\n" + text`, user message unchanged, and the caller's original system dict still has content `"Be brief."` (copy the message being changed, not just the list).
  - `test_merge_prepends_system_message`: `[{"role":"user","content":"Hi"}]` → `[{"role":"system","content":text}, {"role":"user","content":"Hi"}]`.
  - `test_merge_into_parts_system_message`: system content `[{"type":"text","text":"Be brief."}]` → content gains `{"type":"text","text":text}` as last part.
  - `test_default_system_prompt_unchanged`: the system message `Prompt.handle()` sends (capture via monkeypatched `app.prompt.litellm.acompletion`, as `test_write` does) equals `BASE_GUIDANCE + "\n\n" + BARE_TEXT_INSTRUCTION` and still contains `"Do not make biased assumptions."` and `"Here is .."`.

- [ ] **Step 2: Run** `pdm run pytest tests/test_guardrail.py -v` — expected: FAIL, `ModuleNotFoundError: app.guardrail`.

- [ ] **Step 3: Implement** in `app/guardrail.py`. Gender lines, exact copy:
  - German: `When writing German, form gender-inclusive person nouns like "{example}".` with examples `SLASH "Lehrer/in"`, `SLASH_DASH "Lehrer/-in"`, `UNDERSCORE "Lehrer_in"`, `STAR "Lehrer*in"`, `COLON "Lehrer:in"`, `PARENTHESIS_DASH "Lehrer(-in)"`, `PARENTHESIS "Lehrer(in)"`, `CAPITAL_LETTER "LehrerIn"`; `INKLUSIVUM` → no line (models cannot produce it reliably; the review covers it).
  - French: `When writing French, form gender-inclusive person nouns like "{example}".` with `POINT_MEDIAN "étudiant·e"`, `POINT_MEDIAN_S "étudiant·e·s"`, `POINT "étudiant.e"`, `POINT_S "étudiant.e.s"`, `SLASH "étudiant/e"`, `SLASH_S "étudiant/e/s"`.
  - `guidance()` = `BASE_GUIDANCE`, then each applicable line on its own line. In `app/prompt.py`, the `system_prompt is None` default becomes `BASE_GUIDANCE + "\n\n" + BARE_TEXT_INSTRUCTION` (import from `app.guardrail`; `app.guardrail` must not import `app.prompt`).

- [ ] **Step 4: Run** `pdm run pytest tests/test_guardrail.py tests/test_llm_calls.py tests/test_llm_alternatives.py -v` — expected: PASS.

- [ ] **Step 5: Commit** `git add app/guardrail.py app/prompt.py tests/test_guardrail.py && git commit -m "feat: guardrail guidance and message merge"`

### Task 2: `POST /v1.0/guardrail/input`

**Files:**
- Create: `app/routes/guardrail.py`
- Modify: `app/models.py` (new models next to `WriteRequestIn`; `MetricsType` gains `GUARDRAIL_INPUT_COUNTS = "guardrail_input_counts"`, `GUARDRAIL_INPUT_HOST = "guardrail_input_host"`, `GUARDRAIL_OUTPUT_COUNTS = "guardrail_output_counts"`, `GUARDRAIL_OUTPUT_HOST = "guardrail_output_host"`), `app/redis.py:112-126` (two `store_metrics` branches), `app/routes/__init__.py` (register with `tags=["guardrail"]`, before `check`)
- Test: `tests/test_guardrail.py`

**Interfaces:**
- Consumes: `guidance`, `merge_guidance` (Task 1).
- Produces:
  - `GuardrailInputIn(BaseRequestIn)`: `type: str = "guardrail_input"`, `messages: list[dict[str, Any]]` (min length 1), `lang: Optional[LangWithAutoType] = LangWithAutoType.AUTO`.
  - `GuardrailInputOut(BaseModel)`: `action: Literal["modify"] = "modify"`, `messages: list[dict[str, Any]]`, `guidance: str`.
  - `async def guardrail_user(request: Request, request_in: BaseRequestIn, context: AppContext) -> dict` in `app/routes/guardrail.py` — resolves user via `fetch_user` and configs via `fetch_configs_for_request`; raises `HTTPException(401, "User not found" | "User config missing")`.
  - Messages are plain dicts, not a pydantic message model, so unknown keys and `content: null` survive (Review Focus).

- [ ] **Step 1: Write the failing tests:**
  - `test_input_adds_guidance`: POST `{"messages":[{"role":"user","content":"Write a job ad."}]}` with `X-TESTING-AUTH: default@gmail.com` → 200, `messages[0]["role"] == "system"`, `messages[0]["content"] == body["guidance"]`, `messages[1]` equals the input user message, `action == "modify"`.
  - `test_input_respects_config`: body `config: {"german_gender_ending": ":in"}`, `lang: "de"` → `"Lehrer:in"` in `guidance`.
  - `test_input_passes_other_messages_through`: an assistant message `{"role":"assistant","content":None,"tool_calls":[{"id":"1","type":"function","function":{"name":"f","arguments":"{}"}}]}` comes back identical.
  - `test_input_requires_a_user`: without an auth header → 401 (`fetch_user` returns `None` then, as `test_write`'s unauthenticated call relies on).
  - `test_input_makes_no_llm_call`: monkeypatched `acompletion` that records calls → zero calls.
  - Extend `test_prompt_and_write_metrics_are_counted` loop to `("write", "guardrail_input", "guardrail_output")` (drop `"prompt"` there in Task 4).

- [ ] **Step 2: Run** `pdm run pytest tests/test_guardrail.py -v` — expected: new route tests FAIL with 404.

- [ ] **Step 3: Implement** the route `POST /v{REPHRASE_API_VERSION}/guardrail/input`, `response_model=GuardrailInputOut`, same `dependencies=[HTTPBearer, APIKeyHeader]` as `post_check_v2_4`; `client_version()` check as in `post_write`; `store_metrics(..., "guardrail_input")`; guidance from `request_in.config` (resolved by `fetch_configs_for_request`) and `request_in.lang`.

- [ ] **Step 4: Run** `pdm run pytest tests/test_guardrail.py tests/test_api.py -k "guardrail or metrics" -v` — expected: PASS.

- [ ] **Step 5: Commit** `git commit -am "feat: /v1.0/guardrail/input"` (add new files first).

### Task 3: `POST /v1.0/guardrail/output` and the snapshot tests

**Files:**
- Modify: `app/guardrail.py`, `app/routes/guardrail.py`, `app/models.py`
- Modify: `tests/test_api.py:86-107` (`test_review_prompt_dir`), `tests/test_review_prompt/*/output.json` (regenerated)
- Test: `tests/test_guardrail.py`

**Interfaces:**
- Consumes: `guardrail_user` (Task 2).
- Produces:
  - `GuardrailOutputIn(BaseRequestIn)`: `type: str = "guardrail_output"`, `response: str`, `lang: Optional[LangWithAutoType] = AUTO`, `threshold: Annotated[int, Ge(1)] = 1`.
  - `GuardrailOutputOut(BaseModel)`: `verdict: Literal["pass", "fail"]`, `findings: list[ResultOut]`, `language: Optional[str]`, `limit_reached: bool`, `reask: Optional[dict[str, str]] = None`.
  - `async def review(check_request_in: CheckRequestIn, configs: dict, context: AppContext, threshold: int = 1) -> GuardrailOutputOut` in `app/guardrail.py`: `with_inclusive_categories_disabled`, `fetch_text`, `apply_language_rules`, then `ReviewPrompt.handle(results, ReviewType.INCLUDE_PREVIOUS, check_request_in.text, min_changes=threshold - 1)`. `verdict` is `"fail"` exactly when that returns a prompt; `reask = {"role": "user", "content": prompt}`. `fetch_text` returning no language → `verdict="pass"`, `findings=[]`, `language=None`, `limit_reached` as returned.
  - The route builds `CheckRequestIn(text=body.response, lang=body.lang, client=body.client, config=body.config)` after `guardrail_user` has resolved `body.config`, and passes it to `review()`.
  - The reask quotes the whole `response` even when only its first `TEXT_MAX_LENGTH` characters were checked: intended, the gateway needs the full text back.

- [ ] **Step 1: Write the failing tests:**
  - `test_output_fail_with_reask`: `response: "The chairman called the policemen."`, `lang: "en"` → `verdict == "fail"`, `findings` non-empty, `reask["role"] == "user"`, `"The chairman called the policemen." in reask["content"]`.
  - `test_output_pass`: `response: "We support inclusion, diversity and equity."` → `verdict == "pass"`, no `reask` key (`response_model_exclude_none=True`).
  - `test_output_threshold`: same failing text with `threshold` = number of findings with alternatives + 1 → `pass`.
  - `test_output_rejects_threshold_below_one`: `threshold: 0` → 422.
  - `test_output_long_response_is_checked_in_part`: `response` of `"The chairman called. " * 100` (> `TEXT_MAX_LENGTH`) → 200, `limit_reached is True`.
  - `test_output_empty_response_passes`: `response: ""` → 200, `verdict == "pass"`.
  - `test_output_requires_a_user`, `test_output_makes_no_llm_call`: as in Task 2.

- [ ] **Step 2: Run** `pdm run pytest tests/test_guardrail.py -v` — expected: output tests FAIL with 404.

- [ ] **Step 3: Implement** `review()` and the route (`store_metrics(..., "guardrail_output")`, `response_model_exclude_none=True`). If `fetch_text` raises on an empty string, short-circuit empty/whitespace `response` to a `pass` before calling it.

- [ ] **Step 4: Migrate `test_review_prompt_dir`:** wrap each `input.json`'s `text` as `{"response": text}`, POST to `/v1.0/guardrail/output`, snapshot `response.json().get("reask")` (JSON-dumped as today). Regenerate: `pdm run pytest tests/test_api.py -k review_prompt_dir --snapshot-update`. Check the diff by hand: `test_api` now quotes the German text as the "previous response" and has no explanations; `test_api_no_changes` is `null`.

- [ ] **Step 5: Run** `pdm run pytest tests/test_guardrail.py tests/test_api.py -k "guardrail or review_prompt" -v` — expected: PASS.

- [ ] **Step 6: Commit** `git commit -am "feat: /v1.0/guardrail/output with reask"`

### Task 4: `/v1.0/write` on the primitives; remove `/v1.0/prompt` and debug prompt routes

**Files:**
- Modify: `app/routes/prompt.py` (keep `post_write`, `word_edits`, `plain_response`, `WRITE_TEXT_TOKENS`; delete `debug_review_prompt`, `debug_prompt`, `post_prompt`, `prompt`, `review_draft`), `app/llm_access.py:22` (`llm_user`), `app/redis.py` (drop `"prompt"` branch; keep the `PROMPT_*` `MetricsType` members only if something else reads them — grep)
- Test: `tests/test_api.py` (`test_write*`, `test_management_auth` at ~2915, metrics test at ~3427)

**Interfaces:**
- Consumes: `guidance`, `BARE_TEXT_INSTRUCTION` (Task 1), `review` (Task 3).
- Produces: `llm_user(request, request_in, context, refusal, user_email: str | None = None)` — when `user_email` is given it skips `fetch_user` and uses it. `post_write` gains `user_email: str | None = None` (query) and `credentials: Optional[HTTPBasicCredentials] = Depends(security)` from `app.dependencies`; when `user_email` is set it calls `fetch_management_username(request, credentials)` (a plain function; it raises the 401) before `llm_user`. Without `user_email` the management credentials are not looked at.

- [ ] **Step 1: Write / change the failing tests:**
  - `test_write_system_prompt_is_the_guardrail_guidance`: in a `test_write`-style setup, `calls[0]["messages"][0]["content"]` contains `guidance(<resolved config>)` text (assert `"Do not make biased assumptions." in` and `"When writing German" in`) and `"Here is .."` (the bare-text instruction).
  - `test_write_for_a_named_user`: POST `/v1.0/write?user_email=test@gmail.com` without `X-TESTING-AUTH`, with `llm_access(USERS)` → 200, two LLM calls.
  - `test_management_auth`: replace the `/v1.0/prompt` call with `/v1.0/write` + `params={"user_email": ...}`, `json={"prompt": "Hello world."}` → 401.
  - `test_prompt_route_is_gone`: POST to `/v1.0/prompt`, `/debug/prompt`, `/debug/review_prompt` → 404.
  - Metrics test: rename to `test_write_and_guardrail_metrics_are_counted`, loop over `("write", "guardrail_input", "guardrail_output")`.
  - `test_write`: its comment "rather than the 300 tokens of /v1.0/prompt" goes stale; reword to "rather than LLM_MAX_TOKENS alone".

- [ ] **Step 2: Run** `pdm run pytest tests/test_api.py -k "write or management_auth or prompt_route or metrics" -v` — expected: new tests FAIL.

- [ ] **Step 3: Implement.** In `post_write`: `system_prompt = guidance(write_request_in.config, write_request_in.lang) + "\n\n" + BARE_TEXT_INSTRUCTION` passed to `context.prompt.handle`; after the draft, `outcome = await review(check_request_in, configs, context)`; if `outcome.reask`, send `outcome.reask["content"]` with `max_tokens`; `limit_reached`/`check_results` from `outcome`; `outcome.language is None` → the existing 422 "Language could not be determined". Response shape (`PromptOut`) unchanged. Update the route docstring to say it is the managed loop built on the guardrail primitives. Drop imports that only the deleted routes used.

- [ ] **Step 4: Run** the full suite `pdm run pytest` — expected: PASS (snapshot suites included).

- [ ] **Step 5: Commit** `git commit -am "refactor: /v1.0/write on the guardrail primitives, drop /v1.0/prompt"`

### Task 4b: LiteLLM adapter (added 2026-11-02, user decision)

LiteLLM's Generic Guardrail API (beta) calls `POST {api_base}/beta/litellm_basic_guardrail_api` and expects its own format. Contract checked against the docs page and `litellm/proxy/guardrails/guardrail_hooks/generic_guardrail_api/generic_guardrail_api.py` on `main`, 2026-11-02: `api_key` goes out as an `x-api-key` header; a `BLOCKED` reply raises; any other reply applies the returned `texts` / `structured_messages`, and rows echoed back unchanged are kept as they were.

**Files:**
- Create: `app/routes/guardrail_litellm.py` (registered next to `guardrail`)
- Modify: `app/models.py`
- Test: `tests/test_guardrail_litellm.py`

**Interfaces:**
- Consumes: `guardrail_user` (Task 2), `review` (Task 3), `guidance`, `merge_guidance` (Task 1, `app/guidance.py`).
- Route: `POST /v1.0/guardrail/litellm/beta/litellm_basic_guardrail_api`, so `api_base` is `https://<host>/v1.0/guardrail/litellm`. Auth: Witty's own `x-key`, set through LiteLLM's static `headers` (LiteLLM's `api_key` would arrive as `x-api-key`, which Witty doesn't read).
- `LitellmGuardrailIn(BaseModel)`: `texts: list[str] = []`, `input_type: Literal["request", "response"]`, `structured_messages: Optional[list[dict[str, Any]]] = None`, `additional_provider_specific_params: dict[str, Any] = {}`. Other fields are ignored.
- `LitellmGuardrailOut(BaseModel)`: `action: Literal["NONE", "BLOCKED", "GUARDRAIL_INTERVENED"]`, `blocked_reason: Optional[str]`, `texts: Optional[list[str]]`, `structured_messages: Optional[list[dict[str, Any]]]`; `response_model_exclude_none=True`.
- `additional_provider_specific_params`: `lang` (as `LangWithAutoType`, default auto), `threshold` (int ≥ 1, default 1), `on_fail` (`"annotate"` default, or `"block"`). Invalid values → 422.

Behaviour:
- `request` with `structured_messages`: `NONE` if the first message is a system message whose text already contains the guidance (multi-turn clients, and post_call sending the input again), else `GUARDRAIL_INTERVENED` with `merge_guidance(...)`. Without `structured_messages`: `NONE`.
- `response`: each non-blank text goes through `review()` on its own. All pass → `NONE`. Otherwise `on_fail="block"` → `BLOCKED`, `blocked_reason` = `Witty: ` + the issue list; `annotate` → `GUARDRAIL_INTERVENED`, `texts` one-to-one, a failing text gets `\n\n[Witty] ` + the issue list appended.
- Issue list: findings with alternatives, `"<issue>" → <alt> / <alt>`, joined with `; `; a remove alternative reads `(remove)`.

- [ ] **Step 1: Failing tests:** `test_request_gets_guidance`, `test_request_with_guidance_already_is_left_alone`, `test_request_without_messages_is_left_alone`, `test_response_pass_is_none`, `test_response_fail_is_annotated` (`texts[0]` starts with the original, contains `[Witty]` and `"chairman"`), `test_response_fail_can_block` (`on_fail: "block"`), `test_texts_stay_one_to_one` (a pass and a fail text), `test_params_are_validated` (`on_fail: "rewrite"` → 422), `test_requires_a_user`, `test_makes_no_llm_call`.
- [ ] **Step 2:** `pdm run pytest tests/test_guardrail_litellm.py -v` — FAIL, 404.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Same command — PASS.
- [ ] **Step 5:** Commit `feat: LiteLLM generic guardrail adapter`.

### Task 5: NLP API docs

**Files:**
- Create: `docs/guardrails.md`
- Modify: `docs/api.md` (core table, `/v1.0/write` paragraph at line 76, debug table lines 396-397), `docs/technical-notes.md:58-62`, `docs/configuration.md` (lines ~153, ~329-334), `README.md` (capabilities bullet, docs index)

- [ ] **Step 1: Write `docs/guardrails.md`** with sections: *The pattern* (the three-row table from the spec, "prompt injection" named only as the term not to use); *`/v1.0/guardrail/input`* and *`/v1.0/guardrail/output`* (curl examples using the Task 2/3 test bodies, response examples captured from a local run); *Acting on a fail* (reask once, annotate, log; Witty never blocks or rewrites); *What to send* (only human-facing text, not tool calls or structured output); *Streaming* (buffer, or check after delivery and annotate); *LiteLLM* — the `config.yaml` for the Task 4b adapter (`guardrail: generic_guardrail_api`, `mode: [pre_call, post_call]`, `api_base`, `headers: {x-key: ...}`, the three params), what each `on_fail` does, and that reask is not something LiteLLM does: the app, the agent or `/v1.0/write` does it with `/v1.0/guardrail/output`'s `reask`. Name the doc URL and the date it was checked. Other gateways: one paragraph saying they can call the two neutral endpoints through their own HTTP guardrail plugins, with no recipes yet.

- [ ] **Step 2: Update the other docs:** `api.md` core table lists both guardrail rows first and drops `/v1.0/prompt`; the `/v1.0/write` paragraph opens with "the managed loop, built on the guardrail endpoints and used by `/textarea`" and stops calling it a counterpart of `/v1.0/prompt`; remove the two debug rows. `technical-notes.md` "Witty GPT Algorithm" → input guidance / output check / reask, linking `guardrails.md`. `configuration.md`: drop `/v1.0/prompt` from both lists. `README.md`: the bias bullet becomes "Inclusive-language guardrail for LLM and agent gateways — see [Guardrails](docs/guardrails.md)"; add the doc to the index.

- [ ] **Step 3: Verify** `grep -rniE "prompt.injection|v1\.0/prompt|debug/(review_)?prompt" README.md docs app` → only matches inside `docs/superpowers/`.

- [ ] **Step 4: Commit** `git add docs README.md && git commit -m "docs: document Witty GPT as a guardrail API"`

### Task 6: Dashboard — dropped

Out of this work (user, 2026-11-02: the API is not steered by the dashboard's current code). See the spec's "Dashboard (follow-up)" section.

### Task 7: Website copy

Repo: `www.witty.works`, currently on branch `help-editor-french-inklusivum`. **Ask which base branch to use before starting.** Follow `AGENTS.md`. No deploy.

**Files:**
- Modify: `witty-gpt.php` (+ `de/`/`fr/` counterparts if they exist — check `AGENTS.md` "Page structure")

- [ ] **Step 1:** Confirm `grep -rniE "prompt.injection" .` finds nothing (it found nothing on 2026-11-02); if it does, reword to "adds inclusive-language guidance to the prompt".
- [ ] **Step 2:** Add a short "Works with your LLM gateway" section to `witty-gpt.php` (and translations): Witty checks responses from any model your gateway routes, returns a verdict and a ready-to-send follow-up prompt, and never sees your provider keys; link to the API docs on GitHub (`nlp_api-flexible/docs/guardrails.md`). Match the page's existing section markup.
- [ ] **Step 3:** Run the local server per `AGENTS.md` and the registry check it describes; load the page in en/de/fr.
- [ ] **Step 4: Commit** `git commit -am "Witty GPT page: gateway section"`
